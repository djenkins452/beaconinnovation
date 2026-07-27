"""Reusable release engine.

Product-agnostic. Given a :class:`~config.ProductConfig`, it runs the full
release pipeline: locate the exported IPA, inspect it, stage it, synchronize
every deployment artifact from it, generate + publish release notes, archive the
release, validate consistency, commit, push, wait for Railway, and verify the
live deployment byte-for-byte.

The IPA is the single source of truth. If anything disagrees, the pipeline stops
with a clear error (:class:`ReleaseError`) and never reports a false success.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import time
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import ProductConfig
import templates


class ReleaseError(Exception):
    """Raised to stop the pipeline immediately with a clear explanation."""


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


@dataclass
class ReleaseNotes:
    whats_new: List[str] = field(default_factory=list)
    bug_fixes: List[str] = field(default_factory=list)
    known_issues: List[str] = field(default_factory=list)


class ReleaseEngine:
    def __init__(
        self,
        config: ProductConfig,
        repo_root: Path,
        *,
        dry_run: bool = False,
        deploy: bool = True,
        notes_override: Optional[ReleaseNotes] = None,
        poll_timeout: int = 900,
        poll_interval: int = 15,
        scratch_dir: Optional[Path] = None,
        log=print,
    ):
        self.cfg = config
        self.repo_root = Path(repo_root)
        self.dry_run = dry_run
        self.deploy = deploy and not dry_run
        self.notes_override = notes_override
        self.poll_timeout = poll_timeout
        self.poll_interval = poll_interval
        self.scratch_dir = scratch_dir
        self.log = log

        # accumulated state
        self.export_folder: Optional[Path] = None
        self.source_ipa: Optional[Path] = None
        self.ipa: Optional[IPAInfo] = None
        self.notes: Optional[ReleaseNotes] = None
        self.source_sha: Optional[str] = None
        self.release_date = datetime.now().strftime("%B %-d, %Y")
        self.deployed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.commit_id: Optional[str] = None
        self.archive_dir: Optional[Path] = None
        self.report_data: Dict[str, str] = {}

    # -- output target: repo in a real run, scratch in a dry run --------
    @property
    def out_downloads(self) -> Path:
        if self.dry_run:
            return self._scratch() / self.cfg.downloads_dir
        return self.repo_root / self.cfg.downloads_dir

    @property
    def out_releases(self) -> Path:
        if self.dry_run:
            return self._scratch() / self.cfg.releases_dir
        return self.repo_root / self.cfg.releases_dir

    def _scratch(self) -> Path:
        base = self.scratch_dir or (self.repo_root / ".release-dryrun")
        base.mkdir(parents=True, exist_ok=True)
        return base

    # ==================================================================
    # Orchestration
    # ==================================================================
    def run(self) -> Dict[str, str]:
        mode = "DRY RUN" if self.dry_run else ("DEPLOY" if self.deploy else "LOCAL (no deploy)")
        self._banner(f"{self.cfg.product_title} release  [{mode}]")

        self.step_locate()          # 1
        self.step_inspect()         # 2
        self.step_notes()           # 5 (computed early; the portal embeds it)
        self.step_stage()           # 3
        self.step_sync()            # 4 + 6
        self.step_archive()         # 7
        self.step_validate()        # 8
        if self.deploy:
            self.step_commit()      # 9
            self.step_push()        # 10
            self.step_verify_http() # 11
            self.step_verify_sha()  # 12
        else:
            self.log("\n[skip] deploy/verify skipped (dry-run or --no-deploy)")
        self.step_history()         # 14
        return self.step_report()   # 13

    # ==================================================================
    # Step 1 — locate the newest export + IPA
    # ==================================================================
    def step_locate(self) -> None:
        self._step(1, "Locate newest export")
        source_dir = Path(os.path.expanduser(self.cfg.source_dir))
        if not source_dir.is_dir():
            raise ReleaseError(
                f"Source folder not found: {source_dir}\n"
                "Export a release from Xcode into this folder first."
            )
        folders = [
            p for p in source_dir.iterdir()
            if p.is_dir() and fnmatch.fnmatch(p.name, self.cfg.source_folder_glob)
        ]
        if not folders:
            raise ReleaseError(
                f"No export folders matching '{self.cfg.source_folder_glob}' in {source_dir}."
            )
        # Timestamped names (…YYYY-MM-DD HH-MM-SS) sort chronologically by name;
        # fall back to mtime as a tie-breaker for safety.
        self.export_folder = max(folders, key=lambda p: (p.name, p.stat().st_mtime))
        ipa = self.export_folder / self.cfg.ipa_source_name
        if not ipa.is_file():
            raise ReleaseError(
                f"No {self.cfg.ipa_source_name} inside newest export: {self.export_folder}"
            )
        self.source_ipa = ipa
        self.source_sha = self._sha256_file(ipa)
        self.log(f"  export folder : {self.export_folder.name}")
        self.log(f"  ipa           : {ipa}")
        self.log(f"  sha256        : {self.source_sha}")

    # ==================================================================
    # Step 2 — inspect the IPA (source of truth)
    # ==================================================================
    def step_inspect(self) -> None:
        self._step(2, "Inspect IPA")
        with zipfile.ZipFile(self.source_ipa) as zf:
            info_names = [
                n for n in zf.namelist()
                if fnmatch.fnmatch(n, "Payload/*.app/Info.plist")
            ]
            if not info_names:
                raise ReleaseError("Could not find Payload/*.app/Info.plist inside the IPA.")
            info = plistlib.loads(zf.read(sorted(info_names, key=len)[0]))

        bundle_id = info.get("CFBundleIdentifier", "")
        ipa = IPAInfo(
            app_name=info.get("CFBundleName", ""),
            display_name=info.get("CFBundleDisplayName") or info.get("CFBundleName", ""),
            bundle_id=bundle_id,
            version=info.get("CFBundleShortVersionString", ""),
            build=str(info.get("CFBundleVersion", "")),
            min_ios=info.get("MinimumOSVersion", ""),
        )
        ipa.signing = self._read_signing(ipa)
        self.ipa = ipa

        for k, v in [
            ("Application Name", ipa.app_name),
            ("Display Name", ipa.display_name),
            ("Bundle Identifier", ipa.bundle_id),
            ("Version", ipa.version),
            ("Build Number", ipa.build),
            ("Minimum iOS", ipa.min_ios),
        ]:
            self.log(f"  {k:<18}: {v}")
        for k, v in ipa.signing.items():
            self.log(f"  {('signing.' + k):<18}: {v}")

        missing = [n for n, v in [
            ("version", ipa.version), ("build", ipa.build), ("bundle id", ipa.bundle_id)
        ] if not v]
        if missing:
            raise ReleaseError(f"IPA Info.plist missing required keys: {', '.join(missing)}")
        if self.cfg.expected_bundle_id and ipa.bundle_id != self.cfg.expected_bundle_id:
            raise ReleaseError(
                f"Bundle identifier mismatch: IPA is '{ipa.bundle_id}', "
                f"expected '{self.cfg.expected_bundle_id}'. Refusing to publish the wrong app."
            )

    def _read_signing(self, ipa: IPAInfo) -> Dict[str, str]:
        """Prefer Xcode's DistributionSummary.plist; fall back to the profile."""
        summary = self.export_folder / "DistributionSummary.plist"
        if summary.is_file():
            try:
                with open(summary, "rb") as fh:
                    data = plistlib.load(fh)
                # keyed by ipa filename -> [ { ... } ]
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
            except Exception as exc:  # noqa: BLE001 - signing info is best-effort
                self.log(f"  (could not parse DistributionSummary.plist: {exc})")
        return self._read_profile_signing()

    def _read_profile_signing(self) -> Dict[str, str]:
        """Decode embedded.mobileprovision via `security cms` as a fallback."""
        try:
            with zipfile.ZipFile(self.source_ipa) as zf:
                names = [n for n in zf.namelist()
                         if fnmatch.fnmatch(n, "Payload/*.app/embedded.mobileprovision")]
                if not names:
                    return {}
                raw = zf.read(names[0])
            proc = subprocess.run(
                ["security", "cms", "-D", "-i", "/dev/stdin"],
                input=raw, capture_output=True,
            )
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

    # ==================================================================
    # Step 5 — generate release notes
    # ==================================================================
    def step_notes(self) -> None:
        self._step(5, "Generate release notes")
        if self.notes_override is not None:
            self.notes = self.notes_override
            self.log("  using supplied notes override")
        else:
            self.notes = self._auto_notes()
        if not self.notes.known_issues:
            self.notes.known_issues = ["None reported."]
        for heading, items in [
            ("What's New", self.notes.whats_new),
            ("Bug Fixes", self.notes.bug_fixes),
            ("Known Issues", self.notes.known_issues),
        ]:
            self.log(f"  {heading}:")
            for it in (items or ["(none)"]):
                self.log(f"    - {it}")

    def _auto_notes(self) -> ReleaseNotes:
        """Categorize commits since the previous archived release."""
        last_commit = self._previous_commit()
        rng = f"{last_commit}..HEAD" if last_commit else "-n 20"
        args = ["log", "--no-merges", "--pretty=format:%s"]
        args += ([rng] if last_commit else rng.split())
        subjects = [s.strip() for s in self._git(*args).splitlines() if s.strip()]

        notes = ReleaseNotes()
        seen = set()
        for subj in subjects:
            # skip our own deploy commits
            if subj.lower().startswith("deploy ") or "release " in subj.lower()[:20]:
                continue
            clean = self._clean_subject(subj)
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            low = subj.lower()
            if low.startswith("fix") or any(w in low for w in ("fix", "bug", "resolve", "patch")):
                notes.bug_fixes.append(clean)
            else:
                notes.whats_new.append(clean)
        if not notes.whats_new and not notes.bug_fixes:
            notes.whats_new.append(f"Maintenance release (build {self.ipa.build}).")
        return notes

    @staticmethod
    def _clean_subject(subj: str) -> str:
        for prefix in ("feat:", "fix:", "feature:", "add:", "chore:", "docs:"):
            if subj.lower().startswith(prefix):
                subj = subj[len(prefix):].strip()
                break
        return subj[:1].upper() + subj[1:] if subj else subj

    def _previous_commit(self) -> Optional[str]:
        history = self._history_path()
        if not history.is_file():
            return None
        try:
            data = json.loads(history.read_text())
            commit = (data.get("current") or {}).get("commit")
            if commit and self._git("cat-file", "-t", commit, check=False).strip() == "commit":
                return commit
        except Exception:  # noqa: BLE001
            pass
        return None

    # ==================================================================
    # Step 3 — stage the IPA into the public downloads dir
    # ==================================================================
    def step_stage(self) -> None:
        self._step(3, "Stage IPA")
        dest = self.out_downloads / self.cfg.ipa_dest_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.source_ipa, dest)
        staged_sha = self._sha256_file(dest)
        if staged_sha != self.source_sha:
            raise ReleaseError("Staged IPA hash does not match source — copy failed.")
        self.log(f"  copied -> {self._rel(dest)}")

    # ==================================================================
    # Steps 4 + 6 — synchronize + publish deployment artifacts
    # ==================================================================
    def step_sync(self) -> None:
        self._step(4, "Synchronize deployment artifacts")
        # manifest
        manifest = templates.render(templates.MANIFEST_TEMPLATE, {
            "IPA_URL": self.cfg.ipa_url,
            "BUNDLE_ID": self.ipa.bundle_id,
            "VERSION": self.ipa.version,
            "PRODUCT_TITLE": self.cfg.product_title,
        })
        self._write(self.out_downloads / self.cfg.manifest_name, manifest)
        self.log(f"  wrote {self.cfg.manifest_name} (bundle-version {self.ipa.version})")

        # install page / release portal (embeds release notes -> step 6)
        page = templates.render(templates.INSTALL_PAGE_TEMPLATE, {
            "PRODUCT_TITLE": self.cfg.product_title,
            "VERSION": self.ipa.version,
            "BUILD": self.ipa.build,
            "RELEASE_DATE": self.release_date,
            "MANIFEST_URL": self.cfg.manifest_url,
            "BUNDLE_ID": self.ipa.bundle_id,
            "MIN_IOS": self.ipa.min_ios or "—",
            "WHATS_NEW_SECTION": self._notes_section("What's New", self.notes.whats_new),
            "BUG_FIXES_SECTION": self._notes_section("Bug Fixes", self.notes.bug_fixes),
            "KNOWN_ISSUES_SECTION": self._notes_section("Known Issues", self.notes.known_issues, muted=True),
        })
        self._write(self.out_downloads / self.cfg.install_page_name, page)
        self.log(f"  wrote {self.cfg.install_page_name} (release portal)")

    def _notes_section(self, heading: str, items: List[str], muted: bool = False) -> str:
        if not items:
            return ""
        cls = ' class="muted"' if muted else ""
        lis = "\n".join(f"                <li{cls}>{self._esc(i)}</li>" for i in items)
        return templates.render(templates.NOTES_SECTION_TEMPLATE, {
            "HEADING": heading, "ITEMS": lis,
        })

    # ==================================================================
    # Step 7 — permanent archive
    # ==================================================================
    def step_archive(self) -> None:
        self._step(7, "Archive release")
        name = f"v{self.ipa.version}-build{self.ipa.build}"
        self.archive_dir = self.out_releases / name
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy2(self.out_downloads / self.cfg.ipa_dest_name,
                     self.archive_dir / self.cfg.ipa_dest_name)
        shutil.copy2(self.out_downloads / self.cfg.manifest_name,
                     self.archive_dir / self.cfg.manifest_name)
        shutil.copy2(self.out_downloads / self.cfg.install_page_name,
                     self.archive_dir / self.cfg.install_page_name)

        self._write(self.archive_dir / "SHA256.txt",
                    f"{self.source_sha}  {self.cfg.ipa_dest_name}\n")
        self._write(self.archive_dir / "release_notes.md", self._notes_markdown())
        self._write(self.archive_dir / "metadata.json",
                    json.dumps(self._release_record(), indent=2) + "\n")
        self._write(self.archive_dir / "deployment_summary.md", self._summary_markdown())
        self.log(f"  archived -> {self._rel(self.archive_dir)}")

    # ==================================================================
    # Step 8 — validate everything agrees
    # ==================================================================
    def step_validate(self) -> None:
        self._step(8, "Validate consistency")
        # staged IPA
        staged = self.out_downloads / self.cfg.ipa_dest_name
        if self._sha256_file(staged) != self.source_sha:
            raise ReleaseError("Validation failed: staged IPA hash != source IPA hash.")
        # manifest
        with open(self.out_downloads / self.cfg.manifest_name, "rb") as fh:
            man = plistlib.load(fh)
        meta = man["items"][0]["metadata"]
        asset_url = man["items"][0]["assets"][0]["url"]
        checks = [
            ("manifest bundle-identifier", meta["bundle-identifier"], self.ipa.bundle_id),
            ("manifest bundle-version", meta["bundle-version"], self.ipa.version),
            ("manifest asset url", asset_url, self.cfg.ipa_url),
        ]
        for label, got, want in checks:
            if got != want:
                raise ReleaseError(f"Validation failed: {label} is '{got}', expected '{want}'.")
        # install page
        page = (self.out_downloads / self.cfg.install_page_name).read_text()
        for label, needle in [
            ("version", self.ipa.version),
            ("build", self.ipa.build),
            ("bundle id", self.ipa.bundle_id),
            ("manifest url", self.cfg.manifest_url),
        ]:
            if needle not in page:
                raise ReleaseError(f"Validation failed: install page missing {label} '{needle}'.")
        self.log("  bundle id, version, build, manifest, install page, IPA all agree ✓")

    # ==================================================================
    # Step 9 — commit deployment files only
    # ==================================================================
    def step_commit(self) -> None:
        self._step(9, "Commit")
        paths = [
            f"{self.cfg.downloads_dir}/{self.cfg.ipa_dest_name}",
            f"{self.cfg.downloads_dir}/{self.cfg.manifest_name}",
            f"{self.cfg.downloads_dir}/{self.cfg.install_page_name}",
            self.cfg.releases_dir,
        ]
        if self.cfg.changelog_path:
            self._append_changelog()
            paths.append(self.cfg.changelog_path)
        self._git("add", "--", *paths)
        if not self._git("diff", "--cached", "--name-only").strip():
            raise ReleaseError("Nothing staged to commit — deployment artifacts unchanged.")
        message = (
            f"Deploy {self.cfg.product_title} v{self.ipa.version} (Build {self.ipa.build})\n\n"
            f"Synchronized from IPA (source of truth). "
            f"Bundle {self.ipa.bundle_id}, SHA256 {self.source_sha}.\n\n"
            f"Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
        )
        self._git("commit", "-m", message)
        self.commit_id = self._git("rev-parse", "HEAD").strip()
        self.log(f"  committed {self.commit_id[:9]}")

    # ==================================================================
    # Step 10 — push + wait for Railway
    # ==================================================================
    def step_push(self) -> None:
        self._step(10, "Push to GitHub")
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD").strip()
        env = {**os.environ, "GIT_SSH_COMMAND": "ssh -p 443"}
        # push the working branch for the record
        self._git("push", "origin", branch, env=env)
        self.log(f"  pushed {branch}")
        # fast-forward the deploy branch (Railway watches this) without checkout
        if branch != self.cfg.deploy_branch:
            res = self._git("push", "origin", f"HEAD:{self.cfg.deploy_branch}",
                            env=env, check=False)
            if res is None:
                raise ReleaseError(
                    f"Could not fast-forward '{self.cfg.deploy_branch}' from '{branch}'. "
                    f"The deploy branch has diverged — merge manually and re-run."
                )
            self.log(f"  fast-forwarded {self.cfg.deploy_branch} -> Railway will deploy")
        else:
            self.log(f"  {branch} is the deploy branch -> Railway will deploy")

    # ==================================================================
    # Step 11 — verify HTTP 200 (polls until Railway serves the release)
    # ==================================================================
    def step_verify_http(self) -> None:
        self._step(11, "Verify deployment (HTTP 200 + Railway)")
        deadline = time.time() + self.poll_timeout
        target = self.source_sha
        urls = [self.cfg.install_url, self.cfg.manifest_url, self.cfg.ipa_url]
        while True:
            codes = {u: self._http_status(u) for u in urls}
            live_sha = self._http_sha(self.cfg.ipa_url)
            all_200 = all(c == 200 for c in codes.values())
            if all_200 and live_sha == target:
                for u, c in codes.items():
                    self.log(f"  {c}  {u}")
                self.log("  Railway is serving the new IPA ✓")
                return
            if time.time() >= deadline:
                detail = " ".join(f"{self._basename(u)}={c}" for u, c in codes.items())
                raise ReleaseError(
                    f"Deployment not live after {self.poll_timeout}s. "
                    f"Statuses: {detail}; live IPA sha "
                    f"{'matches' if live_sha == target else 'does NOT match'}."
                )
            time.sleep(self.poll_interval)

    # ==================================================================
    # Step 12 — SHA verification (already gated in step 11; assert here)
    # ==================================================================
    def step_verify_sha(self) -> None:
        self._step(12, "Verify live IPA SHA")
        live = self._http_sha(self.cfg.ipa_url)
        if live != self.source_sha:
            raise ReleaseError(
                f"SHA mismatch: live IPA {live} != source {self.source_sha}."
            )
        self.log(f"  live sha matches source ✓  {live}")

    # ==================================================================
    # Step 14 — deployment history
    # ==================================================================
    def step_history(self) -> None:
        self._step(14, "Update deployment history")
        history_path = self._history_path()
        history_path.parent.mkdir(parents=True, exist_ok=True)
        if history_path.is_file():
            data = json.loads(history_path.read_text())
        else:
            data = {"product": self.cfg.key, "current": None, "releases": []}
        record = self._release_record()
        # newest first; de-dupe an identical re-run of the same version+build
        data["releases"] = [r for r in data.get("releases", [])
                            if not (r.get("version") == record["version"]
                                    and r.get("build") == record["build"])]
        data["releases"].insert(0, record)
        data["current"] = record
        self._write(history_path, json.dumps(data, indent=2) + "\n")
        self._write(self.out_releases / "README.md", self._history_readme(data))
        self.log(f"  history -> {self._rel(history_path)} ({len(data['releases'])} releases)")

    # ==================================================================
    # Step 13 — deployment report
    # ==================================================================
    def step_report(self) -> Dict[str, str]:
        self._step(13, "Deployment report")
        self.report_data = {
            "Application Name": self.ipa.app_name,
            "Display Name": self.ipa.display_name,
            "Version": self.ipa.version,
            "Build": self.ipa.build,
            "Bundle Identifier": self.ipa.bundle_id,
            "Minimum iOS": self.ipa.min_ios,
            "Commit ID": self.commit_id or "(not committed)",
            "Railway Status": "deployed & serving new IPA" if self.deploy else "not deployed",
            "Deployment Date": self.deployed_at,
            "SHA-256": self.source_sha,
            "SHA Verification": "PASS (live == source)" if self.deploy else "n/a",
            "Install URL": self.cfg.install_url,
        }
        width = max(len(k) for k in self.report_data)
        self.log("")
        for k, v in self.report_data.items():
            self.log(f"  {k:<{width}} : {v}")
        return self.report_data

    # ==================================================================
    # helpers
    # ==================================================================
    def _release_record(self) -> Dict[str, str]:
        return {
            "product": self.cfg.key,
            "product_title": self.cfg.product_title,
            "version": self.ipa.version,
            "build": self.ipa.build,
            "bundle_id": self.ipa.bundle_id,
            "min_ios": self.ipa.min_ios,
            "sha256": self.source_sha,
            "commit": self.commit_id,
            "deployed_at": self.deployed_at,
            "release_date": self.release_date,
            "archive_dir": self._rel(self.archive_dir) if self.archive_dir else None,
            "install_url": self.cfg.install_url,
            "signing": self.ipa.signing,
        }

    def _notes_markdown(self) -> str:
        lines = [
            f"# {self.cfg.product_title} — Release Notes",
            "",
            f"- **Version:** {self.ipa.version}",
            f"- **Build:** {self.ipa.build}",
            f"- **Release Date:** {self.release_date}",
            "",
            "## What's New",
            *[f"- {i}" for i in (self.notes.whats_new or ["(none)"])],
            "",
            "## Bug Fixes",
            *[f"- {i}" for i in (self.notes.bug_fixes or ["(none)"])],
            "",
            "## Known Issues",
            *[f"- {i}" for i in (self.notes.known_issues or ["None reported."])],
            "",
        ]
        return "\n".join(lines)

    def _summary_markdown(self) -> str:
        signing_lines = [f"- **{k}:** {v}" for k, v in self.ipa.signing.items()]
        if not signing_lines:
            signing_lines = ["- (unavailable)"]
        lines = [
            f"# {self.cfg.product_title} — Deployment Summary",
            "",
            f"- **Application Name:** {self.ipa.app_name}",
            f"- **Display Name:** {self.ipa.display_name}",
            f"- **Version:** {self.ipa.version}",
            f"- **Build:** {self.ipa.build}",
            f"- **Bundle Identifier:** {self.ipa.bundle_id}",
            f"- **Minimum iOS:** {self.ipa.min_ios}",
            f"- **SHA-256:** `{self.source_sha}`",
            f"- **Release Date:** {self.release_date}",
            f"- **Deployed At:** {self.deployed_at}",
            f"- **Source Export:** {self.export_folder.name if self.export_folder else ''}",
            f"- **Install URL:** {self.cfg.install_url}",
            "",
            "## Signing",
            *signing_lines,
            "",
        ]
        return "\n".join(lines)

    def _history_readme(self, data: Dict) -> str:
        rows = ["| Version | Build | Date | Commit | SHA-256 (short) | Archive |",
                "|---------|-------|------|--------|-----------------|---------|"]
        for r in data["releases"]:
            commit = (r.get("commit") or "")[:9] or "—"
            sha = (r.get("sha256") or "")[:12]
            rows.append(
                f"| {r['version']} | {r['build']} | {r.get('release_date','')} | "
                f"{commit} | `{sha}` | {r.get('archive_dir','')} |"
            )
        current = data.get("current") or {}
        return "\n".join([
            f"# {self.cfg.product_title} — Release History",
            "",
            "Permanent, append-only archive maintained by the release engine.",
            "Each `vX.Y.Z-buildN/` folder is a complete, rollback-ready snapshot.",
            "",
            f"**Current release:** v{current.get('version','?')} "
            f"(Build {current.get('build','?')}) — {current.get('release_date','')}",
            "",
            "## Releases",
            "",
            *rows,
            "",
            "## Rollback",
            "",
            "To roll back, copy an archived IPA back over the export source (or "
            "`static/downloads/`) and re-run the release command, or restore the "
            "archived `manifest.plist` / `install.html` and redeploy.",
            "",
        ])

    def _append_changelog(self) -> None:
        path = self.repo_root / self.cfg.changelog_path
        if not path.is_file():
            return
        entry = (
            f"## {datetime.now().strftime('%Y-%m-%d')}\n\n"
            f"### Deploy {self.cfg.product_title} v{self.ipa.version} (Build {self.ipa.build})\n"
            f"- Files: {self.cfg.downloads_dir}/ (IPA, manifest.plist, install.html), "
            f"{self.cfg.releases_dir}/v{self.ipa.version}-build{self.ipa.build}/\n"
            f"- Synced from IPA: version {self.ipa.version}, build {self.ipa.build}, "
            f"bundle {self.ipa.bundle_id}\n"
            f"- SHA-256: {self.source_sha}\n"
            f"- Notes: automated release via /release-{self.cfg.key}\n\n---\n\n"
        )
        text = path.read_text()
        marker = "<!-- \nTEMPLATE FOR NEW ENTRIES:"
        if marker in text:
            text = text.replace(marker, entry + marker, 1)
        else:
            text = text.rstrip() + "\n\n" + entry
        path.write_text(text)
        self.log(f"  appended changelog entry")

    # -- fs / hash --
    def _write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def _history_path(self) -> Path:
        return self.out_releases / "history.json"

    @staticmethod
    def _sha256_file(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _rel(self, path: Path) -> str:
        try:
            return str(Path(path).relative_to(self.repo_root))
        except ValueError:
            return str(path)

    @staticmethod
    def _esc(text: str) -> str:
        return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    @staticmethod
    def _basename(url: str) -> str:
        return url.rstrip("/").rsplit("/", 1)[-1]

    # -- network --
    def _http_status(self, url: str) -> int:
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read(1)
                return resp.status
        except urllib.error.HTTPError as e:  # noqa
            return e.code
        except Exception:  # noqa: BLE001
            return 0

    def _http_sha(self, url: str) -> Optional[str]:
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                if resp.status != 200:
                    return None
                h = hashlib.sha256()
                for chunk in iter(lambda: resp.read(1 << 20), b""):
                    h.update(chunk)
                return h.hexdigest()
        except Exception:  # noqa: BLE001
            return None

    # -- git --
    def _git(self, *args, env=None, check=True):
        proc = subprocess.run(
            ["git", *args], cwd=self.repo_root,
            capture_output=True, text=True, env=env,
        )
        if proc.returncode != 0:
            if check:
                raise ReleaseError(
                    f"git {' '.join(args)} failed:\n{proc.stderr.strip() or proc.stdout.strip()}"
                )
            return None
        return proc.stdout

    # -- logging --
    def _banner(self, text: str) -> None:
        self.log("=" * 68)
        self.log(text)
        self.log("=" * 68)

    def _step(self, n: int, title: str) -> None:
        self.log(f"\n── Step {n}: {title} " + "─" * max(0, 46 - len(title)))
