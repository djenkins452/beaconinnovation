# Beacon Innovation Release Pipeline

Beacon Innovation owns software distribution. Each product's own repo ends at
**Archive → Export IPA**; everything after that — copying the IPA, synchronizing
deployment artifacts, generating release notes, archiving, committing, pushing,
waiting for Railway, and verifying the live deployment — happens here.

The **exported IPA is the single source of truth.** Every deployment artifact is
derived from it automatically. Nobody hand-edits version, build, bundle
identifier, application name, `manifest.plist`, or `install.html`.

## The one command

After exporting AIMS from Xcode into `~/Desktop/AIMS Release Test/`:

```
/release-aims
```

That's the whole workflow:

1. Product → Archive (Xcode)
2. Release testing → Export IPA (Xcode)
3. `/release-aims`

## Architecture — engine vs. configuration

The pipeline is deliberately split so the same **engine** publishes every Beacon
product; only a small **config** differs per product.

```
scripts/release/
├── config.py       Product registry (ProductConfig). Per-product settings only.
├── templates.py    manifest.plist + install.html (release portal) templates.
├── engine.py       ReleaseEngine — the reusable pipeline. Product-agnostic.
└── release.py      CLI entry point:  python3 scripts/release/release.py <product>

.claude/commands/
└── release-aims.md Thin slash command that runs the engine for `aims`.

releases/<product>/ Permanent, append-only archive (see below).
```

### The engine (`engine.py`) runs these steps

| Step | What it does |
|------|--------------|
| 1  | Locate the newest timestamped export folder + IPA (fails if none). |
| 2  | Inspect the IPA: app name, display name, bundle id, version, build, min iOS, signing (from `DistributionSummary.plist` / provisioning profile). |
| 3  | Copy the IPA into the public `downloads/` dir. |
| 4/6| Regenerate `manifest.plist` and the `install.html` **release portal** from IPA values + release notes. |
| 5  | Generate release notes from commits since the previous archived release (overridable with `--notes-file`). |
| 7  | Archive a complete, rollback-ready snapshot under `releases/<product>/vX.Y.Z-buildN/`. |
| 8  | Validate that bundle id, version, build, manifest, install page, and IPA all agree. |
| 9  | Commit only deployment files: `Deploy <Product> v{version} (Build {build})`. |
| 10 | Push, then fast-forward the deploy branch so Railway deploys. |
| 11 | Poll until all three URLs return HTTP 200 and the live IPA matches. |
| 12 | Verify the live IPA SHA-256 equals the source. |
| 13 | Print the deployment report. |
| 14 | Update `releases/<product>/history.json` + `README.md`. |

If anything disagrees — missing IPA, bundle-id/version/build mismatch, manifest or
install-page drift, git/push failure, Railway timeout, or a live SHA mismatch —
the engine **halts with a clear error and a non-zero exit code. It never reports a
false success.**

### CLI options

```
python3 scripts/release/release.py aims               # full release + deploy
python3 scripts/release/release.py aims --dry-run     # build into .release-dryrun/, no git/deploy
python3 scripts/release/release.py aims --no-deploy   # write + commit locally, skip push/verify
python3 scripts/release/release.py aims --notes-file scratchpad/notes.md
python3 scripts/release/release.py aims --poll-timeout 1200
```

## The permanent archive (`releases/<product>/`)

Every release writes an immutable snapshot:

```
releases/aims/
├── history.json                 machine-readable current + full history
├── README.md                    human-readable release table + rollback notes
└── v0.3.0-build2/
    ├── AIMSField.ipa            exact bytes that were deployed
    ├── manifest.plist
    ├── install.html
    ├── release_notes.md
    ├── deployment_summary.md    version, build, bundle id, SHA, signing, dates
    ├── metadata.json
    └── SHA256.txt
```

This is the rollback history. To roll back, restore an archived IPA (and/or the
archived `manifest.plist` / `install.html`) and redeploy.

## Adding a new product (`/release-wlj`, `/release-utmc`, …)

The engine is already reusable. To onboard a product:

1. Add a `ProductConfig` entry to `PRODUCTS` in `scripts/release/config.py`
   (source folder, IPA name, downloads dir, URLs, releases dir, deploy branch).
   A commented WLJ stub is included as a starting point.
2. Add `.claude/commands/release-<key>.md` — copy `release-aims.md` and change the
   product key passed to the engine.

No engine changes required. A future `/release-all` would simply iterate the
`PRODUCTS` registry.

## Product config reference (`ProductConfig`)

| Field | Meaning |
|-------|---------|
| `key` | CLI/command slug (`aims`). |
| `product_title` | Branded name on the portal + manifest title (`AIMS Field`). |
| `source_dir` / `source_folder_glob` / `ipa_source_name` | Where the Xcode export lands. |
| `downloads_dir` / `ipa_dest_name` / `manifest_name` / `install_page_name` | Public artifacts. |
| `base_url` / `download_url_path` | Public URLs. |
| `releases_dir` | Archive root for this product. |
| `deploy_branch` | Branch Railway deploys from (`main`). |
| `changelog_path` | Optional changelog to append to. |
| `expected_bundle_id` | Guard — the engine refuses to publish a different app. |
