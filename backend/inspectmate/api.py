from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import FOLLOWUP_PROMPT_VERSION, PROMPT_VERSION, Settings
from .dataset import load_manifest
from .images import ImageError, decode_image, pixel_hash, png_bytes
from .providers import ProviderError
from .schemas import ExperimentRequest, InspectionRequest, QuestionRequest, ReviewRequest
from .service import InspectionService
from .storage import Store


def create_app(settings=None, provider=None):
    s = settings or Settings()
    store = Store(s.root)
    store.recover_interrupted()
    service = InspectionService(s, store, provider)
    app = FastAPI(title="InspectMate", version="0.1.0")
    app.state.service = service
    app.state.store = store
    origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8740",
        "http://127.0.0.1:8740",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("origin") not in [
            None,
            *origins,
        ]:
            return JSONResponse({"detail": "허용되지 않은 요청 출처"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        return JSONResponse({"detail": str(exc)}, 404)

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({"detail": str(exc), "error_code": exc.code}, 400)

    @app.get("/api/status")
    def status():
        folder = service.manifest_folder(s.default_category)
        manifest = None
        error = None
        if (folder / "inference_manifest.json").exists():
            try:
                manifest = load_manifest(folder)
            except ValueError as exc:
                error = str(exc)
        return {
            "api_key_configured": bool(s.openai_api_key),
            "external_api_enabled": s.allow_external_api,
            "model": s.openai_model,
            "inspection_prompt_version": PROMPT_VERSION,
            "followup_prompt_version": FOLLOWUP_PROMPT_VERSION,
            "category": s.default_category,
            "data_ready": bool(manifest),
            "data_error": error,
            "counts": manifest["counts"] if manifest else None,
            "reference_ids": manifest["reference_ids"] if manifest else [],
            "detector_ready": (store.root / "detectors" / s.default_category / "metadata.json").exists(),
            "requests_used": service.budget.requests,
            "request_limit": s.max_external_requests,
            "max_retries": s.max_retries,
            "cost_configured": s.input_usd_per_million is not None and s.output_usd_per_million is not None,
            "notice": "연구·포트폴리오용 검사 지원. 실제 출하 승인에 사용할 수 없습니다.",
        }

    @app.post("/api/assets")
    async def upload(file: UploadFile = File(...)):
        raw = await file.read(s.max_upload_bytes + 1)
        await file.close()
        try:
            image = decode_image(raw, s.max_upload_bytes, s.max_pixels)
        except ImageError as exc:
            raise HTTPException(422, str(exc)) from exc
        return store.asset(png_bytes(image), pixel_hash(image), *image.size)

    @app.post("/api/demo/sample")
    def demo_sample():
        return service.demo_asset()

    @app.get("/api/assets/{asset_id}")
    def asset(asset_id: str):
        return FileResponse(store.asset_path(asset_id), media_type="image/png")

    @app.get("/api/references/{category}")
    def references(category: str):
        _, refs = service.references(category)
        result = []
        for ref in refs:
            image = decode_image(ref.png)
            result.append({**store.asset(ref.png, pixel_hash(image), *image.size), "image_id": ref.image_id})
        return result

    @app.post("/api/inspections")
    async def inspect(req: InspectionRequest):
        return await service.inspect(req)

    @app.get("/api/inspections")
    def history(
        category: str | None = None,
        method: str | None = None,
        decision: str | None = None,
        status: str | None = None,
    ):
        return store.history(category, method, decision, status)

    @app.get("/api/inspections/{inspection_id}")
    def inspection(inspection_id: str):
        return store.inspection(inspection_id)

    @app.patch("/api/inspections/{inspection_id}/review")
    def review(inspection_id: str, req: ReviewRequest):
        record = store.inspection(inspection_id)
        record["human_review_status"] = req.status
        record["human_review"] = req.model_dump()
        store.save_inspection(record)
        return record

    @app.post("/api/inspections/{inspection_id}/questions")
    async def question(inspection_id: str, req: QuestionRequest):
        return await service.followup(inspection_id, req.question, req.external_consent)

    @app.get("/api/inspections/{inspection_id}/heatmap")
    def heatmap(inspection_id: str):
        record = store.inspection(inspection_id)
        if not record.get("heatmap_file"):
            raise HTTPException(404, "이 검사에는 실제 이상 지도가 없습니다.")
        return FileResponse(store.root / "images" / record["heatmap_file"], media_type="image/png")

    # Experiment runner is lazy-imported so optional detector libraries never block P0.
    from .experiments import ExperimentManager

    manager = ExperimentManager(service)
    app.state.experiments = manager

    @app.post("/api/experiments/preview")
    def preview(req: ExperimentRequest):
        return manager.preview(req)

    @app.post("/api/experiments")
    async def start_experiment(req: ExperimentRequest):
        return manager.start(req)

    @app.get("/api/experiments")
    def experiments():
        return store.experiments()

    @app.get("/api/experiments/{experiment_id}")
    def experiment(experiment_id: str):
        return store.experiment(experiment_id)

    @app.post("/api/experiments/{experiment_id}/cancel")
    def cancel(experiment_id: str):
        return manager.cancel(experiment_id)

    @app.get("/api/experiments/{experiment_id}/download/{name}")
    def download(experiment_id: str, name: str):
        store.experiment(experiment_id)
        if name not in {
            "predictions.jsonl",
            "metrics.json",
            "comparison.csv",
            "report.md",
            "run_config.json",
        }:
            raise HTTPException(404)
        path = store.root / "experiments" / experiment_id / name
        if not path.exists():
            raise HTTPException(404, "아직 생성되지 않은 산출물입니다.")
        return FileResponse(path, filename=name)

    @app.get("/api/experiments/{experiment_id}/cases")
    def cases(experiment_id: str):
        return manager.cases(experiment_id)

    @app.get("/api/experiments/{experiment_id}/masks/{sample_id}")
    def mask(experiment_id: str, sample_id: str):
        path = manager.review_mask(experiment_id, sample_id)
        return FileResponse(path, media_type="image/png")

    return app


app = create_app()
