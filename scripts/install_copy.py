#!/usr/bin/env python3
"""Install a directory from this checkout into a harness directory as a copy.

Some harnesses (abacusai) do not follow symlinks in ~/.agents/skills, so every
install is a real directory. A copy cannot prove whose it is the way a symlink
target does, so each one carries MARKER: the checkout it came from, its source
directory, and a digest of what was copied. Only a directory bearing a marker
from this checkout -- or a legacy symlink into it -- is ever replaced or pruned.

The copied set is what git lists (tracked plus untracked-but-not-ignored), so an
ignored node_modules never lands in a skill directory. Symlinks inside the
source are dereferenced for the same reason the install is a copy.

Commands, each printing one status line per entry and exiting 1 on any FAIL:
  install --repo R --src S --dest D   copy S to D, or report OK if unchanged
  prune --repo R --target T           remove our installs in T whose source is
                                      not in the ship list read from stdin
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from typing import List, Optional

MARKER = ".installed-from.json"


def source_files(src: str) -> List[str]:
    out = subprocess.run(
        ["git", "-C", src, "ls-files", "-co", "--exclude-standard", "-z", "--", "."],
        check=True, capture_output=True).stdout.decode()
    files = sorted(p for p in out.split("\0") if p and os.path.exists(os.path.join(src, p)))
    if not files:
        raise SystemExit("no files to install under %s" % src)
    return files


def digest(src: str, files: List[str]) -> str:
    h = hashlib.sha256()
    for rel in files:
        path = os.path.join(src, rel)
        h.update(rel.encode() + b"\0")
        h.update(b"x" if os.access(path, os.X_OK) else b"-")
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                h.update(fh.read())
        h.update(b"\0")
    return h.hexdigest()


def read_marker(dest: str) -> Optional[dict]:
    try:
        with open(os.path.join(dest, MARKER), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def under(path: str, root: str) -> bool:
    path, root = os.path.normpath(path), os.path.normpath(root)
    return path == root or path.startswith(root + os.sep)


def link_target(link: str) -> str:
    raw = os.readlink(link)
    if not os.path.isabs(raw):
        raw = os.path.join(os.path.dirname(link), raw)
    return os.path.normpath(raw)


def ours(dest: str, repo: str) -> Optional[str]:
    """The source an existing install of ours came from, or None if not ours."""
    if os.path.islink(dest):
        target = link_target(dest)
        return target if under(target, repo) else None
    if os.path.isdir(dest):
        marker = read_marker(dest)
        if marker and marker.get("repo") == repo:
            return str(marker.get("source") or "")
    return None


def remove(dest: str) -> None:
    if os.path.islink(dest) or os.path.isfile(dest):
        os.unlink(dest)
    else:
        shutil.rmtree(dest)


def cmd_install(args: argparse.Namespace) -> int:
    repo, src, dest = (os.path.normpath(p) for p in (args.repo, args.src, args.dest))
    files = source_files(src)
    want = digest(src, files)

    if os.path.lexists(dest):
        if ours(dest, repo) is None:
            kind = "a link to %s" % link_target(dest) if os.path.islink(dest) else \
                "not an install from this checkout"
            print("  FAIL  %s (%s)" % (dest, kind), file=sys.stderr)
            return 1
        marker = None if os.path.islink(dest) else read_marker(dest)
        if marker and marker.get("source") == src and marker.get("digest") == want:
            print("  OK    %s <- %s" % (dest, src))
            return 0

    parent = os.path.dirname(dest)
    os.makedirs(parent, exist_ok=True)
    stage = os.path.join(parent, ".%s.installing.%d" % (os.path.basename(dest), os.getpid()))
    if os.path.lexists(stage):
        remove(stage)
    for rel in files:
        path, out = os.path.join(src, rel), os.path.join(stage, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if os.path.isdir(path):
            shutil.copytree(path, out, symlinks=False)
        else:
            shutil.copy2(path, out)
    with open(os.path.join(stage, MARKER), "w", encoding="utf-8") as fh:
        json.dump({"repo": repo, "source": src, "digest": want}, fh, indent=2)
        fh.write("\n")

    # Swap in with a rename so a harness scanning the directory never sees a
    # half-copied skill; the old install is moved aside before it is deleted.
    old = None
    if os.path.lexists(dest):
        old = os.path.join(parent, ".%s.old.%d" % (os.path.basename(dest), os.getpid()))
        os.rename(dest, old)
    os.rename(stage, dest)
    if old:
        remove(old)
    print("  COPY  %s <- %s" % (dest, src))
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    repo, target = os.path.normpath(args.repo), os.path.normpath(args.target)
    keep = {os.path.normpath(line.strip()) for line in sys.stdin if line.strip()}
    if not keep:
        raise SystemExit("empty ship list; refusing to prune %s" % target)
    if not os.path.isdir(target):
        return 0
    for name in sorted(os.listdir(target)):
        dest = os.path.join(target, name)
        source = ours(dest, repo)
        if source is None or os.path.normpath(source) in keep:
            continue
        remove(dest)
        print("  PRUNE %s <- %s (not in the manifest)" % (dest, source))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("install")
    i.add_argument("--repo", required=True)
    i.add_argument("--src", required=True)
    i.add_argument("--dest", required=True)
    i.set_defaults(func=cmd_install)
    r = sub.add_parser("prune")
    r.add_argument("--repo", required=True)
    r.add_argument("--target", required=True)
    r.set_defaults(func=cmd_prune)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
