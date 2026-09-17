# Limitations and unverified work

## Not measured

- One real B inspection was completed with user authorization on 2026-09-17. This verifies a live response, structured parsing and persistence for that run; it does not establish VLM accuracy or full A/B/C/D performance. See `reports/live-vlm-verification.json`.
- The live response's recommended action suggested passing without further review. This wording has not been independently validated and is not a production release authorization. Natural-language output still requires manual review; schema validation only checks structure.
- Full official test evaluation: not run. The local metal_nut archive is now installed from a public mirror, its published checksum verified, and the manifest frozen at 176 fit / 44 calibration / 115 test. No comparative accuracy, improvement, saved cost or production-readiness claim.
- Pretrained resnet18 PatchCore at 256px has now been fitted on real normal images and calibrated separately. Five selected test-image uploads are an exploratory functional check, not a representative benchmark. Random-weight test artifacts remain separately flagged smoke and blocked from normal inspection.
- Full A/B/C/D live comparison, real refusal/rate-limit timing and small-defect localization quality: unverified.
- Browser visual/click QA and optional WebMCP runtime: not performed. Frontend TypeScript/production build and localhost HTTP were tested; API interaction tests cover the server workflow.

## Prototype constraints

- One backend process, local user, loopback only. No authentication or shared/public hosting. User requested Python/SQLite/local image storage, so no Cloudflare Sites deployment was performed.
- CPU baseline resnet18. Model initialization currently occurs per C/D inspection; measured detector time includes loading and is not optimized steady-state serving latency.
- UI shows one server-configured category. Change DEFAULT_CATEGORY and prepare its own manifest/artifact to use another category. One fixed reference is the implemented protocol; 3-reference and similarity retrieval are future, separate experiments.
- History API returns the most recent 200 matched inspections, experiments most recent 50. Evaluation case UI shows first 40 filtered cases; complete comparison CSV remains available.
- No automatic resumption of a terminated experiment. At startup, unfinished records are marked interrupted/failed with an unknown outcome; partial predictions are preserved. Re-run in a new experiment; do not silently compare incomplete ID sets.
- One external-call budget per backend process / CLI run. Restart resets counters. Unknown usage is conservatively reserved. Dollar estimates use configured prices and can differ from billing; no price is invented.
- Live call cancellation cannot recall an already sent request. Batch cancellation prevents subsequent attempts; single-inspection browser cancellation only stops waiting.
- D with a cached VLM response still runs the detector. Whole combined latency is omitted from non-cache latency metrics; detector_latency_ms remains separately available.
- Model names are environment-configurable; default snapshot capabilities were verified. An arbitrary replacement model may reject image inputs, JSON Schema or temperature and must be separately validated.
- Manual explanation reviews do not establish clinical/industrial safety or causal correctness. No VLM subjective confidence percentage is shown.

## Next verification steps

1. Continue granting per-run consent for additional image transmissions and review the returned observations and recommended actions against the actual images.
2. Run a ≤10-sample exploratory A/B preview, then freeze the protocol before any claimed final comparison.
3. Review 2×4 confusion, coverage, failures, detector raw results, explanations and cost/latency together. Keep the already-installed test data out of any fit/calibration or reference selection.
