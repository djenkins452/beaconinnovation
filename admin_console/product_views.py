"""Beacon Admin → Products — internal product landing, product pages, and the
authenticated Developer Guide host.

Authorization: least privilege. The whole area requires an authenticated
**staff** user (`is_staff`). Internal engineering resources (the AIMS Developer
Guide is proprietary) are never reachable by the customer download-portal users
(`products.Product.authorized_users`), who are not staff. Unauthenticated users
are bounced to the login page; authenticated non-staff get 404 (the area's
existence is not revealed). This reuses Beacon's existing Django-session auth —
no second auth framework.

The Developer Guide is served from an immutable, SHA-identified snapshot the AIMS
pipeline deploys (a tarball under DEVGUIDE_ROOT, outside the public /static/ and
/downloads/ trees). Files are streamed through this view only — an unauthenticated
deep link retrieves nothing. Path traversal is blocked; the guide is generated,
never authored here (its source of truth is the AIMS repository, D-176/D-179).
"""
from __future__ import annotations

import io
import mimetypes
import posixpath
import tarfile
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from . import product_registry as registry

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}


def staff_required(view):
    """Authenticated + is_staff. Unauthenticated → login; authed non-staff → 404
    (do not reveal the internal area to customer-portal users)."""
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            raise Http404()
        return view(request, *args, **kwargs)
    return wrapper


# --------------------------------------------------------------------- pages
@staff_required
def products_index(request):
    """Admin → Products: the reusable landing over all registered Beacon products."""
    return render(request, "admin_console/products_index.html",
                  {"products": registry.list_products(), "active_nav": "products"})


@staff_required
def product_detail(request, product_key):
    """A single product's internal page (overview + backed capabilities)."""
    product = registry.get_product(product_key)
    if not product:
        raise Http404()
    return render(request, "admin_console/product_detail.html",
                  {"product": product, "active_nav": "products"})


# ------------------------------------------------------ Developer Guide host
# Small in-memory cache of a snapshot's files, keyed by (path, mtime) so a
# redeploy is picked up automatically without a restart.
_GUIDE_CACHE: dict[str, tuple[float, dict[str, bytes]]] = {}


def _load_guide(product_key: str) -> tuple[dict | None, dict[str, bytes] | None]:
    snap = registry.guide_snapshot(product_key)
    if not snap or not snap.get("_has_archive"):
        return None, None
    tarpath = registry.devguide_root() / product_key / snap.get("archive", "guide.tar.gz")
    mtime = tarpath.stat().st_mtime
    cached = _GUIDE_CACHE.get(product_key)
    if cached and cached[0] == mtime:
        return snap, cached[1]
    files: dict[str, bytes] = {}
    with tarfile.open(tarpath, "r:*") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            name = m.name[2:] if m.name.startswith("./") else m.name
            f = tf.extractfile(m)
            if f is not None:
                files[name] = f.read()
    _GUIDE_CACHE[product_key] = (mtime, files)
    return snap, files


@staff_required
def developer_guide(request, product_key, path=""):
    """Serve the deployed Developer Guide snapshot, authenticated. A guide root
    with no path redirects to index.html; every nested asset is streamed from the
    snapshot in memory. Traversal outside the snapshot is impossible."""
    snap, files = _load_guide(product_key)
    if files is None:
        raise Http404("No Developer Guide is deployed for this product.")

    rel = path or "index.html"
    if rel.endswith("/"):
        rel = rel + "index.html"
    rel = posixpath.normpath(rel)
    if rel.startswith("..") or rel.startswith("/") or rel == ".":
        raise Http404()

    data = files.get(rel)
    if data is None:
        raise Http404()

    ctype = _CONTENT_TYPES.get("." + rel.rsplit(".", 1)[-1].lower()) if "." in rel else None
    ctype = ctype or mimetypes.guess_type(rel)[0] or "application/octet-stream"
    resp = HttpResponse(data, content_type=ctype)
    # Private, authenticated content — never cache in shared proxies.
    resp["Cache-Control"] = "private, no-store"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp
