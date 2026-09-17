import asyncio
import base64
import json
import time
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import ValidationError

from .config import (
    CRITERIA,
    CRITERIA_VERSION,
    FOLLOWUP_INSTRUCTION,
    PREPROCESS_VERSION,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
)
from .dataset import digest
from .schemas import QuestionResult, VLMResult


@dataclass(frozen=True)
class InputImage:
    image_id: str
    role: str
    png: bytes


@dataclass(frozen=True)
class VLMInput:
    sample_id: str
    category: str
    query: InputImage
    references: tuple[InputImage, ...] = ()
    crops: tuple[InputImage, ...] = ()


def payload(value: VLMInput):
    # Neither method names nor source filenames/labels can enter this allowlisted DTO.
    items = [
        {
            "type": "input_text",
            "text": json.dumps(
                {"sample_id": value.sample_id, "category": value.category, "criteria": CRITERIA},
                ensure_ascii=False,
            ),
        }
    ]
    for image in (value.query, *value.references, *value.crops):
        items.extend(
            [
                {"type": "input_text", "text": f"{image.role} image_id={image.image_id}"},
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64," + base64.b64encode(image.png).decode(),
                    "detail": "high",
                },
            ]
        )
    return [{"role": "user", "content": items}]


def cache_key(value, settings, extra=None):
    return digest(
        {
            "provider": "openai",
            "model": settings.openai_model,
            "prompt_version": PROMPT_VERSION,
            "prompt": SYSTEM_PROMPT,
            "criteria_version": CRITERIA_VERSION,
            "criteria": CRITERIA,
            "preprocess": PREPROCESS_VERSION,
            "payload": payload(value),
            "schema": VLMResult.model_json_schema(),
            "temperature": 0,
            "max_output_tokens": settings.max_output_tokens,
            "extra": extra,
        }
    )


class ProviderError(RuntimeError):
    def __init__(self, code, message, meta=None):
        super().__init__(message)
        self.code, self.meta = code, meta or {}


class Budget:
    """Shared process budget, including retries. Unknown usage keeps a conservative reservation."""

    def __init__(self, settings):
        self.settings = settings
        self.requests, self.tokens, self.cost = 0, 0, 0.0
        self.lock = Lock()

    def reserve(self, image_count):
        # Conservative bound for pinned 4.1-mini, <=1024px/image and bounded text inputs.
        tokens = image_count * 4000 + 8000 + self.settings.max_output_tokens
        s = self.settings
        price_known = s.input_usd_per_million is not None and s.output_usd_per_million is not None
        cost = (
            (
                (tokens - s.max_output_tokens) * s.input_usd_per_million
                + s.max_output_tokens * s.output_usd_per_million
            )
            / 1e6
            if price_known
            else 0
        )
        with self.lock:
            if s.max_budget_usd is not None and not price_known:
                raise ProviderError("pricing_required", "금액 한도를 사용하려면 단가 설정이 필요합니다.")
            if self.requests >= s.max_external_requests or self.tokens + tokens > s.max_total_tokens:
                raise ProviderError("budget_exhausted", "요청 또는 토큰 한도에 도달했습니다.")
            if s.max_budget_usd is not None and self.cost + cost > s.max_budget_usd:
                raise ProviderError("budget_exhausted", "설정된 예산 한도를 초과하는 요청입니다.")
            self.requests += 1
            self.tokens += tokens
            self.cost += cost
        return tokens, cost

    def settle(self, reservation, usage):
        if usage is None:
            return  # an unreported call is never counted as zero usage
        s = self.settings
        with self.lock:
            self.tokens += usage["total_tokens"] - reservation[0]
            if s.input_usd_per_million is not None and s.output_usd_per_million is not None:
                self.cost += (
                    usage["input_tokens"] * s.input_usd_per_million
                    + usage["output_tokens"] * s.output_usd_per_million
                ) / 1e6 - reservation[1]


class Provider(Protocol):
    async def inspect(self, value: VLMInput, consent: bool): ...


