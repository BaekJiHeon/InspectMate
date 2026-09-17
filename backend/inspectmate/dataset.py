"""The inference manifest contains NO labels, masks, source paths or defect names."""

import hashlib
import json
import random
import shutil
from collections import defaultdict
from pathlib import Path

from .images import decode_image, pixel_hash, png_bytes


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def build_manifest(root: Path, category: str, output: Path, seed=42):
    if not category.replace("_", "").isalnum():
        raise ValueError("잘못된 품목 이름")
    root = root.resolve()
    base = root if root.name == category else root / category
    if not (base / "train/good").is_dir() or not (base / "test").is_dir():
        raise ValueError("MVTEC_ROOT 아래 category/train/good 및 category/test 구조가 필요합니다.")
    if output.exists() and any(output.iterdir()):
        raise ValueError("기존 manifest를 덮어쓰지 않습니다. 다른 출력 폴더를 선택하세요.")
    files = []
    for split, folder in (("train", base / "train/good"), ("test", base / "test")):
        for path in sorted(folder.rglob("*")):
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            if not path.resolve().is_relative_to(base.resolve()):
                raise ValueError("데이터 경로 밖으로 향하는 심볼릭 링크")
            image = decode_image(path.read_bytes())
            files.append({"source": path, "hash": pixel_hash(image), "source_split": split})
    groups = defaultdict(list)
    for row in files:
        if row["source_split"] == "train":
            groups[row["hash"]].append(row)
    hashes = sorted(groups)
    if len(hashes) < 2:
        raise ValueError("분할하려면 서로 다른 정상 이미지가 최소 2장 필요합니다.")
    test_hashes = {x["hash"] for x in files if x["source_split"] == "test"}
    if not test_hashes:
        raise ValueError("test 이미지가 없습니다.")
    if set(hashes) & test_hashes:
        raise ValueError("train/test 이미지 해시 중복: 최종 평가 누출을 방지하기 위해 중단합니다.")
    random.Random(seed).shuffle(hashes)
    nfit = min(len(hashes) - 1, max(1, int(len(hashes) * 0.8)))
    fit_hashes = set(hashes[:nfit])
    # Content-based neutral IDs and train ordering are independent of test content/count.
    files.sort(key=lambda x: (x["hash"], str(x["source"])))
    output.mkdir(parents=True, exist_ok=True)
    (output / "inputs").mkdir(exist_ok=True)
    (output / "private_masks").mkdir(exist_ok=True)
    entries, truth, sources = [], {}, {}
    occurrences = defaultdict(int)
    for index, row in enumerate(files):
        occurrence = occurrences[row["hash"]]
        occurrences[row["hash"]] += 1
        sample_id = f"sample_{row['hash'][:20]}_{occurrence:03d}"
        split = (
            "test"
            if row["source_split"] == "test"
            else ("fit_normal" if row["hash"] in fit_hashes else "calibration_normal")
        )
        image_file = f"inputs/{sample_id}.png"
        (output / image_file).write_bytes(png_bytes(decode_image(row["source"].read_bytes())))
        entries.append(
            {"sample_id": sample_id, "image_hash": row["hash"], "split": split, "image_file": image_file}
        )
        sources[sample_id] = {
            "path": str(row["source"]),
            "file_sha256": hashlib.sha256(row["source"].read_bytes()).hexdigest(),
        }
        if split == "test":
            label = "normal" if row["source"].parent.name == "good" else "defect"
            mask = base / "ground_truth" / row["source"].parent.name / f"{row['source'].stem}_mask.png"
            mask_file = None
            if label == "defect" and mask.exists():
                if not mask.resolve().is_relative_to(base.resolve()):
                    raise ValueError("마스크 경로가 데이터 폴더를 벗어납니다.")
                mask_file = f"private_masks/{sample_id}.png"
                shutil.copyfile(mask, output / mask_file)
            truth[sample_id] = {"label": label, "mask_file": mask_file}
    reference_hash = random.Random(seed).choice(sorted(fit_hashes))
    reference = next(x for x in entries if x["image_hash"] == reference_hash)
    fitcal_hashes = {
        split: sorted({x["image_hash"] for x in entries if x["split"] == split})
        for split in ("fit_normal", "calibration_normal")
    }
    manifest = {
        "version": 1,
        "category": category,
        "seed": seed,
        "target_fit_ratio": 0.8,
        "split_hash": digest(fitcal_hashes),
        "entries": entries,
        "reference_ids": [reference["sample_id"]],
        "reference_policy": "fixed-one-seed42",
        "source": "MVTec AD (user-provided; provenance in private sources.json)",
        "counts": {
            s: sum(x["split"] == s for x in entries) for s in ("fit_normal", "calibration_normal", "test")
        },
    }
    manifest["manifest_hash"] = digest(manifest)
    write_json(output / "inference_manifest.json", manifest)
    write_json(output / "evaluator_truth.json", truth)
    write_json(output / "sources.json", sources)
    return manifest


def load_manifest(folder: Path):
    manifest = read_json(folder / "inference_manifest.json")
    claimed = manifest.pop("manifest_hash")
    if digest(manifest) != claimed:
        raise ValueError("Manifest 해시가 맞지 않습니다.")
    manifest["manifest_hash"] = claimed
    ids = {x["sample_id"]: x for x in manifest["entries"]}
    if len(ids) != len(manifest["entries"]):
        raise ValueError("중복 sample_id")
    sets = [
        {x["image_hash"] for x in manifest["entries"] if x["split"] == split}
        for split in ("fit_normal", "calibration_normal", "test")
    ]
    if sets[0] & sets[1] or (sets[0] | sets[1]) & sets[2]:
        raise ValueError("분할 해시 중복")
    for ref in manifest["reference_ids"]:
        if ref not in ids or ids[ref]["split"] != "fit_normal":
            raise ValueError("참조는 fit_normal에서만 선택할 수 있습니다.")
    return manifest


def input_path(folder: Path, entry: dict):
    path = (folder / entry["image_file"]).resolve()
    if not path.is_relative_to((folder / "inputs").resolve()):
        raise ValueError("허용되지 않은 이미지 경로")
    if pixel_hash(decode_image(path.read_bytes(), max_bytes=100 * 1024 * 1024)) != entry["image_hash"]:
        raise ValueError("이미지가 manifest 작성 후 변경되었습니다.")
    return path
