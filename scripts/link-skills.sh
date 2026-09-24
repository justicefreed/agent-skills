#!/usr/bin/env bash
# Install every shipped skill into the local harness skill directories.
# Entries are COPIES, not symlinks: some harnesses (abacusai) do not follow
# symlinks in ~/.agents/skills. Re-run after `git pull`, and after adding,
# renaming or removing a skill -- installs this checkout made that the manifest
# no longer ships are pruned. The copying and ownership rules live in
# install_copy.py.
#
# Portability: macOS ships bash 3.2, so no mapfile, no associative arrays, and no
# `"${arr[@]}"` on a possibly-empty array under `set -u`. Kept array-free deliberately.
set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"

# A linked worktree is a lane: reclaimed when the lane closes, and holding
# work nobody has reviewed. Installing from one would put that unmerged code
# into every session on the machine -- including the status line, which runs
# `~/.claude/skills/orchestrating/scripts/orch.py` after every assistant
# message. A primary checkout resolves --git-dir and --git-common-dir to the
# same path; a linked worktree points the first at <common>/worktrees/<name>.
if [ -z "${LINK_SKILLS_ALLOW_WORKTREE:-}" ] &&
   git_dir="$(git -C "$REPO" rev-parse --absolute-git-dir 2>/dev/null)" &&
   common_dir="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" &&
   [ "$git_dir" != "$common_dir" ]; then
  primary="$(git -C "$REPO" worktree list --porcelain 2>/dev/null \
             | sed -n '1s/^worktree //p')"
  echo "Refusing to install from a linked worktree:" >&2
  echo "  $REPO" >&2
  echo "It is a lane: unmerged, and reclaimed when the lane closes. Installing" >&2
  echo "it would put that work into every session on the machine." >&2
  [ -n "$primary" ] && echo "Run it from the primary checkout instead:" >&2 \
                    && echo "  $primary/scripts/link-skills.sh" >&2
  echo "Set LINK_SKILLS_ALLOW_WORKTREE=1 if this worktree really is permanent." >&2
  exit 1
fi

# Naming `python3` and letting PATH answer it is the expensive way to get an
# interpreter: where a pyenv/asdf shim sits first, the name costs a bash process
# that re-execs into another before any Python starts. This script pays it once
# per plugin rather than once per tool call, so the stakes are nothing like
# `spend.py`'s HOOK_PY -- it is here so the repo has one answer to "which
# interpreter", not two.
PY="${LINK_SKILLS_PYTHON:-}"
[ -x "$PY" ] || PY=/usr/bin/python3
[ -x "$PY" ] || PY=python3

# Ship list comes from each plugin manifest's `skills` array — never a glob, so
# in-progress and unlisted skills are not linked.
skill_paths() {
  for manifest in "$REPO"/plugins/*/.claude-plugin/plugin.json; do
    [ -e "$manifest" ] || continue
    plugin_dir="$(dirname "$(dirname "$manifest")")"
    "$PY" -c '
import json, os, sys
manifest, plugin_dir = sys.argv[1], sys.argv[2]
with open(manifest) as fh:
    data = json.load(fh)
for rel in data.get("skills", []):
    print(os.path.normpath(os.path.join(plugin_dir, rel)))
' "$manifest" "$plugin_dir"
  done
}

COPY="$REPO/scripts/install_copy.py"
failed=0

SKILLS="$(skill_paths)"
if [ -z "$SKILLS" ]; then
  echo "No skills listed in any plugin manifest — nothing to install." >&2
  exit 1
fi

# Skill scripts reach past their own directory into the plugin root --
# delegating-economically's `spend` is `<plugin>/scripts/spend.py`, and orch.py
# finds it as a sibling plugin. A symlinked skill got that for free by resolving
# into this checkout; a copied one cannot, so each shipping plugin's root is
# installed too, at the location both scripts search: ~/.agents/plugins/<name>.
PLUGINS="$(for manifest in "$REPO"/plugins/*/.claude-plugin/plugin.json; do
  [ -e "$manifest" ] && dirname "$(dirname "$manifest")"
done)"

install_all() {  # $1 = target directory, $2 = newline-separated source dirs
  mkdir -p "$1"
  while IFS= read -r src; do
    [ -n "$src" ] || continue
    if [ ! -d "$src" ]; then
      echo "  FAIL  $(basename "$src") (listed in manifest but missing on disk: $src)" >&2
      failed=1
      continue
    fi
    "$PY" "$COPY" install --repo "$REPO" --src "$src" \
      --dest "$1/$(basename "$src")" || failed=1
  done <<EOF
$2
EOF
  printf '%s\n' "$2" | "$PY" "$COPY" prune --repo "$REPO" --target "$1" || failed=1
}

# These providers discover user skills from different locations. `.agents` is
# retained for harnesses following the cross-harness Agent Skills convention,
# including Paseo-hosted provider processes.
for target in "$HOME/.claude/skills" "$HOME/.codex/skills" \
              "$HOME/.cursor/skills" "$HOME/.agents/skills"; do
  install_all "$target" "$SKILLS"
done
install_all "$HOME/.agents/plugins" "$PLUGINS"

if [ "$failed" -ne 0 ]; then
  echo "Failed: see FAIL lines above." >&2
  exit 1
fi
echo "Done."
