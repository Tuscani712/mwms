"""Profile picture uploads — hardened image sanitization.

Strategy: never trust the client's filename or Content-Type. Decode with Pillow,
verify it's actually a parseable image of an allowed format, then **re-encode**
to the canonical format. This strips EXIF/ICC metadata and breaks polyglots
(files that are valid as both an image and as HTML/JS, etc.).
"""

from __future__ import annotations

import io
import secrets
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# (Pillow format-name, canonical extension, save kwargs)
_ALLOWED: dict[str, tuple[str, dict]] = {
    "PNG": ("png", {"format": "PNG", "optimize": True}),
    "JPEG": ("jpg", {"format": "JPEG", "quality": 88, "optimize": True}),
    "WEBP": ("webp", {"format": "WEBP", "quality": 88}),
    "GIF": ("gif", {"format": "GIF"}),
}


def sanitize_image(
    data: bytes, *, max_bytes: int, max_dim: int
) -> tuple[bytes, str]:
    """Validate + re-encode. Returns (clean_bytes, canonical_extension).

    Raises ValueError on any issue: oversize, unsupported format, dimensions
    too large, or undecodable file.
    """
    if not data:
        raise ValueError("Empty file")
    if len(data) > max_bytes:
        raise ValueError(f"File too large (>{max_bytes // (1024 * 1024)} MB)")

    # First pass: verify() catches structural corruption without decoding pixels.
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise ValueError("Not a valid image file") from e

    # Second pass: actually decode (verify() consumes the stream).
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError("Image could not be decoded") from e

    fmt = (img.format or "").upper()
    if fmt not in _ALLOWED:
        raise ValueError(
            f"Unsupported image format '{fmt or 'unknown'}' — "
            "allowed: PNG, JPEG, WebP, GIF (SVG/BMP/TIFF explicitly rejected)"
        )

    w, h = img.size
    if w > max_dim or h > max_dim:
        raise ValueError(f"Image too large ({w}×{h}, max {max_dim}×{max_dim})")
    if w == 0 or h == 0:
        raise ValueError("Image has zero dimensions")

    ext, save_kwargs = _ALLOWED[fmt]

    # Re-encode through a fresh buffer. Flatten alpha for JPEG (which has no alpha).
    out = io.BytesIO()
    if fmt == "JPEG" and img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.save(out, **save_kwargs)
    return out.getvalue(), ext


def save_avatar(
    data: bytes, *, user_id: int, upload_dir: Path, max_bytes: int, max_dim: int
) -> tuple[str, str]:
    """Sanitize + persist. Returns (public_url, absolute_path_str)."""
    clean, ext = sanitize_image(data, max_bytes=max_bytes, max_dim=max_dim)
    upload_dir.mkdir(parents=True, exist_ok=True)
    name = f"{user_id}-{secrets.token_hex(6)}.{ext}"
    path = upload_dir / name
    path.write_bytes(clean)
    return f"/uploads/avatars/{name}", str(path)
