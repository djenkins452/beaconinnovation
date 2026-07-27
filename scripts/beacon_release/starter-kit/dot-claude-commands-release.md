---
description: Publish this product's latest release via the Beacon Release Engine (fully automated).
---

# /release — Beacon product release

This repo is a Beacon **product**. It ends at *Export IPA*; Beacon Innovation owns
everything after that. This command hands the exported IPA to the **Beacon Release
Engine**, which does the rest: inspect → stage → sync manifest + Release Portal →
release notes → archive → validate → commit → push → wait for Railway → verify.

The engine is product-agnostic and lives in the Beacon repo — this command just
invokes it for the current product. **Never fabricate success**: if the engine
halts, report the exact error and stop.

## Do this

1. **Confirm this is a Beacon product repo.** Read `./release.yaml`. If it's missing,
   stop and tell the user to install the Beacon release starter kit. Note the
   `beacon.repo` path (the Beacon repo that hosts the engine).

2. **Confirm a pending IPA exists** in the `source.pending_dir` from `release.yaml`
   (default `releases/pending/`). If none, stop and tell the user to export the IPA
   there first.

3. **Preview (dry run).** Run the engine with the Beacon repo path from `release.yaml`:
   ```bash
   python3 <beacon.repo>/scripts/beacon_release/release.py --product-repo "$PWD" --dry-run
   ```
   Read the output: confirm Version, Build, and Bundle Identifier look right, and read
   the auto-generated release-notes draft. If the engine halts here, report the error
   and STOP.

4. **Polish the release notes.** The auto-draft is derived from this repo's git
   commits and is often noisy. Write a clean, user-facing version to a scratch file
   (e.g. `/tmp/release-notes.md`) using:
   ```markdown
   ## What's New
   - <concise, user-facing line>
   ## Bug Fixes
   - <concise, user-facing line>   (omit the section if none)
   ## Known Issues
   - <line>                        (or omit — defaults to "None reported.")
   ```
   Base it only on what actually changed since the previous release.

5. **Release for real.** Run:
   ```bash
   python3 <beacon.repo>/scripts/beacon_release/release.py --product-repo "$PWD" --notes-file /tmp/release-notes.md
   ```
   This publishes into the Beacon repo, commits, pushes, waits for Railway, and verifies
   HTTP 200 + live IPA SHA. It exits non-zero on any failure (missing IPA,
   bundle-id/version mismatch, artifact drift, push failure, Railway timeout, SHA
   mismatch). The Railway wait can take a couple of minutes.

6. **Report** the engine's Deployment Report: Application Name, Version, Build, Bundle
   Identifier, Commit ID, Railway status, Deployment Date, SHA verification, and the
   canonical Install URL.

## Notes

- Fully automatic — no prompts to the user during a run.
- All permanent artifacts (IPA, manifest, portal, notes, history, rollback) live in the
  **Beacon** repo, not here. This repo only holds `release.yaml` and the pending IPA.
- See the Beacon repo's `docs/beacon_release_framework.md` for architecture.
