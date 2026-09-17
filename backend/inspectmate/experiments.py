import asyncio
import json
import platform
import uuid
from importlib.metadata import PackageNotFoundError, version

from .config import CRITERIA, CRITERIA_VERSION, PREPROCESS_VERSION, PROMPT_VERSION, SYSTEM_PROMPT
from .dataset import input_path, load_manifest, read_json, write_json
from .images import decode_image, pixel_hash, png_bytes
from .providers import ProviderError
from .schemas import InspectionRequest
from .storage import now


def runtime_info():
    packages = {}
    for package in ("openai", "fastapi", "pydantic", "numpy", "pillow", "torch", "torchvision", "anomalib"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "local_detector_device": "cpu",
        "remote_provider_hardware": "unknown",
        "packages": packages,
    }


class ExperimentManager:
    def __init__(self, service):
        self.service, self.store = service, service.store
        self.tasks, self.cancelled = {}, set()

    def preview(self, req):
        folder = self.service.manifest_folder(req.category)
        if not (folder / "inference_manifest.json").exists():
            raise ProviderError("data_missing", "데이터 manifest를 먼저 생성하세요.")
        manifest = load_manifest(folder)
        methods = list(dict.fromkeys(req.methods))
        test = [x for x in manifest["entries"] if x["split"] == "test"]
        count = len(test) if req.full_evaluation else min(10, req.sample_limit, len(test))
        calls = count * sum(m != "patchcore" for m in methods)
        return {
            "sample_count": count,
            "available_samples": len(test),
            "planned_api_calls": calls,
            "maximum_attempts": calls * (self.service.settings.max_retries + 1),
            "request_limit": self.service.settings.max_external_requests,
            "cost_usd": None,
            "cost_status": "미산정",
            "methods": methods,
            "manifest_hash": manifest["manifest_hash"],
            "reference_ids": manifest["reference_ids"],
            "exploratory": req.exploratory,
            "full_evaluation": req.full_evaluation,
        }

    def start(self, req):
        if any(not task.done() for task in self.tasks.values()):
            raise ProviderError("experiment_busy", "한 번에 하나의 비교 실험만 실행할 수 있습니다.")
        preview = self.preview(req)
        if preview["planned_api_calls"]:
            self.service.provider.authorize(req.external_consent)
        eid = uuid.uuid4().hex
        record = {
            "experiment_id": eid,
            "created_at": now(),
            "status": "running",
            "completed": 0,
            "total": preview["sample_count"] * len(preview["methods"]),
            "preview": preview,
            "request": req.model_dump(),
            "metrics": None,
            "error": None,
        }
        self.store.save_experiment(record)
        self.tasks[eid] = asyncio.create_task(self.run(eid, req))
        return record

    async def run(self, eid, req):
        try:
            return await self._run(eid, req)
        except Exception as exc:
            record = self.store.experiment(eid)
            record.update(status="failed", error=str(exc), finished_at=now())
            self.store.save_experiment(record)
            return record

    async def _run(self, eid, req):
        record = self.store.experiment(eid)
        destination = self.store.root / "experiments" / eid
        destination.mkdir(parents=True, exist_ok=True)
        folder = self.service.manifest_folder(req.category)
        manifest = load_manifest(folder)
        test = sorted((x for x in manifest["entries"] if x["split"] == "test"), key=lambda x: x["sample_id"])
        if not req.full_evaluation:
            test = test[: min(10, req.sample_limit)]
        methods = list(dict.fromkeys(req.methods))
        config = {
            **runtime_info(),
            "created_at": record["created_at"],
            "request": req.model_dump(exclude={"external_consent"}),
            "external_consent_recorded": req.external_consent,
            "model": self.service.settings.openai_model,
            "prompt_version": PROMPT_VERSION,
            "prompt": SYSTEM_PROMPT,
            "criteria_version": CRITERIA_VERSION,
            "criteria": CRITERIA,
            "preprocessing": PREPROCESS_VERSION,
            "temperature": 0,
            "max_output_tokens": self.service.settings.max_output_tokens,
            "reference_ids": manifest["reference_ids"],
            "manifest_hash": manifest["manifest_hash"],
            "split_hash": manifest["split_hash"],
            "sample_ids": [r["sample_id"] for r in test],
            "benchmark_pretraining_contamination": "unknown",
            "exploratory": req.exploratory,
        }
        write_json(destination / "run_config.json", config)
        try:
            with (destination / "predictions.jsonl").open("w") as writer:
                for entry in test:
                    input_error = None
                    try:
                        im = decode_image(input_path(folder, entry).read_bytes(), max_bytes=100 * 1024 * 1024)
                        asset = self.store.asset(png_bytes(im), pixel_hash(im), *im.size)
                    except (ValueError, OSError) as exc:
                        input_error = str(exc)
                    for method in methods:
                        if input_error:
                            result = {
                                "sample_id": entry["sample_id"],
                                "method": method,
                                "execution_status": "failed",
                                "error_code": "input_integrity_error",
                                "error_message": input_error,
                                "is_demo": False,
                                "final_decision": None,
                                "latency_ms": None,
                            }
                        elif eid in self.cancelled:
                            result = {
                                "sample_id": entry["sample_id"],
                                "method": method,
                                "execution_status": "failed",
                                "error_code": "cancelled",
                                "is_demo": False,
                                "final_decision": None,
                                "latency_ms": None,
                            }
                        else:
                            request = InspectionRequest(
                                asset_id=asset["asset_id"],
                                category=req.category,
                                method=method,
                                provider="openai",
                                external_consent=req.external_consent,
                                use_cache=req.use_cache,
                            )
                            result = await self.service.inspect(
                                request, entry["sample_id"], lambda: eid in self.cancelled
                            )
                        writer.write(json.dumps(result, ensure_ascii=False) + "\n")
                        writer.flush()
                        record["completed"] += 1
                        self.store.save_experiment(record)
                        await asyncio.sleep(0)
            # The prediction file is CLOSED before any evaluator truth is read.
            from .evaluation import evaluate

            record["metrics"] = evaluate(
                destination / "predictions.jsonl",
                folder / "evaluator_truth.json",
                destination,
                config["sample_ids"],
                methods,
                self.store.root / "images",
            )
            record["status"] = "cancelled" if eid in self.cancelled else "completed"
            report = destination / "report.md"
            report.write_text(
                report.read_text()
                + f"\n\n실험 구분: {'exploratory' if req.exploratory else 'frozen final configuration (user-declared)'}\n"
            )
        except Exception as exc:
            record["status"], record["error"] = "failed", str(exc)
        record["finished_at"] = now()
        self.store.save_experiment(record)
        return record

    def cancel(self, eid):
        record = self.store.experiment(eid)
        if record["status"] == "running":
            self.cancelled.add(eid)
            record["cancel_requested"] = True
            self.store.save_experiment(record)
        return record

    def cases(self, eid):
        record = self.store.experiment(eid)
        if record["status"] not in {"completed", "cancelled"}:
            raise ProviderError("evaluation_not_ready", "평가 완료 후 정답을 검토할 수 있습니다.")
        folder = self.service.manifest_folder(record["request"]["category"])
        truth = read_json(folder / "evaluator_truth.json")
        predictions = self.store.root / "experiments" / eid / "predictions.jsonl"
        return [
            {
                **r,
                "truth": truth[r["sample_id"]]["label"],
                "mask_available": bool(truth[r["sample_id"]]["mask_file"]),
            }
            for r in (json.loads(line) for line in predictions.read_text().splitlines())
        ]

    def review_mask(self, eid, sample_id):
        cases = self.cases(eid)
        if not any(c["sample_id"] == sample_id for c in cases):
            raise KeyError("평가 대상이 아닙니다.")
        record = self.store.experiment(eid)
        folder = self.service.manifest_folder(record["request"]["category"])
        relative = read_json(folder / "evaluator_truth.json")[sample_id]["mask_file"]
        if not relative:
            raise KeyError("정답 마스크 없음")
        path = (folder / relative).resolve()
        if not path.is_relative_to((folder / "private_masks").resolve()):
            raise ValueError("Invalid mask path")
        return path
