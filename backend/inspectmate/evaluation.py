"""Offline evaluator. The inference runner never imports evaluator labels."""

import csv
import json
from pathlib import Path

import numpy as np
from scipy.stats import rankdata

from .dataset import read_json, write_json

PREDICTIONS = ("normal", "defect_suspected", "uncertain", "failed")


def fraction(n, d, reason="분모가 0입니다."):
    return {"value": n / d if d else None, "numerator": n, "denominator": d, "reason": None if d else reason}


def auc(labels, scores):
    pos, neg = sum(labels), len(labels) - sum(labels)
    if not pos or not neg:
        return {
            "value": None,
            "reason": "정답 두 클래스의 유효 점수가 필요합니다.",
            "sample_count": len(labels),
        }
    ranks = rankdata(scores)
    return {
        "value": float((ranks[np.asarray(labels, dtype=bool)].sum() - pos * (pos + 1) / 2) / (pos * neg)),
        "reason": None,
        "sample_count": len(labels),
    }


def method_metrics(records, truth, decision_field="final_decision"):
    table = {label: {p: 0 for p in PREDICTIONS} for label in ("normal", "defect")}
    for record in records:
        label = truth[record["sample_id"]]["label"]
        prediction = "failed" if record["execution_status"] != "succeeded" else record[decision_field]
        if prediction not in PREDICTIONS:
            raise ValueError("알 수 없는 판정")
        table[label][prediction] += 1
    n = len(records)
    normal, defect = table["normal"], table["defect"]
    tp, fp, fn, tn = (
        defect["defect_suspected"],
        normal["defect_suspected"],
        defect["normal"],
        normal["normal"],
    )
    selected = tp + fp + fn + tn
    failed = sum(v["failed"] for v in table.values())
    pending = sum(v["uncertain"] for v in table.values())
    latencies = [
        r["latency_ms"] for r in records if r.get("latency_ms") is not None and not r.get("cache_hit")
    ]

    def latency_stats(items):
        return {
            "sample_count": len(items),
            "median_ms": float(np.median(items)) if items else None,
            "p95_ms": float(np.quantile(items, 0.95, method="linear")) if items else None,
            "reason": None if items else "실제 비캐시 추론 측정 없음",
        }

    usage = [r["usage"] for r in records if r.get("usage") is not None and not r.get("cache_hit")]
    result = {
        "total": n,
        "succeeded": n - failed,
        "failed": failed,
        "uncertain": pending,
        "confusion": table,
        "automatic_coverage": fraction(selected, n),
        "defect_pass_rate": fraction(fn, sum(defect.values())),
        "normal_false_alarm_rate": fraction(fp, sum(normal.values())),
        "class_rates": {
            label: {
                "uncertain": fraction(row["uncertain"], sum(row.values())),
                "failed": fraction(row["failed"], sum(row.values())),
            }
            for label, row in table.items()
        },
        "selective": {
            "subset_size": selected,
            "normal_count": tn + fp,
            "defect_count": tp + fn,
            "precision": fraction(tp, tp + fp),
            "recall": fraction(tp, tp + fn),
            "f1": fraction(2 * tp, 2 * tp + fp + fn),
        },
        "latency": {
            **latency_stats(latencies),
            "population": "non-cache attempted inference; success and failure",
            "quantile_method": "linear",
            "by_status": {
                s: latency_stats(
                    [
                        r["latency_ms"]
                        for r in records
                        if r["execution_status"] == s
                        and not r.get("cache_hit")
                        and r.get("latency_ms") is not None
                    ]
                )
                for s in ("succeeded", "failed")
            },
        },
        "usage": {
            "reported": {
                k: sum(u[k] for u in usage) for k in ("input_tokens", "output_tokens", "total_tokens")
            }
            if usage
            else None,
            "reported_records": len(usage),
            "unknown_records": sum(
                r.get("external_requests", 0) > 0 and not r.get("usage_complete", False) for r in records
            ),
        },
        "cache_hits": sum(bool(r.get("cache_hit")) for r in records),
        "explanation_accuracy": {"value": None, "reason": "별도 수동 검토 필요; 미평가"},
    }
    if records and records[0]["method"] in {"patchcore", "patchcore_vlm"}:
        scored = [r for r in records if r.get("anomaly_score") is not None]
        result["detector_image_auroc"] = auc(
            [truth[r["sample_id"]]["label"] == "defect" for r in scored], [r["anomaly_score"] for r in scored]
        )
        result["detector_image_auroc"]["scored_coverage"] = fraction(len(scored), n)
    return result


