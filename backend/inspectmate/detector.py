"""Explicit anomalib 2.3.1 raw Torch PatchCore. No Engine or automatic test/val split."""

import hashlib
import random
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from .dataset import digest, input_path, load_manifest, read_json, write_json
from .images import decode_image, letterbox, restore_map
from .providers import ProviderError

DEFAULTS = {
    "backbone": "resnet18",
    "layers": ["layer2", "layer3"],
    "num_neighbors": 9,
    "size": 256,
    "coreset_ratio": 0.1,
    "seed": 42,
    "image_quantile": 0.95,
    "pixel_quantile": 0.995,
    "quantile_method": "linear",
    "max_rois": 3,
    "min_area_fraction": 0.0005,
    "padding_fraction": 0.02,
    "pixel_sampling_max_per_image": 100000,
    "heatmap_low_quantile": 0.01,
    "heatmap_high_quantile": 0.999,
    "normalization_mean": [0.485, 0.456, 0.406],
    "normalization_std": [0.229, 0.224, 0.225],
}


def _imports():
    try:
        import torch
        from anomalib.models.image.patchcore.torch_model import PatchcoreModel

        return torch, PatchcoreModel
    except ImportError as exc:
        raise ProviderError(
            "detector_dependency_missing", "uv sync --extra detector 로 선택 의존성을 설치하세요."
        ) from exc


def _tensor(image, config):
    torch, _ = _imports()
    canvas, transform = letterbox(image, config["size"])
    array = np.asarray(canvas, dtype=np.float32) / 255
    array = (array - np.array(config["normalization_mean"])) / np.array(config["normalization_std"])
    return torch.from_numpy(array.transpose(2, 0, 1).astype(np.float32)), transform


def calibration_thresholds(scores, maps, config=DEFAULTS):
    scores = np.asarray(scores)
    samples = []
    for array in maps:
        flattened = np.asarray(array, dtype=np.float32).ravel()
        step = max(1, int(np.ceil(len(flattened) / config["pixel_sampling_max_per_image"])))
        samples.append(flattened[::step])
    if not len(scores) or not samples or not np.isfinite(scores).all():
        raise ValueError("Calibration 점수가 비어 있거나 유한하지 않습니다.")
    pixels = np.concatenate(samples)
    if not np.isfinite(pixels).all():
        raise ValueError("Calibration 이상 지도에 유한하지 않은 값이 있습니다.")

    def q(a, p):
        return float(np.quantile(a, p, method=config["quantile_method"]))

    low, high = q(pixels, config["heatmap_low_quantile"]), q(pixels, config["heatmap_high_quantile"])
    return {
        "image_threshold": q(scores, config["image_quantile"]),
        "pixel_threshold": q(pixels, config["pixel_quantile"]),
        "heatmap_limits": [low, max(high, low + 1e-6)],
        "calibration_count": len(scores),
        "pixel_sample_count": len(pixels),
        "quantile_method": config["quantile_method"],
    }


def rois_from_map(array, threshold, config=DEFAULTS):
    height, width = array.shape
    components, _ = ndimage.label(array > threshold)
    slices = ndimage.find_objects(components)
    minimum = max(9, int(width * height * config["min_area_fraction"]))
    padding = max(1, round(min(width, height) * config["padding_fraction"]))
    boxes = []
    for label_id, region in enumerate(slices, 1):
        if region is None or np.count_nonzero(components[region] == label_id) < minimum:
            continue
        ys, xs = region
        boxes.append(
            [
                max(0, xs.start - padding),
                max(0, ys.start - padding),
                min(width, xs.stop + padding),
                min(height, ys.stop + padding),
            ]
        )
    # Merge overlapping padded connected-component boxes to avoid redundant crops.
    changed = True
    while changed:
        changed = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    boxes.pop(j)
                    changed = True
                    break
            if changed:
                break
    results = [
        {"box": b, "peak_score": float(array[b[1] : b[3], b[0] : b[2]].max()), "role": "review_candidate"}
        for b in boxes
    ]
    return sorted(results, key=lambda x: x["peak_score"], reverse=True)[: config["max_rois"]]


