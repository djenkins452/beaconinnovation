---
description: Publish the latest AIMS Field release from the exported IPA (fully automated).
---

# /release-aims — AIMS Field release pipeline

The exported IPA is the **single source of truth**. After archiving and exporting
AIMS from Xcode into `~/Desktop/AIMS Release Test/`, this command performs every
remaining step automatically: locate → inspect → stage → sync artifacts →
release notes → archive → validate → commit → push → wait for Railway → verify.

The heavy lifting lives in a reusable engine (`scripts/release/`). Your job is to
run it, add judgment where it helps (polished release notes, error explanation),
and report the result. **Never fabricate success** — if the engine halts, explain
why and stop.

## Do this

1. **Preview (dry run).** Run:
   ```bash
   python3 scripts/release/release.py aims --dry-run
   ```
   This locates the newest export, inspects the IPA, and generates artifacts into
   `.release-dryrun/` without touching git or the live site. Read the output:
   confirm the Version, Build, and Bundle Identifier look right, and read the
   auto-generated **What's New / Bug Fixes** draft.
   - If the engine halts here (no IPA, bundle-id mismatch, etc.), report the exact
     error and STOP. Do not proceed.

2. **Polish the release notes.** The auto-draft is derived from git commits and is
   often noisy. Write a clean, user-facing version to a scratch file, e.g.
   `scratchpad/aims-notes.md`, using this structure:
   ```markdown
   ## What's New
   - <concise, user-facing line>
   ## Bug Fixes
   - <concise, user-facing line>   (omit the section if none)
   ## Known Issues
   - <line>                        (or omit — engine defaults to "None reported.")
   ```
   Keep it short and honest — base it only on what actually changed since the
   previous release. If nothing meaningful changed, a one-line maintenance note is
   fine.

3. **Deploy for real.** Run:
   ```bash
   python3 scripts/release/release.py aims --notes-file scratchpad/aims-notes.md
   ```
   This copies the IPA into `static/downloads/`, regenerates `manifest.plist` and
   the `install.html` release portal, archives the release under `releases/aims/`,
   validates that everything agrees, commits only the deployment files, pushes,
   fast-forwards the deploy branch so Railway deploys, then polls the live site
   until all three URLs return HTTP 200 **and** the live IPA SHA-256 matches the
   source. It exits non-zero on any failure.
   - The push waits for Railway; this can take a couple of minutes. If it exceeds
     the poll timeout the engine reports which check failed — relay that verbatim.

4. **Report.** Relay the engine's final Deployment Report: Application Name,
   Version, Build, Bundle Identifier, Commit ID, Railway status, Deployment Date,
   SHA verification, and the Install URL
   (https://beacon-innovation.com/static/downloads/install.html).

## Notes

- Fully automatic — no prompts to the user during a run.
- The engine stops immediately on: missing IPA, bundle-id/version/build mismatch,
  manifest/install-page disagreement, git/push failure, Railway timeout, or a live
  SHA mismatch. Surface the real error; never claim success it didn't report.
- Config for AIMS (and future products) lives in `scripts/release/config.py`.
  See `docs/beacon_release_pipeline.md` for architecture and how to add
  `/release-wlj`, `/release-utmc`, etc.
