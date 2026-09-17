# Data card

- Intended dataset: MVTec Anomaly Detection (MVTec AD), initial category **metal_nut**.
- Source: [MVTec official dataset](https://www.mvtec.com/research-teaching/datasets/mvtec-ad).
- Publisher description: normal training images; normal and defective test images; pixel-level defect masks.
- Local status, updated 2026-09-16: **metal_nut installed** under `datasets/mvtec_ad/metal_nut`. 220 normal training images, 115 test images (22 normal / 93 anomalous), and 93 masks. Formal comparative evaluation is not yet performed. Dataset files are excluded from Git and the source-only ZIP.
- Download source: [public archive mirror, pinned revision](https://huggingface.co/datasets/XavierZXY/MvT-tar/tree/dc1c313de9de1be8e41fe6818dc43caac8601efa). The historical MyDrive category URL returned 404. The 165,414,484-byte archive matched the mirror's published SHA256 `86e3c8e163ceb19146ad3ddc408e85cc34ae02e0da430e07a73bac6bbb48532a`. This is mirror integrity verification, not a separately publisher-certified checksum. Original `license.txt` and `readme.txt` are retained; download details are in `datasets/mvtec_ad/metal_nut/DOWNLOAD_PROVENANCE.json`.
- Installed split: 176 fit normal / 44 calibration normal / 115 official test. Five copies for manual upload are in `data/quick_test/metal_nut`; these are exploratory examples and remain separate from model fitting and threshold selection.
- Unit: individual product image. RGB/EXIF-normalized content hash and source file SHA-256 retained.
- Split: seed=42, normal hash-group 80/20 fit/calibration; official test preserved.
- Labels: normal/defect only joined offline after predictions are written. Defect folder names never enter model payloads.
- Reference: fixed single fit_normal image, never calibration/test.
- Test fixtures: programmatically generated small color images used solely for tests; **not MVTec, not performance evidence**.
- Demo: explicit geometric UI fixture; no model inference; official evaluator rejects demo records.

## Usage conditions

MVTec AD uses **CC BY-NC-SA 4.0** with non-commercial restriction; refer to the publisher's current terms. Source attribution and applicable share-alike obligations remain with redistributed adaptations. This project's MIT code license does **not** relicense the dataset. Third-party backbone/model weights and API service terms are separate.

Do not commit the raw dataset, masks, API credentials, user uploads, DBs or large model files. These are ignored under data/artifacts/datasets. Curated documentation GIFs, the example gallery, and the diagnosis figure are the explicit media exception; their source and CC BY-NC-SA 4.0 conditions are recorded in [docs/media/ATTRIBUTION.md](docs/media/ATTRIBUTION.md). Do not represent these benchmark samples as data from a deployed factory line. Real factory images may need separate permissions before external API transmission.

Limits: single-category scope, controlled benchmark imagery, unknown external VLM pretraining contamination, no verified physical defect dimensions, no process history or material composition labels. No causal manufacturing diagnosis is supported.
