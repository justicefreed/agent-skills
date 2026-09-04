#!/usr/bin/env python3
"""orch - dispatch tracker for the `orchestrating` skill.

Holds the one thing an orchestrator cannot re-derive: what it commissioned, under
what brief, and what it intends to do with the result. Everything derivable --
above all worker liveness -- is deliberately absent, because a stored copy of
derivable state competes with the source of truth and wins on cost.

Design constraints this file enforces (see docs/DESIGN.md):

* Working set, not a log. Open dispatches only; entries are deleted when their
  output is consumed. An entry you cannot close is an output nobody consumed.
* One writer per file. Each orchestrator owns exactly one tracker file, so
  mutation needs no locking -- only atomic replacement.
* Parent-minted ids. A child never mints its own tracker id; that is what keeps
  ordinals collision-free. Recovery is a read, never a mint.
* Substrate-agnostic. This script never calls an agent daemon or harness. Where
  a command needs substrate facts (e.g. which agents are alive), the caller
  supplies them. That boundary is why the skill's adapters stay swappable.

Python 3.9+, standard library only.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = 1

# Fields a brief's front matter must supply. These are the fields that make an
# orphaned worker recoverable and its output consumable; anything else is
# provenance and lives in the brief body.
REQUIRED_BRIEF_FIELDS = (
    "title",
    "worktree",
    "expected_artifacts",
    "advances",
    "consumption",
)
OPTIONAL_BRIEF_FIELDS = (
    "archetype",
    "model",
    "effort",
    "progress_artifact",
    "tracker_id",
    "parent_tracker",
    "plan_doc",
)

# Values that look like compliance but carry no information. Rejecting these is
# the difference between enforcement and ritual: a required field answered
# "unknown" is an omission wearing a costume.
PLACEHOLDERS = {
    "", "-", "n/a", "na", "none yet", "tbd", "todo", "unknown", "unspecified",
    "?", "???", "xxx", "fixme", "placeholder",
}

STATUSES = ("pending", "running", "harvested")

# An unfilled template slot -- `<one line, imperative>` -- is the likeliest form
# of copy-the-template-without-reading-it, so it is rejected as a placeholder.
UNFILLED_SLOT = re.compile(r"^<.+>$")


def is_placeholder(value: Any) -> bool:
    text = str(value).strip()
    return text.lower() in PLACEHOLDERS or bool(UNFILLED_SLOT.match(text))


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #

class OrchError(Exception):
    """A user-facing failure. Printed without a traceback."""


# --------------------------------------------------------------------------- #
# identity: repo key, state root, program discovery
# --------------------------------------------------------------------------- #

def _git(args: List[str], cwd: str) -> str:
    try:
        out = subprocess.run(
            ["git"] + args, cwd=cwd, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise OrchError("git not found on PATH")
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", "replace").strip()
        raise OrchError("not a git repository (%s): %s" % (cwd, detail))
    return out.stdout.decode("utf-8", "replace").strip()


def repo_identity(start: str) -> Tuple[str, str, str]:
    """Return (repo_key, repo_root, git_common_dir).

    Keyed on the *common* git dir so every linked worktree of one repository
    maps to a single key. That is what lets the tracker outlive any individual
    lane worktree, and what keeps an orchestrator that moves between worktrees
    pointed at the same state.
    """
    common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], start)
    common = os.path.realpath(common)
    root = os.path.realpath(os.path.dirname(common)) if common.endswith(".git") \
        else os.path.realpath(_git(["rev-parse", "--show-toplevel"], start))
    digest = hashlib.sha256(common.encode("utf-8")).hexdigest()[:8]
    return "%s-%s" % (os.path.basename(root), digest), root, common


def state_root() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    return os.path.join(base, "agent-orchestration")


def program_dir(repo_key: str, program: str) -> str:
    return os.path.join(state_root(), repo_key, program)


def list_programs(repo_key: str) -> List[Dict[str, Any]]:
    root = os.path.join(state_root(), repo_key)
    if not os.path.isdir(root):
        return []
    found = []
    for name in sorted(os.listdir(root)):
        pdir = os.path.join(root, name)
        if not os.path.isdir(pdir):
            continue
        trackers = [f for f in os.listdir(pdir) if f.endswith(".json")]
        open_entries = 0
        newest = 0.0
        for fname in trackers:
            path = os.path.join(pdir, fname)
            newest = max(newest, os.path.getmtime(path))
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    open_entries += len(json.load(fh).get("entries", []))
            except (OSError, ValueError):
                pass
        found.append({
            "program": name,
            "path": pdir,
            "trackers": len(trackers),
            "open_entries": open_entries,
            "updated": datetime.fromtimestamp(newest, timezone.utc).isoformat(
                timespec="seconds") if newest else None,
        })
    return found


def resolve_program(repo_key: str, requested: Optional[str]) -> str:
    """Pick the program, or explain why the caller must choose.

    Deliberately refuses to guess when several programs exist. A second
    namespace opened alongside an existing one splits state into halves that
    each look internally consistent -- the one minting mistake worth an
    interruption.
    """
    if requested:
        return requested
    programs = list_programs(repo_key)
    if not programs:
        return "default"
    if len(programs) == 1:
        return programs[0]["program"]
    names = ", ".join(p["program"] for p in programs)
    raise OrchError(
        "several programs exist for this repo (%s); pass --program to choose.\n"
        "Do NOT mint a new one to avoid choosing: that splits your state." % names
    )


# --------------------------------------------------------------------------- #
# tracker file I/O
# --------------------------------------------------------------------------- #

def check_tracker_id(tracker_id: str) -> None:
    if not re.fullmatch(r"root(\.\d+)*", tracker_id):
        raise OrchError(
            "tracker id %r is not parent-minted form (root, root.1, root.1.2)."
            % tracker_id
        )


def tracker_path(repo_key: str, program: str, tracker_id: str) -> str:
    check_tracker_id(tracker_id)
    return os.path.join(program_dir(repo_key, program), tracker_id + ".json")


def load_tracker(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise OrchError(
            "no tracker at %s.\nRun `orch open` to mint one, or `orch programs` "
            "to see what exists." % path
        )
    except ValueError as exc:
        raise OrchError("tracker at %s is not valid JSON: %s" % (path, exc))
    if data.get("version") != SCHEMA_VERSION:
        raise OrchError(
            "tracker at %s has schema version %r, expected %d"
            % (path, data.get("version"), SCHEMA_VERSION)
        )
    return data


def save_tracker(path: str, data: Dict[str, Any]) -> None:
    """Atomic whole-file replace.

    Safe without locking only because each tracker file has exactly one writer.
    If that ever stops being true, this is the function that breaks first -- and
    the fix is to restore single-writer scoping, not to add a lock.
    """
    data["updated_at"] = _now()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def new_tracker(tracker_id: str, program: str, repo_key: str, repo_root: str,
                common_dir: str, plan_doc: Optional[str],
                parent: Optional[str]) -> Dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "tracker_id": tracker_id,
        "parent_tracker": parent,
        "program": program,
        "repo_key": repo_key,
        "repo_path": repo_root,
        "git_common_dir": common_dir,
        "plan_doc": plan_doc,
        "created_at": _now(),
        "updated_at": _now(),
        "next_child_ordinal": 1,
        "next_entry": 1,
        "entries": [],
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# brief front matter
# --------------------------------------------------------------------------- #

def parse_front_matter(path: str) -> Dict[str, Any]:
    """Parse a brief's `---` delimited front matter.

    A deliberately small subset -- scalars, `- item` blocks, and inline
    `[a, b]` -- with hard failure on anything else. A lenient parser here would
    silently accept a malformed required field, which is the one thing this
    script exists to prevent.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise OrchError("cannot read brief %s: %s" % (path, exc))

    match = re.match(r"^---\r?\n(.*?)\r?\n---\s*(\r?\n|$)", text, re.DOTALL)
    if not match:
        raise OrchError(
            "brief %s has no `---` front matter block at the top of the file.\n"
            "The front matter is what supplies the tracker's required fields."
            % path
        )

    out: Dict[str, Any] = {}
    key = None
    for lineno, raw in enumerate(match.group(1).splitlines(), start=2):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.lstrip().startswith("- "):
            if key is None:
                raise OrchError("%s:%d list item before any key" % (path, lineno))
            out.setdefault(key, [])
            if not isinstance(out[key], list):
                raise OrchError(
                    "%s:%d cannot mix a scalar and a list for %r"
                    % (path, lineno, key)
                )
            out[key].append(_scalar(line.lstrip()[2:].strip()))
            continue
        if ":" not in line:
            raise OrchError(
                "%s:%d cannot parse %r (expected `key: value` or `- item`)"
                % (path, lineno, line)
            )
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not value:
            out[key] = []          # a `- item` block is expected to follow
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            out[key] = [_scalar(p.strip()) for p in inner.split(",") if p.strip()]
        else:
            out[key] = _scalar(value)
    return out


