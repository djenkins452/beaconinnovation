"""Inspect an exported IPA — the single source of truth for a release.

Reads the app's Info.plist from inside the IPA (stdlib zipfile + plistlib) and
extracts signing details from Xcode's DistributionSummary.plist when present, or
the embedded provisioning profile otherwise.
"""

from __future__ import annotations

import fnmatch
import plistlib
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


class IPAError(Exception):
    pass


@dataclass
class IPAInfo:
    app_name: str            # CFBundleName
    display_name: str        # CFBundleDisplayName (home-screen name)
    bundle_id: str           # CFBundleIdentifier
    version: str             # CFBundleShortVersionString (marketing version)
    build: str               # CFBundleVersion
    min_ios: str             # MinimumOSVersion
    architectures: List[str] = field(default_factory=list)
    signing: Dict[str, str] = field(default_factory=dict)


def inspect_ipa(ipa_path: Path, extra_dir: Optional[Path] = None) -> IPAInfo:
    """Extract metadata from ``ipa_path``. ``extra_dir`` may hold a sibling
    DistributionSummary.plist (from the Xcode export)."""
    with zipfile.ZipFile(ipa_path) as zf:
        info_names = [n for n in zf.namelist()
                      if fnmatch.fnmatch(n, "Payload/*.app/Info.plist")]
        if not info_names:
            raise IPAError("Could not find Payload/*.app/Info.plist inside the IPA.")
        info = plistlib.loads(zf.read(sorted(info_names, key=len)[0]))

    ipa = IPAInfo(
        app_name=info.get("CFBundleName", ""),
        display_name=info.get("CFBundleDisplayName") or info.get("CFBundleName", ""),
        bundle_id=info.get("CFBundleIdentifier", ""),
        version=info.get("CFBundleShortVersionString", ""),
        build=str(info.get("CFBundleVersion", "")),
        min_ios=info.get("MinimumOSVersion", ""),
    )
    ipa.signing = _read_signing(ipa_path, ipa, extra_dir)

    missing = [n for n, v in [("version", ipa.version),
                              ("build", ipa.build),
                              ("bundle id", ipa.bundle_id)] if not v]
    if missing:
        raise IPAError(f"IPA Info.plist missing required keys: {', '.join(missing)}")
    return ipa


def _read_signing(ipa_path: Path, ipa: IPAInfo, extra_dir: Optional[Path]) -> Dict[str, str]:
    # Prefer Xcode's DistributionSummary.plist if it sits next to the IPA.
    if extra_dir:
        summary = Path(extra_dir) / "DistributionSummary.plist"
        if summary.is_file():
            parsed = _from_distribution_summary(summary, ipa)
            if parsed:
                return parsed
    return _from_embedded_profile(ipa_path)


def _from_distribution_summary(summary: Path, ipa: IPAInfo) -> Dict[str, str]:
    try:
        with open(summary, "rb") as fh:
            data = plistlib.load(fh)
        for entries in data.values():
            if entries:
                e = entries[0]
                cert = e.get("certificate", {})
                team = e.get("team", {})
                profile = e.get("profile", {})
                ipa.architectures = list(e.get("architectures", []))
                return {
                    "team": f"{team.get('name', '')} ({team.get('id', '')})".strip(),
                    "certificate": cert.get("type", ""),
                    "cert_expires": cert.get("dateExpires", ""),
                    "profile": profile.get("name", ""),
                    "profile_expires": profile.get("dateExpires", ""),
                    "architectures": ", ".join(ipa.architectures),
                }
    except Exception:  # noqa: BLE001 - signing info is best-effort
        return {}
    return {}


def _from_embedded_profile(ipa_path: Path) -> Dict[str, str]:
    try:
        with zipfile.ZipFile(ipa_path) as zf:
            names = [n for n in zf.namelist()
                     if fnmatch.fnmatch(n, "Payload/*.app/embedded.mobileprovision")]
            if not names:
                return {}
            raw = zf.read(names[0])
        proc = subprocess.run(["security", "cms", "-D", "-i", "/dev/stdin"],
                              input=raw, capture_output=True)
        if proc.returncode != 0:
            return {}
        prof = plistlib.loads(proc.stdout)
        return {
            "team": ", ".join(prof.get("TeamIdentifier", []) or []),
            "profile": prof.get("Name", ""),
            "profile_expires": str(prof.get("ExpirationDate", "")),
        }
    except Exception:  # noqa: BLE001
        return {}
