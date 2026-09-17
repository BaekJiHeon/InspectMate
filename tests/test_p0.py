import json
from types import SimpleNamespace

import pytest
from conftest import image_bytes
from fastapi.testclient import TestClient
from inspectmate.api import create_app
from inspectmate.dataset import build_manifest, input_path, load_manifest, write_json
from inspectmate.evaluation import evaluate, method_metrics
from inspectmate.providers import Budget, InputImage, OpenAIProvider, ProviderError, VLMInput, payload


def vlm_response(status="completed", output_text=None, refusal=False):
    data = {
        "decision": "normal",
        "summary": "관찰되는 외관 이상이 없습니다.",
        "observations": [],
        "uncertainties": [],
        "recommended_action": "검사자가 검토하세요.",
    }
    return SimpleNamespace(
        status=status,
        output_text=output_text or json.dumps(data),
        output=[SimpleNamespace(content=[SimpleNamespace(type="refusal" if refusal else "output_text")])],
        usage=SimpleNamespace(input_tokens=50, output_tokens=20, total_tokens=70),
    )


class FakeResponses:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.calls = response or vlm_response(), exc, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.response


def provider(settings, response=None, exc=None):
    responses = FakeResponses(response, exc)
    return OpenAIProvider(settings, Budget(settings), SimpleNamespace(responses=responses)), responses


def test_split_and_reference_hashes(dataset_root, tmp_path):
    # Identical train images stay in the same hash group.
    root = dataset_root / "metal_nut/train/good"
    (root / "duplicate.png").write_bytes((root / "0.png").read_bytes())
    folder = tmp_path / "manifest"
    manifest = build_manifest(dataset_root, "metal_nut", folder)
    entries = manifest["entries"]
    groups = [
        {x["image_hash"] for x in entries if x["split"] == s}
        for s in ("fit_normal", "calibration_normal", "test")
    ]
    assert not groups[0] & groups[1] and not (groups[0] | groups[1]) & groups[2]
    assert all(x["split"] == "fit_normal" for x in entries if x["sample_id"] in manifest["reference_ids"])
    assert load_manifest(folder) == manifest
    assert "scratch" not in json.dumps(manifest)


def test_train_test_duplicate_blocked(dataset_root, tmp_path):
    (dataset_root / "metal_nut/test/good/a.png").write_bytes(
        (dataset_root / "metal_nut/train/good/0.png").read_bytes()
    )
    with pytest.raises(ValueError, match="train/test"):
        build_manifest(dataset_root, "metal_nut", tmp_path / "manifest")


def test_ab_payload_truth_independent(dataset_root, tmp_path):
    folder = tmp_path / "manifest"
    manifest = build_manifest(dataset_root, "metal_nut", folder)
    q = next(x for x in manifest["entries"] if x["split"] == "test")
    ref = next(x for x in manifest["entries"] if x["sample_id"] == manifest["reference_ids"][0])
    query = InputImage(q["sample_id"], "QUERY", input_path(folder, q).read_bytes())
    reference = InputImage(ref["sample_id"], "NORMAL_REFERENCE", input_path(folder, ref).read_bytes())
    a = VLMInput(q["sample_id"], "metal_nut", query)
    b = VLMInput(q["sample_id"], "metal_nut", query, (reference,))
    before = payload(b)
    assert payload(a)[0]["content"] == payload(b)[0]["content"][:-2]
    write_json(
        folder / "evaluator_truth.json", {q["sample_id"]: {"label": "changed", "mask_file": "SECRET_MASK"}}
    )
    assert payload(b) == before
    encoded = json.dumps(before)
    assert all(
        x not in encoded for x in ("scratch", "mask_file", "test/good", "evaluator_truth", "image_file")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["key", "server", "consent"])