def _scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def validate_brief(fields: Dict[str, Any], path: str) -> None:
    missing = [f for f in REQUIRED_BRIEF_FIELDS if f not in fields]
    if missing:
        raise OrchError(
            "brief %s is missing required front matter: %s\n"
            "See assets/BRIEF.template.md." % (path, ", ".join(missing))
        )

    for field in ("title", "worktree", "consumption"):
        value = fields[field]
        if isinstance(value, list):
            raise OrchError("brief %s: %s must be a single value" % (path, field))
        if is_placeholder(value):
            raise OrchError(
                "brief %s: %s is a placeholder (%r).\n"
                "A required field answered with a placeholder is an omission, "
                "and the tracker cannot use it." % (path, field, value)
            )

    artifacts = fields["expected_artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise OrchError(
            "brief %s: expected_artifacts must be a non-empty list.\n"
            "It is what tells a fresh orchestrator which uncommitted files are "
            "legitimately this worker's." % path
        )
    for item in artifacts:
        if is_placeholder(item):
            raise OrchError(
                "brief %s: expected_artifacts contains a placeholder (%r)."
                % (path, item)
            )

    advances = fields["advances"]
    if isinstance(advances, str):
        if advances.strip().lower() != "none":
            raise OrchError(
                "brief %s: advances must be a list of plan-item ids, or the "
                "literal `none`. Got %r.\n"
                "An explicit `none` is a decision; a blank is an omission."
                % (path, advances)
            )
    elif not isinstance(advances, list) or not advances:
        raise OrchError(
            "brief %s: advances must be a non-empty list or the literal `none`."
            % path
        )

    if "progress_artifact" in fields:
        if is_placeholder(fields["progress_artifact"]):
            raise OrchError(
                "brief %s: progress_artifact is a placeholder. Omit the field or "
                "name a real artifact -- resumption after an interrupt is "
                "computed from it." % path
            )


