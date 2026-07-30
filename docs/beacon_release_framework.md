# Beacon Release Framework

**One release engine, many products.** Beacon Innovation is the **authoritative
software distribution platform** for Beacon products. Each product repo (AIMS, Whole
Life Journey, UTMC HR, future products) remains authoritative for its **source code
and build artifacts**, and ends at **Code → Archive → Export IPA**. Everything after
that — publishing, archiving, verifying, distributing — is owned by the Beacon
Innovation platform and performed by a single, product-agnostic **Beacon Release
Engine**.

In short: the product is authoritative for *building* the release; Beacon is
authoritative for *distributing* it.

The **exported IPA is the single source of truth.** Every deployment artifact is
derived from it automatically. Nobody hand-edits version, build, bundle identifier,
application name, `manifest.plist`, or the install page.

## The workflow

Inside any Beacon product repo:

1. Product → **Archive** (Xcode)
2. Release Testing → **Export IPA** → drop it in `releases/pending/`
3. `/release`

### Two modes: publish (fast) and verify (authoritative)

Publishing and production verification are **separate**, so a developer is never
forced to wait 10–15 minutes for Railway unless they explicitly want end-to-end
verification.

- **`/release`** (default) — **publish**: locate the IPA, sync the manifest +
  install portal, generate notes, archive, validate, **commit and push**, then
  **return the instant GitHub accepts the push**. Railway deploys in the
  background. Fast (seconds).
- **`/release verify`** — **verify**: wait for Railway with **live progress and
  elapsed time** (polling, stopping the moment the new build is detected), then run
  the **complete, authoritative production validation** of the deployed build:
  install page (HTTP 200), manifest (HTTP 200), IPA download, **SHA-256 match**,
  bundle id, version, and legacy redirects. It never reports success unless every
  check passes.

The split removes no safety checks — it moves the long Railway wait out of the
common path; verify remains the single authoritative production-validation path.
All verification requests present a browser User-Agent, so a WAF that blocks
non-browser clients cannot cause a false negative. `--dry-run` previews a publish
with no git or deploy.

## Architecture — engine vs. configuration

```
PRODUCT REPO (AIMS, WLJ, …)                 BEACON INNOVATION REPO (this repo)
──────────────────────────                  ──────────────────────────────────
release.yaml               ──reads──▶        scripts/beacon_release/   ← the ONE engine
releases/pending/<app>.ipa ──ingest─▶        distribution/             ← serves /downloads/<p>/
.claude/commands/release.md ─invokes▶        downloads/<product>/      ← live artifacts (served)
   (generic, from kit)                       releases/<product>/       ← permanent archive + history
```

- **Product repo** (authoritative for source + build) owns only: `release.yaml`,
  `releases/pending/` (drop zone), and the generic `/release` command. No manifests,
  install pages, or committed binaries.
- **Beacon platform** (authoritative for distribution) owns: the engine, the serving
  layer, the live artifacts, and the permanent archive / rollback history.

## User experience — how people actually get the app

Users never navigate the `/downloads/<product>/` URLs directly. Those are the internal
distribution plumbing (OTA manifest + IPA + install portal). The user-facing path is
the authenticated products portal:

```
Login → My Products → Product → Download
```

The `products` app owns that flow; its "Download" action leads to the OTA install for
the product. `/downloads/<product>/` exists so that flow — and iOS itms-services OTA —
have stable, public artifact URLs behind it. Treat `/downloads/<product>/` as an
implementation detail, not an entry point.

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

0. **Preflight sync** (publish only; `deploy.require_sync`, default on) — `git fetch origin`,
   then require the product repo to be **exactly** `origin/<deploy_branch>`: on that branch,
   same commit, clean working tree (no staged, unstaged, or untracked files). **Behind,
   ahead, diverged, dirty, or wrong-branch all hard-stop before the IPA is touched**, so
   every release is reproducible from one known commit. Skipped in `--dry-run`.
   *(A future model moves the cleanliness enforcement to build/export time and records it
   in the artifact, so unrelated parallel-session work no longer blocks publication — see
   **[Design Amendment 001](#design-amendment-001--provenance-based-publishing)**. It is
   **not yet active**; this strict guard remains in force unchanged until every migration
   step there is complete and verified.)*
1. **Locate** the pending IPA in the product repo (fail if none). A non-blocking **warning**
   fires if the IPA's mtime predates HEAD (the engine publishes a pre-exported IPA, so it
   cannot prove the binary was built from current source — the operator confirms).
