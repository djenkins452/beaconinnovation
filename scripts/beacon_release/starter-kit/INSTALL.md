# Beacon Release Starter Kit

Install this kit into a Beacon **product** repo (AIMS, Whole Life Journey, UTMC HR,
future products) to give it a one-command `/release` that publishes through the
**Beacon Release Engine**. One engine, many products — no release logic is
duplicated into the product repo.

## What the product repo owns (and only this)

- `release.yaml` — the product's release configuration.
- `releases/pending/` — a temporary drop zone for the exported IPA.
- `.claude/commands/release.md` — the generic `/release` command.

The product repo stays **authoritative for source code and build artifacts**.
Everything else — copying the IPA, the manifest, the install portal, release notes,
the permanent archive, deployment history, rollback, verification — is owned by the
**Beacon Innovation** platform, which is **authoritative for distribution**. Products
produce releases; Beacon publishes, archives, verifies, and distributes them.

Users reach releases through the authenticated products portal
(**Login → My Products → Product → Download**), never by navigating
`/downloads/<product>/` directly.

## Installation

From the root of the product repo:

1. **Copy the config template**
   ```bash
   cp <beacon-repo>/scripts/beacon_release/starter-kit/release.yaml.template ./release.yaml
   ```

2. **Create the drop zone**
   ```bash
   mkdir -p releases/pending
   cp <beacon-repo>/scripts/beacon_release/starter-kit/releases/pending/.gitkeep releases/pending/
   ```

3. **Install the `/release` command**
   ```bash
   mkdir -p .claude/commands
   cp <beacon-repo>/scripts/beacon_release/starter-kit/dot-claude-commands-release.md .claude/commands/release.md
   ```

4. **Keep IPAs out of product git** — add to the product repo's `.gitignore`:
   ```
   releases/pending/*.ipa
   ```

## Integration checklist

- [ ] `release.yaml` copied to the repo root.
- [ ] `product.key` set (unique slug → `/downloads/<key>/`, e.g. `aims`).
- [ ] `product.display_name` set (branded portal title).
- [ ] `product.name` set to the app's CFBundleName (guard).
- [ ] `product.bundle_id` set to the app's CFBundleIdentifier (guard).
- [ ] `beacon.repo` points to the Beacon Innovation repo on this machine.
- [ ] `deploy.base_url` and `deploy.url_path` set (`/downloads/<key>`).
- [ ] `deploy.legacy_redirects` lists any old URLs to preserve (optional).
- [ ] Optional metadata set if desired: `product.public_name`, `description`, `icon`,
      `platform` (all absent-safe — the engine works without them).
- [ ] `releases/pending/` exists and `*.ipa` is git-ignored.
- [ ] `.claude/commands/release.md` installed.
- [ ] Verified with a dry run (see below).

## Everyday workflow

1. In Xcode: **Product → Archive**, then **Release Testing → Export**.
2. Drop the exported `*.ipa` into `releases/pending/`.
3. Run `/release`.

That's it. The engine inspects the IPA (the single source of truth), publishes to
`https://<base_url>/downloads/<key>/`, archives the release in the Beacon repo, waits
for Railway, and verifies the live deployment.

## Verify the setup (dry run — no git, no deploy)

```bash
python3 <beacon-repo>/scripts/beacon_release/release.py --product-repo "$PWD" --dry-run
```

This locates the pending IPA, inspects it, and builds all artifacts into
`<beacon-repo>/.release-dryrun/` without touching git or the live site. If it reports
the correct Version / Build / Bundle Identifier and passes validation, you're ready to
run `/release` for real.

## Adding a brand-new product

There is nothing to build in the engine. Install this kit, fill in `release.yaml`, and
run `/release`. The Beacon serving layer already serves `/downloads/<any-product>/`.