# --------------------------------------------------------------------------- #
# entry helpers
# --------------------------------------------------------------------------- #

def find_entry(data: Dict[str, Any], ref: str) -> Dict[str, Any]:
    for entry in data["entries"]:
        if entry["entry"] == ref or entry.get("agent_id") == ref:
            return entry
    known = ", ".join(e["entry"] for e in data["entries"]) or "(none open)"
    raise OrchError("no open entry %r in %s. Open entries: %s"
                    % (ref, data["tracker_id"], known))


def entry_summary(entry: Dict[str, Any]) -> str:
    flags = []
    if entry["status"] == "pending" and not entry.get("agent_id"):
        flags.append("NO-AGENT-ID")
    if entry.get("pending_message"):
        flags.append("MSG-QUEUED")
    if entry.get("child_tracker"):
        flags.append("sub:" + entry["child_tracker"])
    brief = entry.get("brief_path")
    if brief and not os.path.exists(brief):
        flags.append("BRIEF-MISSING")
    return "  ".join(filter(None, [
        entry["entry"],
        entry["status"],
        (entry.get("agent_id") or "-")[:8],
        entry.get("session_name") or "-",
        entry["title"],
        ("[" + " ".join(flags) + "]") if flags else "",
    ]))


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def cmd_programs(args: argparse.Namespace) -> int:
    repo_key, root, _ = repo_identity(args.repo)
    programs = list_programs(repo_key)
    print("repo %s  (%s)" % (repo_key, root))
    if not programs:
        print("  no programs yet; `orch open` mints one")
        return 0
    for p in programs:
        print("  %-24s trackers=%d open=%d updated=%s"
              % (p["program"], p["trackers"], p["open_entries"], p["updated"]))
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    repo_key, root, common = repo_identity(args.repo)
    fields = parse_front_matter(args.brief)
    validate_brief(fields, args.brief)

    if args.program:
        program = args.program
    elif list_programs(repo_key):
        # Something already exists: reuse it, or refuse to guess between several.
        program = resolve_program(repo_key, None)
    else:
        # First program for this repo. Derive from the plan document's directory
        # if there is one, else `default`. Notify, do not ask -- a poor name is
        # recoverable, and an interruption per program is not worth it.
        plan_doc = fields.get("plan_doc")
        derived = os.path.basename(os.path.dirname(str(plan_doc))) if plan_doc else ""
        program = derived or "default"

    tracker_id = args.tracker or fields.get("tracker_id") or "root"
    path = tracker_path(repo_key, program, tracker_id)

    if os.path.exists(path):
        data = load_tracker(path)
    else:
        data = new_tracker(
            tracker_id, program, repo_key, root, common,
            fields.get("plan_doc"), fields.get("parent_tracker"),
        )
        print("minted program %r tracker %r at %s"
              % (program, tracker_id, path), file=sys.stderr)

    entry_id = "e%d" % data["next_entry"]
    data["next_entry"] += 1
    entry = {
        "entry": entry_id,
        "status": "pending",
        "title": fields["title"],
        "brief_path": os.path.abspath(args.brief),
        "worktree": fields["worktree"],
        "expected_artifacts": fields["expected_artifacts"],
        "advances": fields["advances"],
        "consumption": fields["consumption"],
        "progress_artifact": fields.get("progress_artifact"),
        "agent_id": args.agent_id,
        "session_name": None,
        "archetype": fields.get("archetype"),
        "model": fields.get("model"),
        "effort": fields.get("effort"),
        "child_tracker": None,
        "pending_message": None,
        "opened_at": _now(),
        "updated_at": _now(),
        "notes": [],
    }
    if args.agent_id:
        entry["status"] = "running"
    data["entries"].append(entry)
    save_tracker(path, data)

    print(entry_id)
    if not args.agent_id:
        print("recorded before spawn. After spawning, run:\n"
              "  orch update %s --agent-id <id> --session-name <name>"
              % entry_id, file=sys.stderr)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    repo_key, _, _ = repo_identity(args.repo)
    program = resolve_program(repo_key, args.program)
    path = tracker_path(repo_key, program, args.tracker)
    data = load_tracker(path)
    entry = find_entry(data, args.entry)

    changed = []
    if args.agent_id:
        entry["agent_id"] = args.agent_id
        if entry["status"] == "pending":
            entry["status"] = "running"
        changed.append("agent_id")
    if args.session_name:
        entry["session_name"] = args.session_name
        changed.append("session_name")
    if args.status:
        if args.status not in STATUSES:
            raise OrchError("status must be one of %s" % ", ".join(STATUSES))
        entry["status"] = args.status
        changed.append("status")
    if args.pending_message is not None:
        entry["pending_message"] = args.pending_message or None
        changed.append("pending_message")
    if args.note:
        entry["notes"].append({"at": _now(), "note": args.note})
        changed.append("note")

    if not changed:
        raise OrchError("nothing to update; pass at least one field")
    entry["updated_at"] = _now()
    save_tracker(path, data)
    print("%s updated: %s" % (entry["entry"], ", ".join(changed)))
    return 0


