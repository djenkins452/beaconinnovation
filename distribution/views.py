"""Serve Beacon product release artifacts at /downloads/<product>/.

Physical files live in ``<BASE_DIR>/downloads/<product>/`` and are written by the
Beacon Release Engine. This app serves them directly (not through the WhiteNoise
/static/ pipeline) so iOS OTA installs get correct content types and no redirects
on the manifest or IPA.

Generic: one product path parameter, no per-product code. Adding a product means
new files under ``downloads/<product>/`` — no changes here.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404


def _downloads_root() -> Path:
    return Path(getattr(settings, "DOWNLOADS_ROOT", Path(settings.BASE_DIR) / "downloads"))


_CONTENT_TYPES = {
    ".ipa": "application/octet-stream",
    ".plist": "text/xml; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
}


def _safe_file(product: str, rel_path: str) -> Path:
    root = _downloads_root().resolve()
    target = (root / product / rel_path).resolve()
    # prevent path traversal outside the downloads root
    if root not in target.parents and target != root:
        raise Http404("Not found")
    if not target.is_file():
        raise Http404("Not found")
    return target


def _file_response(target: Path) -> FileResponse:
    ctype = _CONTENT_TYPES.get(target.suffix.lower()) or \
        (mimetypes.guess_type(str(target))[0] or "application/octet-stream")
    resp = FileResponse(open(target, "rb"), content_type=ctype)
    # allow OTA clients / browsers to cache briefly; artifacts are immutable per release
    resp["Cache-Control"] = "public, max-age=300"
    return resp


def serve_download(request, product, path):
    """Serve downloads/<product>/<path> with a correct content type."""
    return _file_response(_safe_file(product, path))


def download_index(request, product):
    """Serve the product's Release Portal (install.html)."""
    return _file_response(_safe_file(product, "install.html"))
