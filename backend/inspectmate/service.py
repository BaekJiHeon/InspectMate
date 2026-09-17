import time
import uuid

from PIL import Image, ImageDraw

from .config import CRITERIA_VERSION, FOLLOWUP_PROMPT_VERSION, PREPROCESS_VERSION, PROMPT_VERSION
from .dataset import input_path, load_manifest, read_json, write_json
from .images import decode_image, pixel_hash, png_bytes, vlm_image
from .providers import Budget, DemoProvider, InputImage, OpenAIProvider, ProviderError, VLMInput, cache_key
from .storage import now


def combine(detector, vlm):
    return detector if detector == vlm and detector in {"normal", "defect_suspected"} else "uncertain"


class InspectionService:
    def __init__(self, settings, store, provider=None):
        self.settings, self.store = settings, store
        self.budget = Budget(settings)
        self.provider = provider or OpenAIProvider(settings, self.budget)

    def manifest_folder(self, category):
        if not category.replace("_", "").isalnum():
            raise ValueError("Invalid category")
        return self.store.root / "manifests" / category

    def references(self, category):
        folder = self.manifest_folder(category)
        if not (folder / "inference_manifest.json").exists():
            raise ProviderError(
                "data_missing", "데이터 manifest가 없습니다. README의 데이터 설치 명령을 실행하세요."
            )
        manifest = load_manifest(folder)
        entries = {x["sample_id"]: x for x in manifest["entries"]}
        return manifest, [
            InputImage(r, "NORMAL_REFERENCE", vlm_image(input_path(folder, entries[r])))
            for r in manifest["reference_ids"]
        ]

    def demo_asset(self):
        # Deliberately non-product geometry. Never called MVTec or used for benchmark.
        image = Image.new("RGB", (640, 480), "#e8edf4")
        draw = ImageDraw.Draw(image)
        for i in range(8):
            draw.rectangle((50 + i * 67, 100, 94 + i * 67, 380), fill=(40 + i * 20, 100, 170))
        return self.store.asset(png_bytes(image), pixel_hash(image), *image.size, is_demo=True)

    def input_from_record(self, record):
        refs = tuple(
            InputImage(r["image_id"], "NORMAL_REFERENCE", vlm_image(self.store.asset_path(r["asset_id"])))
            for r in record.get("reference_assets", [])
        )
        crops = tuple(
            InputImage(r["image_id"], "ROI_CANDIDATE", vlm_image(self.store.asset_path(r["asset_id"])))
            for r in record.get("crop_assets", [])
        )
        return VLMInput(
            record["sample_id"],
            record["category"],
            InputImage(record["sample_id"], "QUERY", vlm_image(self.store.asset_path(record["asset_id"]))),
            refs,
            crops,
        )

    async def inspect(self, req, sample_id=None, cancelled=None):
        asset = self.store.get_asset(req.asset_id)
        iid = uuid.uuid4().hex
        record = {
            "inspection_id": iid,
            "created_at": now(),
            "sample_id": sample_id or asset["sample_id"],
            "asset_id": req.asset_id,
            "image_url": asset["url"],
            "image_width": asset["width"],
            "image_height": asset["height"],
            "category": req.category,
            "method": req.method,
            "provider": "patchcore" if req.method == "patchcore" else req.provider,
            "model": "patchcore-resnet18"
            if req.method == "patchcore"
            else ("demo-ui-fixture" if req.provider == "demo" else self.settings.openai_model),
            "prompt_version": PROMPT_VERSION,
            "criteria_version": CRITERIA_VERSION,
            "preprocess_version": PREPROCESS_VERSION,
            "image_hash": asset["image_hash"],
            "reference_ids": [],
            "reference_assets": [],
            "crop_assets": [],
            "roi": [],
            "detector_decision": None,
            "vlm_decision": None,
            "final_decision": None,
            "anomaly_score": None,
            "threshold": None,
            "result": None,
            "is_demo": req.provider == "demo",
            "execution_status": "running",
            "error_code": None,
            "human_review_status": "unreviewed",
            "latency_ms": None,
            "usage": None,
            "retry_count": 0,
            "cache_hit": False,
            "external_requests": 0,
            "config_hash": None,
            "cost_usd": None,
        }
        self.store.save_inspection(record)
        t = time.perf_counter()
        try:
            if req.provider == "demo" and (
                not asset["is_demo_fixture"] or req.method in {"patchcore", "patchcore_vlm"}
            ):
                raise ProviderError(
                    "demo_fixture_only",
                    "데모는 전용 UI 샘플의 A/B 흐름에서만 가능합니다. 실제 이미지를 분석하지 않습니다.",
                )
            if asset["is_demo_fixture"] and req.provider != "demo":
                raise ProviderError("demo_fixture_only", "데모 샘플을 실제 연구 데이터로 검사할 수 없습니다.")
            if req.method != "patchcore" and req.provider != "demo":
                self.provider.authorize(req.external_consent)
            refs = []
            manifest = None
            if req.method in {"vlm_reference", "patchcore_vlm"} and req.provider != "demo":
                manifest, refs = self.references(req.category)
            for ref in refs:
                im = decode_image(ref.png)
                a = self.store.asset(ref.png, pixel_hash(im), *im.size)
                record["reference_assets"].append({**a, "image_id": ref.image_id})
            record["reference_ids"] = [x.image_id for x in refs]
            if manifest:
                record["split_hash"] = manifest["split_hash"]
                record["manifest_hash"] = manifest["manifest_hash"]
            crops = []
            if req.method in {"patchcore", "patchcore_vlm"}:
                from .detector import Detector

                dt = time.perf_counter()
                detector = Detector(
                    self.store.root / "detectors" / req.category, self.manifest_folder(req.category)
                )
                import asyncio

                det = await asyncio.to_thread(
                    detector.predict, self.store.asset_path(req.asset_id), self.store.root / "images", iid
                )
                record.update(det)
                record["detector_latency_ms"] = (time.perf_counter() - dt) * 1000
                original = decode_image(
                    self.store.asset_path(req.asset_id).read_bytes(), max_bytes=100 * 1024 * 1024
                )
                for index, roi in enumerate(record["roi"]):
                    crop = original.crop(tuple(roi["box"]))
                    a = self.store.asset(png_bytes(crop), pixel_hash(crop), *crop.size)
                    image_id = f"roi_{index + 1}"
                    record["crop_assets"].append({**a, "image_id": image_id})
                    crops.append(
                        InputImage(image_id, "ROI_CANDIDATE", vlm_image(self.store.asset_path(a["asset_id"])))
                    )
                record["roi_absent"] = not bool(record["roi"])
            if req.method == "patchcore":
                record["final_decision"] = record["detector_decision"]
                record["explanation_type"] = "rule_template"
                record["result"] = {
                    "decision": record["final_decision"],
                    "summary": "규칙 기반 안내: 이미지 이상 점수와 정상 calibration 임계값을 비교한 결과입니다.",
                    "observations": [],
                    "uncertainties": ["점수는 불량 확률이 아닙니다."],
                    "recommended_action": "원본 이미지와 의심 영역을 검사자가 검토하세요.",
                }
                record["latency_ms"] = record["detector_latency_ms"]
                record["config_hash"] = record["detector_config_hash"]
            else:
                value = VLMInput(
                    record["sample_id"],
                    req.category,
                    InputImage(record["sample_id"], "QUERY", vlm_image(self.store.asset_path(req.asset_id))),
                    tuple(refs),
                    tuple(crops),
                )
                key = cache_key(
                    value,
                    self.settings,
                    {"detector": record.get("detector_config_hash"), "demo": req.provider == "demo"},
                )
                record["config_hash"] = key
                cache = self.store.root / "cache" / f"{key}.json"
                if req.use_cache and cache.exists() and req.provider != "demo":
                    ct = time.perf_counter()
                    cached = read_json(cache)
                    from .schemas import VLMResult

                    result = VLMResult.model_validate(cached["result"])
                    meta = {
                        "cache_hit": True,
                        "cache_lookup_ms": (time.perf_counter() - ct) * 1000,
                        "latency_ms": None,
                        "usage": None,
                        "retry_count": 0,
                        "external_requests": 0,
                        "cached_original_meta": cached["meta"],
                    }
                else:
                    provider = DemoProvider() if req.provider == "demo" else self.provider
                    if req.provider == "demo":
                        result, meta = await provider.inspect(value, req.external_consent)
                    else:
                        result, meta = await provider.call(value, req.external_consent, cancelled=cancelled)
                    if req.provider != "demo":
                        write_json(cache, {"result": result.model_dump(), "meta": meta})
                record.update(meta)
                record["vlm_latency_ms"] = meta.get("latency_ms")
                record["result"] = result.model_dump()
                record["explanation_type"] = (
                    "demo" if req.provider == "demo" else "vlm_observation_unreviewed"
                )
                record["vlm_decision"] = result.decision
                record["final_decision"] = (
                    combine(record["detector_decision"], result.decision)
                    if req.method == "patchcore_vlm"
                    else result.decision
                )
                if req.method == "patchcore_vlm" and record["latency_ms"] is not None:
                    record["latency_ms"] += record["detector_latency_ms"]
            if (
                record["usage"] is not None
                and self.settings.input_usd_per_million is not None
                and self.settings.output_usd_per_million is not None
            ):
                record["cost_usd"] = (
                    record["usage"]["input_tokens"] * self.settings.input_usd_per_million
                    + record["usage"]["output_tokens"] * self.settings.output_usd_per_million
                ) / 1e6
            record["execution_status"] = "succeeded"
        except ProviderError as exc:
            record.update(exc.meta)
            if record.get("detector_latency_ms") is not None and record.get("latency_ms") is not None:
                record["vlm_latency_ms"] = record["latency_ms"]
                record["latency_ms"] += record["detector_latency_ms"]
            record.update(execution_status="failed", error_code=exc.code, error_message=str(exc))
        except (ValueError, FileNotFoundError, ImportError) as exc:
            record.update(execution_status="failed", error_code="configuration_error", error_message=str(exc))
        except Exception:
            record.update(
                execution_status="failed",
                error_code="internal_error",
                error_message="검사 실행 중 오류가 발생했습니다. 서버 로그와 설정을 확인하세요.",
            )
        record["end_to_end_ms"] = (time.perf_counter() - t) * 1000
        self.store.save_inspection(record)
        return record

    async def followup(self, inspection_id, question, consent):
        record = self.store.inspection(inspection_id)
        if record["execution_status"] != "succeeded" or record["is_demo"] or record["method"] == "patchcore":
            raise ProviderError(
                "followup_unavailable", "완료된 실제 VLM 검사에서만 후속 질문을 사용할 수 있습니다."
            )
        result, meta = await self.provider.call(
            self.input_from_record(record), consent, question, record["result"]
        )
        answer = {
            "question_id": uuid.uuid4().hex,
            "inspection_id": inspection_id,
            "created_at": now(),
            "question": question,
            "model": self.settings.openai_model,
            "provider": "openai",
            "prompt_version": FOLLOWUP_PROMPT_VERSION,
            "inspection_prompt_version": record["prompt_version"],
            **result.model_dump(),
            "meta": meta,
        }
        with self.store.connect() as db:
            import json

            db.execute(
                "INSERT INTO questions VALUES (?,?,?)",
                (answer["question_id"], inspection_id, json.dumps(answer)),
            )
        return answer
