# Beacon Release Framework

**One release engine, many products.** Beacon Innovation owns software distribution.
Each product repo (AIMS, Whole Life Journey, UTMC HR, future products) ends at
**Code → Archive → Export IPA**. Everything after that — publishing, archiving,
verifying, distributing — is owned by the Beacon Innovation repo and performed by a
single, product-agnostic **Beacon Release Engine**.

The **exported IPA is the single source of truth.** Every deployment artifact is
derived from it automatically. Nobody hand-edits version, build, bundle identifier,
application name, `manifest.plist`, or the install page.

## The workflow

Inside any Beacon product repo:

1. Product → **Archive** (Xcode)
2. Release Testing → **Export IPA** → drop it in `releases/pending/`
3. `/release`

The `/release` command hands the IPA to the engine, which does everything else and
returns the live install URL.

## Architecture — engine vs. configuration

```
PRODUCT REPO (AIMS, WLJ, …)                 BEACON INNOVATION REPO (this repo)
──────────────────────────                  ──────────────────────────────────
release.yaml               ──reads──▶        scripts/beacon_release/   ← the ONE engine
releases/pending/<app>.ipa ──ingest─▶        distribution/             ← serves /downloads/<p>/
.claude/commands/release.md ─invokes▶        downloads/<product>/      ← live artifacts (served)
   (generic, from kit)                       releases/<product>/       ← permanent archive + history
```

- **Product repo** owns only: `release.yaml`, `releases/pending/` (drop zone), and the
  generic `/release` command. No manifests, install pages, or committed binaries.
- **Beacon repo** owns: the engine, the serving layer, the live artifacts, and the
  permanent archive / rollback history.

### Engine (`scripts/beacon_release/`)

| File | Responsibility |
|------|----------------|
| `config.py`    | Load + validate `release.yaml` → `ProductConfig`. Never guesses. |
| `yamlcompat.py`| YAML load: PyYAML if present, else a minimal built-in fallback. |
| `ipainfo.py`   | Inspect the IPA (stdlib `zipfile`/`plistlib`); signing from `DistributionSummary.plist` or the embedded profile. |
| `templates.py` | `manifest.plist` + Release Portal `install.html` (incl. Previous Releases). |
| `engine.py`    | `ReleaseEngine` — the cross-repo pipeline. |
| `release.py`   | CLI entry point. |
| `starter-kit/` | What gets installed into each product repo. |

### Pipeline (halts with a clear error + non-zero exit on any inconsistency)

1. **Locate** the pending IPA in the product repo (fail if none).
2. **Inspect** the IPA → app name, display name, bundle id, version, build, min iOS, signing.
3. **Validate guards**: IPA bundle id / name must match `release.yaml`.
4. **Stage** IPA → `downloads/<product>/` (verify copied SHA == source).
5. **Release notes** from the product repo's git log since the last released commit
   (categorized into What's New / Bug Fixes; overridable via `--notes-file`).
6. **Sync + publish** `manifest.plist` + Release Portal from IPA values + notes + history.
7. **Archive** an immutable snapshot → `releases/<product>/vX.Y.Z-buildN/`; update
   `history.json` + `README.md` + `downloads/_redirects.json`.
8. **Validate consistency**: bundle id / version / build / manifest / install page / IPA agree.
9. **Commit** the Beacon repo — only deployment files: `Deploy <display> vX.Y.Z (Build N)`.
10. **Push** + fast-forward the deploy branch (Railway) via `ssh -p 443`.
11. **Verify** live: poll until all `/downloads/<product>/` URLs are HTTP 200 **and** the
    live IPA SHA-256 matches the source.
12. **Report** + return the canonical install URL.

The engine is non-destructive to the product repo (it reads the pending IPA; it does
not commit or delete it).

### CLI

```bash
# normally invoked by a product repo's /release command:
python3 <beacon>/scripts/beacon_release/release.py --product-repo <product-repo> [options]

--dry-run          build artifacts into <beacon>/.release-dryrun/, no git/deploy
--no-deploy        write + commit in the Beacon repo, skip push/verify
--notes-file PATH  markdown overriding the auto-generated release notes
--poll-timeout N   override release.yaml deploy.poll_timeout
```

## Serving layer — `distribution` app

`/downloads/<product>/` is served by the `distribution` Django app (generic; one product
param, no per-product code):

- `serve_download` / `download_index` → `FileResponse` from `downloads/<product>/…` with
  correct content types (`.ipa`, `.plist`, `.html`). Reliable for iOS OTA (no redirect on
  the manifest/IPA).
- `LegacyRedirectMiddleware` → 301s any path listed in `downloads/_redirects.json` to its
  canonical target. Populated per product from `release.yaml` `deploy.legacy_redirects`, so
  old links survive with **zero** per-product code.
- Wired in `beaconinnovation/settings.py` (`INSTALLED_APPS`, `MIDDLEWARE`, `DOWNLOADS_ROOT`)
  and `beaconinnovation/urls.py`.

## `release.yaml`

See `scripts/beacon_release/starter-kit/release.yaml.template` for the fully-commented
template. Key fields: `product.{key,display_name,name,bundle_id}`,
`source.{pending_dir,ipa_name}`, `beacon.repo`, `deploy.{base_url,url_path,deploy_branch,
poll_timeout,legacy_redirects}`, `portal.show_previous_releases`.

## Permanent archive (`releases/<product>/`)

```
releases/<product>/
    history.json                 # current + full history (powers "Previous Releases")
    README.md                    # human-readable table + rollback notes
    vX.Y.Z-buildN/               # immutable, rollback-ready snapshot
        <App>.ipa  manifest.plist  install.html
        release_notes.md  deployment_summary.md  metadata.json  SHA256.txt
```

**Rollback:** restore a snapshot's IPA / manifest / install page into
`downloads/<product>/` and redeploy.

## Onboarding a product (AIMS, WLJ, UTMC HR, …)

There is nothing to change in the engine. Install the starter kit and fill in
`release.yaml`. Full steps + integration checklist:
`scripts/beacon_release/starter-kit/INSTALL.md`.

## Future

- `/release-all` — iterate every product's `release.yaml`.
- `/rollback <product> <version>` — the history + immutable snapshots already support it.
- The per-product Release Portal is the foundation for a full Beacon Deployment Portal.
