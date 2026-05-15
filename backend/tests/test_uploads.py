"""Profile picture upload — sanitization, format whitelist, and approval flow."""

import io
import shutil
from pathlib import Path

import pytest
from PIL import Image

from wms.core.config import get_settings


@pytest.fixture(autouse=True)
def isolated_upload_dir(tmp_path, monkeypatch):
    """Each test gets its own upload dir so files don't leak between tests."""
    settings = get_settings()
    original = settings.upload_dir
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))
    yield upload_dir
    if Path(original).exists() and Path(original) != upload_dir:
        # Belt-and-suspenders: don't accidentally trash dev data
        pass
    shutil.rmtree(upload_dir, ignore_errors=True)


def _png_bytes(w: int = 32, h: int = 32, color=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(w: int = 32, h: int = 32) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (0, 128, 255)).save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def _webp_bytes(w: int = 32, h: int = 32) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (0, 255, 0)).save(buf, format="WEBP")
    return buf.getvalue()


def test_upload_accepts_png(client, auth_headers, isolated_upload_dir):
    r = client.post(
        "/api/v1/profile/picture/upload",
        files={"file": ("avatar.png", _png_bytes(), "image/png")},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"].startswith("/uploads/avatars/")
    assert body["url"].endswith(".png")
    # File actually written to disk
    saved = isolated_upload_dir / "avatars" / Path(body["url"]).name
    assert saved.exists()
    assert saved.stat().st_size > 0


def test_upload_accepts_jpeg_and_returns_jpg_extension(client, auth_headers):
    r = client.post(
        "/api/v1/profile/picture/upload",
        files={"file": ("photo.jpeg", _jpeg_bytes(), "image/jpeg")},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["url"].endswith(".jpg")


def test_upload_accepts_webp(client, auth_headers):
    r = client.post(
        "/api/v1/profile/picture/upload",
        files={"file": ("a.webp", _webp_bytes(), "image/webp")},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["url"].endswith(".webp")


def test_upload_rejects_text_disguised_as_png(client, auth_headers):
    """Lying Content-Type and filename — server must verify by decoding."""
    r = client.post(
        "/api/v1/profile/picture/upload",
        files={"file": ("trojan.png", b"this is plain text, not an image", "image/png")},
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert "valid image" in r.json()["detail"].lower()


def test_upload_rejects_svg(client, auth_headers):
    """SVG can embed <script> — explicitly out of the whitelist."""
    svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    r = client.post(
        "/api/v1/profile/picture/upload",
        files={"file": ("evil.svg", svg, "image/svg+xml")},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_upload_rejects_oversize(client, auth_headers, monkeypatch):
    """Cap is enforced before the whole body lands in memory."""
    settings = get_settings()
    monkeypatch.setattr(settings, "max_upload_bytes", 1024)  # 1 KB cap for the test
    big_png = _png_bytes(512, 512)  # ~1KB+, well over the cap
    r = client.post(
        "/api/v1/profile/picture/upload",
        files={"file": ("big.png", big_png, "image/png")},
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert "too large" in r.json()["detail"].lower()


def test_upload_rejects_oversized_dimensions(client, auth_headers, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "max_image_dimension", 64)
    r = client.post(
        "/api/v1/profile/picture/upload",
        files={"file": ("huge.png", _png_bytes(128, 128), "image/png")},
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert "too large" in r.json()["detail"].lower()


def test_uploaded_url_flows_through_approval_request(client, auth_headers):
    """End-to-end: upload → URL → display-picture-request → pending approval row."""
    up = client.post(
        "/api/v1/profile/picture/upload",
        files={"file": ("a.png", _png_bytes(), "image/png")},
        headers=auth_headers,
    ).json()

    r = client.post(
        "/api/v1/profile/display-picture-request",
        json={"requested_value": up["url"]},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["field_name"] == "display_picture"
    assert body["requested_value"] == up["url"]


def test_polyglot_re_encoding_strips_appended_payload(client, auth_headers, isolated_upload_dir):
    """A real PNG with garbage appended after the IEND chunk should be re-encoded
    and the trailing payload dropped on disk."""
    original = _png_bytes(16, 16)
    poisoned = original + b"<script>alert('xss')</script>" * 10
    r = client.post(
        "/api/v1/profile/picture/upload",
        files={"file": ("a.png", poisoned, "image/png")},
        headers=auth_headers,
    )
    assert r.status_code == 200
    saved = isolated_upload_dir / "avatars" / Path(r.json()["url"]).name
    written = saved.read_bytes()
    # The re-encoded file should not contain the appended HTML payload.
    assert b"<script>" not in written
    assert b"alert" not in written


def test_upload_filename_does_not_use_client_input(client, auth_headers):
    """Even if the client claims `../../etc/passwd`, the saved path is server-generated."""
    r = client.post(
        "/api/v1/profile/picture/upload",
        files={"file": ("../../etc/passwd", _png_bytes(), "image/png")},
        headers=auth_headers,
    )
    assert r.status_code == 200
    url = r.json()["url"]
    assert ".." not in url
    assert url.startswith("/uploads/avatars/")
    # Saved name only contains user_id-hex.ext
    name = Path(url).name
    assert "/" not in name and "\\" not in name
