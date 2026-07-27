---
description: Publish (default) or verify (/release verify) this product's release via the Beacon Release Engine. Default returns after the GitHub push; verify waits for Railway and runs full production validation.
---

# /release — Beacon product release

This repo is a Beacon **product**. It ends at *Export IPA*; Beacon Innovation owns
everything after that. The engine is product-agnostic and lives in the Beacon repo;
this command invokes it for the current product. Two modes, chosen by `$ARGUMENTS`:

- **(no argument) → PUBLISH** — stage the exported IPA and run the engine's publish
  (inspect → manifest → install page → notes → commit → push), then **return the
  moment GitHub accepts the push**. Railway deploys in the background. Fast.
- **`verify` (or `--verify`) → VERIFY** — wait for Railway (with live progress and
  elapsed time), then run the **complete, authoritative production validation**.

**Never fabricate success:** if the engine halts, report the exact error and stop.
Read `beacon.repo` from `./release.yaml`; if `release.yaml` is missing, tell the
user to install the Beacon release starter kit.

## If `$ARGUMENTS` contains "verify" → VERIFY MODE

```bash
python3 <beacon.repo>/scripts/beacon_release/release.py --product-repo "$PWD" --verify
```
Report each ✓ check (install page 200, manifest 200, IPA downloaded, SHA-256,
bundle id, version, legacy redirects) and the install URL. If it halts with
"Deployment not live", Railway is still building — tell the user to run
`/release verify` again shortly. Do not report success unless every check passes.

## Otherwise → PUBLISH MODE

1. **Confirm a pending IPA** exists in `source.pending_dir` (default
   `releases/pending/`). If none, stop and tell the user to export the IPA there.
   (A product may customize this command to auto-locate the IPA from its export
   folder — see the AIMS command for an example.)

2. **Write concise, user-facing release notes** to a scratch file (e.g.
   `/tmp/release-notes.md`), based only on what changed since the last release:
   ```markdown
   ## What's New
   - <concise line>
   ## Bug Fixes
   - <concise line>   (omit if none)
   ```

3. **Publish (returns after the push — no Railway wait):**
   ```bash
   python3 <beacon.repo>/scripts/beacon_release/release.py \
     --product-repo "$PWD" --notes-file /tmp/release-notes.md
   ```
   It exits non-zero on any failure (missing IPA, bundle-id/version mismatch,
   artifact drift, push failure).

4. **Report** the publish summary (Version, Build, Bundle ID, Commit ID, Install
   URL) and tell the user the release is published, Railway is deploying in the
   background, and to run `/release verify` for production verification.

## Notes

- Default publish is fast; production verification is a deliberate, separate step
  (`/release verify`) — developers are not forced to wait 10–15 minutes per release.
- Verify is the authoritative production path and removes none of the safety checks.
- A preview with no git/deploy: add `--dry-run` to the publish command.
- All permanent artifacts (IPA, manifest, portal, notes, history, rollback) live in
  the **Beacon** repo. This repo owns only `release.yaml`, `releases/pending/`, and
  this command. See `docs/beacon_release_framework.md`.
