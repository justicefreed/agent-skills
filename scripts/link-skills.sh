#!/usr/bin/env bash
# Link every shipped skill into the local harness skill directories.
# Entries are symlinks into this repo, so `git pull` keeps installed skills current.
# Re-run after adding, renaming, or removing a skill.
#
# Portability: macOS ships bash 3.2, so no mapfile, no associative arrays, and no
# `"${arr[@]}"` on a possibly-empty array under `set -u`. Kept array-free deliberately.
set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"

# Every entry installed below is a symlink INTO $REPO, so $REPO has to outlive
# the install. A linked worktree does not: it is reclaimed when its lane closes,
# and each link then dangles. That is silent for a skill -- the file is simply
# not found -- but not for the status line, which runs
# `~/.claude/skills/orchestrating/scripts/orch.py` after every assistant message
# in every session on the machine. Same hazard as a hook pinned to a disposable
# checkout, one layer up; see `spend.py`'s HOOK_DIRS for the other half.
#
# A primary checkout resolves --git-dir and --git-common-dir to the same path; a
# linked worktree points the first at <common>/worktrees/<name>. That is the
# whole test, and it is also how `orch.py` keys state that must SURVIVE a
# worktree -- the same distinction, read the other way round.
if [ -z "${LINK_SKILLS_ALLOW_WORKTREE:-}" ] &&
   git_dir="$(git -C "$REPO" rev-parse --absolute-git-dir 2>/dev/null)" &&
   common_dir="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" &&
   [ "$git_dir" != "$common_dir" ]; then
  primary="$(git -C "$REPO" worktree list --porcelain 2>/dev/null \
             | sed -n '1s/^worktree //p')"
  echo "Refusing to link from a linked worktree:" >&2
  echo "  $REPO" >&2
  echo "Links would point here, and this checkout is reclaimed when its lane" >&2
  echo "closes -- taking every installed skill, and the status line, with it." >&2
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

count=0
linked=0
for target in "$HOME/.claude/skills" "$HOME/.agents/skills"; do
  mkdir -p "$target"
  while IFS= read -r src; do
    [ -n "$src" ] || continue
    count=$((count + 1))
    name="$(basename "$src")"
    dest="$target/$name"

    if [ ! -d "$src" ]; then
      echo "  SKIP  $name (listed in manifest but missing on disk: $src)" >&2
      continue
    fi

    # Replace only our own symlinks; never clobber a real directory.
    if [ -L "$dest" ]; then
      rm "$dest"
    elif [ -e "$dest" ]; then
      echo "  SKIP  $name ($dest exists and is not a symlink)" >&2
      continue
    fi

    ln -s "$src" "$dest"
    linked=$((linked + 1))
    echo "  LINK  $dest -> $src"
  done <<EOF
$(skill_paths)
EOF
done

if [ "$count" -eq 0 ]; then
  echo "No skills listed in any plugin manifest — nothing to link." >&2
  exit 1
fi

echo "Done. $linked symlink(s) created."
