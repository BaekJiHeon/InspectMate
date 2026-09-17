import argparse
import asyncio
import json
from pathlib import Path

from .config import Settings
from .dataset import build_manifest, load_manifest, read_json
from .experiments import ExperimentManager
from .schemas import ExperimentRequest
from .service import InspectionService
from .storage import Store


def main():
    parser = argparse.ArgumentParser(description="InspectMate local research workflow")
    commands = parser.add_subparsers(dest="command", required=True)
    data = commands.add_parser(
        "manifest", help="Validate user-provided MVTec data and freeze hash-group split"
    )
    data.add_argument("--root", type=Path)
    data.add_argument("--category", default=None)
    fit = commands.add_parser("detector-fit", help="Fit memory bank then calibrate on held-out normals")
    fit.add_argument("--category", default=None)
    fit.add_argument("--size", type=int, default=256, choices=[128, 256, 384])
    predict = commands.add_parser("detector-predict", help="Local detector inference, no VLM")
    predict.add_argument("image", type=Path)
    predict.add_argument("--category", default=None)
    run = commands.add_parser(
        "experiment", help="Run identical test samples; explicit consent required for VLM"
    )
    run.add_argument("--category", default=None)
    run.add_argument("--methods", nargs="+", default=["vlm_only", "vlm_reference"])
    run.add_argument("--limit", type=int, default=10)
    run.add_argument("--full", action="store_true")
    run.add_argument(
        "--final", action="store_true", help="Declare frozen configuration; otherwise exploratory"
    )
    run.add_argument("--consent-external", action="store_true")
    run.add_argument("--execute", action="store_true", help="Without this flag, only show call preview")
    ev = commands.add_parser("evaluate", help="Offline evaluation after saving all predictions")
    ev.add_argument("run_directory", type=Path)
    ev.add_argument("--category", default=None)
    report = commands.add_parser(
        "report", help="Regenerate CSV/metrics/report from a completed prediction file"
    )
    report.add_argument("run_directory", type=Path)
    report.add_argument("--category", default=None)
    commands.add_parser("status")
    args = parser.parse_args()
    s = Settings()
    category = getattr(args, "category", None) or s.default_category
    folder = s.root / "manifests" / category
    try:
        if args.command == "manifest":
            root = args.root or s.mvtec_root
            if root is None:
                parser.error("MVTEC_ROOT 또는 --root로 실제 MVTec AD 폴더를 지정하세요. README 참고.")
            manifest = build_manifest(root, category, folder)
            print(
                json.dumps(
                    {
                        "counts": manifest["counts"],
                        "split_hash": manifest["split_hash"],
                        "reference_ids": manifest["reference_ids"],
                    },
                    indent=2,
                )
            )
        elif args.command == "detector-fit":
            from .detector import fit_detector

            metadata = fit_detector(folder, s.root / "detectors" / category, {"size": args.size})
            print(
                json.dumps(
                    {
                        k: metadata[k]
                        for k in ("image_threshold", "pixel_threshold", "calibration_count", "config_hash")
                    },
                    indent=2,
                )
            )
        elif args.command == "detector-predict":
            import uuid

            from .detector import Detector

            result = Detector(s.root / "detectors" / category, folder).predict(
                args.image, s.root / "images", uuid.uuid4().hex
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "experiment":
            req = ExperimentRequest(
                category=category,
                methods=args.methods,
                sample_limit=args.limit,
                full_evaluation=args.full,
                exploratory=not args.final,
                external_consent=args.consent_external,
            )
            manager = ExperimentManager(InspectionService(s, Store(s.root)))
            print(json.dumps(manager.preview(req), ensure_ascii=False, indent=2))
            if args.execute:

                async def execute():
                    started = manager.start(req)
                    await manager.tasks[started["experiment_id"]]
                    result = manager.store.experiment(started["experiment_id"])
                    print(
                        json.dumps(
                            {
                                "status": result["status"],
                                "processed": result["completed"],
                                "output": str(s.root / "experiments" / started["experiment_id"]),
                            },
                            indent=2,
                        )
                    )

                asyncio.run(execute())
        elif args.command in {"evaluate", "report"}:
            from .evaluation import evaluate

            config = read_json(args.run_directory / "run_config.json")
            current = load_manifest(folder)
            if current["manifest_hash"] != config["manifest_hash"]:
                raise ValueError("실험과 evaluator 데이터 manifest가 일치하지 않습니다.")
            evaluate(
                args.run_directory / "predictions.jsonl",
                folder / "evaluator_truth.json",
                args.run_directory,
                config["sample_ids"],
                config["request"]["methods"],
                s.root / "images",
            )
            print("metrics.json, comparison.csv, report.md 생성 완료")
        else:
            print(
                json.dumps(
                    {
                        "api_key_configured": bool(s.openai_api_key),
                        "external_api_enabled": s.allow_external_api,
                        "manifest_present": (folder / "inference_manifest.json").exists(),
                        "category": category,
                    },
                    indent=2,
                )
            )
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        parser.exit(2, f"설정/실행 오류: {exc}\n")


if __name__ == "__main__":
    main()
