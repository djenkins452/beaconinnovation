#!/bin/bash
# Beacon build-time provenance stamp (Design Amendment 001).
#
# Wire this into the product's Xcode target as a **Run Script build phase**, placed
# AFTER "Copy Bundle Resources" so it edits the built Info.plist, and BEFORE the
# implicit code-sign so the stamp lands INSIDE the signed .app (tamper-evident).
# Uncheck "Based on dependency analysis" so it runs every build.
#
# It records, into the built app's Info.plist, the exact source state that produced
# the binary. The Beacon Release Engine reads these keys back and enforces:
#
#     BeaconSourceCommit == HEAD == origin/<branch>   AND   BeaconSourceClean == true
#
# so a release is provably reproducible from a pushed commit — independent of any
# unrelated working-tree churn, other worktrees, or post-export edits.
#
# Keys written (contract shared with scripts/beacon_release/ipainfo.py):
#   BeaconSourceCommit      full 40-char git SHA
#   BeaconSourceClean       "true" iff `git status --porcelain` is EMPTY (strict:
#                           staged, unstaged, unmerged, AND untracked all count)
#   BeaconSourceBranch      current branch (informational)
#   BeaconBuildTimestamp    ISO-8601 archive time
#   BeaconBuildEnvironment  Xcode + macOS versions (informational)
#
set -euo pipefail

PLIST="${TARGET_BUILD_DIR:-}/${INFOPLIST_PATH:-}"
if [ -z "${TARGET_BUILD_DIR:-}" ] || [ -z "${INFOPLIST_PATH:-}" ] || [ ! -f "$PLIST" ]; then
  echo "warning: provenance stamp skipped — built Info.plist not found (\$TARGET_BUILD_DIR/\$INFOPLIST_PATH)."
  exit 0
fi

# Resolve git in Xcode's sandboxed environment.
GIT="$(xcrun --find git 2>/dev/null || echo /usr/bin/git)"
REPO_ROOT="$("$GIT" -C "${SRCROOT:-$PWD}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO_ROOT" ]; then
  echo "warning: provenance stamp skipped — not inside a git repository."
  exit 0
fi

COMMIT="$("$GIT" -C "$REPO_ROOT" rev-parse HEAD)"
BRANCH="$("$GIT" -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
# STRICT cleanliness: any porcelain output (incl. untracked '??') => dirty.
if [ -z "$("$GIT" -C "$REPO_ROOT" status --porcelain)" ]; then
  CLEAN="true"
else
  CLEAN="false"
fi
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
ENVN="Xcode ${XCODE_VERSION_ACTUAL:-?}; macOS $(sw_vers -productVersion 2>/dev/null || echo '?')"

PB=/usr/libexec/PlistBuddy
set_key() {  # set_key <Key> <Value>
  "$PB" -c "Set :$1 $2" "$PLIST" 2>/dev/null || "$PB" -c "Add :$1 string $2" "$PLIST"
}
set_key BeaconSourceCommit     "$COMMIT"
set_key BeaconSourceClean      "$CLEAN"
set_key BeaconSourceBranch     "$BRANCH"
set_key BeaconBuildTimestamp   "$TS"
set_key BeaconBuildEnvironment "$ENVN"

echo "Beacon provenance stamped: commit=${COMMIT:0:9} branch=$BRANCH clean=$CLEAN"
if [ "$CLEAN" != "true" ]; then
  echo "warning: building from a NON-CLEAN tree — this artifact will be refused at /release."
fi
