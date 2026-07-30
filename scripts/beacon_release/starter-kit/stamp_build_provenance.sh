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

# Write a DEDICATED BeaconProvenance.plist into the app bundle rather than editing
# Info.plist. Under the modern build system Info.plist is (re)generated AFTER run-script
# phases when GENERATE_INFOPLIST_FILE=YES, so a post-hoc Info.plist edit is overwritten.
# A separate file is not touched by Info.plist processing, and — written here, before the
# final CodeSign step — it is sealed inside the signed bundle (tamper-evident).
BUNDLE_DIR="${TARGET_BUILD_DIR:-}/${CONTENTS_FOLDER_PATH:-${WRAPPER_NAME:-}}"
if [ -z "${TARGET_BUILD_DIR:-}" ] || [ -z "$BUNDLE_DIR" ] || [ ! -d "$BUNDLE_DIR" ]; then
  echo "warning: provenance stamp skipped — app bundle dir not found (\$TARGET_BUILD_DIR/\$CONTENTS_FOLDER_PATH)."
  exit 0
fi
PLIST="$BUNDLE_DIR/BeaconProvenance.plist"

GIT="$(xcrun --find git 2>/dev/null || echo /usr/bin/git)"
SRC="${SRCROOT:-$PWD}"
REPO_ROOT="$("$GIT" -C "$SRC" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO_ROOT" ]; then
  echo "warning: provenance stamp skipped — not inside a git repository."
  exit 0
fi

# Path scope (repo-relative). Default: SRCROOT relative to the repo root, computed
# by git itself (`--show-prefix`) so it is robust to symlinks (e.g. /tmp ->
# /private/tmp) and path normalization — a string-prefix strip is NOT reliable here.
if [ -n "${BEACON_SOURCE_PATHS:-}" ]; then
  PATHS="$BEACON_SOURCE_PATHS"
else
  PREFIX="$("$GIT" -C "$SRC" rev-parse --show-prefix 2>/dev/null || true)"
  PATHS="${PREFIX%/}"
  [ -z "$PATHS" ] && PATHS="."
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

xesc() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>BeaconSourceTree</key><string>$(xesc "$FINGERPRINT")</string>
	<key>BeaconSourcePaths</key><string>$(xesc "$PATHS")</string>
	<key>BeaconSourceCommit</key><string>$(xesc "$COMMIT")</string>
	<key>BeaconSourceClean</key><string>$(xesc "$CLEAN")</string>
	<key>BeaconSourceBranch</key><string>$(xesc "$BRANCH")</string>
	<key>BeaconBuildTimestamp</key><string>$(xesc "$TS")</string>
	<key>BeaconBuildEnvironment</key><string>$(xesc "$ENVN")</string>
</dict>
</plist>
EOF
plutil -lint "$PLIST" >/dev/null

echo "Beacon provenance stamped: source_tree=${FINGERPRINT:0:9} paths='$PATHS' base=${COMMIT:0:9} clean=$CLEAN"
if [ "$CLEAN" != "true" ]; then
  echo "note: built from a dirty tree — publishable once this exact source is committed + pushed to origin/$BRANCH."
fi
