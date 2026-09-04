#!/usr/bin/env bash
# Link every shipped skill into the local harness skill directories.
# Entries are symlinks into this repo, so `git pull` keeps installed skills current.
# Re-run after adding, renaming, or removing a skill.
#
# Portability: macOS ships bash 3.2, so no mapfile, no associative arrays, and no
# `"${arr[@]}"` on a possibly-empty array under `set -u`. Kept array-free deliberately.
set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"

# Ship list comes from each plugin manifest's `skills` array — never a glob, so
# in-progress and unlisted skills are not linked.
skill_paths() {
  for manifest in "$REPO"/plugins/*/.claude-plugin/plugin.json; do
    [ -e "$manifest" ] || continue
    plugin_dir="$(dirname "$(dirname "$manifest")")"
    python3 -c '
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