def cmd_mint_child(args: argparse.Namespace) -> int:
    """Allocate a child tracker id. The parent is the only minter, by design."""
    repo_key, _, _ = repo_identity(args.repo)
    program = resolve_program(repo_key, args.program)
    path = tracker_path(repo_key, program, args.tracker)
    data = load_tracker(path)
    entry = find_entry(data, args.entry)

    if entry.get("child_tracker"):
        print(entry["child_tracker"])
        return 0

    child = "%s.%d" % (data["tracker_id"], data["next_child_ordinal"])
    data["next_child_ordinal"] += 1
    entry["child_tracker"] = child
    entry["updated_at"] = _now()
    save_tracker(path, data)
    print(child)
    print("put `tracker_id: %s` in that worker's brief front matter; it must "
          "never mint its own." % child, file=sys.stderr)
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    repo_key, _, _ = repo_identity(args.repo)
    program = resolve_program(repo_key, args.program)
    path = tracker_path(repo_key, program, args.tracker)
    data = load_tracker(path)
    entry = find_entry(data, args.entry)

    if not args.consumed or is_placeholder(args.consumed):
        raise OrchError(
            "closing requires --consumed '<what happened to the output>'.\n"
            "This entry's stated consumption was: %s\n"
            "An entry you cannot describe as consumed is one whose output "
            "nobody used -- that is the signal, not a formality."
            % entry["consumption"]
        )

    data["entries"] = [e for e in data["entries"] if e["entry"] != entry["entry"]]
    save_tracker(path, data)
    print("closed %s (%s): %s" % (entry["entry"], entry["title"], args.consumed))
    if entry.get("child_tracker"):
        child = tracker_path(repo_key, program, entry["child_tracker"])
        if os.path.exists(child):
            remaining = len(load_tracker(child).get("entries", []))
            if remaining:
                print("NOTE: sub-orchestrator %s still has %d open entr%s"
                      % (entry["child_tracker"], remaining,
                         "y" if remaining == 1 else "ies"), file=sys.stderr)
    return 0