async def test_external_guard(settings, missing):
    if missing == "key":
        settings.openai_api_key = ""
    if missing == "server":
        settings.allow_external_api = False
    p, client = provider(settings)
    with pytest.raises(ProviderError):
        await p.inspect(
            VLMInput("sample_neutral", "metal_nut", InputImage("sample_neutral", "QUERY", image_bytes())),
            missing != "consent",
        )
    assert not client.calls and p.budget.requests == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response,code",
    [
        (vlm_response(status="incomplete"), "truncated"),
        (vlm_response(refusal=True), "refusal"),
        (vlm_response(output_text='{"decision":"invented"}'), "schema_error"),
    ],
)
async def test_response_errors(settings, response, code):
    p, client = provider(settings, response)
    with pytest.raises(ProviderError) as error:
        await p.inspect(
            VLMInput("sample_neutral", "metal_nut", InputImage("sample_neutral", "QUERY", image_bytes())),
            True,
        )
    assert error.value.code == code
    assert error.value.meta["external_requests"] == 1


def test_upload_inspection_history(settings):
    p, upstream = provider(settings)
    client = TestClient(create_app(settings, p))
    asset = client.post(
        "/api/assets", files={"file": ("../../scratch.png", image_bytes(), "image/png")}
    ).json()
    assert "scratch" not in json.dumps(asset)
    response = client.post(
        "/api/inspections",
        json={"asset_id": asset["asset_id"], "method": "vlm_only", "external_consent": True},
    ).json()
    assert response["execution_status"] == "succeeded" and response["final_decision"] == "normal"
    assert len(upstream.calls) == 1
    assert upstream.calls[0]["text"]["format"]["strict"] is True
    assert upstream.calls[0]["store"] is False
    assert client.get("/api/inspections").json()[0]["inspection_id"] == response["inspection_id"]
    assert (
        client.get("/api/inspections/" + response["inspection_id"]).json()["image_hash"]
        == asset["image_hash"]
    )
    cached = client.post(
        "/api/inspections",
        json={"asset_id": asset["asset_id"], "method": "vlm_only", "external_consent": True},
    ).json()
    assert cached["cache_hit"] and cached["usage"] is None and cached["latency_ms"] is None
    assert len(upstream.calls) == 1
    assert client.get("/api/assets/" + asset["asset_id"]).status_code == 200


def test_demo_and_invalid_upload(settings):
    client = TestClient(create_app(settings))
    assert (
        client.post("/api/assets", files={"file": ("fake.png", b"bad image", "image/png")}).status_code == 422
    )
    assert client.post("/api/demo/sample", headers={"Origin": "https://malicious.example"}).status_code == 403
    sample = client.post("/api/demo/sample").json()
    record = client.post(
        "/api/inspections",
        json={"asset_id": sample["asset_id"], "provider": "demo", "method": "vlm_reference"},
    ).json()
    assert record["is_demo"] and record["execution_status"] == "succeeded" and record["usage"] is None
    asset = client.post("/api/assets", files={"file": ("upload.png", image_bytes(), "image/png")}).json()
    rejected = client.post(
        "/api/inspections", json={"asset_id": asset["asset_id"], "provider": "demo", "method": "vlm_only"}
    ).json()
    assert rejected["error_code"] == "demo_fixture_only"


@pytest.mark.asyncio
async def test_followup_reobserves_images_without_prior_verdict(settings):
    import base64

    value = VLMInput(
        "sample_query",
        "metal_nut",
        InputImage("sample_query", "QUERY", image_bytes()),
        (InputImage("ref", "NORMAL_REFERENCE", image_bytes((20, 30, 40))),),
        (InputImage("roi_1", "ROI_CANDIDATE", image_bytes((90, 80, 70))),),
    )
    prior = {
        "decision": "normal",
        "summary": "PREVIOUS_VERDICT_SENTINEL",
        "recommended_action": "PREVIOUS_ACTION_SENTINEL",
        "observations": [{"image_id": "sample_query", "fact": "손상 없음"}],
    }
    p, client = provider(
        settings,
        vlm_response(
            output_text=json.dumps(
                {
                    "answer": "이전 설명을 정정합니다. 검토 후보에서 선형 흔적이 보입니다.",
                    "uncertainties": ["표면 깊이를 알 수 없습니다."],
                }
            )
        ),
    )
    result, _ = await p.call(value, True, question="다른 부분을 설명해줘.", prior=prior)
    content = client.calls[0]["input"][0]["content"]
    context = json.loads(content[-1]["text"])
    assert context["unverified_previous_observations"] == prior["observations"]
    assert "이전 결론을 유지할 의무가 없다" in context["instruction"]
    assert "정정한다" in context["instruction"]
    encoded = json.dumps(content, ensure_ascii=False)
    assert "PREVIOUS_VERDICT_SENTINEL" not in encoded
    assert "PREVIOUS_ACTION_SENTINEL" not in encoded
    assert "최초 검사 판정을 변경하지 않는다" not in encoded
    images = [x for x in content if x["type"] == "input_image"]
    assert [base64.b64decode(x["image_url"].split(",", 1)[1]) for x in images] == [
        value.query.png,
        value.references[0].png,
        value.crops[0].png,
    ]
    assert all(x["detail"] == "high" for x in images)
    assert "정정" in result.answer