class OpenAIProvider:
    def __init__(self, settings, budget, client=None):
        self.settings, self.budget, self.client = settings, budget, client

    def authorize(self, consent):
        if not self.settings.openai_api_key:
            raise ProviderError("api_key_missing", "서버의 OPENAI_API_KEY 설정이 필요합니다.")
        if not self.settings.allow_external_api or not consent:
            raise ProviderError(
                "consent_required", "서버 외부 전송 허용과 이번 실행의 전송 동의가 모두 필요합니다."
            )

    async def call(self, value, consent, question=None, prior=None, cancelled=None):
        self.authorize(consent)
        if self.client is None:
            self.client = AsyncOpenAI(
                api_key=self.settings.openai_api_key, timeout=self.settings.api_timeout_seconds, max_retries=0
            )
        client = self.client
        inputs = payload(value)
        schema = VLMResult
        if question is not None:
            schema = QuestionResult
            inputs[0]["content"].append(
                {
                    "type": "input_text",
                    "text": json.dumps(
                        {
                            # Keep conversational context without supplying the old verdict as a target.
                            "unverified_previous_observations": (prior or {}).get("observations", []),
                            "question": question,
                            "instruction": FOLLOWUP_INSTRUCTION,
                        },
                        ensure_ascii=False,
                    ),
                }
            )
        attempts, usage_records = [], []
        started = time.perf_counter()
        for retry in range(self.settings.max_retries + 1):
            try:
                if cancelled and cancelled():
                    raise ProviderError("cancelled", "추가 API 호출이 취소되었습니다.")
                reservation = self.budget.reserve(1 + len(value.references) + len(value.crops))
            except ProviderError as exc:
                meta = self._meta(started, attempts, usage_records, max(0, len(attempts) - 1))
                if not attempts:
                    meta["latency_ms"] = None
                raise ProviderError(exc.code, str(exc), meta) from exc
            t = time.perf_counter()
            try:
                response = await client.responses.create(
                    model=self.settings.openai_model,
                    instructions=SYSTEM_PROMPT,
                    input=inputs,
                    store=False,
                    temperature=0,
                    max_output_tokens=self.settings.max_output_tokens,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": schema.__name__,
                            "schema": schema.model_json_schema(),
                            "strict": True,
                        }
                    },
                )
                usage = (
                    {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                        "total_tokens": response.usage.total_tokens,
                    }
                    if response.usage
                    else None
                )
                usage_records.append(usage)
                self.budget.settle(reservation, usage)
                if response.status == "incomplete":
                    raise ProviderError("truncated", "응답이 출력 한도 등으로 완료되지 않았습니다.")
                if any(
                    getattr(c, "type", None) == "refusal"
                    for o in response.output
                    for c in getattr(o, "content", [])
                ):
                    raise ProviderError("refusal", "모델이 요청에 대한 답변을 거절했습니다.")
                if response.status != "completed":
                    raise ProviderError("api_failed", "API 응답이 완료 상태가 아닙니다.")
                try:
                    result = schema.model_validate_json(response.output_text)
                    if isinstance(result, VLMResult):
                        allowed = {x.image_id for x in (value.query, *value.references, *value.crops)}
                        refs = {x.image_id for x in value.references}
                        if any(
                            o.image_id not in allowed or (o.reference_id and o.reference_id not in refs)
                            for o in result.observations
                        ):
                            raise ValueError("unknown image/reference ID")
                except (ValidationError, ValueError) as exc:
                    raise ProviderError(
                        "schema_error", "응답 구조 또는 이미지 ID 검증에 실패했습니다."
                    ) from exc
                attempts.append((time.perf_counter() - t) * 1000)
                return result, self._meta(started, attempts, usage_records, retry)
            except (
                APITimeoutError,
                RateLimitError,
                APIConnectionError,
                APIStatusError,
                ProviderError,
            ) as exc:
                attempts.append((time.perf_counter() - t) * 1000)
                retryable = isinstance(exc, (APITimeoutError, RateLimitError, APIConnectionError)) or (
                    isinstance(exc, APIStatusError) and exc.status_code >= 500
                )
                code = (
                    exc.code
                    if isinstance(exc, ProviderError)
                    else (
                        "timeout"
                        if isinstance(exc, APITimeoutError)
                        else "rate_limit"
                        if isinstance(exc, RateLimitError)
                        else "connection_error"
                        if isinstance(exc, APIConnectionError)
                        else "api_error"
                    )
                )
                if retryable and retry < self.settings.max_retries:
                    await asyncio.sleep(min(2**retry, 4))
                    continue
                raise ProviderError(
                    code,
                    str(exc) if isinstance(exc, ProviderError) else "외부 API 요청이 실패했습니다.",
                    self._meta(started, attempts, usage_records, retry),
                ) from exc

    def _meta(self, started, attempts, usage_records, retry):
        valid = [u for u in usage_records if u is not None]
        usage = (
            {k: sum(u[k] for u in valid) for k in ("input_tokens", "output_tokens", "total_tokens")}
            if valid
            else None
        )
        return {
            "latency_ms": (time.perf_counter() - started) * 1000,
            "provider_attempt_ms": attempts,
            "usage": usage,
            "usage_complete": len(valid) == len(attempts),
            "retry_count": retry,
            "external_requests": len(attempts),
            "cache_hit": False,
        }

    async def inspect(self, value, consent):
        return await self.call(value, consent)


class DemoProvider:
    async def inspect(self, value, consent=False):
        # Caller only permits explicit built-in UI fixtures; never arbitrary uploads.
        result = VLMResult(
            decision="uncertain",
            summary="데모 응답입니다. 이 이미지를 실제 모델로 분석하지 않았습니다.",
            observations=[],
            uncertainties=["화면과 저장 흐름을 확인하는 전용 데모입니다."],
            recommended_action="실제 이미지는 OpenAI 모드에서 검사하세요.",
        )
        return result, {
            "latency_ms": None,
            "provider_attempt_ms": [],
            "usage": None,
            "retry_count": 0,
            "external_requests": 0,
            "cache_hit": False,
        }
