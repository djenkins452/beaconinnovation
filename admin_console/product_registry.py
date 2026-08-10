"""Beacon Admin → Products — the internal product registry.

A code-level registry, not a database model: Beacon owns only a handful of
products, and each product's *dynamic* state (lifecycle, version, source
provenance) is owned by that product's own repository and travels with its
deployed artifact — so a DB table would just duplicate truth that lives
elsewhere. Registering a new product (Whole Life Journey, Beacon HCM, …) is a
new dict entry here plus its deployed metadata; the Products UI discovers and
renders it — no per-product views, routes, or templates to copy.

Capabilities are *declared* per product but only *rendered* when actually
backed (e.g. ``developer_guide`` shows only when a Guide snapshot is deployed).
Nothing here is AIMS-specific except the AIMS entry.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings

# Ordered so the Products landing renders deterministically.
_PRODUCTS: list[dict] = [
    {
        "key": "aims",
        "name": "AIMS",
        "full_name": "Advanced Inventory Management System",
        "owner": "Beacon Innovation, LLC",
        "summary": (
            "Military property accountability & inventory — an offline-first iOS "
            "Field app plus a Django Console. Faster inventories without reducing "
            "accountability."
        ),
        # Declared capabilities; each renders only when backed (see capability_backed).
        "capabilities": ["overview", "developer_guide"],
    },
    # Future: {"key": "wlj", "name": "Whole Life Journey", ...},
    #         {"key": "beacon-hcm", "name": "Beacon HCM", ...}
]

_BY_KEY = {p["key"]: p for p in _PRODUCTS}


def devguide_root() -> Path:
    """Private root for deployed Developer Guide snapshots (never a public /static/ dir)."""
    return Path(getattr(settings, "DEVGUIDE_ROOT", Path(settings.BASE_DIR) / "product_guides"))


def guide_snapshot(product_key: str) -> dict | None:
    """The deployed Guide snapshot metadata for a product, or None if none deployed.

    Read from the artifact the product's own pipeline deployed — so lifecycle/version/
    provenance come from that product's repository truth, never hard-coded in Beacon.
    """
    meta = devguide_root() / product_key / "snapshot.json"
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text())
        data["_has_archive"] = (devguide_root() / product_key / data.get("archive", "")).is_file()
        return data
    except Exception:
        return None


def capability_backed(product_key: str, capability: str) -> bool:
    """True only when a declared capability has real backing right now."""
    if capability == "developer_guide":
        snap = guide_snapshot(product_key)
        return bool(snap and snap.get("_has_archive"))
    if capability == "overview":
        return True
    return False


def list_products() -> list[dict]:
    """Products for the landing page, each enriched with its live snapshot/lifecycle."""
    out = []
    for p in _PRODUCTS:
        snap = guide_snapshot(p["key"])
        out.append({**p,
                    "lifecycle": (snap or {}).get("lifecycle", "Unknown"),
                    "has_developer_guide": capability_backed(p["key"], "developer_guide")})
    return out


def get_product(product_key: str) -> dict | None:
    p = _BY_KEY.get(product_key)
    if not p:
        return None
    snap = guide_snapshot(product_key)
    return {**p,
            "snapshot": snap,
            "lifecycle": (snap or {}).get("lifecycle", "Unknown"),
            "backed_capabilities": [c for c in p["capabilities"]
                                    if capability_backed(product_key, c)]}
