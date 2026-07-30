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


# Provenance stamp keys, written INTO the app's Info.plist by the build/export
# pipeline (Design Amendment 001). Kept here as the single contract shared by the
# stamping script and the engine's verifier.
#
# The RELEASE GATE is reproducibility, not cleanliness: the artifact identifies the
# exact source it was built from (a git tree fingerprint over the product's source
# paths), and the engine publishes iff that fingerprint matches a commit reachable
# from origin/<branch>. Clean/dirty is recorded for diagnostics only — a dirty build
# whose exact source is later committed + pushed is fully reproducible and allowed.
PROV_SOURCE_TREE = "BeaconSourceTree"     # git tree SHA of the built source (the FINGERPRINT)
PROV_SOURCE_PATHS = "BeaconSourcePaths"   # repo-relative path(s) the fingerprint covers
PROV_COMMIT = "BeaconSourceCommit"        # HEAD at build time (base commit; informational)
PROV_CLEAN = "BeaconSourceClean"          # "true"/"false": strict porcelain-empty (DIAGNOSTIC)
PROV_BRANCH = "BeaconSourceBranch"        # branch built from (informational)
PROV_TIMESTAMP = "BeaconBuildTimestamp"   # ISO-8601 build/archive time
PROV_ENVIRONMENT = "BeaconBuildEnvironment"  # e.g. "Xcode 26.2; macOS 15.5" (informational)


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
    # Provenance stamp read from the app Info.plist (empty dict if unstamped).
    provenance: Dict[str, str] = field(default_factory=dict)

    @property
    def has_provenance(self) -> bool:
        """A stamp is present iff it carries at least a base commit."""
        return bool(self.provenance.get("commit"))

    @property
    def has_fingerprint(self) -> bool:
        """A reproducibility fingerprint (source tree hash) is present."""
        return bool(self.provenance.get("source_tree"))

    @property
    def prov_commit(self) -> str:
        return self.provenance.get("commit", "")

    @property
    def prov_source_tree(self) -> str:
        """Git tree SHA of the built source — the reproducibility fingerprint."""
        return self.provenance.get("source_tree", "")

    @property
    def prov_source_paths(self) -> str:
        """Repo-relative path scope the fingerprint covers (e.g. 'mobile/aims_field')."""
        return self.provenance.get("source_paths", "")

    @property
    def prov_clean(self) -> Optional[bool]:
        """Strict cleanliness recorded at build time (DIAGNOSTIC only, not a gate);
        None if unstamped/unparseable."""
        raw = self.provenance.get("clean")
        if raw is None:
            return None
        return str(raw).strip().lower() in ("true", "1", "yes")


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
        provenance=_read_provenance(info),
    )
    ipa.signing = _read_signing(ipa_path, ipa, extra_dir)

    missing = [n for n, v in [("version", ipa.version),
                              ("build", ipa.build),
                              ("bundle id", ipa.bundle_id)] if not v]
    if missing:
        raise IPAError(f"IPA Info.plist missing required keys: {', '.join(missing)}")
    return ipa


def _read_provenance(info: dict) -> Dict[str, str]:
    """Extract the Beacon provenance stamp from the app Info.plist. Returns a
    normalized dict (empty if the app was built without the stamping build phase —
    the pre-Amendment-001 case, handled gracefully by the engine)."""
    prov: Dict[str, str] = {}
    commit = str(info.get(PROV_COMMIT, "")).strip()
    if commit:
        prov["commit"] = commit
    if PROV_CLEAN in info:
        prov["clean"] = str(info.get(PROV_CLEAN, "")).strip()
    for src, dst in ((PROV_SOURCE_TREE, "source_tree"), (PROV_SOURCE_PATHS, "source_paths"),
                     (PROV_BRANCH, "branch"), (PROV_TIMESTAMP, "timestamp"),
                     (PROV_ENVIRONMENT, "environment")):
        val = str(info.get(src, "")).strip()
        if val:
            prov[dst] = val
    return prov


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
