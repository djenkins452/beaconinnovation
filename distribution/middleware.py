"""Config-driven legacy redirects.

When a product moves to its ``/downloads/<product>/`` namespace, its old URLs are
listed in ``release.yaml`` (``deploy.legacy_redirects``). The Release Engine writes
those into ``downloads/_redirects.json`` as ``{legacy_path: canonical_path}``. This
middleware issues a 301 for any registered legacy path — so old bookmarks, QR
codes, and text-message links keep working with zero per-product code.

The map is reloaded when the file's mtime changes.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.http import HttpResponsePermanentRedirect


class LegacyRedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self._map = {}
        self._mtime = None

    def _redirects_file(self) -> Path:
        root = Path(getattr(settings, "DOWNLOADS_ROOT", Path(settings.BASE_DIR) / "downloads"))
        return root / "_redirects.json"

    def _load(self) -> dict:
        path = self._redirects_file()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            self._map, self._mtime = {}, None
            return self._map
        if mtime != self._mtime:
            try:
                self._map = json.loads(path.read_text())
            except Exception:  # noqa: BLE001 - a bad map should never 500 the site
                self._map = {}
            self._mtime = mtime
        return self._map

    def __call__(self, request):
        target = self._load().get(request.path)
        if target:
            return HttpResponsePermanentRedirect(target)
        return self.get_response(request)
