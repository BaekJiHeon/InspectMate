import numpy as np
import pytest
from conftest import image_bytes
from inspectmate.dataset import build_manifest, input_path
from inspectmate.detector import DEFAULTS, Detector, calibration_thresholds, fit_detector, rois_from_map
from inspectmate.images import letterbox, restore_map
from inspectmate.service import combine
from PIL import Image


def test_transform_and_roi_original_coordinates():
    image = Image.new("RGB", (200, 100))
    _, transform = letterbox(image, 100)
    assert transform["top"] == 25 and transform["height"] == 50
    padded = np.zeros((100, 100), dtype=np.float32)
    padded[35:45, 30:40] = 10
    restored = restore_map(padded, transform)
    assert restored.shape == (100, 200)
    roi = rois_from_map(restored, 5, {**DEFAULTS, "padding_fraction": 0})[0]["box"]
    assert abs(roi[0] - 60) <= 3 and abs(roi[1] - 20) <= 3
    assert abs(roi[2] - 80) <= 3 and abs(roi[3] - 40) <= 3
    assert rois_from_map(np.zeros((50, 80)), 1) == []
    assert len(rois_from_map(np.eye(50, dtype=np.float32), 0.5)) <= 3


def test_calibration_rule_no_test_dependency():
    scores = [1, 2, 3, 4, 5]
    maps = [np.arange(100).reshape(10, 10)]
    thresholds = calibration_thresholds(scores, maps)
    assert thresholds["image_threshold"] == pytest.approx(4.8)
    assert thresholds["pixel_threshold"] == pytest.approx(98.505)
    assert thresholds["calibration_count"] == 5
    with pytest.raises(ValueError):
        calibration_thresholds([float("nan")], maps)


def test_test_changes_do_not_affect_fit_or_reference(dataset_root, tmp_path):
    first = build_manifest(dataset_root, "metal_nut", tmp_path / "first")
    for i in range(7):
        (dataset_root / f"metal_nut/test/good/new_{i}.png").write_bytes(image_bytes((200 + i, 100, 200)))
    second = build_manifest(dataset_root, "metal_nut", tmp_path / "second")
    assert first["split_hash"] == second["split_hash"]
    assert first["reference_ids"] == second["reference_ids"]
    assert [x for x in first["entries"] if x["split"] != "test"] == [
        x for x in second["entries"] if x["split"] != "test"
    ]


@pytest.mark.parametrize(
    "a,b,result",
    [
        ("normal", "normal", "normal"),
        ("defect_suspected", "defect_suspected", "defect_suspected"),
        ("normal", "defect_suspected", "uncertain"),
        ("defect_suspected", "normal", "uncertain"),
        ("normal", "uncertain", "uncertain"),
    ],
)
def test_fusion_policy(a, b, result):
    assert combine(a, b) == result


def test_real_anomalib_cpu_smoke(dataset_root, tmp_path):
    pytest.importorskip("anomalib")
    folder, artifact = tmp_path / "manifest", tmp_path / "artifact"
    manifest = build_manifest(dataset_root, "metal_nut", folder)
    metadata = fit_detector(folder, artifact, {"size": 64, "coreset_ratio": 0.1}, pretrained=False)
    assert metadata["is_smoke"] and metadata["calibration_count"] == 2
    test = next(x for x in manifest["entries"] if x["split"] == "test")
    first = Detector(artifact, folder, allow_smoke=True).predict(
        input_path(folder, test), tmp_path / "out", "first"
    )
    second = Detector(artifact, folder, allow_smoke=True).predict(
        input_path(folder, test), tmp_path / "out", "second"
    )
    assert first["anomaly_score"] == second["anomaly_score"]
    assert np.array_equal(
        np.load(tmp_path / "out/first.npz")["anomaly_map"],
        np.load(tmp_path / "out/second.npz")["anomaly_map"],
    )
    assert first["transform"]["original_width"] == 80
    from inspectmate.providers import ProviderError

    with pytest.raises(ProviderError, match="smoke"):
        Detector(artifact, folder)

    # Rebuild after changing only official test inputs. Memory and calibration
    # must depend exclusively on the unchanged fit/calibration partitions.
    (dataset_root / "metal_nut/test/good/extra.png").write_bytes(image_bytes((213, 111, 89)))
    changed_folder = tmp_path / "changed_manifest"
    build_manifest(dataset_root, "metal_nut", changed_folder)
    changed = fit_detector(
        changed_folder, tmp_path / "changed_artifact", {"size": 64, "coreset_ratio": 0.1}, pretrained=False
    )
    for key in [
        "split_hash",
        "fit_ids",
        "calibration_ids",
        "calibration_scores",
        "image_threshold",
        "pixel_threshold",
        "heatmap_limits",
    ]:
        assert changed[key] == metadata[key]