def location_metrics(records, truth, truth_folder, image_folder):
    from PIL import Image

    tp = fp = fn = evaluated = missing = 0
    for r in records:
        if not r.get("anomaly_map_file"):
            continue
        gt = truth[r["sample_id"]]
        if gt["label"] == "defect" and not gt.get("mask_file"):
            missing += 1
            continue
        path = (image_folder / r["anomaly_map_file"]).resolve()
        if not path.is_relative_to(image_folder.resolve()):
            raise ValueError("Invalid map path")
        array = np.load(path, allow_pickle=False)["anomaly_map"]
        if gt["label"] == "normal":
            mask = np.zeros(array.shape, dtype=bool)
        else:
            mask_path = (truth_folder / gt["mask_file"]).resolve()
            if not mask_path.is_relative_to((truth_folder / "private_masks").resolve()):
                raise ValueError("Invalid mask path")
            mask = np.asarray(Image.open(mask_path).convert("L")) > 0
            if mask.shape != array.shape:
                raise ValueError("마스크와 원본 좌표 이상 지도 크기가 다릅니다.")
        binary = array > r["pixel_threshold"]
        tp += int(np.count_nonzero(binary & mask))
        fp += int(np.count_nonzero(binary & ~mask))
        fn += int(np.count_nonzero(~binary & mask))
        evaluated += 1
    return {
        "source": "PatchCore only; NOT VLM localization",
        "sample_count": evaluated,
        "missing_defect_masks": missing,
        "pixel_iou": fraction(tp, tp + fp + fn),
        "pixel_precision": fraction(tp, tp + fp),
        "pixel_recall": fraction(tp, tp + fn),
        "threshold_policy": "frozen normal-calibration pixel threshold",
    }


def evaluate(
    predictions: Path, truth_file: Path, output: Path, expected_ids=None, methods=None, image_folder=None
):
    # Loading truth happens only here, after predictions have been fully persisted.
    records = [json.loads(line) for line in predictions.read_text().splitlines() if line.strip()]
    if any(r.get("is_demo") for r in records):
        raise ValueError("데모 결과를 정식 평가에 포함할 수 없습니다.")
    truth = read_json(truth_file)
    expected_ids = set(expected_ids if expected_ids is not None else truth)
    methods = methods or sorted({r["method"] for r in records})
    if not expected_ids or not methods:
        raise ValueError("평가할 샘플 또는 방식이 없습니다.")
    pairs = [(r["method"], r["sample_id"]) for r in records]
    if len(set(pairs)) != len(pairs) or set(pairs) != {(m, i) for m in methods for i in expected_ids}:
        raise ValueError("방식별 평가 샘플 누락·중복·초과가 있습니다.")
    if not expected_ids <= set(truth):
        raise ValueError("정답이 없는 샘플입니다.")
    metrics = {
        "status": "evaluated",
        "is_demo": False,
        "methods": {},
        "sample_count": len(expected_ids),
        "explanation_review": "미평가",
        "warning": "낮은 불량 통과율은 coverage·보류·실패율과 함께 해석해야 합니다.",
    }
    if (output / "run_config.json").exists():
        config = read_json(output / "run_config.json")
        metrics["exploratory"] = config.get("exploratory", True)
        metrics["manifest_hash"] = config.get("manifest_hash")
    for method in methods:
        subset = [r for r in records if r["method"] == method]
        metrics["methods"][method] = method_metrics(subset, truth)
        if method == "patchcore_vlm":
            metrics["methods"][method]["vlm_raw"] = method_metrics(subset, truth, "vlm_decision")
        if method in {"patchcore", "patchcore_vlm"} and image_folder:
            metrics["methods"][method]["patchcore_localization"] = location_metrics(
                subset, truth, truth_file.parent, Path(image_folder)
            )
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "metrics.json", metrics)
    with (output / "comparison.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample_id",
                "truth",
                "method",
                "execution_status",
                "final_decision",
                "detector_decision",
                "vlm_decision",
                "error_code",
                "latency_ms",
                "cache_hit",
            ],
        )
        writer.writeheader()
        for r in records:
            writer.writerow(
                {k: truth[r["sample_id"]]["label"] if k == "truth" else r.get(k) for k in writer.fieldnames}
            )
    lines = [
        "# InspectMate 비교 실험",
        "",
        "연구·포트폴리오용 결과. 출하 승인 또는 제조 원인 진단이 아닙니다.",
        "",
        "| 방식 | 전체 | 성공 | 실패 | 판단 보류 | 자동 판정 coverage |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for method, m in metrics["methods"].items():
        lines.append(
            f"| {method} | {m['total']} | {m['succeeded']} | {m['failed']} | {m['uncertain']} | {m['automatic_coverage']['value']:.1%} |"
        )
    lines += [
        "",
        "상세 교차표·분모·N/A 사유: metrics.json. 설명 정확성: 수동 검토 전 미평가.",
        "캐시 조회는 latency에 포함하지 않습니다. 외부 VLM의 사전학습 데이터 오염 여부는 확인되지 않았습니다.",
        "탐색/최종 평가 구분과 모델·프롬프트·분할·실행 환경은 run_config.json에 기록합니다.",
        f"실험 구분: {'exploratory' if metrics.get('exploratory', True) else 'frozen final configuration (user-declared)'}",
    ]
    (output / "report.md").write_text("\n".join(lines))
    return metrics
