#!/bin/bash
# Beacon build-time provenance stamp (Design Amendment 001).
#
# Wire this into the product's Xcode target as a **Run Script build phase**, placed
# AFTER "Copy Bundle Resources" so it edits the built Info.plist, and BEFORE the
# implicit code-sign so the stamp lands INSIDE the signed .app (tamper-evident).
# Uncheck "Based on dependency analysis" so it runs every build.
#
# THE RELEASE GATE IS REPRODUCIBILITY, NOT CLEANLINESS. This records a *source
# fingerprint* — the git tree hash of the product's source paths, computed from the
# exact working-tree state that was compiled (committed or not). The Beacon Release
# Engine publishes iff that fingerprint matches a commit reachable from
# origin/<branch>. So: build from a dirty tree, then commit that exact source and
# push, and the artifact is reproducible and publishable. Clean/dirty is recorded
# for diagnostics only, and later development elsewhere never invalidates the stamp.
#
# Keys written (contract shared with scripts/beacon_release/ipainfo.py):
#   BeaconSourceTree        git tree SHA of the built source paths  (THE FINGERPRINT)
#   BeaconSourcePaths       repo-relative path scope of the fingerprint
#   BeaconSourceCommit      HEAD at build time (base commit; informational)
#   BeaconSourceClean       "true" iff `git status --porcelain` empty (DIAGNOSTIC)
#   BeaconSourceBranch      current branch (informational)
#   BeaconBuildTimestamp    ISO-8601 archive time
#   BeaconBuildEnvironment  Xcode + macOS versions (informational)
#
# Source-path scope: override with BEACON_SOURCE_PATHS (repo-relative, space-sep).
# Default: Xcode's $SRCROOT relative to the repo root — i.e. the product source
# directory that actually feeds the build.
set -euo pipefail

PLIST="${TARGET_BUILD_DIR:-}/${INFOPLIST_PATH:-}"
if [ -z "${TARGET_BUILD_DIR:-}" ] || [ -z "${INFOPLIST_PATH:-}" ] || [ ! -f "$PLIST" ]; then
  echo "warning: provenance stamp skipped — built Info.plist not found (\$TARGET_BUILD_DIR/\$INFOPLIST_PATH)."
  exit 0
fi

GIT="$(xcrun --find git 2>/dev/null || echo /usr/bin/git)"
SRC="${SRCROOT:-$PWD}"
REPO_ROOT="$("$GIT" -C "$SRC" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO_ROOT" ]; then
  echo "warning: provenance stamp skipped — not inside a git repository."
  exit 0
fi

# Path scope (repo-relative). Default: SRCROOT relative to the repo root.
if [ -n "${BEACON_SOURCE_PATHS:-}" ]; then
  PATHS="$BEACON_SOURCE_PATHS"
else
  case "$SRC" in
    "$REPO_ROOT")   PATHS="." ;;
    "$REPO_ROOT"/*) PATHS="${SRC#$REPO_ROOT/}" ;;
    *)              PATHS="." ;;
  esac
fi

COMMIT="$("$GIT" -C "$REPO_ROOT" rev-parse HEAD)"
BRANCH="$("$GIT" -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
if [ -z "$("$GIT" -C "$REPO_ROOT" status --porcelain)" ]; then CLEAN="true"; else CLEAN="false"; fi

# FINGERPRINT: hash the exact working-tree source (tracked + untracked, .gitignore
# respected) WITHOUT disturbing the real index — seed a throwaway index from HEAD,
# stage the working state of the source paths, write the tree, extract the subtree.
TMP_INDEX="$(mktemp -u "${TMPDIR:-/tmp}/beacon-index.XXXXXX")"
export GIT_INDEX_FILE="$TMP_INDEX"
"$GIT" -C "$REPO_ROOT" read-tree HEAD
if [ "$PATHS" = "." ]; then
  "$GIT" -C "$REPO_ROOT" add -A
  FULLTREE="$("$GIT" -C "$REPO_ROOT" write-tree)"
  FINGERPRINT="$FULLTREE"
else
  # shellcheck disable=SC2086
  "$GIT" -C "$REPO_ROOT" add -A -- $PATHS
  FULLTREE="$("$GIT" -C "$REPO_ROOT" write-tree)"
  # Single-path scope: the subtree SHA is the fingerprint (self-contained, exact).
  FIRST_PATH="${PATHS%% *}"
  FINGERPRINT="$("$GIT" -C "$REPO_ROOT" rev-parse "$FULLTREE:$FIRST_PATH")"
fi
unset GIT_INDEX_FILE
rm -f "$TMP_INDEX"

TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
ENVN="Xcode ${XCODE_VERSION_ACTUAL:-?}; macOS $(sw_vers -productVersion 2>/dev/null || echo '?')"

PB=/usr/libexec/PlistBuddy
set_key() { "$PB" -c "Set :$1 $2" "$PLIST" 2>/dev/null || "$PB" -c "Add :$1 string $2" "$PLIST"; }
set_key BeaconSourceTree       "$FINGERPRINT"
set_key BeaconSourcePaths      "$PATHS"
set_key BeaconSourceCommit     "$COMMIT"
set_key BeaconSourceClean      "$CLEAN"
set_key BeaconSourceBranch     "$BRANCH"
set_key BeaconBuildTimestamp   "$TS"
set_key BeaconBuildEnvironment "$ENVN"

echo "Beacon provenance stamped: source_tree=${FINGERPRINT:0:9} paths='$PATHS' base=${COMMIT:0:9} clean=$CLEAN"
if [ "$CLEAN" != "true" ]; then
  echo "note: built from a dirty tree — publishable once this exact source is committed + pushed to origin/$BRANCH."
fi
