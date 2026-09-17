import io

import pytest
from inspectmate.config import Settings
from PIL import Image


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        inspectmate_data_dir=tmp_path / "app",
        openai_api_key="test-not-a-real-key",
        allow_external_api=True,
        max_retries=0,
    )


def image_bytes(color=(100, 110, 120), size=(80, 40)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def dataset_root(tmp_path):
    """Generated test fixtures ONLY. Not real MVTec data or performance evidence."""
    root = tmp_path / "fixtures" / "metal_nut"
    for part in ("train/good", "test/good", "test/scratch", "ground_truth/scratch"):
        (root / part).mkdir(parents=True)
    for i in range(10):
        (root / "train/good" / f"{i}.png").write_bytes(image_bytes((i * 13, 40, 80)))
    (root / "test/good/a.png").write_bytes(image_bytes((220, 40, 80)))
    (root / "test/scratch/b.png").write_bytes(image_bytes((240, 40, 80)))
    Image.new("L", (80, 40), 255).save(root / "ground_truth/scratch/b_mask.png")
    return root.parent
