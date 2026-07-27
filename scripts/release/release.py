#!/usr/bin/env python3
"""Beacon Innovation release pipeline — CLI entry point.

Usage:
    python3 scripts/release/release.py <product> [options]

Examples:
    python3 scripts/release/release.py aims            # full release + deploy
    python3 scripts/release/release.py aims --dry-run  # build artifacts, no git/deploy
    python3 scripts/release/release.py aims --no-deploy # write + commit locally, skip push
    python3 scripts/release/release.py aims --notes-file notes.md

The IPA is the single source of truth. On any inconsistency the pipeline stops
with a non-zero exit code and a clear explanation — it never fabricates success.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# allow running as a plain script (no package install)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import get_product           # noqa: E402
from engine import ReleaseEngine, ReleaseError, ReleaseNotes  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_notes_file(path: Path) -> ReleaseNotes:
    """Parse a markdown file with ## What's New / ## Bug Fixes / ## Known Issues."""
    notes = ReleaseNotes()
    bucket = None
    mapping = {
        "what's new": notes.whats_new,
        "whats new": notes.whats_new,
        "bug fixes": notes.bug_fixes,
        "known issues": notes.known_issues,
    }
    for line in path.read_text().splitlines():
        m = re.match(r"^#+\s*(.+?)\s*$", line)
        if m:
            bucket = mapping.get(m.group(1).strip().lower())
            continue
        item = re.match(r"^\s*[-*]\s+(.*)$", line)
        if item and bucket is not None:
            text = item.group(1).strip()
            if text:
                bucket.append(text)
    return notes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Beacon Innovation release pipeline")
    parser.add_argument("product", help="product key (e.g. aims)")
    parser.add_argument("--dry-run", action="store_true",
                        help="build artifacts into .release-dryrun/, no git or deploy")
    parser.add_argument("--no-deploy", action="store_true",
                        help="write + commit in the repo but skip push/verify")
    parser.add_argument("--notes-file", type=Path,
                        help="markdown file overriding the auto-generated release notes")
    parser.add_argument("--poll-timeout", type=int, default=900,
                        help="seconds to wait for Railway (default 900)")
    parser.add_argument("--poll-interval", type=int, default=15)
    args = parser.parse_args(argv)

    try:
        config = get_product(args.product)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    notes_override = None
    if args.notes_file:
        if not args.notes_file.is_file():
            print(f"error: notes file not found: {args.notes_file}", file=sys.stderr)
            return 2
        notes_override = parse_notes_file(args.notes_file)

    engine = ReleaseEngine(
        config,
        REPO_ROOT,
        dry_run=args.dry_run,
        deploy=not args.no_deploy,
        notes_override=notes_override,
        poll_timeout=args.poll_timeout,
        poll_interval=args.poll_interval,
    )

    try:
        engine.run()
    except ReleaseError as exc:
        print("\n" + "=" * 68)
        print("RELEASE HALTED — deployment did NOT succeed")
        print("=" * 68)
        print(str(exc))
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130

    print("\n✅ Release pipeline complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