def fit_detector(manifest_folder: Path, artifact: Path, config=None, pretrained=True):
    torch, Model = _imports()
    config = {**DEFAULTS, **(config or {})}
    manifest = load_manifest(manifest_folder)
    random.seed(config["seed"])
    np.random.seed(config["seed"])
    torch.manual_seed(config["seed"])
    torch.set_num_threads(min(4, torch.get_num_threads()))
    model = Model(
        layers=config["layers"],
        backbone=config["backbone"],
        pre_trained=pretrained,
        num_neighbors=config["num_neighbors"],
    ).cpu()
    model.train()
    model.feature_extractor.eval()
    fit = sorted(
        (r for r in manifest["entries"] if r["split"] == "fit_normal"), key=lambda x: x["image_hash"]
    )
    calibration = sorted(
        (r for r in manifest["entries"] if r["split"] == "calibration_normal"), key=lambda x: x["image_hash"]
    )
    if not fit or not calibration:
        raise ValueError("fit_normal과 calibration_normal이 모두 필요합니다.")
    with torch.no_grad():
        for row in fit:
            tensor, _ = _tensor(
                decode_image(input_path(manifest_folder, row).read_bytes(), max_bytes=100 * 1024 * 1024),
                config,
            )
            model(tensor.unsqueeze(0))
    model.subsample_embedding(sampling_ratio=config["coreset_ratio"])
    if model.memory_bank.shape[0] < config["num_neighbors"]:
        raise ValueError("메모리뱅크가 너무 작습니다. coreset 크기를 늘리세요.")
    model.eval()
    scores, maps = [], []
    with torch.no_grad():
        for row in calibration:
            tensor, transform = _tensor(
                decode_image(input_path(manifest_folder, row).read_bytes(), max_bytes=100 * 1024 * 1024),
                config,
            )
            output = model(tensor.unsqueeze(0))
            scores.append(float(output.pred_score.item()))
            maps.append(restore_map(output.anomaly_map[0, 0].cpu().numpy(), transform))
    thresholds = calibration_thresholds(scores, maps, config)
    from .experiments import runtime_info

    artifact.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), artifact / "state.pt")
    meta = {
        "config": config,
        **thresholds,
        "pretrained": pretrained,
        "is_smoke": not pretrained,
        "split_hash": manifest["split_hash"],
        "manifest_hash_at_fit": manifest["manifest_hash"],
        "fit_ids": [x["sample_id"] for x in fit],
        "calibration_ids": [x["sample_id"] for x in calibration],
        "fit_hashes": [x["image_hash"] for x in fit],
        "calibration_hashes": [x["image_hash"] for x in calibration],
        "calibration_scores": scores,
        "memory_shape": list(model.memory_bank.shape),
        "state_sha256": hashlib.sha256((artifact / "state.pt").read_bytes()).hexdigest(),
        "runtime": runtime_info(),
        "preprocessing": "letterbox RGB, bilinear resize, ImageNet normalization",
        "threshold_notice": "95백분위수는 실제 정상 오탐률 5%를 보장하지 않습니다.",
    }
    meta["config_hash"] = digest(meta)
    write_json(artifact / "metadata.json", meta)
    return meta


class Detector:
    def __init__(self, artifact: Path, manifest_folder: Path, allow_smoke=False):
        if not (artifact / "metadata.json").exists():
            raise ProviderError(
                "detector_missing",
                "PatchCore 메모리·calibration 산출물이 없습니다. detector-fit 명령을 실행하세요.",
            )
        self.meta = read_json(artifact / "metadata.json")
        if self.meta["is_smoke"] and not allow_smoke:
            raise ProviderError(
                "smoke_artifact_blocked", "무작위 가중치 smoke 산출물은 실제 검사에 사용할 수 없습니다."
            )
        if self.meta["split_hash"] != load_manifest(manifest_folder)["split_hash"]:
            raise ProviderError("detector_split_mismatch", "모델과 현재 데이터 분할이 일치하지 않습니다.")
        expected = self.meta["config_hash"]
        if digest({k: v for k, v in self.meta.items() if k != "config_hash"}) != expected:
            raise ValueError("Detector metadata integrity mismatch")
        if hashlib.sha256((artifact / "state.pt").read_bytes()).hexdigest() != self.meta["state_sha256"]:
            raise ValueError("Detector weights integrity mismatch")
        torch, Model = _imports()
        self.torch, self.config = torch, self.meta["config"]
        torch.set_num_threads(min(4, torch.get_num_threads()))
        self.model = Model(
            layers=self.config["layers"],
            backbone=self.config["backbone"],
            pre_trained=False,
            num_neighbors=self.config["num_neighbors"],
        ).cpu()
        self.model.load_state_dict(
            torch.load(artifact / "state.pt", map_location="cpu", weights_only=True), strict=True
        )
        self.model.eval()

    def predict(self, path: Path, output_dir: Path, inspection_id: str):
        image = decode_image(path.read_bytes(), max_bytes=100 * 1024 * 1024)
        tensor, transform = _tensor(image, self.config)
        with self.torch.no_grad():
            prediction = self.model(tensor.unsqueeze(0))
        score = float(prediction.pred_score.item())
        array = restore_map(prediction.anomaly_map[0, 0].cpu().numpy(), transform)
        if not np.isfinite(score) or not np.isfinite(array).all():
            raise ValueError("유한하지 않은 탐지 결과")
        rois = rois_from_map(array, self.meta["pixel_threshold"], self.config)
        output_dir.mkdir(parents=True, exist_ok=True)
        map_file, heatmap_file = f"{inspection_id}.npz", f"{inspection_id}_heatmap.png"
        np.savez_compressed(output_dir / map_file, anomaly_map=array)
        low, high = self.meta["heatmap_limits"]
        normalized = np.clip((array - low) / (high - low), 0, 1)
        # Fixed blue -> amber scale, never normalized per query image.
        rgb = np.stack([35 + 220 * normalized, 85 + 65 * normalized, 190 - 155 * normalized], axis=-1).astype(
            np.uint8
        )
        Image.fromarray(rgb).save(output_dir / heatmap_file)
        return {
            "anomaly_score": score,
            "threshold": self.meta["image_threshold"],
            "pixel_threshold": self.meta["pixel_threshold"],
            "heatmap_limits": self.meta["heatmap_limits"],
            "detector_decision": "defect_suspected" if score > self.meta["image_threshold"] else "normal",
            "roi": rois,
            "transform": transform,
            "heatmap_file": heatmap_file,
            "anomaly_map_file": map_file,
            "detector_config_hash": self.meta["config_hash"],
            "detector_metadata": self.meta,
        }