2. **Inspect** the IPA → app name, display name, bundle id, version, build, min iOS, signing.
2b. **Build-number integrity** (hard gate; runs in `--dry-run` too, against the **real**
    published `history.json`). Guarantees the universal invariant **before** anything is
    written or committed: (a) **one build number ↔ one binary** — a build number already
    published with *different* bytes is refused (SHA-256 mismatch); (b) **monotonic builds**
    — the build must be strictly greater than every published build (never reused, never
    decreased). An exact re-publish of the *identical* artifact (same build **and** same
    SHA-256) is idempotent and allowed. This holds even if a product's own build-number
    automation (e.g. the iOS `/release` command) is bypassed — the engine is the single gate.
2c. **Provenance verification** (Design Amendment 001; additive). If the IPA carries a
    Beacon provenance stamp, verify `stampedCommit == HEAD` and `stampedClean == true`
    (HEAD `== origin/<branch>` is pinned separately by step 0). A dirty-built or
    wrong-commit artifact is **refused**. With `deploy.require_provenance: true` a valid
    stamp is **mandatory** (unstamped IPAs refused); default **off** → unstamped IPAs
    pass and rely on step 0.
3. **Validate guards**: IPA bundle id / name must match `release.yaml`.
4. **Stage** IPA → `downloads/<product>/` (verify copied SHA == source).
5. **Release notes** from the product repo's git log since the last released commit
   (categorized into What's New / Bug Fixes; overridable via `--notes-file`).
6. **Sync + publish** `manifest.plist` + Release Portal from IPA values + notes + history.
7. **Archive** an immutable snapshot → `releases/<product>/vX.Y.Z-buildN/`; update
   `history.json` + `README.md` + `downloads/_redirects.json`.
7b. **Legacy public install** (reconcile to `deploy.legacy_install`) — enabled: render
    `install.html` + `manifest.plist` into `served_dirs` (OTA asset → canonical IPA) and
    prune every redirect under `url_path`; disabled: remove any previously-published legacy
    files so state matches config. Never a second artifact; Portal untouched. See below.
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

## Temporary legacy public install target (optional, single flag)

Some products need a **public, unauthenticated installer page** for a while — e.g. a
customer who does not yet have a Beacon Portal account. `deploy.legacy_install` in
`release.yaml` publishes exactly that, without ever creating a second release artifact:

```yaml
deploy:
  legacy_install:
    enabled: true
    url_path: /static/downloads          # public path (served by WhiteNoise)
    served_dirs:                          # Beacon-repo dirs backing url_path
      - static/downloads                  #   STATICFILES_DIRS source
      - staticfiles/downloads             #   STATIC_ROOT (committed, served in prod)
```

- **One IPA, one SHA-256, no drift.** Only the lightweight `install.html` +
  `manifest.plist` are written to `served_dirs`. The legacy manifest points its OTA
  asset at the **canonical** `/downloads/<product>/<App>.ipa` — the same URL the Portal
  manifest uses. The engine writes **no** IPA under the legacy path and deletes any that
  reappears there (single-artifact invariant), so the Portal and the legacy installer can
  never diverge.
- **Two files only — nothing else.** The legacy directory holds `install.html` +
  `manifest.plist` and nothing more: no IPA, no redirect, no placeholder. The engine
  prunes **every** `downloads/_redirects.json` entry under `url_path`, so the two pages are
  served as real files (`LegacyRedirectMiddleware` runs before WhiteNoise and would
  otherwise 301-shadow them) and every other path under the legacy prefix — including the
  old `…/AIMSField.ipa` URL — **404s by design**. The OTA manifest points straight at the
  canonical IPA, so the legacy IPA URL is never part of the install flow.
- **Publish + verify cover both targets.** Publish reports `✓ Beacon Product Portal
  updated` and `✓ Legacy Public Install updated`; `/release verify` additionally checks the
  legacy page (200), legacy manifest (200), and that the legacy manifest references the
  canonical IPA (bundle id + version match, no drift).
- **Self-cleaning removal.** Set `enabled: false` (keep `url_path` + `served_dirs`) and run
  `/release`. The engine automatically removes the previously-published legacy files,
  commits their deletion, prunes the legacy redirects, and leaves the canonical Portal
  byte-for-byte unchanged. The deployment state is a pure function of config — the operator
  never manually deletes a file or directory. Once retracted, the block may be deleted.

## `release.yaml`

See `scripts/beacon_release/starter-kit/release.yaml.template` for the fully-commented
template. Required: `product.{key,display_name}`, `deploy.{base_url,url_path}`. Guards
+ common fields: `product.{name,bundle_id}`, `source.{pending_dir,ipa_name}`,
`beacon.repo`, `deploy.{deploy_branch,poll_timeout,legacy_redirects}`,
`portal.show_previous_releases`.

**Optional metadata** (products become almost configuration-only; the engine works
fine when these are absent): `product.public_name` (user-facing portal title,
overrides `display_name` there), `product.description` (portal subtitle),
`product.icon` (icon URL, shown on the portal), `product.platform` (`ios`/`android`/…,
informational). These are also recorded in each release's `metadata.json` /
`history.json`, so the products portal can render product info straight from config.

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

## Design Amendment 001 — Provenance-based publishing

> **Status: Partially adopted — engine-side verification live; stamping wiring + guard
> relaxation pending.**
> Implemented and shipping: the engine reads a build-time provenance stamp from the
> IPA and verifies it (**Pipeline step 2c**, `ReleaseEngine.step_provenance`); the
> `deploy.require_provenance` config flag (default **off**); the stamp contract in
> `ipainfo.py`; and a reusable stamping build-phase script
> (`starter-kit/stamp_build_provenance.sh`). Because `require_provenance` defaults off
> and verification is **additive** (a stamp, when present, is verified; when absent the
> existing guard stands), **current behavior is unchanged** for products that have not
> yet wired the stamp.
> Pending per product: (1) add the stamping Run Script build phase to the Xcode target
> so exports carry the stamp; (2) validate stamping against clean / dirty / untracked
> scenarios; (3) flip `deploy.require_provenance: true`; (4) **only then** retire the
> step-0 clean-tree guard and the step-1 mtime warning (exact provenance supersedes
> them). Until a product completes (1)–(3), its **step-0 guard remains in force.**
>
> **Stamp contract** (Info.plist keys inside the signed `.app`; single source of truth
> is `ipainfo.py`): `BeaconSourceCommit` (full SHA), `BeaconSourceClean`
> (`"true"`/`"false"`, strict porcelain-empty incl. untracked), `BeaconSourceBranch`,
> `BeaconBuildTimestamp`, `BeaconBuildEnvironment`.

### The decision

`origin/<deploy_branch>` is the **approved source of truth**, not production. Production is
the **exported IPA** published through `/release`. The IPA's bytes are fixed at export;
the state of the working tree *at publish time, hours later,* has no causal relationship
to what is inside that artifact.

The current step-0 gate is therefore both **too strict and too weak**:

- **Too strict** — it hard-stops publication when an *unrelated* parallel session has left
  the working tree dirty, even though that work cannot alter the already-exported IPA.
- **Too weak** — a *clean* tree with a *stale* IPA passes step 0 entirely; only a
  **non-blocking** mtime warning (step 1) stands between the operator and shipping a binary
  that does not match `HEAD`.

**Decision:** enforce and **capture repository cleanliness at build/export time, inside the
artifact**, and make `/release` a **provenance verification + publication** step. Repository
cleanliness becomes a *build/export requirement*; `/release` verifies the artifact's recorded
provenance against the repository and publishes. This is a net **increase** in safety — it
replaces a live-but-misdirected check with an exact, auditable artifact↔commit binding, and
it closes the stale-IPA gap the mtime warning only flags.

### The release invariant

```
IPA.stampedCommit  ==  local HEAD  ==  origin/<deploy_branch>
        AND
IPA.stampedClean   ==  true
```

**"Clean" is defined strictly**: the IPA was built from a repository whose
`git status --porcelain` output was **completely empty** — no staged, unstaged, unmerged,
**or untracked** files. `git describe --dirty` is **insufficient** and must not be used as
the sole determinant: it considers only tracked files, so an **untracked source file**
(e.g. a new `.swift` referenced by the Xcode project and compiled into the build) would be
reported "clean" while the binary contains uncommitted source. A dirty artifact — by this
strict definition — **must never be publishable**.

When the invariant holds, the release provably satisfies all four properties simultaneously:
the IPA came from **committed** code; that commit is **pushed** to the approved branch; the
artifact contains **no uncommitted source**; and the published binary **exactly matches** the
approved source of truth.

### Trust boundary

The provenance stamp is an **attestation produced by the build/export pipeline**, not
mathematical proof.

- The release process **trusts the build/export pipeline** to compute and record the stamp
  honestly. That trust boundary is deliberate and correct: the build pipeline is the
  authority on what source produced the artifact.
- The stamp **should be made tamper-resistant where practical.** Recording it *inside the
  signed `.app` bundle* (rather than loose alongside the IPA) means any post-export edit
  **invalidates the code signature** — which the engine already inspects (`ipainfo.py`) —
  making tampering evident rather than silent.
- **iOS builds are not guaranteed byte-for-byte reproducible**: signing identity, provisioning
  profile, toolchain (Xcode/SDK) versions, embedded timestamps, and dependency resolution all
  vary between builds of the same commit. Commit identity therefore proves **source lineage**,
  not full reproducibility. The guarantee is *attested provenance*, and its strength is bounded
  by build-pipeline honesty; it must not be described as cryptographic proof.

### Build / export responsibilities

The build/export process (in the **product repo**, which remains authoritative for building)
must, before producing the IPA, verify cleanliness, and must **stamp into the artifact**:

| Stamped field | Meaning |
|---------------|---------|
| **Commit SHA** (full, 40-char) | The exact commit the archive was built from. |
| **Branch** (where useful) | The branch at build time; informational, and cross-checked against `deploy_branch`. |
| **Build timestamp** | When the archive/export was produced. |
| **Clean/dirty state** | The strict determination below — the gate on publishability. |
| **Build-environment metadata** (where practical) | Xcode version, SDK version — for audit and drift diagnosis. |

- **Clean/dirty is determined by `git status --porcelain` being empty**, untracked files
  included — **not** `git describe --dirty` alone.
- **Time-of-check/time-of-use (TOCTOU) must be addressed.** Source can change during a
  multi-minute archive, so a single up-front check is not enough:
  1. Cleanliness (strict) **and** `HEAD` are checked **before** archive.
  2. The source **must not change during** archive/export.
  3. Cleanliness **and** `HEAD` identity are **re-checked after** archive/export.
  4. If either changed between the pre- and post-checks, the artifact is **rejected** — it is
     not stamped clean, and thus is not publishable.

### Publish-time responsibilities (`/release`)

`/release` continues to require (unchanged):

- Correct branch.
- Successful `git fetch`.
- Local `HEAD` **exactly equals** `origin/<deploy_branch>` — no ahead, behind, or diverged state.

`/release` **additionally** requires:

- IPA **stamped commit** exactly equals local `HEAD`.
- IPA **stamped clean state** is `true`.
- A **verifiable stamp is present and parseable** — **fail-closed**: an IPA with a missing or
  unreadable stamp (e.g. built before stamping existed, or by a broken pipeline) is
  **rejected**, never grandfathered as "probably clean."

What changes: the product **working tree may contain unrelated parallel-session work at
publish time**, and that no longer blocks publication. What does **not** change: `/release`
**must still refuse** when a **release-owned path** is itself modified or conflicted — that is
a genuine release conflict, not unrelated dirt (see next section).

### Parallel-session safety model

The release engine must **never** use repository-wide staging — `git add -A` or any
equivalent — while unrelated working-tree changes may exist. (Today, `git add -A` is safe only
*because* step 0 guarantees an empty tree; the moment publish tolerates unrelated dirt, broad
staging would sweep a parallel session's uncommitted work into the release commit — a violation
of the platform's "parallel work is sacred" rule.)

There must be **one authoritative declaration of release-owned paths**. That single declaration
is the sole source of truth and must drive **all** of:

- Preflight **conflict checks** (refuse if any owned path is already modified/conflicted).
- The files the engine **may write**.
- The files the engine **may delete**.
- Git **staging** (explicit paths only — the exact owned set, never a wildcard sweep).
- **Validation**.
- **Cleanup / retraction** (e.g. legacy-install self-removal).

The engine **must fail loudly** if it writes, stages, or deletes anything **outside** the
declared ownership set — a write-outside-owned-set is a defect, not a silent no-op. (Corollary:
if publish ever needs to touch a new path, that path must be *added to the declaration first*,
or explicit-path staging will silently omit it and leave the release incomplete.)

### Gates that remain independent

Provenance verification **does not replace** — and must not be conflated with — these existing
checks, each of which remains a separate hard gate:

- **Version / build monotonicity** (a matching commit can still be a revert or an older build).
  *Enforced* by the step-2b build-number integrity gate: one build number ↔ one binary, and
  strictly-increasing builds, checked against the published `history.json`.
- **Bundle identifier** validation.
- **IPA signing and package inspection**.
- **Manifest correctness**.
- **Production HTTP verification** (`/release verify`).
- **Live IPA SHA-256** verification against source.
- **One canonical IPA across Portal and Legacy Public Install** (single-artifact invariant).
- **Legacy manifest references the canonical IPA**.
- **No duplicate IPA under the legacy path**.

### Failure reporting

Mismatch reports must be **self-contained**: the operator should never need to run separate Git
commands merely to understand why publication was blocked. Each failure names the specific
equality that broke and the remedy.

| Detected condition | Report → remedy |
|--------------------|-----------------|
| `IPA commit abc123 != local HEAD def456` | **Stale IPA** — rebuild/export from `def456`. |
| `local HEAD def456 != origin/<branch> ghi789` | **Repository not synchronized** — reconcile (pull/push) before release. |
| `IPA clean state = false` | **Artifact contains or may contain uncommitted source** — rebuild from a clean tree. |
| **No verifiable stamp on IPA** | **Unverifiable provenance** — rebuild with a stamping-capable pipeline. |
| **Release-owned path already modified** | **Release conflict** — resolve that specific path before publishing. |

### Migration sequence

Adopt in this order. **Each step strengthens or holds safety; the global clean-working-tree
guard (step 0) is only relaxed at the very end, after its replacement is proven.**

1. Add **build-time provenance stamping** (commit, clean/dirty, timestamp, environment).
2. **Validate stamping** against clean, dirty, and **untracked-source** scenarios.
3. Add **post-build source-stability verification** (the TOCTOU pre/post re-check).
4. Add **publish-time provenance inspection** and the equality checks (commit == HEAD ==
   origin; clean == true; fail-closed on missing stamp).
5. Replace **repository-wide staging** with **explicit release-owned-path staging**.
6. Add **write-outside-owned-set detection** (fail loudly).
7. **Preserve** all existing version, SHA, manifest, and production-verification gates.
8. **Only after all prior controls are working and verified**, relax the global
   clean-working-tree requirement at **publish** time (retire step 0's tree check and the
   step-1 mtime warning, which exact SHA equality supersedes).

Until step 8, the **existing strict clean-tree guard remains in force.**

### Acceptance criteria

The amendment is fully adopted when **all** hold:

- [ ] Every produced IPA carries a parseable stamp: full commit SHA, clean/dirty (strict,
      `git status --porcelain`-based, untracked included), build timestamp, and build-environment
      metadata where practical.
- [ ] Build/export **refuses to stamp clean** when the tree is dirty by the strict definition,
      **including** when the only dirt is an untracked source file.
- [ ] Build/export performs the **pre- and post-archive** cleanliness + `HEAD` re-check and
      **rejects** the artifact on any change during archive.
- [ ] `/release` **publishes** with a valid provenant IPA **even when** the working tree
      contains unrelated parallel-session changes.
- [ ] `/release` **refuses** on: commit ≠ HEAD, HEAD ≠ origin, stamped clean = false, missing/
      unparseable stamp, or a modified release-owned path — each with a self-contained report.
- [ ] The engine stages/writes/deletes **only** declared release-owned paths, uses **no**
      repository-wide staging, and **fails loudly** on any write outside the owned set.
- [ ] All independent gates (version monotonicity, bundle id, signing, manifest, production
      HTTP + live SHA-256, single-artifact/no-drift across Portal + Legacy) still pass and are
      unchanged.
- [ ] A single authoritative **release-owned-paths declaration** exists and provably drives
      conflict checks, writes, deletes, staging, validation, and cleanup.

### Open design decisions (require approval before implementation)

1. **Stamp location & format** — ✅ **Decided: Info.plist keys inside the signed `.app`**
   (`BeaconSource*` / `BeaconBuild*`, contract in `ipainfo.py`). Chosen for tamper-evidence
   (covered by the code signature) and zero-dependency reads (stdlib `plistlib`).
2. **How the build guarantees source immutability during archive** — a pre/post
   porcelain+`HEAD` comparison around Xcode's archive, vs. building from an isolated clean
   checkout / `git worktree`. (Determines how robustly the TOCTOU window is closed.)
3. **Home of the release-owned-paths declaration** — engine constant, `release.yaml`, or a
   dedicated manifest — and whether it is per-product or global with per-product extension.
4. **Fail-closed policy for legacy/unstamped IPAs** during the migration window — confirmed as
   *reject*, with the implication that no pre-amendment IPA can be published once step 4 lands.
5. **Disposition of the step-1 mtime warning** — retire at step 8 (superseded by exact SHA
   equality), confirmed.
6. **Reproducibility ceiling** — accept *attested* provenance as the guarantee, or later invest
   in dependency pinning / build determinism to tighten it (out of scope here, noted for the
   record).

## Future

- `/release-all` — iterate every product's `release.yaml`.
- `/rollback <product> <version>` — the history + immutable snapshots already support it.
- The per-product Release Portal is the foundation for a full Beacon Deployment Portal.
