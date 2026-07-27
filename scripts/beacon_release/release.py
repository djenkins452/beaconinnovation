#!/usr/bin/env python3
"""Beacon Release Engine — CLI entry point.

One engine, many products. Run it from a product repo (via that repo's `/release`
command) or directly:

    python3 <beacon_repo>/scripts/beacon_release/release.py --product-repo <path>

Options:
    --product-repo PATH   product repo containing release.yaml (default: cwd)
    --dry-run             build artifacts into <beacon>/.release-dryrun/, no git/deploy
    --no-deploy           write + commit in the Beacon repo but skip push/verify
    --notes-file PATH     markdown overriding the auto-generated release notes
    --poll-timeout SECS   override release.yaml deploy.poll_timeout

The IPA is the single source of truth. On any inconsistency the pipeline stops
with a non-zero exit code and a clear explanation — it never fabricates success.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_product_config, ConfigError   # noqa: E402
from engine import ReleaseEngine, ReleaseError, ReleaseNotes  # noqa: E402

# scripts/beacon_release/release.py -> repo root is parents[2]
BEACON_REPO = Path(__file__).resolve().parents[2]


def parse_notes_file(path: Path) -> ReleaseNotes:
    notes = ReleaseNotes()
    bucket = None
    mapping = {
        "what's new": notes.whats_new, "whats new": notes.whats_new,
        "bug fixes": notes.bug_fixes, "known issues": notes.known_issues,
    }
    for line in path.read_text().splitlines():
        h = re.match(r"^#+\s*(.+?)\s*$", line)
        if h:
            bucket = mapping.get(h.group(1).strip().lower())
            continue
        item = re.match(r"^\s*[-*]\s+(.*)$", line)
        if item and bucket is not None and item.group(1).strip():
            bucket.append(item.group(1).strip())
    return notes


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Beacon Release Engine")
    p.add_argument("--product-repo", type=Path, default=Path.cwd(),
                   help="product repo containing release.yaml (default: cwd)")
    p.add_argument("--beacon-repo", type=Path, default=None,
                   help="override Beacon repo location (default: engine's own repo, "
                        "or beacon.repo in release.yaml)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-deploy", action="store_true")
    p.add_argument("--notes-file", type=Path)
    p.add_argument("--poll-timeout", type=int, default=None)
    p.add_argument("--poll-interval", type=int, default=15)
    args = p.parse_args(argv)

    product_repo = args.product_repo.resolve()
    try:
        cfg = load_product_config(product_repo)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Beacon repo: CLI override > release.yaml beacon.repo > engine's own repo
    beacon_repo = args.beacon_repo or (Path(cfg.beacon_repo) if cfg.beacon_repo else BEACON_REPO)
    beacon_repo = Path(beacon_repo).expanduser().resolve()
    if not (beacon_repo / "scripts" / "beacon_release").is_dir():
        print(f"error: Beacon repo not found at {beacon_repo} "
              f"(set beacon.repo in release.yaml).", file=sys.stderr)
        return 2

    notes_override = None
    if args.notes_file:
        if not args.notes_file.is_file():
            print(f"error: notes file not found: {args.notes_file}", file=sys.stderr)
            return 2
        notes_override = parse_notes_file(args.notes_file)

    engine = ReleaseEngine(
        cfg, product_repo, beacon_repo,
        dry_run=args.dry_run,
        deploy=not args.no_deploy,
        notes_override=notes_override,
        poll_timeout=args.poll_timeout,
        poll_interval=args.poll_interval,
    )
    try:
        engine.run()
    except ReleaseError as exc:
        print("\n" + "=" * 70)
        print("RELEASE HALTED — deployment did NOT succeed")
        print("=" * 70)
        print(str(exc))
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130

    print("\n✅ Release pipeline complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
