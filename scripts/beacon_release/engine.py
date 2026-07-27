"""The Beacon Release Engine — product-agnostic release pipeline.

Reads a product repo's `release.yaml` + pending IPA (the single source of truth)
and publishes the release into the Beacon repo: stage artifacts, synchronize the
manifest + Release Portal, generate release notes, archive an immutable snapshot,
validate, commit, push, wait for Railway, and verify the live deployment
byte-for-byte. Stops with a clear error on any inconsistency — never a false
success.

One engine, many products. Nothing here is AIMS-specific.
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
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import ProductConfig
from ipainfo import inspect_ipa, IPAInfo
import templates


# The production site sits behind a WAF that returns 403 to non-browser
# user-agents. Every verification request presents a real browser UA so the
# checks see what a device/browser sees (HTTP 200), never a false 403.
BROWSER_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


class ReleaseError(Exception):
    """Stops the pipeline immediately with a clear explanation."""


@dataclass
class ReleaseNotes:
    whats_new: List[str] = field(default_factory=list)
    bug_fixes: List[str] = field(default_factory=list)
    known_issues: List[str] = field(default_factory=list)


class ReleaseEngine:
    def __init__(
        self,
        config: ProductConfig,
        product_repo: Path,
        beacon_repo: Path,
        *,
        dry_run: bool = False,
        deploy: bool = True,
        verify_only: bool = False,
        notes_override: Optional[ReleaseNotes] = None,
        poll_timeout: Optional[int] = None,
        poll_interval: int = 15,
        scratch_dir: Optional[Path] = None,
        log=print,
    ):
        self.cfg = config
        self.product_repo = Path(product_repo)
        self.beacon_repo = Path(beacon_repo)
        self.dry_run = dry_run
        self.deploy = deploy and not dry_run
        # Verify mode waits for Railway and validates the ALREADY-published
        # release; it never stages, commits, or pushes.
        self.verify_only = verify_only
        self.notes_override = notes_override
        self.poll_timeout = poll_timeout if poll_timeout is not None else config.poll_timeout
        self.poll_interval = poll_interval
        self.scratch_dir = scratch_dir
        self.log = log

        # state
        self.source_ipa: Optional[Path] = None
        self.ipa_dest_name: Optional[str] = None
        self.ipa: Optional[IPAInfo] = None
        self.notes: Optional[ReleaseNotes] = None
        self.source_sha: Optional[str] = None
        self.product_commit: Optional[str] = None
        self.release_date = datetime.now().strftime("%B %-d, %Y")
        self.deployed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.commit_id: Optional[str] = None
        self.archive_dir: Optional[Path] = None
        self.report_data: Dict[str, str] = {}
        # verify-mode expectations (loaded from the published artifacts)
        self.expected_version: Optional[str] = None
        self.expected_bundle_id: Optional[str] = None

    # -- output roots (scratch in dry-run, beacon repo otherwise) --
    def _root(self) -> Path:
        if self.dry_run:
            base = self.scratch_dir or (self.beacon_repo / ".release-dryrun")
            base.mkdir(parents=True, exist_ok=True)
            return base
        return self.beacon_repo

    @property
    def out_downloads(self) -> Path:
        return self._root() / "downloads" / self.cfg.downloads_subpath

    @property
    def out_releases(self) -> Path:
        return self._root() / "releases" / self.cfg.key

    @property
    def redirects_file(self) -> Path:
        return self._root() / "downloads" / "_redirects.json"

    # ==================================================================
    def run(self) -> Dict[str, str]:
        """Dispatch: verify-only waits for + validates the live deployment;
        otherwise publish (and, in default mode, stop after the push)."""
        if self.verify_only:
            return self.run_verify()
        return self.run_publish()

    # -- publish (default): discover → … → commit → push, then STOP ----
    def run_publish(self) -> Dict[str, str]:
        mode = "DRY RUN" if self.dry_run else ("PUBLISH" if self.deploy else "LOCAL (no push)")
        self._banner(f"Beacon Release — {self.cfg.display_name} [{mode}]")
        self._phase("Preparing release...")
        self.step_locate()      # ✓ Located latest IPA
        self.step_inspect()     # guards (bundle id / name)
        self.step_notes()       # ✓ Generated release notes
        self.step_stage()       # ✓ Staged IPA
        self.step_sync()        # ✓ Updated manifest / install page
        self.step_archive()     # ✓ Archived snapshot
        self.step_history()     # record BEFORE the commit so it is included
        self.step_validate()    # ✓ Consistency validated
        if self.deploy:
            self.step_commit()  # ✓ Commit created
            self.step_push()    # ✓ Pushed to GitHub
        else:
            self._ok("Local publish only — commit/push skipped (dry-run or --no-deploy)")
        data = self.step_report()
        if self.deploy:
            self._phase("Release published to GitHub.")
            self.log("Railway deployment is occurring in the background.")
            self.log('Run "/release verify" to wait for production verification.')
        return data

    # -- verify: wait for Railway + full production validation ----------
    def run_verify(self) -> Dict[str, str]:
        self._banner(f"Beacon Release — {self.cfg.display_name} [VERIFY]")
        self._load_published()      # expected version/build/bundle/sha from the published artifacts
        self._wait_for_railway()    # progress + elapsed time; stop the moment it's detected
        self._production_validation()  # the authoritative, complete check set
        self._phase("Release complete.")
        return self.report_data

    # -- 1. locate ------------------------------------------------------
    def step_locate(self) -> None:
        self._step(1, "Locate pending IPA")
        pending = self.product_repo / self.cfg.pending_dir
        if not pending.is_dir():
            raise ReleaseError(
                f"Pending dir not found: {pending}\n"
                f"Export the IPA into {self.cfg.pending_dir}/ inside the product repo."
            )
        if self.cfg.ipa_name:
            ipa = pending / self.cfg.ipa_name
            if not ipa.is_file():
                raise ReleaseError(f"Configured IPA not found: {ipa}")
        else:
            ipas = sorted(pending.glob("*.ipa"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not ipas:
                raise ReleaseError(f"No *.ipa in {pending}. Drop the exported IPA there first.")
            ipa = ipas[0]
        self.source_ipa = ipa
        self.ipa_dest_name = ipa.name
        self.source_sha = self._sha256_file(ipa)
        # Product repo HEAD, captured now so history (written before the Beacon
        # commit) records which product commit produced this build.
        self.product_commit = (self._git_product("rev-parse", "HEAD", check=False) or "").strip() or None
        self.log(f"  ipa    : {self._rel(ipa, self.product_repo)}")
        self.log(f"  sha256 : {self.source_sha}")
        self._ok("Located latest IPA")

    # -- 2. inspect -----------------------------------------------------
    def step_inspect(self) -> None:
        self._step(2, "Inspect IPA (source of truth)")
        self.ipa = inspect_ipa(self.source_ipa, extra_dir=self.source_ipa.parent)
        ipa = self.ipa
        for k, v in [
            ("Application Name", ipa.app_name), ("Display Name", ipa.display_name),
            ("Bundle Identifier", ipa.bundle_id), ("Version", ipa.version),
            ("Build Number", ipa.build), ("Minimum iOS", ipa.min_ios),
        ]:
            self.log(f"  {k:<18}: {v}")
        for k, v in ipa.signing.items():
            self.log(f"  {('signing.' + k):<18}: {v}")
        # guards from release.yaml
        if self.cfg.bundle_id and ipa.bundle_id != self.cfg.bundle_id:
            raise ReleaseError(
                f"Bundle id mismatch: IPA '{ipa.bundle_id}' != release.yaml '{self.cfg.bundle_id}'. "
                f"Refusing to publish the wrong app."
            )
        if self.cfg.name and ipa.app_name and ipa.app_name != self.cfg.name:
            raise ReleaseError(
                f"App name mismatch: IPA CFBundleName '{ipa.app_name}' != release.yaml '{self.cfg.name}'."
            )
        self._ok(f"Inspected IPA — v{ipa.version} (Build {ipa.build}), {ipa.bundle_id}")

    # -- 5. release notes (computed early; portal embeds them) ---------
    def step_notes(self) -> None:
        self._step(5, "Generate release notes")
        if self.notes_override is not None:
            self.notes = self.notes_override
            self.log("  using supplied notes override")
        else:
            self.notes = self._auto_notes()
        if not self.notes.known_issues:
            self.notes.known_issues = ["None reported."]
        for heading, items in [("What's New", self.notes.whats_new),
                               ("Bug Fixes", self.notes.bug_fixes),
                               ("Known Issues", self.notes.known_issues)]:
            self.log(f"  {heading}:")
            for it in (items or ["(none)"]):
                self.log(f"    - {it}")
        self._ok("Generated release notes")

    def _auto_notes(self) -> ReleaseNotes:
        subjects = self._product_commit_subjects()
        notes = ReleaseNotes()
        seen = set()
        for subj in subjects:
            if subj.lower().startswith("deploy "):
                continue
            clean = self._clean_subject(subj)
            key = clean.lower()
            if not clean or key in seen:
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

    def _product_commit_subjects(self) -> List[str]:
        if not (self.product_repo / ".git").exists():
            return []
        prev = self._previous_product_commit()
        args = ["log", "--no-merges", "--pretty=format:%s"]
        args += ([f"{prev}..HEAD"] if prev else ["-n", "20"])
        out = self._git_product(*args)
        return [s.strip() for s in (out or "").splitlines() if s.strip()]

    def _previous_product_commit(self) -> Optional[str]:
        history = self._history_path()
        if not history.is_file():
            return None
        try:
            data = json.loads(history.read_text())
            commit = (data.get("current") or {}).get("product_commit")
            if commit and self._git_product("cat-file", "-t", commit, check=False):
                return commit
        except Exception:  # noqa: BLE001
            pass
        return None

    @staticmethod
    def _clean_subject(subj: str) -> str:
        for prefix in ("feat:", "fix:", "feature:", "add:", "chore:", "docs:"):
            if subj.lower().startswith(prefix):
                subj = subj[len(prefix):].strip()
                break
        return subj[:1].upper() + subj[1:] if subj else subj

    # -- 3. stage -------------------------------------------------------
    def step_stage(self) -> None:
        self._step(3, "Stage IPA into Beacon downloads")
        dest = self.out_downloads / self.ipa_dest_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.source_ipa, dest)
        if self._sha256_file(dest) != self.source_sha:
            raise ReleaseError("Staged IPA hash does not match source — copy failed.")
        self.log(f"  copied -> {self._rel(dest, self.beacon_repo)}")
        self._ok("Staged IPA")

    # -- 4/6. synchronize + publish ------------------------------------
    def step_sync(self) -> None:
        self._step(4, "Synchronize manifest + Release Portal")
        title = self.cfg.portal_title
        manifest = templates.render(templates.MANIFEST_TEMPLATE, {
            "IPA_URL": self.cfg.ipa_url(self.ipa_dest_name),
            "BUNDLE_ID": self.ipa.bundle_id,
            "VERSION": self.ipa.version,
            "PRODUCT_TITLE": title,
        })
        self._write(self.out_downloads / self.cfg.manifest_name, manifest)
        self._ok("Updated manifest")

        icon_block = (
            f'            <img class="app-icon" src="{self._esc(self.cfg.icon)}" '
            f'alt="{self._esc(title)} icon">\n' if self.cfg.icon else ""
        )
        desc_block = (
            f'            <p class="desc">{self._esc(self.cfg.description)}</p>\n'
            if self.cfg.description else ""
        )
        page = templates.render(templates.INSTALL_PAGE_TEMPLATE, {
            "PRODUCT_TITLE": title,
            "ICON_BLOCK": icon_block,
            "DESCRIPTION_BLOCK": desc_block,
            "VERSION": self.ipa.version,
            "BUILD": self.ipa.build,
            "RELEASE_DATE": self.release_date,
            "MANIFEST_URL": self.cfg.manifest_url,
            "BUNDLE_ID": self.ipa.bundle_id,
            "MIN_IOS": self.ipa.min_ios or "—",
            "WHATS_NEW_SECTION": self._notes_section("What's New", self.notes.whats_new),
            "BUG_FIXES_SECTION": self._notes_section("Bug Fixes", self.notes.bug_fixes),
            "KNOWN_ISSUES_SECTION": self._notes_section("Known Issues", self.notes.known_issues, muted=True),
            "PREVIOUS_RELEASES_SECTION": self._previous_releases_section(),
        })
        self._write(self.out_downloads / self.cfg.install_page_name, page)
        self._ok("Updated install page")

    def _notes_section(self, heading: str, items: List[str], muted: bool = False) -> str:
        if not items:
            return ""
        cls = ' class="muted"' if muted else ""
        lis = "\n".join(f"                <li{cls}>{self._esc(i)}</li>" for i in items)
        return templates.render(templates.NOTES_SECTION_TEMPLATE, {"HEADING": heading, "ITEMS": lis})

    def _previous_releases_section(self) -> str:
        if not self.cfg.show_previous_releases:
            return ""
        history = self._load_history()
        prior = [r for r in history.get("releases", [])
                 if not (r.get("version") == self.ipa.version and r.get("build") == self.ipa.build)]
        if not prior:
            return ""
        rows = "\n".join(
            f"                <tr><td>{self._esc(r['version'])}</td>"
            f"<td>{self._esc(str(r['build']))}</td>"
            f"<td>{self._esc(r.get('release_date',''))}</td></tr>"
            for r in prior[:10]
        )
        return templates.render(templates.PREVIOUS_RELEASES_TEMPLATE, {"ROWS": rows})

    # -- 7. archive -----------------------------------------------------
    def step_archive(self) -> None:
        self._step(7, "Archive immutable snapshot")
        name = f"v{self.ipa.version}-build{self.ipa.build}"
        self.archive_dir = self.out_releases / name
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        for fn in (self.ipa_dest_name, self.cfg.manifest_name, self.cfg.install_page_name):
            shutil.copy2(self.out_downloads / fn, self.archive_dir / fn)
        self._write(self.archive_dir / "SHA256.txt", f"{self.source_sha}  {self.ipa_dest_name}\n")
        self._write(self.archive_dir / "release_notes.md", self._notes_markdown())
        self._write(self.archive_dir / "deployment_summary.md", self._summary_markdown())
        self._write(self.archive_dir / "metadata.json", json.dumps(self._release_record(), indent=2) + "\n")
        self._update_redirects()
        self._ok("Archived immutable snapshot")

    def _update_redirects(self) -> None:
        if not self.cfg.legacy_redirects:
            return
        path = self.redirects_file
        current = {}
        if path.is_file():
            try:
                current = json.loads(path.read_text())
            except Exception:  # noqa: BLE001
                current = {}
        for legacy in self.cfg.legacy_redirects:
            target = f"{self.cfg.url_path.rstrip('/')}/{legacy.rstrip('/').rsplit('/', 1)[-1]}"
            current[legacy] = target
        self._write(path, json.dumps(current, indent=2, sort_keys=True) + "\n")
        self.log(f"  redirects -> {len(self.cfg.legacy_redirects)} legacy path(s) mapped")

    # -- 8. validate ----------------------------------------------------
    def step_validate(self) -> None:
        self._step(8, "Validate consistency")
        staged = self.out_downloads / self.ipa_dest_name
        if self._sha256_file(staged) != self.source_sha:
            raise ReleaseError("Validation failed: staged IPA hash != source.")
        with open(self.out_downloads / self.cfg.manifest_name, "rb") as fh:
            man = plistlib.load(fh)
        meta = man["items"][0]["metadata"]
        asset_url = man["items"][0]["assets"][0]["url"]
        for label, got, want in [
            ("manifest bundle-identifier", meta["bundle-identifier"], self.ipa.bundle_id),
            ("manifest bundle-version", meta["bundle-version"], self.ipa.version),
            ("manifest asset url", asset_url, self.cfg.ipa_url(self.ipa_dest_name)),
        ]:
            if got != want:
                raise ReleaseError(f"Validation failed: {label} is '{got}', expected '{want}'.")
        page = (self.out_downloads / self.cfg.install_page_name).read_text()
        for label, needle in [("version", self.ipa.version), ("build", self.ipa.build),
                              ("bundle id", self.ipa.bundle_id),
                              ("manifest url", self.cfg.manifest_url)]:
            if needle not in page:
                raise ReleaseError(f"Validation failed: install page missing {label} '{needle}'.")
        self._ok("Consistency validated (bundle id, version, build, manifest, install page, IPA)")

    # -- 9. commit ------------------------------------------------------
    def step_commit(self) -> None:
        self._step(9, "Commit (Beacon repo)")
        paths = [
            f"downloads/{self.cfg.downloads_subpath}",
            f"releases/{self.cfg.key}",
            "downloads/_redirects.json",
        ]
        self.product_commit = self._git_product("rev-parse", "HEAD", check=False)
        self.product_commit = self.product_commit.strip() if self.product_commit else None
        self._git("add", "--", *paths)
        if not (self._git("diff", "--cached", "--name-only") or "").strip():
            raise ReleaseError("Nothing staged to commit — deployment artifacts unchanged.")
        message = (
            f"Deploy {self.cfg.display_name} v{self.ipa.version} (Build {self.ipa.build})\n\n"
            f"Published from IPA (source of truth). Bundle {self.ipa.bundle_id}, "
            f"SHA256 {self.source_sha}.\n\n"
            f"Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
        )
        self._git("commit", "-m", message)
        self.commit_id = (self._git("rev-parse", "HEAD") or "").strip()
        self._ok(f"Commit created ({self.commit_id[:9]})")

    # -- 10. push -------------------------------------------------------
    def step_push(self) -> None:
        self._step(10, "Push to GitHub")
        branch = (self._git("rev-parse", "--abbrev-ref", "HEAD") or "").strip()
        # GitHub's SSH-over-443 endpoint; accept-new trusts the host key on first
        # use (standard for automation) so a fresh machine needs no known_hosts setup.
        env = {**os.environ, "GIT_SSH_COMMAND": "ssh -p 443 -o StrictHostKeyChecking=accept-new"}
        self._git("push", "origin", branch, env=env)
        if branch != self.cfg.deploy_branch:
            res = self._git("push", "origin", f"HEAD:{self.cfg.deploy_branch}", env=env, check=False)
            if res is None:
                raise ReleaseError(
                    f"Could not fast-forward '{self.cfg.deploy_branch}' from '{branch}'. "
                    f"Merge manually and re-run."
                )
            self.log(f"  {branch} -> fast-forwarded {self.cfg.deploy_branch}")
        self._ok(f"Pushed to GitHub ({self.cfg.deploy_branch}) — Railway will deploy")

    # -- 11+12. verify --------------------------------------------------
    def step_verify(self) -> None:
        self._step(11, "Verify deployment (HTTP 200 + live SHA)")
        deadline = time.time() + self.poll_timeout
        urls = [self.cfg.install_url, self.cfg.manifest_url, self.cfg.ipa_url(self.ipa_dest_name)]
        while True:
            codes = {u: self._http_status(u) for u in urls}
            live_sha = self._http_sha(self.cfg.ipa_url(self.ipa_dest_name))
            if all(c == 200 for c in codes.values()) and live_sha == self.source_sha:
                for u, c in codes.items():
                    self.log(f"  {c}  {u}")
                self.log(f"  live IPA SHA matches source ✓  {live_sha}")
                return
            if time.time() >= deadline:
                detail = " ".join(f"{self._basename(u)}={c}" for u, c in codes.items())
                raise ReleaseError(
                    f"Deployment not live after {self.poll_timeout}s. Statuses: {detail}; "
                    f"live IPA SHA {'matches' if live_sha == self.source_sha else 'does NOT match'}."
                )
            time.sleep(self.poll_interval)

    # -- 14. history ----------------------------------------------------
    def step_history(self) -> None:
        self._step(14, "Update deployment history")
        data = self._load_history()
        record = self._release_record()
        data["releases"] = [r for r in data.get("releases", [])
                            if not (r.get("version") == record["version"]
                                    and r.get("build") == record["build"])]
        data["releases"].insert(0, record)
        data["current"] = record
        data["product"] = self.cfg.key
        self._write(self._history_path(), json.dumps(data, indent=2) + "\n")
        self._write(self.out_releases / "README.md", self._history_readme(data))
        self.log(f"  history -> {self._rel(self._history_path(), self.beacon_repo)} "
                 f"({len(data['releases'])} releases)")

    # -- 13. report -----------------------------------------------------
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
            "Railway Status": "pushed — deploying in background" if self.deploy else "not deployed",
            "Deployment Date": self.deployed_at,
            "SHA-256": self.source_sha,
            "Production Verification": "run '/release verify'" if self.deploy else "n/a",
            "Install URL": self.cfg.install_url,
        }
        width = max(len(k) for k in self.report_data)
        self.log("")
        for k, v in self.report_data.items():
            self.log(f"  {k:<{width}} : {v}")
        return self.report_data

    # ==================================================================
    # verify mode (authoritative production validation)
    # ==================================================================
    def _load_published(self) -> None:
        """Read what SHOULD be live from the already-published Beacon artifacts —
        never from a pending IPA. Verify checks the deployed build, not a rebuild."""
        self._phase("Loading published release...")
        manifest_path = self.out_downloads / self.cfg.manifest_name
        if not manifest_path.is_file():
            raise ReleaseError(
                f"Nothing published yet for '{self.cfg.key}' "
                f"({self._rel(manifest_path, self.beacon_repo)} not found). "
                f"Run /release to publish first."
            )
        with open(manifest_path, "rb") as fh:
            man = plistlib.load(fh)
        meta = man["items"][0]["metadata"]
        asset_url = man["items"][0]["assets"][0]["url"]
        self.expected_version = str(meta["bundle-version"])
        self.expected_bundle_id = str(meta["bundle-identifier"])
        self.ipa_dest_name = self._basename(asset_url)
        ipa_path = self.out_downloads / self.ipa_dest_name
        if not ipa_path.is_file():
            raise ReleaseError(f"Published IPA missing: {self._rel(ipa_path, self.beacon_repo)}")
        self.source_sha = self._sha256_file(ipa_path)
        self._ok(f"Published build: v{self.expected_version}, {self.ipa_dest_name}")
        self.log(f"  bundle id : {self.expected_bundle_id}")
        self.log(f"  sha256    : {self.source_sha}")

    def _wait_for_railway(self) -> None:
        """Poll until the live IPA matches the published build. Shows elapsed time
        and what is being waited on; returns the instant the deployment is detected."""
        self._phase("Waiting for Railway deployment...")
        ipa_url = self.cfg.ipa_url(self.ipa_dest_name)
        start = time.time()
        deadline = start + self.poll_timeout
        first = True
        while True:
            elapsed = int(time.time() - start)
            live_sha = self._http_sha(ipa_url)
            if live_sha == self.source_sha:
                self._ok(f"Deployment detected (after {elapsed}s)")
                return
            # Not live yet — say why, with elapsed time.
            status = self._http_status(ipa_url)
            if first:
                self._bullet("Polling deployment status...")
                first = False
            reason = ("build in progress (old build still serving)"
                      if status == 200 else f"waiting for site (HTTP {status or 'no response'})")
            self._bullet(f"[{elapsed:>3}s] {reason}")
            if time.time() >= deadline:
                raise ReleaseError(
                    f"Deployment not live after {self.poll_timeout}s. The push succeeded, "
                    f"so Railway may still be building — re-run '/release verify' shortly. "
                    f"(Last: live IPA SHA does not yet match the published build.)"
                )
            time.sleep(self.poll_interval)

    def _production_validation(self) -> None:
        """The complete, authoritative production check set. Any failure stops the
        pipeline — success is never reported unless every check passes."""
        self._phase("Running production verification...")
        install_url = self.cfg.install_url
        manifest_url = self.cfg.manifest_url
        ipa_url = self.cfg.ipa_url(self.ipa_dest_name)

        # install page + manifest reachable
        self._require(self._http_status(install_url) == 200, f"Install page not 200: {install_url}")
        self._ok("Install page (HTTP 200)")
        self._require(self._http_status(manifest_url) == 200, f"Manifest not 200: {manifest_url}")
        self._ok("Manifest (HTTP 200)")

        # IPA downloads and its bytes match the published build
        live_sha = self._http_sha(ipa_url)
        self._require(live_sha is not None, f"IPA did not download: {ipa_url}")
        self._ok("IPA downloaded")
        self._require(live_sha == self.source_sha,
                      f"SHA-256 mismatch: live {live_sha} != published {self.source_sha}")
        self._ok("SHA-256 matches build")

        # live manifest agrees on identity
        man = self._http_plist(manifest_url)
        self._require(man is not None, "Could not parse the live manifest.plist.")
        meta = man["items"][0]["metadata"]
        self._require(meta.get("bundle-identifier") == self.expected_bundle_id,
                      f"Live manifest bundle id '{meta.get('bundle-identifier')}' "
                      f"!= '{self.expected_bundle_id}'")
        self._ok("Bundle ID verified")
        self._require(str(meta.get("bundle-version")) == self.expected_version,
                      f"Live manifest version '{meta.get('bundle-version')}' != '{self.expected_version}'")
        self._ok("Version verified")

        # legacy redirects still 301 to the canonical path
        self._verify_redirects()
        self._ok("Legacy redirects verified")

        self.report_data = {
            "Product": self.cfg.display_name,
            "Version": self.expected_version,
            "Bundle Identifier": self.expected_bundle_id,
            "SHA-256": self.source_sha,
            "Install URL": install_url,
            "Verification": "PASS (all production checks)",
        }

    def _verify_redirects(self) -> None:
        base = self.cfg.base_url.rstrip("/")
        for legacy in self.cfg.legacy_redirects:
            want = f"{self.cfg.url_path.rstrip('/')}/{legacy.rstrip('/').rsplit('/', 1)[-1]}"
            code, location = self._http_redirect(base + legacy)
            self._require(
                code in (301, 302, 308) and location and location.endswith(want),
                f"Legacy redirect broken: {legacy} -> {code} {location or '(none)'} "
                f"(expected 301 -> {want})"
            )

    def _require(self, ok: bool, message: str) -> None:
        if not ok:
            raise ReleaseError(message)

    # ==================================================================
    # helpers
    # ==================================================================
    def _load_history(self) -> Dict:
        p = self._history_path()
        if p.is_file():
            try:
                return json.loads(p.read_text())
            except Exception:  # noqa: BLE001
                pass
        return {"product": self.cfg.key, "current": None, "releases": []}

    def _history_path(self) -> Path:
        return self.out_releases / "history.json"

    def _release_record(self) -> Dict:
        return {
            "product": self.cfg.key,
            "display_name": self.cfg.display_name,
            "public_name": self.cfg.portal_title,
            "description": self.cfg.description,
            "icon": self.cfg.icon,
            "platform": self.cfg.platform,
            "version": self.ipa.version,
            "build": self.ipa.build,
            "bundle_id": self.ipa.bundle_id,
            "min_ios": self.ipa.min_ios,
            "sha256": self.source_sha,
            "commit": self.commit_id,
            "product_commit": self.product_commit,
            "deployed_at": self.deployed_at,
            "release_date": self.release_date,
            "archive_dir": self._rel(self.archive_dir, self.beacon_repo) if self.archive_dir else None,
            "install_url": self.cfg.install_url,
            "signing": self.ipa.signing,
        }

    def _notes_markdown(self) -> str:
        return "\n".join([
            f"# {self.cfg.display_name} — Release Notes", "",
            f"- **Version:** {self.ipa.version}",
            f"- **Build:** {self.ipa.build}",
            f"- **Release Date:** {self.release_date}", "",
            "## What's New", *[f"- {i}" for i in (self.notes.whats_new or ["(none)"])], "",
            "## Bug Fixes", *[f"- {i}" for i in (self.notes.bug_fixes or ["(none)"])], "",
            "## Known Issues", *[f"- {i}" for i in (self.notes.known_issues or ["None reported."])], "",
        ])

    def _summary_markdown(self) -> str:
        signing_lines = [f"- **{k}:** {v}" for k, v in self.ipa.signing.items()] or ["- (unavailable)"]
        return "\n".join([
            f"# {self.cfg.display_name} — Deployment Summary", "",
            f"- **Application Name:** {self.ipa.app_name}",
            f"- **Display Name:** {self.ipa.display_name}",
            f"- **Version:** {self.ipa.version}",
            f"- **Build:** {self.ipa.build}",
            f"- **Bundle Identifier:** {self.ipa.bundle_id}",
            f"- **Minimum iOS:** {self.ipa.min_ios}",
            f"- **SHA-256:** `{self.source_sha}`",
            f"- **Release Date:** {self.release_date}",
            f"- **Deployed At:** {self.deployed_at}",
            f"- **Install URL:** {self.cfg.install_url}", "",
            "## Signing", *signing_lines, "",
        ])

    def _history_readme(self, data: Dict) -> str:
        rows = ["| Version | Build | Date | Commit | SHA-256 (short) | Archive |",
                "|---------|-------|------|--------|-----------------|---------|"]
        for r in data["releases"]:
            commit = (r.get("commit") or "")[:9] or "—"
            rows.append(f"| {r['version']} | {r['build']} | {r.get('release_date','')} | "
                        f"{commit} | `{(r.get('sha256') or '')[:12]}` | {r.get('archive_dir','')} |")
        current = data.get("current") or {}
        return "\n".join([
            f"# {self.cfg.display_name} — Release History", "",
            "Permanent, append-only archive maintained by the Beacon Release Engine.",
            "Each `vX.Y.Z-buildN/` folder is a complete, rollback-ready snapshot.", "",
            f"**Current:** v{current.get('version','?')} (Build {current.get('build','?')}) — "
            f"{current.get('release_date','')}", "",
            "## Releases", "", *rows, "",
            "## Rollback", "",
            "Restore an archived snapshot's IPA / manifest / install page into "
            f"`downloads/{self.cfg.downloads_subpath}/` and redeploy.", "",
        ])

    # -- fs / hash --
    def _write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    @staticmethod
    def _sha256_file(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _rel(self, path, root) -> str:
        try:
            return str(Path(path).relative_to(root))
        except ValueError:
            return str(path)

    @staticmethod
    def _esc(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    @staticmethod
    def _basename(url: str) -> str:
        return url.rstrip("/").rsplit("/", 1)[-1]

    # -- network (all requests present a browser UA; the site 403s others) --
    @staticmethod
    def _request(url: str, method: str = "GET") -> "urllib.request.Request":
        return urllib.request.Request(url, method=method, headers={"User-Agent": BROWSER_UA})

    def _http_status(self, url: str) -> int:
        try:
            with urllib.request.urlopen(self._request(url), timeout=30) as r:
                r.read(1)
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception:  # noqa: BLE001
            return 0

    def _http_sha(self, url: str) -> Optional[str]:
        try:
            with urllib.request.urlopen(self._request(url), timeout=120) as r:
                if r.status != 200:
                    return None
                h = hashlib.sha256()
                for chunk in iter(lambda: r.read(1 << 20), b""):
                    h.update(chunk)
                return h.hexdigest()
        except Exception:  # noqa: BLE001
            return None

    def _http_plist(self, url: str):
        try:
            with urllib.request.urlopen(self._request(url), timeout=30) as r:
                if r.status != 200:
                    return None
                return plistlib.loads(r.read())
        except Exception:  # noqa: BLE001
            return None

    def _http_redirect(self, url: str):
        """Return (status, Location) WITHOUT following the redirect, so a 301 is
        visible. Used to prove legacy URLs still redirect to the canonical path."""
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):  # noqa: D401
                return None
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(self._request(url), timeout=30) as r:
                return r.status, r.headers.get("Location")
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Location")
        except Exception:  # noqa: BLE001
            return 0, None

    # -- git --
    def _git(self, *args, env=None, check=True):
        return self._run_git(self.beacon_repo, args, env=env, check=check)

    def _git_product(self, *args, check=True):
        return self._run_git(self.product_repo, args, env=None, check=check)

    def _run_git(self, cwd, args, env=None, check=True):
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            if check:
                raise ReleaseError(f"git {' '.join(args)} failed:\n"
                                   f"{proc.stderr.strip() or proc.stdout.strip()}")
            return None
        return proc.stdout

    # -- logging (phased progress: "Phase..." / "✓ done" / "• waiting") --
    def _banner(self, text: str) -> None:
        self.log("=" * 70)
        self.log(text)
        self.log("=" * 70)

    def _phase(self, text: str) -> None:
        self.log(f"\n{text}")

    def _ok(self, text: str) -> None:
        self.log(f"✓ {text}")

    def _bullet(self, text: str) -> None:
        self.log(f"• {text}")

    # Retained for the step methods; quiet now so the phased ✓/• output reads
    # cleanly. The detailed inner logs and the ✓ summaries carry the narrative.
    def _step(self, n: int, title: str) -> None:
        return
