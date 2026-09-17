import json
from types import SimpleNamespace

import httpx
import pytest
from conftest import image_bytes
from inspectmate.config import FOLLOWUP_PROMPT_VERSION
from inspectmate.dataset import build_manifest, read_json
from inspectmate.experiments import ExperimentManager
from inspectmate.images import decode_image, pixel_hash
from inspectmate.providers import InputImage, ProviderError, VLMInput, cache_key
from inspectmate.schemas import ExperimentRequest, InspectionRequest
from inspectmate.service import InspectionService
from inspectmate.storage import Store
from openai import APITimeoutError
from test_p0 import FakeResponses, provider


@pytest.mark.asyncio
async def test_batch_identical_ids_evaluation_and_failure_accounting(dataset_root, settings):
    store = Store(settings.root)
    build_manifest(dataset_root, "metal_nut", settings.root / "manifests/metal_nut")
    p, client = provider(settings)
    service = InspectionService(settings, store, p)
    manager = ExperimentManager(service)
    req = ExperimentRequest(external_consent=True)
    assert manager.preview(req)["sample_count"] == 2
    started = manager.start(req)
    await manager.tasks[started["experiment_id"]]
    result = store.experiment(started["experiment_id"])
    assert result["status"] == "completed"
    assert result["completed"] == result["total"] == 4
    path = store.root / "experiments" / started["experiment_id"]
    predictions = [json.loads(x) for x in (path / "predictions.jsonl").read_text().splitlines()]
    ids = {m: {r["sample_id"] for r in predictions if r["method"] == m} for m in req.methods}
    assert ids["vlm_only"] == ids["vlm_reference"]
    assert {tuple(r["reference_ids"]) for r in predictions if r["method"] == "vlm_reference"} == {
        tuple(load_refs(settings))
    }
    assert all(r["execution_status"] == "succeeded" for r in predictions)
    assert result["metrics"]["methods"]["vlm_only"]["total"] == 2
    from inspectmate.evaluation import evaluate

    regenerated = evaluate(
        path / "predictions.jsonl",
        service.manifest_folder("metal_nut") / "evaluator_truth.json",
        path,
        expected_ids=ids["vlm_only"],
        methods=req.methods,
    )
    assert regenerated["exploratory"] is True
    assert len(client.calls) == 4
    assert all("scratch" not in json.dumps(c) and "mask_file" not in json.dumps(c) for c in client.calls)
    assert {r["sample_id"] for r in manager.cases(started["experiment_id"])} == ids["vlm_only"]


def load_refs(settings):
    return read_json(settings.root / "manifests/metal_nut/inference_manifest.json")["reference_ids"]


@pytest.mark.asyncio
async def test_batch_cancel_keeps_every_row(dataset_root, settings):
    store = Store(settings.root)
    build_manifest(dataset_root, "metal_nut", settings.root / "manifests/metal_nut")
    p, client = provider(settings)
    manager = ExperimentManager(InspectionService(settings, store, p))
    started = manager.start(ExperimentRequest(external_consent=True))
    manager.cancel(started["experiment_id"])
    await manager.tasks[started["experiment_id"]]
    result = store.experiment(started["experiment_id"])
    assert result["status"] == "cancelled" and result["completed"] == 4 and not client.calls
    assert result["metrics"]["methods"]["vlm_only"]["failed"] == 2


@pytest.mark.asyncio
async def test_prepare_failure_terminates_state(dataset_root, settings):
    store = Store(settings.root)
    folder = settings.root / "manifests/metal_nut"
    build_manifest(dataset_root, "metal_nut", folder)
    p, _ = provider(settings)
    manager = ExperimentManager(InspectionService(settings, store, p))
    started = manager.start(ExperimentRequest(external_consent=True))
    (folder / "inference_manifest.json").write_text("{}")
    await manager.tasks[started["experiment_id"]]
    result = store.experiment(started["experiment_id"])
    assert result["status"] == "failed" and result["finished_at"]


@pytest.mark.asyncio
async def test_retry_budget_preserves_attempt_metadata(settings, monkeypatch):
    settings.max_retries = 2
    settings.max_external_requests = 1

    async def no_sleep(_):
        pass

    monkeypatch.setattr("inspectmate.providers.asyncio.sleep", no_sleep)
    p, client = provider(
        settings, exc=APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    )
    value = VLMInput("sample_neutral", "metal_nut", InputImage("sample_neutral", "QUERY", image_bytes()))
    with pytest.raises(ProviderError) as error:
        await p.inspect(value, True)
    assert error.value.code == "budget_exhausted"
    assert error.value.meta["external_requests"] == 1 and error.value.meta["latency_ms"] > 0
    assert len(client.calls) == 1 and p.budget.requests == 1


@pytest.mark.asyncio
async def test_cancel_prevents_retry(settings, monkeypatch):
    settings.max_retries = 2

    async def no_sleep(_):
        pass

    monkeypatch.setattr("inspectmate.providers.asyncio.sleep", no_sleep)
    p, client = provider(
        settings, exc=APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    )
    value = VLMInput("sample_neutral", "metal_nut", InputImage("sample_neutral", "QUERY", image_bytes()))
    with pytest.raises(ProviderError) as error:
        await p.call(value, True, cancelled=lambda: len(client.calls) > 0)
    assert error.value.code == "cancelled" and len(client.calls) == 1


@pytest.mark.asyncio
async def test_followup_preserves_benchmark_record(settings):
    p, _ = provider(settings)
    store = Store(settings.root)
    raw = image_bytes()
    a = store.asset(raw, pixel_hash(decode_image(raw)), 80, 40)
    service = InspectionService(settings, store, p)
    record = await service.inspect(
        InspectionRequest(asset_id=a["asset_id"], method="vlm_only", external_consent=True)
    )
    p.client.responses = FakeResponses(
        SimpleNamespace(
            status="completed",
            output_text='{"answer":"이전 설명을 정정합니다. 표면에 선형 흔적이 보입니다.","uncertainties":["깊이는 판단할 수 없습니다."]}',
            output=[],
            usage=None,
        )
    )
    answer = await service.followup(record["inspection_id"], "다른 점을 설명해줘.", True)
    assert answer["answer"]
    assert answer["prompt_version"] == FOLLOWUP_PROMPT_VERSION
    assert answer["inspection_prompt_version"] == record["prompt_version"]
    assert store.inspection(record["inspection_id"]) == record


def test_cache_changes_with_reference_crop_prompt_and_model(settings, monkeypatch):
    query = InputImage("sample_neutral", "QUERY", image_bytes())
    a = VLMInput("sample_neutral", "metal_nut", query)
    b = VLMInput(
        "sample_neutral",
        "metal_nut",
        query,
        (InputImage("ref_neutral", "NORMAL_REFERENCE", image_bytes((1, 2, 3))),),
    )
    assert cache_key(a, settings) != cache_key(b, settings)
    original = cache_key(a, settings)
    settings.openai_model = "another-supported-model"
    assert original != cache_key(a, settings)
    monkeypatch.setattr("inspectmate.providers.SYSTEM_PROMPT", "changed prompt")
    assert original != cache_key(a, settings)
