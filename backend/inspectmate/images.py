import hashlib
import io
import warnings
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError


class ImageError(ValueError):
    pass


def decode_image(raw: bytes, max_bytes=10 * 1024 * 1024, max_pixels=20_000_000) -> Image.Image:
    if not raw or len(raw) > max_bytes:
        raise ImageError("이미지 용량은 10MB 이하여야 합니다.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as im:
                if im.format not in {"PNG", "JPEG", "WEBP"} or getattr(im, "n_frames", 1) != 1:
                    raise ImageError("정지 PNG, JPEG, WEBP 이미지만 지원합니다.")
                if im.width * im.height > max_pixels:
                    raise ImageError("최대 픽셀 수를 초과했습니다.")
                im.load()
                return ImageOps.exif_transpose(im).convert("RGB")
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ImageError("디코딩할 수 없는 이미지입니다.") from exc


def png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def pixel_hash(im: Image.Image) -> str:
    return hashlib.sha256(f"RGB:{im.size}".encode() + im.tobytes()).hexdigest()


def vlm_image(path: Path) -> bytes:
    # Internal RGB PNG may be larger than its already-validated compressed upload.
    image = decode_image(path.read_bytes(), max_bytes=100 * 1024 * 1024)
    image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    return png_bytes(image)


def letterbox(im: Image.Image, size=256):
    ratio = min(size / im.width, size / im.height)
    width, height = max(1, round(im.width * ratio)), max(1, round(im.height * ratio))
    left, top = (size - width) // 2, (size - height) // 2
    canvas = Image.new("RGB", (size, size), (0, 0, 0))
    canvas.paste(im.resize((width, height), Image.Resampling.BILINEAR), (left, top))
    return canvas, {
        "original_width": im.width,
        "original_height": im.height,
        "width": width,
        "height": height,
        "left": left,
        "top": top,
        "size": size,
    }


def restore_map(array: np.ndarray, transform: dict) -> np.ndarray:
    size = transform["size"]
    image = Image.fromarray(np.asarray(array, dtype=np.float32)).resize(
        (size, size), Image.Resampling.BILINEAR
    )
    x, y, w, h = (transform[k] for k in ("left", "top", "width", "height"))
    image = image.crop((x, y, x + w, y + h))
    return np.asarray(
        image.resize((transform["original_width"], transform["original_height"]), Image.Resampling.BILINEAR)
    )