def _read_all_trackers(repo_key: str, program: str,
                       recursive: bool, tracker_id: str
                       ) -> List[Tuple[str, Dict[str, Any]]]:
    pdir = program_dir(repo_key, program)
    if recursive:
        if not os.path.isdir(pdir):
            return []
        names = sorted(f[:-5] for f in os.listdir(pdir) if f.endswith(".json"))
        return [(n, load_tracker(os.path.join(pdir, n + ".json"))) for n in names]

    # Named tracker: a bad id or a never-minted one must FAIL, not read as an
    # empty program. Those two look identical to the caller otherwise, which is
    # how a typo'd tracker id becomes a silent "nothing in flight".
    check_tracker_id(tracker_id)
    path = os.path.join(pdir, tracker_id + ".json")
    if not os.path.exists(path):
        existing = sorted(f[:-5] for f in os.listdir(pdir)) \
            if os.path.isdir(pdir) else []
        raise OrchError(
            "no tracker %r in program %r. Existing trackers: %s"
            % (tracker_id, program, ", ".join(existing) or "(none)")
        )
    return [(tracker_id, load_tracker(path))]


def cmd_roster(args: argparse.Namespace) -> int:
    repo_key, _, _ = repo_identity(args.repo)
    program = resolve_program(repo_key, args.program)
    trackers = _read_all_trackers(repo_key, program, args.recursive, args.tracker)

    if args.json:
        print(json.dumps(
            {name: data["entries"] for name, data in trackers}, indent=2))
        return 0

    if not trackers:
        print("no trackers for program %r" % program)
        return 0

    total = 0
    for name, data in trackers:
        print("%s  (program %s, plan_doc %s)"
              % (name, data["program"], data.get("plan_doc") or "-"))
        if not data["entries"]:
            print("  (no open entries)")
        for entry in data["entries"]:
            total += 1
            print("  " + entry_summary(entry))
    print("\n%d open entr%s. This is RECORDED intent, not liveness -- reconcile "
          "against the substrate before acting."
          % (total, "y" if total == 1 else "ies"))
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    repo_key, _, _ = repo_identity(args.repo)
    program = resolve_program(repo_key, args.program)
    trackers = _read_all_trackers(repo_key, program, args.recursive, args.tracker)
    print("# Open dispatches - %s\n" % program)
    for name, data in trackers:
        print("## %s\n" % name)
        if not data["entries"]:
            print("_none_\n")
            continue
        print("| entry | status | agent | title | advances | consumption |")
        print("|---|---|---|---|---|---|")
        for e in data["entries"]:
            advances = e["advances"]
            adv = ", ".join(advances) if isinstance(advances, list) else advances
            print("| %s | %s | %s | %s | %s | %s |" % (
                e["entry"], e["status"], e.get("session_name")
                or (e.get("agent_id") or "-")[:8],
                e["title"], adv, e["consumption"]))
        print()
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    """Recover a sub-orchestrator's tracker id from its worktree.

    Only unambiguous when the worker has its own worktree. Returns nothing
    rather than a guess otherwise: a child that guesses and then mints creates
    two tracker files for one job, each internally consistent.
    """
    repo_key, root, _ = repo_identity(args.repo)
    worktree = os.path.realpath(args.worktree or os.getcwd())
    program = resolve_program(repo_key, args.program)
    matches = []
    for name, data in _read_all_trackers(repo_key, program, True, "root"):
        for entry in data["entries"]:
            if os.path.realpath(entry["worktree"]) == worktree:
                matches.append((name, entry))
    if not matches:
        print("no entry matches worktree %s.\nAsk your parent for your "
              "tracker_id; do not mint one." % worktree, file=sys.stderr)
        return 1
    if len(matches) > 1:
        print("ambiguous: %d entries share worktree %s (inherited worktrees "
              "cannot be disambiguated this way). Ask your parent."
              % (len(matches), worktree), file=sys.stderr)
        return 1
    name, entry = matches[0]
    print(entry.get("child_tracker") or "")
    print("parent tracker %s, entry %s, brief %s"
          % (name, entry["entry"], entry["brief_path"]), file=sys.stderr)
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    """Drop entries whose agent is no longer alive.

    The alive set is supplied by the caller, not queried here -- this script
    knows nothing about any substrate. Safe because nothing durable lives in the
    tracker: provenance has already graduated into the repo.
    """
    repo_key, _, _ = repo_identity(args.repo)
    program = resolve_program(repo_key, args.program)
    alive = {a.strip() for a in (args.alive or "").split(",") if a.strip()}
    if not alive and not args.assume_none_alive:
        raise OrchError(
            "pass --alive <id,id,...> with the substrate's live agent ids, or "
            "--assume-none-alive to prune every entry that has an agent id.\n"
            "Refusing to guess: an empty alive set would delete everything."
        )
    dropped = []
    for name, data in _read_all_trackers(repo_key, program, args.recursive,
                                         args.tracker):
        keep = []
        for entry in data["entries"]:
            agent = entry.get("agent_id")
            if agent and agent not in alive:
                dropped.append((name, entry))
            else:
                keep.append(entry)
        if len(keep) != len(data["entries"]) and not args.dry_run:
            data["entries"] = keep
            save_tracker(tracker_path(repo_key, program, name), data)
    verb = "would drop" if args.dry_run else "dropped"
    for name, entry in dropped:
        print("%s %s/%s (%s) agent=%s"
              % (verb, name, entry["entry"], entry["title"],
                 (entry.get("agent_id") or "-")[:8]))
    if not dropped:
        print("nothing to prune")
    return 0


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="orch",
        description="Dispatch tracker for the orchestrating skill.",
    )
    p.add_argument("--repo", default=".",
                   help="any path inside the repository (default: cwd)")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp: argparse.ArgumentParser, tracker_default: str = "root") -> None:
        sp.add_argument("--program", help="program name (discovered if omitted)")
        sp.add_argument("--tracker", default=tracker_default,
                        help="tracker id (default: %s)" % tracker_default)

    sp = sub.add_parser("programs", help="list programs for this repo")
    sp.set_defaults(func=cmd_programs)

    sp = sub.add_parser("open", help="record a dispatch from its brief")
    sp.add_argument("--brief", required=True, help="path to the brief file")
    sp.add_argument("--agent-id", help="omit when recording before the spawn")
    common(sp)
    sp.set_defaults(func=cmd_open)

    sp = sub.add_parser("update", help="update an open entry")
    sp.add_argument("entry", help="entry id or agent id")
    sp.add_argument("--agent-id")
    sp.add_argument("--session-name")
    sp.add_argument("--status", choices=STATUSES)
    sp.add_argument("--pending-message",
                    help="message to deliver when the worker next goes idle")
    sp.add_argument("--note")
    common(sp)
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("mint-child",
                        help="allocate a child tracker id for a sub-orchestrator")
    sp.add_argument("entry")
    common(sp)
    sp.set_defaults(func=cmd_mint_child)

    sp = sub.add_parser("close", help="delete a consumed entry")
    sp.add_argument("entry")
    sp.add_argument("--consumed", help="what happened to the output")
    common(sp)
    sp.set_defaults(func=cmd_close)

    sp = sub.add_parser("roster", help="print open entries")
    sp.add_argument("--recursive", action="store_true",
                    help="include sub-orchestrator trackers")
    sp.add_argument("--json", action="store_true")
    common(sp)
    sp.set_defaults(func=cmd_roster)

    sp = sub.add_parser("render", help="print open entries as markdown")
    sp.add_argument("--recursive", action="store_true")
    common(sp)
    sp.set_defaults(func=cmd_render)

    sp = sub.add_parser("whoami",
                        help="recover a sub-orchestrator tracker id by worktree")
    sp.add_argument("--worktree")
    common(sp)
    sp.set_defaults(func=cmd_whoami)

    sp = sub.add_parser("prune", help="drop entries whose agent is gone")
    sp.add_argument("--alive", help="comma-separated live agent ids")
    sp.add_argument("--assume-none-alive", action="store_true")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--recursive", action="store_true")
    common(sp)
    sp.set_defaults(func=cmd_prune)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except OrchError as exc:
        print("orch: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