def rows_and_truth():
    records, truth = [], {}
    for label, predictions in [
        ("normal", ["normal", "normal", "defect_suspected", "uncertain", "failed"]),
        ("defect", ["normal", "defect_suspected", "defect_suspected", "defect_suspected", "uncertain"]),
    ]:
        for prediction in predictions:
            sid = f"sample_{len(records)}"
            truth[sid] = {"label": label}
            records.append(
                {
                    "sample_id": sid,
                    "method": "vlm_only",
                    "execution_status": "failed" if prediction == "failed" else "succeeded",
                    "final_decision": None if prediction == "failed" else prediction,
                    "is_demo": False,
                }
            )
    return records, truth


def test_metrics_uncertain_failures():
    records, truth = rows_and_truth()
    m = method_metrics(records, truth)
    assert (m["total"], m["succeeded"], m["failed"], m["uncertain"]) == (10, 9, 1, 2)
    assert m["automatic_coverage"]["value"] == 0.7
    assert m["defect_pass_rate"]["value"] == 0.2
    assert m["selective"]["recall"]["value"] == 0.75
    assert m["selective"]["subset_size"] == 7
    for r in records:
        r.update(execution_status="succeeded", final_decision="uncertain")
    m = method_metrics(records, truth)
    assert m["automatic_coverage"]["value"] == 0
    assert m["selective"]["recall"]["value"] is None


def test_evaluator_blocks_demo_and_missing(tmp_path):
    records, truth = rows_and_truth()
    source, labels = tmp_path / "predictions.jsonl", tmp_path / "truth.json"
    write_json(labels, truth)
    records[0]["is_demo"] = True
    source.write_text("\n".join(json.dumps(r) for r in records))
    with pytest.raises(ValueError, match="데모"):
        evaluate(source, labels, tmp_path / "out")
    source.write_text("\n".join(json.dumps(r) for r in records[1:]))
    with pytest.raises(ValueError, match="누락"):
        evaluate(source, labels, tmp_path / "out")


@pytest.mark.asyncio
async def test_actual_sdk_transport_contract(settings):
    # Actual installed SDK + mock HTTP transport, no network and no charged requests.
    import httpx
    from openai import AsyncOpenAI

    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        text = vlm_response().output_text
        return httpx.Response(
            200,
            json={
                "id": "resp_fixture",
                "object": "response",
                "created_at": 1,
                "model": settings.openai_model,
                "status": "completed",
                "output": [
                    {
                        "id": "msg_fixture",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}],
                    }
                ],
                "usage": {"input_tokens": 50, "output_tokens": 20, "total_tokens": 70},
            },
        )

    client = AsyncOpenAI(
        api_key="test-not-real",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    p = OpenAIProvider(settings, Budget(settings), client)
    result, meta = await p.inspect(
        VLMInput("sample_neutral", "metal_nut", InputImage("sample_neutral", "QUERY", image_bytes())), True
    )
    assert result.decision == "normal" and meta["usage"]["total_tokens"] == 70
    assert seen[0]["input"][0]["content"][2]["type"] == "input_image"
    assert seen[0]["text"]["format"]["schema"]["additionalProperties"] is False
    await client.close()
