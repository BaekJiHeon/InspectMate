import json

import pytest
from conftest import image_bytes
from inspectmate.dataset import build_manifest
from inspectmate.images import decode_image, pixel_hash
from inspectmate.providers import InputImage, ProviderError, VLMInput
from inspectmate.schemas import InspectionRequest
from inspectmate.service import InspectionService
from inspectmate.storage import Store
from test_p0 import provider, vlm_response


@pytest.mark.asyncio
async def test_detector_normal_no_roi_still_calls_vlm(dataset_root, settings, monkeypatch):
    store = Store(settings.root)
    build_manifest(dataset_root, "metal_nut", settings.root / "manifests/metal_nut")

    class StubDetector:
        def __init__(self, *args):
            pass

        def predict(self, *args):
            return {
                "anomaly_score": 0.2,
                "threshold": 0.5,
                "pixel_threshold": 0.5,
                "detector_decision": "normal",
                "roi": [],
                "detector_config_hash": "fixture-detector-v1",
            }

    monkeypatch.setattr("inspectmate.detector.Detector", StubDetector)
    p, client = provider(settings)
    service = InspectionService(settings, store, p)
    raw = image_bytes()
    a = store.asset(raw, pixel_hash(decode_image(raw)), 80, 40)
    result = await service.inspect(
        InspectionRequest(asset_id=a["asset_id"], method="patchcore_vlm", external_consent=True)
    )
    assert result["execution_status"] == "succeeded" and result["detector_decision"] == "normal"
    assert result["vlm_decision"] == "normal" and result["final_decision"] == "normal"
    assert result["roi_absent"] and result["crop_assets"] == [] and len(client.calls) == 1
    assert "NORMAL_REFERENCE" in json.dumps(client.calls[0])
    assert "QUERY" in json.dumps(client.calls[0])


@pytest.mark.asyncio
async def test_unknown_observation_ids_rejected(settings):
    response = vlm_response()
    data = json.loads(response.output_text)
    data["observations"] = [
        {"image_id": "made_up_id", "location": "left", "fact": "visible", "reference_id": None}
    ]
    response.output_text = json.dumps(data)
    p, _ = provider(settings, response)
    with pytest.raises(ProviderError) as error:
        await p.inspect(
            VLMInput("sample_neutral", "metal_nut", InputImage("sample_neutral", "QUERY", image_bytes())),
            True,
        )
    assert error.value.code == "schema_error"


@pytest.mark.asyncio
async def test_monetary_budget_without_prices_blocks(settings):
    settings.max_budget_usd = 1
    p, client = provider(settings)
    with pytest.raises(ProviderError) as error:
        await p.inspect(
            VLMInput("sample_neutral", "metal_nut", InputImage("sample_neutral", "QUERY", image_bytes())),
            True,
        )
    assert error.value.code == "pricing_required" and not client.calls


def test_recovery_keeps_unknown_external_outcome(settings):
    store = Store(settings.root)
    record = {
        "inspection_id": "interrupted_fixture",
        "created_at": "2026-01-01",
        "category": "metal_nut",
        "method": "vlm_only",
        "execution_status": "running",
        "final_decision": None,
    }
    store.save_inspection(record)
    store.recover_interrupted()
    result = store.inspection("interrupted_fixture")
    assert result["execution_status"] == "failed" and result["error_code"] == "process_interrupted"
