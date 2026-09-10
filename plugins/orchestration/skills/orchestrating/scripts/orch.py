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
import shutil
import subprocess
import sys
import tempfile
import time
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
    "review",
    "review_waiver",
)

# Who reads this lane's diff before it lands. Declared at dispatch, because it
# is a property of the spec -- not a judgment the integrator makes at landing
# time with the work already in front of it and an incentive to wave it through.
REVIEW_MODES = ("integrator", "in-brief", "none")

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

# A parent-minted tracker id: `root`, `root.1`, `root.1.2`. Also the filter for
# scanning a program directory, which holds this program's other state files too
# (budget, transcripts, caches) -- reading one of those as a tracker used to
# abort a recursive read, and an aborted read looks exactly like an empty roster.
TRACKER_ID = re.compile(r"root(\.\d+)*")


def check_tracker_id(tracker_id: str) -> None:
    if not TRACKER_ID.fullmatch(tracker_id):
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

    if "review" in fields:
        mode = str(fields["review"]).strip()
        if mode not in REVIEW_MODES:
            raise OrchError(
                "brief %s: review must be one of %s. Got %r.\n"
                "`in-brief` claims this lane's own spec requires an independent "
                "pass, and the integrator will refuse to land unless the report "
                "actually carries that pass's result." % (path, ", ".join(REVIEW_MODES), mode)
            )
        if mode == "none" and not str(fields.get("review_waiver", "")).strip():
            raise OrchError(
                "brief %s: review: none requires review_waiver: <why this needs "
                "no second reader>.\nAn unreviewed lane is a decision someone "
                "must be able to find later." % path
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
        "review": fields.get("review", "integrator"),
        "review_waiver": fields.get("review_waiver"),
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
        names = sorted(f[:-5] for f in os.listdir(pdir)
                       if f.endswith(".json") and TRACKER_ID.fullmatch(f[:-5]))
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
# inbox: queued input for a running agent
# --------------------------------------------------------------------------- #
#
# The one place this file accepts MANY writers. Everything else here is
# single-writer by design (Principle 3), and the inbox earns its exception two
# ways:
#
#   * Appends only. A sender appends one line and never mutates another; a line
#     once written never moves, so line INDEX is a stable name for an item.
#     A single small append under O_APPEND lands whole, so concurrent senders
#     interleave lines but never corrupt one.
#   * One reader. Only the addressed agent drains, and the cursor -- the only
#     mutable file -- therefore still has exactly one writer.
#
# That combination is what removes the race that makes sending to a running
# agent unsafe: nobody sends, everybody appends, and the receiver decides when
# to look. There is no check-then-send window to lose.

INBOX_KINDS = ("approval", "correction", "task", "answer", "question", "fyi")

# A line is refused above this size rather than truncated. Single-write appends
# are atomic only while they stay small, and an item too big for one line is a
# document -- so it belongs in a file the item points at, exactly as a brief
# does. Truncating instead would corrupt the item silently.
MAX_ITEM_BYTES = 4000


def inbox_dir(repo_key: str, program: str) -> str:
    return os.path.join(program_dir(repo_key, program), "inbox")


def inbox_slug(target: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", target.strip())
    if not slug or slug in (".", "..") or len(slug) > 120:
        raise OrchError("inbox target %r is not a usable name" % target)
    return slug


def inbox_paths(repo_key: str, program: str, target: str) -> Tuple[str, str]:
    base = os.path.join(inbox_dir(repo_key, program), inbox_slug(target))
    return base + ".jsonl", base + ".cursor"


def claims_path(repo_key: str) -> str:
    return os.path.join(state_root(), repo_key, "inbox-claims.json")


def _load_claims(repo_key: str) -> Dict[str, Any]:
    try:
        with open(claims_path(repo_key), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _worktree_key(start: str) -> str:
    """This agent's worktree, realpathed.

    Sound as an identity only because of the skill's standing rule that a
    worktree has exactly one writer. If that rule is broken, two agents claim
    one inbox and both drain it -- which is why the rule is a rule.
    """
    return os.path.realpath(_git(["rev-parse", "--show-toplevel"], start))


def resolve_target(args: argparse.Namespace, repo_key: str
                   ) -> Tuple[Optional[str], Optional[str]]:
    """Return (program, target), or (None, None) when this agent has no inbox.

    Order: explicit flag, then the claim recorded for this worktree, then the
    environment. Never guessed: an agent that drains an inbox addressed to
    someone else consumes input meant for another lane, and the sender has no
    way to discover that it happened.

    The claim outranks ORCH_INBOX_TARGET deliberately. A claim is something an
    agent did on purpose with a role name; the environment variable is a default
    injected per-agent by the substrate, carrying the agent's own id. Ranking
    the injected default higher meant an orchestrator that claimed `root` still
    drained a UUID nobody addresses -- and worse, an agent-id target cannot be
    handed to a successor, because the successor has a different id. The
    environment stays as the fallback for agents that never claim, which is the
    case it was added for: a worker addressing its own inbox without having been
    told its id.
    """
    program = getattr(args, "program", None)
    explicit = getattr(args, "to", None)
    if explicit:
        return (program or resolve_program(repo_key, None)), explicit
    claim = _load_claims(repo_key).get(_worktree_key(args.repo))
    if claim and claim.get("target"):
        return (program or claim.get("program") or "default"), claim["target"]
    from_env = os.environ.get("ORCH_INBOX_TARGET")
    if from_env:
        return (program or resolve_program(repo_key, None)), from_env
    return None, None


def _read_pending(log: str, cursor: str) -> Tuple[List[Dict[str, Any]], int]:
    """Return (undelivered items, total line count)."""
    try:
        with open(log, "r", encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    except FileNotFoundError:
        return [], 0
    delivered = 0
    try:
        with open(cursor, "r", encoding="utf-8") as fh:
            delivered = int(json.load(fh).get("delivered", 0))
    except (FileNotFoundError, ValueError, TypeError):
        delivered = 0
    items = []
    for index, line in enumerate(lines[delivered:], start=delivered + 1):
        try:
            item = json.loads(line)
        except ValueError:
            item = {"kind": "fyi", "body": line, "malformed": True}
        item["index"] = index
        items.append(item)
    return items, len(lines)


def _advance_cursor(cursor: str, delivered: int) -> None:
    os.makedirs(os.path.dirname(cursor), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(cursor), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"delivered": delivered, "at": _now()}, fh)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, cursor)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def render_inbox(items: List[Dict[str, Any]], target: str) -> str:
    head = "INBOX — %d queued item%s for `%s`, delivered now and cleared." % (
        len(items), "" if len(items) == 1 else "s", target)
    parts = [head, ""]
    for item in items:
        meta = [str(item.get("kind", "fyi"))]
        if item.get("from"):
            meta.append("from %s" % item["from"])
        if item.get("at"):
            meta.append(str(item["at"]))
        if item.get("ref"):
            meta.append("ref %s" % item["ref"])
        parts.append("[%d] %s" % (item.get("index", 0), " · ".join(meta)))
        parts.append(str(item.get("body", "")).strip())
        parts.append("")
    # The steer matters more than the items. This is the exact moment an
    # orchestrator starts doing the work itself, because it has just been handed
    # something small and its context is already loaded.
    parts.append(
        "These are queued inputs, not a brief. Route each through the "
        "delegate-or-inline decision before acting, and keep this turn bounded."
    )
    return "\n".join(parts).strip() + "\n"


def _write_claims(repo_key: str, claims: Dict[str, Any]) -> None:
    path = claims_path(repo_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(claims, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def cmd_inbox_claim(args: argparse.Namespace) -> int:
    repo_key, _, _ = repo_identity(args.repo)
    program = resolve_program(repo_key, args.program)
    worktree = _worktree_key(args.repo)
    claims = _load_claims(repo_key)
    prior = claims.get(worktree)
    if prior and prior.get("target") != args.target and not args.force:
        raise OrchError(
            "worktree %s is already claimed by %r (program %r).\n"
            "Two agents draining one inbox split its items; pass --force only "
            "if you know the prior claimant is gone."
            % (worktree, prior.get("target"), prior.get("program"))
        )
    # The claim is keyed by worktree, so a second worktree claiming the same
    # TARGET is not a conflict this map can represent -- both entries are valid
    # and both agents drain. That is the failure a rotation into a fresh
    # worktree produces, and it is silent from either side, so it is refused
    # here rather than warned about. `orch rotate claim` is the sanctioned
    # takeover: it removes the predecessor's claim in the same write.
    others = [w for w, c in claims.items()
              if c.get("target") == args.target and w != worktree]
    if others and not args.force:
        raise OrchError(
            "%r is already claimed by another worktree:\n  %s\n"
            "Claiming it here would leave two claimants for one inbox, and "
            "while both agents live both drain it -- items split, and no sender "
            "can tell. If you are replacing that agent, use the rotation "
            "protocol (`orch rotate begin` in the predecessor, `orch rotate "
            "claim` here) which transfers the claim instead of duplicating it. "
            "Pass --force only if that worktree's agent is already gone."
            % (args.target, "\n  ".join(others))
        )
    for stale in others:                      # only reachable under --force
        claims.pop(stale, None)
    claims[worktree] = {"target": args.target, "program": program,
                        "at": _now()}
    _write_claims(repo_key, claims)
    print("inbox for %s claimed by %r (program %s)"
          % (worktree, args.target, program))
    if others:
        print("released stale claim(s): %s" % ", ".join(others))
    return 0


def cmd_inbox_send(args: argparse.Namespace) -> int:
    repo_key, _, _ = repo_identity(args.repo)
    if not args.to:
        raise OrchError("--to is required when sending; a sender never guesses "
                        "whose inbox it is writing to")
    program = resolve_program(repo_key, args.program)
    if is_placeholder(args.body):
        raise OrchError("--body must say something actionable")
    item = {
        "at": _now(),
        "kind": args.kind,
        "from": args.sender or os.environ.get("ORCH_INBOX_TARGET") or "unknown",
        "body": args.body,
    }
    if args.ref:
        item["ref"] = args.ref
    line = json.dumps(item, sort_keys=True) + "\n"
    encoded = line.encode("utf-8")
    if len(encoded) > MAX_ITEM_BYTES:
        raise OrchError(
            "item is %d bytes, over the %d-byte line limit.\n"
            "Write the detail to a file and send a body that points at it -- "
            "the same reason a brief is a file." % (len(encoded), MAX_ITEM_BYTES)
        )
    log, _ = inbox_paths(repo_key, program, args.to)
    os.makedirs(os.path.dirname(log), exist_ok=True)
    # One open, one write, one close: appends interleave but never tear.
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, encoded)
    finally:
        os.close(fd)
    if not args.quiet:
        print("queued %s for %s" % (args.kind, args.to))
    return 0


def cmd_inbox_peek(args: argparse.Namespace) -> int:
    repo_key, _, _ = repo_identity(args.repo)
    program, target = resolve_target(args, repo_key)
    if not target:
        if not args.quiet:
            print("no inbox claimed for this worktree")
        return 3
    log, cursor = inbox_paths(repo_key, program, target)
    items, _ = _read_pending(log, cursor)
    if not items:
        if not args.quiet:
            print("inbox for %s is empty" % target)
        return 3
    if not args.quiet:
        kinds = ", ".join(sorted({str(i.get("kind", "fyi")) for i in items}))
        print("%d pending for %s (%s)" % (len(items), target, kinds))
    return 0


def cmd_inbox_drain(args: argparse.Namespace) -> int:
    """Print undelivered items and advance the cursor.

    Silent and successful when there is nothing to do, because this runs from a
    turn-end hook on every turn. A drain that printed or failed when idle would
    make the hook cost tokens forever, and the first thing anyone would do is
    remove the hook.
    """
    if args.format == "hook" and args.repo == ".":
        # A turn-end hook is not guaranteed to run in the directory the agent is
        # working in, and the harness says so by putting `cwd` in the payload it
        # pipes to the hook. Trusting the process cwd instead is how the hook
        # silently drains the wrong repo's inbox, or none at all.
        args.repo = _hook_cwd() or args.repo
    try:
        repo_key, _, _ = repo_identity(args.repo)
        program, target = resolve_target(args, repo_key)
    except OrchError:
        # A hook fires everywhere, including outside a repo and in sessions
        # that never orchestrated anything. Refusing loudly there would train
        # the human to delete the hook.
        if args.format == "hook":
            return 0
        raise
    if not target:
        return 0
    log, cursor = inbox_paths(repo_key, program, target)
    items, total = _read_pending(log, cursor)
    if not items:
        return 0
    text = render_inbox(items, target)
    # Cursor advances only after the text is in hand, and the caller must
    # deliver what it printed: a drain whose output is discarded loses the
    # items. That is why nothing but the receiver may drain.
    _advance_cursor(cursor, total)
    if args.format == "json":
        print(json.dumps({"target": target, "items": items}, indent=2))
    elif args.format == "hook":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": text,
        }}))
    else:
        print(text, end="")
    return 0


_HOOK_PAYLOAD: Optional[Dict[str, Any]] = None
_HOOK_PAYLOAD_READ = False


def hook_payload() -> Dict[str, Any]:
    """The turn-end hook's JSON payload, or {} when not running as a hook.

    Read at most once, because stdin is not re-readable. Silent on every
    failure path: an interactive invocation has a terminal on stdin and must not
    block, and a payload that is absent or unparseable is simply not a hook
    invocation.
    """
    global _HOOK_PAYLOAD, _HOOK_PAYLOAD_READ
    if _HOOK_PAYLOAD_READ:
        return _HOOK_PAYLOAD or {}
    _HOOK_PAYLOAD_READ = True
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        raw = sys.stdin.read(1 << 20)
    except (OSError, ValueError):
        return {}
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    _HOOK_PAYLOAD = parsed if isinstance(parsed, dict) else None
    return _HOOK_PAYLOAD or {}


def _hook_cwd() -> Optional[str]:
    cwd = hook_payload().get("cwd")
    return cwd if isinstance(cwd, str) and os.path.isdir(cwd) else None


def cmd_inbox_list(args: argparse.Namespace) -> int:
    repo_key, _, _ = repo_identity(args.repo)
    program, target = resolve_target(args, repo_key)
    if not target:
        raise OrchError("no inbox target; pass --to or run `orch inbox claim`")
    log, cursor = inbox_paths(repo_key, program, target)
    items, total = _read_pending(log, cursor)
    pending_from = total - len(items) + 1
    if not args.all:
        print("%s: %d delivered, %d pending" % (target, total - len(items),
                                                len(items)))
        for item in items:
            line = "  [%d] %s %s" % (item.get("index", 0), item.get("kind"),
                                     item.get("body", ""))
            print(line[:200])
        return 0
    try:
        with open(log, "r", encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    except FileNotFoundError:
        lines = []
    for index, line in enumerate(lines, start=1):
        mark = "pending " if index >= pending_from else "delivered"
        print("%s [%d] %s" % (mark, index, line[:400]))
    return 0


# --------------------------------------------------------------------------- #
# cost: what the orchestrator's own context is charging per step
# --------------------------------------------------------------------------- #
#
# Measured on a real program: identical work cost $0.42 per model call while the
# orchestrator carried 118K of context, $1.35 at 668K, and $0.23 after an
# auto-compaction dropped it to 88K. Cache reads were 61% of the bill, output
# 16%, and reasoning tokens only ~3%.
#
# The consequence is the point of this section: an orchestrator's context is not
# a private convenience, it is a **tax on every remaining step of the program**.
# A 20K tool result read once is 20K re-read on every subsequent call. Nothing
# in a token count makes that visible, so the numbers are computed here instead.

# Per-million-token rates, USD. An ESTIMATE for advisory purposes, current as of
# 2026-09; override with ORCH_RATES (JSON) or <program>/rates.json rather than
# editing this table, so a price change does not need a code change.
DEFAULT_RATES = {
    "default":  {"in": 15.0, "out": 75.0, "cache_write": 18.75, "cache_read": 1.5},
    "haiku":    {"in": 1.0,  "out": 5.0,  "cache_write": 1.25,  "cache_read": 0.1},
    "sonnet":   {"in": 3.0,  "out": 15.0, "cache_write": 3.75,  "cache_read": 0.3},
}

# Context thresholds, in tokens. The first is where the per-step tax starts to
# dominate; the second is where rotating is almost always cheaper than continuing.
CONTEXT_WARN = int(os.environ.get("ORCH_CONTEXT_WARN", 250_000))
CONTEXT_URGENT = int(os.environ.get("ORCH_CONTEXT_URGENT", 400_000))
# Fan-out width past which a program is usually generating more intake than it
# can consume. Advisory only -- there is no safe universal cap.
FANOUT_WARN = int(os.environ.get("ORCH_FANOUT_WARN", 8))


def load_rates(repo_key: Optional[str], program: Optional[str]) -> Dict[str, Any]:
    override = os.environ.get("ORCH_RATES")
    if override:
        try:
            return {**DEFAULT_RATES, **json.loads(override)}
        except ValueError:
            pass
    if repo_key and program:
        path = os.path.join(program_dir(repo_key, program), "rates.json")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return {**DEFAULT_RATES, **json.load(fh)}
        except (OSError, ValueError):
            pass
    return dict(DEFAULT_RATES)


def rate_for(model: str, rates: Dict[str, Any]) -> Dict[str, float]:
    name = (model or "").lower()
    for key, value in rates.items():
        if key != "default" and key in name:
            return value
    return rates["default"]


def project_dir_for(cwd: str) -> Optional[str]:
    """The harness transcript directory for a working directory, if it exists."""
    base = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd))
    path = os.path.join(base, slug)
    return path if os.path.isdir(path) else None


def find_transcript(args: argparse.Namespace) -> Optional[str]:
    if getattr(args, "transcript", None):
        return args.transcript
    from_hook = hook_payload().get("transcript_path")
    if isinstance(from_hook, str) and os.path.isfile(os.path.expanduser(from_hook)):
        return os.path.expanduser(from_hook)
    pdir = project_dir_for(args.repo if os.path.isdir(args.repo) else ".")
    if not pdir:
        return None
    files = [os.path.join(pdir, f) for f in os.listdir(pdir) if f.endswith(".jsonl")]
    return max(files, key=os.path.getmtime) if files else None


def read_usage(path: str, rates: Dict[str, Any]) -> Dict[str, Any]:
    """Summarise a harness transcript's model calls.

    Reads the file streaming and keeps only aggregates, because the whole point
    is to answer a question about a large file without carrying it anywhere.
    """
    totals = {"in": 0, "out": 0, "cache_write": 0, "cache_read": 0}
    steps = 0
    cost = 0.0
    recent: List[Tuple[int, float]] = []          # (context, cost) per step
    models: Dict[str, int] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("type") != "assistant":
                    continue
                message = row.get("message") or {}
                usage = message.get("usage") or {}
                if not usage:
                    continue
                model = message.get("model") or ""
                rate = rate_for(model, rates)
                models[model] = models.get(model, 0) + 1
                fields = {
                    "in": usage.get("input_tokens", 0) or 0,
                    "out": usage.get("output_tokens", 0) or 0,
                    "cache_write": usage.get("cache_creation_input_tokens", 0) or 0,
                    "cache_read": usage.get("cache_read_input_tokens", 0) or 0,
                }
                step_cost = sum(fields[k] * rate[k] for k in fields) / 1e6
                for key, value in fields.items():
                    totals[key] += value
                cost += step_cost
                steps += 1
                context = fields["in"] + fields["cache_write"] + fields["cache_read"]
                recent.append((context, step_cost))
                if len(recent) > 25:
                    recent.pop(0)
    except OSError:
        return {}
    if not steps:
        return {}
    window = recent[-25:]
    return {
        "transcript": path,
        "steps": steps,
        "tokens": totals,
        "cost": cost,
        "context": window[-1][0] if window else 0,
        "cost_per_step": sum(c for _, c in window) / len(window) if window else 0.0,
        "models": models,
        "shares": {k: (totals[k] * rate_for(max(models, key=models.get) if models else "",
                                           rates)[k] / 1e6 / cost if cost else 0)
                   for k in totals},
    }


def budget_path(repo_key: str, program: str) -> str:
    return os.path.join(program_dir(repo_key, program), "budget.json")


def load_budget(repo_key: str, program: str) -> Dict[str, Any]:
    try:
        with open(budget_path(repo_key, program), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def cost_advisories(usage: Dict[str, Any], budget: Dict[str, Any],
                    open_entries: int) -> List[str]:
    """Only things worth interrupting for, and each with the action attached."""
    out = []
    context = usage.get("context", 0)
    per_step = usage.get("cost_per_step", 0.0)
    if context >= CONTEXT_URGENT:
        out.append(
            "CONTEXT %dK — every further model call costs about $%.2f, and a "
            "typical turn is a dozen calls. Rotate now: write a handoff note, "
            "then hand the program to a fresh orchestrator, which resumes from "
            "the tracker, the briefs and the plan document. Measured: the same "
            "work runs ~5x cheaper at a low context."
            % (context // 1000, per_step)
        )
    elif context >= CONTEXT_WARN:
        out.append(
            "CONTEXT %dK — at about $%.2f per model call and rising. Stop "
            "reading anything large into this session; delegate reads and keep "
            "only conclusions. Plan a rotation."
            % (context // 1000, per_step)
        )
    limit = budget.get("limit")
    if isinstance(limit, (int, float)) and limit > 0:
        spent = usage.get("cost", 0.0)
        if spent >= limit:
            out.append("BUDGET — about $%.0f spent against a $%.0f limit for this "
                       "session. Say so plainly and let the human decide whether "
                       "to continue." % (spent, limit))
        elif spent >= 0.75 * limit:
            out.append("BUDGET — about $%.0f of $%.0f used." % (spent, limit))
    if open_entries >= FANOUT_WARN:
        out.append(
            "FAN-OUT %d open dispatches — each one returns a report you must "
            "read, and intake is what grows this context. Land and close what "
            "is finished before dispatching more." % open_entries
        )
    return out


def transcripts_path(repo_key: str, program: str) -> str:
    return os.path.join(program_dir(repo_key, program), "transcripts.json")


def _load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def record_transcript(repo_key: str, program: str, target: str, path: str) -> None:
    """Remember which transcript belongs to which inbox target.

    Written by the agent itself from its own hook payload, so a front desk can
    later ask `orch cost --for root` about the backend without either of them
    knowing the other's session id -- a mapping the substrate does not expose.
    """
    tpath = transcripts_path(repo_key, program)
    data = _load_json(tpath)
    if data.get(target) == path:
        return
    data[target] = path
    _save_json(tpath, data)


def cmd_cost(args: argparse.Namespace) -> int:
    quiet = args.format == "hook"
    if quiet and args.repo == ".":
        args.repo = _hook_cwd() or args.repo
    try:
        repo_key, _, _ = repo_identity(args.repo)
        program = resolve_program(repo_key, args.program)
    except OrchError:
        if quiet:
            return 0
        repo_key, program = None, None
    rates = load_rates(repo_key, program)
    if getattr(args, "for_target", None):
        if not (repo_key and program):
            raise OrchError("--for needs a repository with a program")
        known = _load_json(transcripts_path(repo_key, program)).get(args.for_target)
        if not known:
            raise OrchError(
                "no transcript recorded for %r yet. The target records its own "
                "transcript the first time its turn-end hook runs." % args.for_target
            )
        args.transcript = known
    path = find_transcript(args)
    if quiet and path and repo_key and program:
        try:
            _, target = resolve_target(args, repo_key)
        except OrchError:
            target = None
        if target:
            record_transcript(repo_key, program, target, path)
    if not path:
        if quiet:
            return 0
        raise OrchError("no transcript found; pass --transcript")
    usage = read_usage(path, rates)
    if not usage:
        if quiet:
            return 0
        raise OrchError("no model calls found in %s" % path)

    # The status line must never read a transcript itself, so the read that just
    # happened is written down for it. Best effort: a failed cache write is not
    # worth failing a cost report over.
    if repo_key and program:
        try:
            _, snapshot_target = resolve_target(args, repo_key)
            if snapshot_target:
                record_cost_usage(repo_key, program, snapshot_target, usage)
        except (OrchError, OSError):
            pass

    open_entries = 0
    budget: Dict[str, Any] = {}
    if repo_key and program:
        budget = load_budget(repo_key, program)
        try:
            for _, data in _read_all_trackers(repo_key, program, True, "root"):
                open_entries += len(data.get("entries", []))
        except OrchError:
            pass

    advisories = cost_advisories(usage, budget, open_entries)
    if repo_key and program:
        stale = rotation_advisory(load_rotation(repo_key, program))
        if stale:
            advisories.insert(0, stale)

    if args.format == "json":
        print(json.dumps({**usage, "advisories": advisories,
                          "open_entries": open_entries}, indent=2))
        return 0

    if quiet:
        if not advisories or not _should_warn(repo_key, program, usage,
                                              advisories):
            return 0
        text = ("COST — $%.0f this session, ~$%.2f per model call at %dK "
                "context.\n\n%s\n" % (usage["cost"], usage["cost_per_step"],
                                      usage["context"] // 1000,
                                      "\n\n".join(advisories)))
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "Stop", "additionalContext": text}}))
        return 0

    t = usage["tokens"]
    print("transcript   %s" % usage["transcript"])
    print("model calls  %d" % usage["steps"])
    print("context now  %dK tokens" % (usage["context"] // 1000))
    print("tokens       in %s · out %s · cache write %s · cache read %s"
          % tuple("{:,}".format(t[k]) for k in
                  ("in", "out", "cache_write", "cache_read")))
    print("cost (est)   $%.2f total · $%.2f per model call (last 25)"
          % (usage["cost"], usage["cost_per_step"]))
    print("cost share   %s" % " · ".join(
        "%s %.0f%%" % (k.replace("_", " "), v * 100)
        for k, v in sorted(usage["shares"].items(), key=lambda x: -x[1])))
    if open_entries:
        print("open work    %d dispatches" % open_entries)
    if budget.get("limit"):
        print("budget       $%s" % budget["limit"])
    for line in advisories:
        print("\n! %s" % line)
    if not advisories:
        print("\nno advisories: context and fan-out are within thresholds.")
    return 0


def _should_warn(repo_key: Optional[str], program: Optional[str],
                 usage: Dict[str, Any], advisories: List[str]) -> bool:
    """Warn when something new is true, or when it got materially worse.

    A hook that repeats itself gets switched off, and then it is worth nothing
    at the moment it would have mattered. The signature is the *set* of
    advisory kinds, so a newly-blown budget still speaks even if a context
    warning already fired at this level.
    """
    if not repo_key or not program:
        return True
    path = os.path.join(program_dir(repo_key, program), "cost-warned.json")
    context = usage.get("context", 0)
    signature = "|".join(sorted(a.split(" ")[0] for a in advisories))
    if context >= CONTEXT_URGENT:
        signature += "|urgent"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            prior = json.load(fh)
    except (OSError, ValueError):
        prior = {}
    if (prior.get("signature") == signature
            and context < prior.get("context", 0) * 1.5):
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"signature": signature, "context": context,
                       "at": _now()}, fh)
    except OSError:
        pass
    return True


def cmd_budget(args: argparse.Namespace) -> int:
    repo_key, _, _ = repo_identity(args.repo)
    program = resolve_program(repo_key, args.program)
    path = budget_path(repo_key, program)
    if args.limit is None:
        data = load_budget(repo_key, program)
        print("budget for %s: %s" % (program,
                                     ("$%s" % data["limit"]) if data.get("limit")
                                     else "none set"))
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"limit": args.limit, "at": _now()}, fh)
        fh.write("\n")
    print("budget for %s set to $%s" % (program, args.limit))
    return 0


# --------------------------------------------------------------------------- #
# resume: re-derive orchestration state after compaction or resume
# --------------------------------------------------------------------------- #
#
# Compaction is the cheapest rotation there is -- measured, the per-call price
# fell 5.9x when it fired -- and the only thing wrong with it is that the summary
# is a *recollection* of state. Nothing here needs recollecting: the tracker,
# the inbox and the plan document are on disk. This command prints them, so the
# fresh context starts from the source of truth rather than from a paraphrase.

def frontdesk_path(repo_key: str, program: str) -> str:
    return os.path.join(program_dir(repo_key, program), "frontdesk.json")


def render_resume(repo_key: str, program: str, args: argparse.Namespace) -> str:
    lines = ["ORCHESTRATION STATE — re-derived from disk, not from memory."]
    tracker_id = getattr(args, "tracker", None) or "root"
    try:
        _, data = _read_all_trackers(repo_key, program, False, tracker_id)[0]
    except (OrchError, IndexError):
        data = None
    if data is None:
        lines.append("program %r has no tracker %r yet." % (program, tracker_id))
    else:
        lines.append("program %s · tracker %s · plan %s"
                     % (program, data["tracker_id"], data.get("plan_doc") or "none"))
        entries = data.get("entries", [])
        lines.append("open dispatches: %d" % len(entries))
        for entry in entries:
            lines.append("  " + entry_summary(entry))
    try:
        inbox_program, target = resolve_target(args, repo_key)
    except OrchError:
        inbox_program, target = None, None
    if target:
        log, cursor = inbox_paths(repo_key, inbox_program or program, target)
        pending, _ = _read_pending(log, cursor)
        lines.append("inbox `%s`: %s" % (
            target, ("%d pending — run `orch inbox drain`" % len(pending))
            if pending else "empty"))
    else:
        lines.append("inbox: none claimed for this worktree — run `orch inbox claim --as root`")
    rotation = load_rotation(repo_key, program)
    if rotation.get("state") in ("pending", "claimed"):
        old = rotation.get("from") or {}
        lines.append("ROTATION %s — replacing %r (agent %s). Handoff note: %s"
                     % (rotation["state"], old.get("handle"),
                        (old.get("agent_id") or "-")[:8],
                        rotation.get("handoff")))
        lines.append("  outstanding: %s"
                     % ("`orch rotate claim`, then CLOSE the predecessor, then "
                        "`orch rotate complete --alive <ids>`"
                        if rotation["state"] == "pending"
                        else "CLOSE the predecessor, then `orch rotate complete "
                             "--alive <ids>`"))
    cmp_rec = _load_json(compaction_path(repo_key, program))
    if cmp_rec.get("floor"):
        lines.append("context floor %dK · this program should launch with "
                     "CLAUDE_CODE_AUTO_COMPACT_WINDOW=%d"
                     % (int(cmp_rec["floor"]) // 1000, cmp_rec.get("window") or 0))
    fd = _load_json(frontdesk_path(repo_key, program))
    if fd.get("target"):
        lines.append("front desk: `%s` — human input arrives through it; answer it "
                     "via `orch inbox send --to %s`" % (fd["target"], fd["target"]))
    lines.append("")
    lines.append("Before acting: reload the orchestrating skill, then reconcile "
                 "liveness against the substrate (tracker → substrate → OS). The "
                 "roster above is recorded intent, not proof of life.")
    return "\n".join(lines) + "\n"


def cmd_resume(args: argparse.Namespace) -> int:
    quiet = args.format == "hook"
    if quiet and args.repo == ".":
        args.repo = _hook_cwd() or args.repo
    try:
        repo_key, _, _ = repo_identity(args.repo)
        programs = list_programs(repo_key)
        if not programs:
            # Nothing was ever orchestrated here; a hook must say nothing.
            if quiet:
                return 0
            raise OrchError("no programs for this repo")
        program = resolve_program(repo_key, args.program)
    except OrchError:
        if quiet:
            return 0
        raise
    text = render_resume(repo_key, program, args)
    if quiet:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart", "additionalContext": text}}))
    else:
        print(text, end="")
    return 0


def cmd_frontdesk(args: argparse.Namespace) -> int:
    repo_key, _, _ = repo_identity(args.repo)
    program = resolve_program(repo_key, args.program)
    path = frontdesk_path(repo_key, program)
    if args.clear:
        if os.path.exists(path):
            os.unlink(path)
        print("front desk cleared for %s" % program)
        return 0
    if not args.target:
        data = _load_json(path)
        print("front desk for %s: %s" % (program, data.get("target") or "none"))
        return 0
    _save_json(path, {"target": args.target, "agent_id": args.agent_id,
                      "at": _now()})
    print("front desk for %s is `%s`" % (program, args.target))
    return 0


# --------------------------------------------------------------------------- #
# guard: say so at the moment a large tool input becomes permanent context
# --------------------------------------------------------------------------- #

GUARD_BYTES = int(os.environ.get("ORCH_GUARD_BYTES", 6000))
GUARD_COOLDOWN_S = int(os.environ.get("ORCH_GUARD_COOLDOWN", 600))


def _tool_input_size(name: str, tool_input: Dict[str, Any]) -> int:
    if name == "Bash":
        return len(str(tool_input.get("command", "")))
    if name == "Write":
        return len(str(tool_input.get("content", "")))
    if name in ("Edit", "MultiEdit"):
        return len(str(tool_input.get("new_string", "")))
    return 0


def cmd_guard(args: argparse.Namespace) -> int:
    """PreToolUse: a non-blocking note when a tool input is large.

    Large content the orchestrator writes is re-read on every later model call.
    Measured, inline document-writing was the single largest self-inflicted item
    in one program's context. Nothing is blocked -- the model may well be right
    to write it -- but the choice should be made knowing what it costs.
    """
    payload = hook_payload()
    name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(name, str) or not isinstance(tool_input, dict):
        return 0
    size = _tool_input_size(name, tool_input)
    if size < GUARD_BYTES:
        return 0
    cwd = payload.get("cwd")
    try:
        repo_key, _, _ = repo_identity(cwd if isinstance(cwd, str) else args.repo)
        program = resolve_program(repo_key, None)
    except OrchError:
        return 0
    if not list_programs(repo_key):
        return 0
    marker = os.path.join(program_dir(repo_key, program), "guard-warned.json")
    prior = _load_json(marker)
    try:
        last = datetime.fromisoformat(prior.get("at", "1970-01-01T00:00:00+00:00"))
    except ValueError:
        last = datetime.fromtimestamp(0, timezone.utc)
    if (datetime.now(timezone.utc) - last).total_seconds() < GUARD_COOLDOWN_S:
        return 0
    try:
        _save_json(marker, {"at": _now(), "tool": name, "bytes": size})
    except OSError:
        pass
    text = (
        "CONTEXT — this %s input is about %dKB, and it is now permanent context "
        "for the rest of this session, re-read on every later model call. If it "
        "is a document (brief body, review doc, plan patch, report), a doc-writer "
        "worker at economy tier should author it from a one-paragraph spec, and "
        "you should hold only the path. If it genuinely has to be yours, carry on."
        % (name, size // 1024)
    )
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "additionalContext": text}}))
    return 0


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# statusline: the one status surface the model never pays for
# --------------------------------------------------------------------------- #
#
# An orchestrator that narrates -- "three lanes running, two intakes pending" --
# pays for that sentence on every later model call, because its own output is
# re-read as input for the rest of the session. A status line is the opposite
# trade: the harness draws it as chrome, the human reads it, and not one token
# of it reaches a model. Two rules follow, and they are the whole design:
#
#   1. Read only what is already on disk. Anything needing a transcript, a
#      substrate query, or another process is cached or left out. This runs on
#      every assistant message; it must not become the turn's biggest cost.
#   2. Never fail, and never speak when there is nothing to say. A renderer that
#      throws, or that shows noise in a repo with no program, is a renderer the
#      human switches off -- and it is then worth nothing at the moment it
#      would have mattered.
#
# The same JSON feeds a GUI surface (see references/statusline.md), so the
# rendering rules live here rather than in each adapter.

# Seconds to wait for a harness to write its payload. Only spent when a caller
# leaves stdin open without writing; pass `--stdin never` to skip it entirely.
STDIN_WAIT_S = float(os.environ.get("ORCH_STATUSLINE_STDIN_WAIT", 2.0))
# Seconds a borrowed `track` count may be reused. That segment is the only one
# that spawns a process, so it is the only one that needs a cache.
TRACK_TTL_S = int(os.environ.get("ORCH_STATUSLINE_TRACK_TTL", 15))
# Age past which a spend figure renders as approximate. The turn-end cost hook
# refreshes it; a stale number means that hook stopped running, not that the
# spending stopped.
COST_STALE_S = int(os.environ.get("ORCH_STATUSLINE_COST_STALE", 900))
# Percent of the compaction window. Low on purpose: rotating early is the
# cheapest saving available, so the warning has to arrive while it is still a
# choice (references/cost.md).
CTX_WARN_PCT = int(os.environ.get("ORCH_STATUSLINE_CTX_WARN", 60))
CTX_URGENT_PCT = int(os.environ.get("ORCH_STATUSLINE_CTX_URGENT", 80))
DEFAULT_WINDOW = 200_000

STATUS_SEGMENTS = ("prog", "lanes", "inbox", "cost", "ctx", "alerts", "track")

_ANSI = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33",
         "blue": "34", "magenta": "35", "cyan": "36"}


def _paint(text: str, style: str, color: bool) -> str:
    if not color or not style:
        return text
    codes = ";".join(_ANSI[s] for s in style.split() if s in _ANSI)
    return "\033[%sm%s\033[0m" % (codes, text) if codes else text


def _payload_from_stdin(mode: str) -> Dict[str, Any]:
    """The harness payload, or an empty dict -- never a block and never a raise.

    Claude Code pipes one JSON document and waits for stdout. Other callers pipe
    nothing and may hold the pipe open forever, which is why this waits for
    readability first instead of reading unconditionally.
    """
    if mode == "never":
        return {}
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
    except (AttributeError, ValueError):
        return {}
    try:
        import select
        if not select.select([sys.stdin], [], [], STDIN_WAIT_S)[0]:
            return {}
    except Exception:  # no select for this handle: fall through and read
        pass
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _payload_cwd(payload: Dict[str, Any]) -> Optional[str]:
    workspace = payload.get("workspace") or {}
    for value in (workspace.get("current_dir"), payload.get("cwd"),
                  workspace.get("project_dir")):
        if isinstance(value, str) and value:
            return value
    return None


# --------------------------------------------------------------------------- #
# cost snapshots: measured once by the turn-end hook, read cheaply here

def cost_snapshot_dir(repo_key: str, program: str) -> str:
    return os.path.join(program_dir(repo_key, program), "cost")


def record_cost_usage(repo_key: str, program: str, target: str,
                      usage: Dict[str, Any]) -> None:
    """Write down what a transcript read already measured.

    A transcript is megabytes and the status line runs on every assistant
    message, so the renderer must never read one. The turn-end cost hook has
    already paid for that read; this makes the result readable in a few
    microseconds. One file per target, because every lane's hook writes its own
    and a shared file would make them lose each other's numbers.
    """
    _save_json(
        os.path.join(cost_snapshot_dir(repo_key, program),
                     inbox_slug(target) + ".json"),
        {"target": target,
         "cost": round(float(usage.get("cost", 0.0)), 4),
         "cost_per_step": round(float(usage.get("cost_per_step", 0.0)), 4),
         "context": int(usage.get("context", 0)),
         "steps": int(usage.get("steps", 0)),
         "at": _now()},
    )


def load_cost_snapshots(repo_key: str, program: str) -> Dict[str, Dict[str, Any]]:
    root = cost_snapshot_dir(repo_key, program)
    out: Dict[str, Dict[str, Any]] = {}
    if not os.path.isdir(root):
        return out
    for fname in sorted(os.listdir(root)):
        if not fname.endswith(".json"):
            continue
        data = _load_json(os.path.join(root, fname))
        if data:
            out[fname[:-5]] = data
    return out


def _age_seconds(stamp: Optional[str]) -> Optional[float]:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - when).total_seconds())


# --------------------------------------------------------------------------- #
# the one borrowed number

def _track_counts(repo_root: str, cache_path: str,
                  mode: str) -> Optional[Dict[str, Any]]:
    """How many `track` items await a human, when this repo happens to use track.

    One number, obtained by asking the `track` CLI rather than by reading its
    files: agent-track owns that model, and a second parser of its markdown
    would go stale exactly when it disagreed. Everything else it computes --
    critical path, blockers, per-item detail -- stays its job, and this segment
    disappears entirely in a repo without it.
    """
    if mode == "off" or not os.path.isdir(os.path.join(repo_root, ".track")):
        return None
    cached = _load_json(cache_path)
    fresh = cached.get("at_ts")
    if isinstance(fresh, (int, float)) and (time.time() - fresh) < TRACK_TTL_S:
        return cached.get("counts")
    exe = shutil.which("track")
    if not exe:
        return None
    try:
        done = subprocess.run(
            [exe, "inbox", "--json", "--cwd", repo_root],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
        )
        items = json.loads(done.stdout.decode("utf-8", "replace") or "[]")
    except Exception:
        # Last good value beats a blank: a slow CLI is not news.
        return cached.get("counts")
    counts = {"awaiting": len(items) if isinstance(items, list) else 0}
    try:
        _save_json(cache_path, {"at_ts": time.time(), "counts": counts})
    except OSError:
        pass
    return counts


# --------------------------------------------------------------------------- #
# collection

def collect_status(args: argparse.Namespace,
                   payload: Dict[str, Any]) -> Dict[str, Any]:
    """Everything both surfaces render, from disk only. {} means say nothing."""
    repo_key, root, _ = repo_identity(args.repo)
    programs = [p["program"] for p in list_programs(repo_key)]
    if not programs:
        # Nothing was ever orchestrated in this repo. Silence is the answer.
        return {}
    program = args.program or (programs[0] if len(programs) == 1 else None)
    status: Dict[str, Any] = {
        "repo": os.path.basename(root), "repo_path": root,
        "program": program, "programs": programs, "at": _now(),
    }
    if program is None:
        # Same refusal as everywhere else: naming the choice beats guessing it.
        status["ambiguous"] = True
        return status

    counts = {"running": 0, "pending": 0, "harvested": 0}
    flags = {"no_agent_id": 0, "queued_message": 0, "brief_missing": 0}
    entries: List[Dict[str, Any]] = []
    try:
        trackers = _read_all_trackers(repo_key, program, True, "root")
    except OrchError:
        trackers = []
    for name, data in trackers:
        for entry in data.get("entries", []):
            state = entry.get("status") or "pending"
            counts[state] = counts.get(state, 0) + 1
            row_flags = []
            if state == "pending" and not entry.get("agent_id"):
                flags["no_agent_id"] += 1
                row_flags.append("no-agent-id")
            if entry.get("pending_message"):
                flags["queued_message"] += 1
                row_flags.append("msg-queued")
            brief = entry.get("brief_path")
            if brief and not os.path.exists(brief):
                flags["brief_missing"] += 1
                row_flags.append("brief-missing")
            entries.append({
                "tracker": name,
                "entry": entry.get("entry"),
                "status": state,
                "title": entry.get("title"),
                "agent_id": entry.get("agent_id"),
                "session_name": entry.get("session_name"),
                "worktree": entry.get("worktree"),
                "archetype": entry.get("archetype"),
                "model": entry.get("model"),
                "child_tracker": entry.get("child_tracker"),
                "flags": row_flags,
            })
    status["lanes"] = {"counts": counts, "flags": flags,
                       "total": sum(counts.values()), "entries": entries,
                       "plan_doc": trackers[0][1].get("plan_doc")
                       if trackers else None}

    try:
        _, target = resolve_target(args, repo_key)
    except OrchError:
        target = None
    mine_slug = None
    if target:
        try:
            mine_slug = inbox_slug(target)
        except OrchError:
            mine_slug = None
    mine: Optional[int] = 0 if target else None
    others: List[Dict[str, Any]] = []
    idir = inbox_dir(repo_key, program)
    for fname in sorted(os.listdir(idir)) if os.path.isdir(idir) else []:
        if not fname.endswith(".jsonl"):
            continue
        slug = fname[: -len(".jsonl")]
        items, _total = _read_pending(os.path.join(idir, fname),
                                      os.path.join(idir, slug + ".cursor"))
        if slug == mine_slug:
            mine = len(items)
        elif items:
            others.append({"name": slug, "pending": len(items)})
    status["inbox"] = {
        "target": target, "pending": mine, "others": others,
        "others_pending": sum(o["pending"] for o in others),
    }
    status["frontdesk"] = _load_json(frontdesk_path(repo_key, program)).get("target")

    snapshots = load_cost_snapshots(repo_key, program)
    mine_snap = snapshots.get(mine_slug or "", {})
    program_cost = sum(float(s.get("cost", 0.0) or 0.0)
                       for s in snapshots.values())
    ages = [a for a in (_age_seconds(s.get("at")) for s in snapshots.values())
            if a is not None]
    session_cost = (payload.get("cost") or {}).get("total_cost_usd")
    if session_cost is None and mine_snap:
        session_cost = mine_snap.get("cost")
    budget = load_budget(repo_key, program)
    status["cost"] = {
        "program": round(program_cost, 2) if snapshots else None,
        "session": round(float(session_cost), 2) if session_cost is not None else None,
        "per_step": mine_snap.get("cost_per_step"),
        "limit": budget.get("limit"),
        "measured_targets": len(snapshots),
        "stale": bool(ages) and min(ages) > COST_STALE_S,
        "age_s": round(min(ages)) if ages else None,
    }

    window = payload.get("context_window") or {}
    tokens = window.get("used_tokens") or mine_snap.get("context") or 0
    total = int(window.get("total_tokens") or 0) or int(
        os.environ.get("ORCH_AUTOCOMPACT_WINDOW") or 0) or DEFAULT_WINDOW
    percent = window.get("used_percentage")
    if percent is None and tokens:
        percent = 100.0 * tokens / total
    status["context"] = {
        "percent": round(float(percent), 1) if percent is not None else None,
        "tokens": int(tokens) or None, "window": total,
    }

    # Same thresholds the turn-end cost hook advises on, so the two surfaces
    # cannot disagree about whether something is wrong.
    alerts = []
    if tokens and tokens >= CONTEXT_URGENT:
        alerts.append("rotate")
    elif percent is not None and percent >= CTX_URGENT_PCT:
        alerts.append("rotate")
    elif (tokens and tokens >= CONTEXT_WARN) or (
            percent is not None and percent >= CTX_WARN_PCT):
        alerts.append("ctx")
    if budget.get("limit") and program_cost >= float(budget["limit"]):
        alerts.append("budget")
    if counts.get("running", 0) >= FANOUT_WARN:
        alerts.append("fanout")
    if flags["no_agent_id"]:
        alerts.append("unrecorded")
    if flags["brief_missing"]:
        alerts.append("brief")
    status["alerts"] = alerts

    status["track"] = _track_counts(
        root, os.path.join(program_dir(repo_key, program), "track-cache.json"),
        getattr(args, "track", "auto"))
    return status


# --------------------------------------------------------------------------- #
# rendering

def _glyphs(ascii_only: bool) -> Dict[str, str]:
    if ascii_only:
        return {"inbox": "in ", "sep": " | ", "alert": "!"}
    return {"inbox": "✉", "sep": " · ", "alert": "!"}


def render_status_line(status: Dict[str, Any], color: bool = True,
                       ascii_only: bool = False,
                       segments: Optional[Any] = None) -> str:
    """The compact line. Empty string when there is nothing worth a pixel."""
    if not status:
        return ""
    want = set(segments or STATUS_SEGMENTS)
    g = _glyphs(ascii_only)
    parts: List[str] = []

    if "prog" in want:
        label = "orch"
        if status.get("program") and status["program"] != "default":
            label = "orch:%s" % status["program"]
        parts.append(_paint(label, "dim", color))
    if status.get("ambiguous"):
        parts.append(_paint("pick --program (%s)"
                            % ", ".join(status.get("programs", [])),
                            "yellow", color))
        return g["sep"].join(parts)

    lanes = status.get("lanes") or {}
    counts = lanes.get("counts") or {}
    flags = lanes.get("flags") or {}
    if "lanes" in want:
        if not lanes.get("total"):
            parts.append(_paint("idle", "dim", color))
        else:
            if counts.get("running"):
                parts.append(_paint("%d run" % counts["running"], "green", color))
            if counts.get("pending"):
                parts.append(_paint(
                    "%d pend" % counts["pending"],
                    "yellow" if flags.get("no_agent_id") else "dim", color))
            if counts.get("harvested"):
                parts.append(_paint("%d harv" % counts["harvested"], "dim", color))

    inbox = status.get("inbox") or {}
    if "inbox" in want and (inbox.get("pending") or inbox.get("others_pending")):
        text = g["inbox"] + (str(inbox["pending"]) if inbox.get("pending") else "")
        if inbox.get("others_pending"):
            text += "+%d" % inbox["others_pending"]
        parts.append(_paint(text, "cyan bold" if inbox.get("pending")
                            else "dim", color))

    cost = status.get("cost") or {}
    if "cost" in want and cost.get("program") is not None:
        text = "$%s" % _money(cost["program"])
        limit = cost.get("limit")
        if limit:
            text += "/%s" % _money(limit)
        if cost.get("stale"):
            text += "~"
        style = "dim"
        if limit and cost["program"] >= float(limit):
            style = "red bold"
        elif limit and cost["program"] >= 0.8 * float(limit):
            style = "yellow"
        parts.append(_paint(text, style, color))

    ctx = status.get("context") or {}
    if "ctx" in want and ctx.get("percent") is not None:
        percent = ctx["percent"]
        style = ("red bold" if percent >= CTX_URGENT_PCT
                 else "yellow" if percent >= CTX_WARN_PCT else "dim")
        parts.append(_paint("ctx %d%%" % round(percent), style, color))

    if "alerts" in want and status.get("alerts"):
        parts.append(_paint(g["alert"] + " ".join(status["alerts"]),
                            "red bold", color))

    track = status.get("track") or {}
    if "track" in want and track.get("awaiting"):
        parts.append(_paint("trk %d" % track["awaiting"], "magenta", color))

    return g["sep"].join(p for p in parts if p)


def _money(value: Any) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "?"
    return "%.0f" % amount if amount >= 10 else "%.2f" % amount


def render_status_lines(status: Dict[str, Any], color: bool = True,
                        ascii_only: bool = False, max_lanes: int = 5,
                        width: int = 0,
                        segments: Optional[Any] = None) -> List[str]:
    """The compact line, then one row per lane. For a taller status bar."""
    first = render_status_line(status, color, ascii_only, segments)
    if not first:
        return []
    lines = [first]
    entries = ((status.get("lanes") or {}).get("entries") or [])[:max_lanes]
    limit = width or int(os.environ.get("COLUMNS") or 0) or 100
    for entry in entries:
        who = entry.get("session_name") or (entry.get("agent_id") or "-")[:8]
        # Flags before the title: the title is what gets truncated, and a
        # dispatch with no recorded agent id is the thing worth reading first.
        row = "  %s %s %s %s%s" % (
            entry.get("entry"), entry.get("status"), who,
            ("[%s] " % " ".join(entry["flags"])) if entry.get("flags") else "",
            entry.get("title") or "")
        if len(row) > limit:
            row = row[: max(0, limit - 1)] + "…"
        lines.append(_paint(row, "dim", color))
    remaining = (status.get("lanes") or {}).get("total", 0) - len(entries)
    if remaining > 0:
        lines.append(_paint("  +%d more" % remaining, "dim", color))
    return lines


def cmd_statusline(args: argparse.Namespace) -> int:
    payload = _payload_from_stdin(args.stdin)
    if args.repo == ".":
        args.repo = _payload_cwd(payload) or args.repo
    color = args.color == "always" or (
        args.color == "auto" and not os.environ.get("NO_COLOR"))
    segments = [s.strip() for s in args.segments.split(",")
                if s.strip()] if args.segments else None
    try:
        # JSON is what a GUI adapter consumes, so its strings carry no escapes.
        paint = color and args.format != "json"
        status = collect_status(args, payload)
        line = render_status_line(status, paint, args.ascii, segments)
        lines = render_status_lines(status, paint, args.ascii, args.max_lanes,
                                    args.width, segments)
    except Exception:
        # The module note applies: a renderer that reports its own failure into
        # the harness's chrome is a renderer that gets removed. --debug when
        # something is wrong; silence otherwise.
        if args.debug:
            raise
        return 0
    if args.format == "json":
        print(json.dumps({**status, "line": line, "lines": lines}, indent=2))
        return 0
    if args.format == "multiline":
        for row in lines:
            print(row)
        return 0
    if line:
        print(line)
    return 0


# --------------------------------------------------------------------------- #
# compaction: measure the floor, and catch a window set too low
# --------------------------------------------------------------------------- #
#
# Compaction is the rotation mechanism, so its threshold is a safety-critical
# setting rather than a tuning knob. The failure it can cause is specific: a
# session has an irreducible FLOOR -- system prompt, tool schemas, skill and
# project instructions, plus the compaction summary and whatever the
# session-start hooks print -- and a window set near that floor leaves almost no
# working room. The session then compacts, lands back at or above the trigger,
# and compacts again. Measured across this machine's transcripts, session-open
# floors ran 7K to 97K (p90 50K) and post-compaction floors in coding worktrees
# ran 39K to 63K, so "200K" is safe in one repo and a loop in another.
#
# Everything here therefore works from a MEASURED floor rather than a constant,
# and expresses the safeguard as a ratio. No model tokens are spent: the
# transcript is read on disk, exactly as `orch cost` does.

# Working room as a multiple of the floor. At 3, two thirds of the window is
# usable, which is the smallest margin under which none of the observed floors
# produces a loop.
FLOOR_SAFETY_RATIO = float(os.environ.get("ORCH_FLOOR_RATIO", 3.0))

# What to set when nothing has been measured yet. A blind default has to survive
# the worst floor seen on this machine (97K at session open), not the median --
# hence 300K rather than the 200K a measured floor of 50K would justify.
WINDOW_BLIND_DEFAULT = int(os.environ.get("ORCH_AUTOCOMPACT_WINDOW", 300_000) or 0)

# The smallest window this tool will ever recommend, whatever the floor says.
# Everything here is a SAFETY device, and a safety device that recommends
# lowering a setting has misunderstood its job: `cost.md` shows a lower window
# is genuinely cheaper per unit of work, so choosing to go below this is a
# deliberate cost decision, never something a floor measurement should trigger.
# 200K is also where the harness was observed to fire by default in these repos.
WINDOW_SAFE_MIN = int(os.environ.get("ORCH_WINDOW_MIN", 200_000))

# The harness clamps the window into this range; a recommendation outside it
# would silently become something else.
WINDOW_FLOOR = 100_000
WINDOW_CEILING = 1_000_000

# What the compaction summary and the session-start hooks add on top of a
# session-open floor. A floor measured before this session's first compaction
# has not paid for the summary yet, so it understates the figure that actually
# matters -- where the NEXT cycle starts. Measured, post-compaction floors ran
# 5-15K above session-open floors in the same repos; this errs to the top of
# that range because the consequence of erring low is a loop.
SUMMARY_ALLOWANCE = int(os.environ.get("ORCH_SUMMARY_ALLOWANCE", 15_000))

# Two compactions closer together than this are not a cycle, they are a loop.
# Healthy cycles in the measured transcripts ran 76-140 model calls apart.
LOOP_CALL_GAP = int(os.environ.get("ORCH_LOOP_CALL_GAP", 15))

# The roles whose context ACCUMULATES, and therefore the only ones an early
# compaction window helps. An orchestrator or a front desk lives for the whole
# program; a worker carries a small context and dies at the end of its task, so
# it has nothing to gain from an early window and a half-finished task to lose
# to one. Membership is read from the worktree's inbox claim rather than from
# anything passed at spawn: `agent.session_open` exposes no labels, and the
# claim is a role name the skill already maintains (`root`, `frontdesk`).
LONG_LIVED_ROLES = tuple(
    r.strip() for r in os.environ.get(
        "ORCH_AUTOCOMPACT_ROLES", "root,frontdesk,integrator").split(",")
    if r.strip())

# A call carrying less than this is a title generation or a similar side call,
# not a step of the conversation, and would drag the floor estimate down.
MIN_REAL_CONTEXT = 1_000


def compaction_path(repo_key: str, program: str) -> str:
    return os.path.join(program_dir(repo_key, program), "compaction.json")


def scan_compaction(path: str) -> Dict[str, Any]:
    """Floor, observed window and compaction spacing, from a transcript.

    Streams the file and keeps only aggregates. A boundary appears twice in the
    transcript (the summary message and the boundary metadata); consecutive
    markers with no model call between them collapse to one event, which is why
    `pending` is a latch rather than a counter.
    """
    calls = 0
    prev = 0
    first = None
    events: List[Dict[str, Any]] = []
    pending = False
    peak = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line and "ompact" not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if (row.get("isCompactSummary")
                        or row.get("subtype") == "compact_boundary"):
                    if not pending:
                        pending = True
                        events.append({"at_call": calls, "before": prev,
                                       "after": None})
                    continue
                if row.get("type") != "assistant":
                    continue
                usage = (row.get("message") or {}).get("usage") or {}
                if not usage:
                    continue
                context = ((usage.get("input_tokens") or 0)
                           + (usage.get("cache_creation_input_tokens") or 0)
                           + (usage.get("cache_read_input_tokens") or 0))
                if context < MIN_REAL_CONTEXT:
                    continue
                calls += 1
                peak = max(peak, context)
                if first is None:
                    first = context
                if pending:
                    events[-1]["after"] = context
                    pending = False
                prev = context
    except OSError:
        return {}
    if not calls:
        return {}
    landed = [e["after"] for e in events if e.get("after")]
    # The floor that matters is where a cycle STARTS, so post-compaction beats
    # session-open -- it carries the summary too. Take the worst observed, not
    # the best: a margin computed from the friendliest cycle is not a margin.
    floor = max(landed) if landed else (first or 0)
    return {
        "transcript": path,
        "calls": calls,
        "floor": floor,
        "floor_source": "post-compaction" if landed else "session-open",
        "open_floor": first or 0,
        "peak": peak,
        # Where the harness actually fired, which is the window in effect --
        # more trustworthy than any setting we can read from here.
        "observed_window": max([e["before"] for e in events if e.get("before")]
                               or [0]),
        "events": events,
        "compactions": len(events),
    }


def effective_floor(scan: Dict[str, Any]) -> int:
    """The floor the next cycle will actually start from."""
    floor = int(scan.get("floor") or 0)
    if scan.get("floor_source") != "post-compaction":
        floor += SUMMARY_ALLOWANCE
    return floor


def recommend_window(floor: int) -> int:
    want = max(floor * FLOOR_SAFETY_RATIO, WINDOW_SAFE_MIN)
    want = min(max(want, WINDOW_FLOOR), WINDOW_CEILING)
    return int(round(want / 50_000.0) * 50_000)


def compaction_advisories(scan: Dict[str, Any], window: int,
                          floor: int) -> List[str]:
    """Only the two conditions that mean the window is wrong, not merely tight."""
    out = []
    events = scan.get("events", [])
    effective = window or scan.get("observed_window", 0)
    room = effective - floor if effective else 0

    gaps = []
    prev_call = 0
    for event in events:
        gaps.append(event["at_call"] - prev_call)
        prev_call = event["at_call"]
    tight = [g for g in gaps[1:] if g < LOOP_CALL_GAP]
    if tight:
        out.append(
            "COMPACTION LOOP — %d of %d compactions in this session came less "
            "than %d model calls after the previous one. That is not a rotation "
            "cycle, it is a window set too close to this session's floor of "
            "%dK. The window cannot be changed from inside a running session: "
            "stop taking new work, finish the turn, and ROTATE into a fresh "
            "session with the window at %dK (`references/rotation.md`)."
            % (len(tight), len(events), LOOP_CALL_GAP, floor // 1000,
               recommend_window(floor) // 1000)
        )
    elif effective and room < floor * (FLOOR_SAFETY_RATIO - 1):
        out.append(
            "COMPACTION HEADROOM — this session's floor is %dK against a %dK "
            "window, leaving %dK of working room. One large tool result "
            "triggers a compaction, and the next cycle starts from the same "
            "floor. Raise the window to %dK for the next session; nothing can "
            "change it in this one."
            % (floor // 1000, effective // 1000, max(room, 0) // 1000,
               recommend_window(floor) // 1000)
        )
    return out


def cmd_compaction(args: argparse.Namespace) -> int:
    quiet = getattr(args, "format", "text") == "hook"
    if quiet and args.repo == ".":
        args.repo = _hook_cwd() or args.repo
    try:
        repo_key, _, _ = repo_identity(args.repo)
        program = resolve_program(repo_key, args.program)
    except OrchError:
        if quiet:
            return 0
        repo_key, program = None, None

    # `window` answers from the record alone. It is called at session_open,
    # before any transcript for the new session exists, so it must never depend
    # on one. It prints a number only when this worktree SHOULD have a window
    # set, and nothing otherwise -- the whole policy lives here rather than half
    # here and half in a plugin, so there is one place to correct.
    if args.action == "window":
        if not (repo_key and program):
            return 3
        role = None
        try:
            claim = _load_claims(repo_key).get(_worktree_key(args.repo)) or {}
            role = claim.get("target")
        except OrchError:
            role = None
        if not args.any_role and role not in LONG_LIVED_ROLES:
            if args.explain:
                print("no window for this worktree: its inbox claim is %r, "
                      "which is not a long-lived role (%s). A worker's context "
                      "dies with its task, so an early window costs it a "
                      "half-finished task and saves nothing."
                      % (role, ", ".join(LONG_LIVED_ROLES)), file=sys.stderr)
            return 3
        recorded = _load_json(compaction_path(repo_key, program))
        window = max(int(recorded.get("window") or 0), WINDOW_BLIND_DEFAULT)
        if not window:
            return 3
        print(window)
        if args.explain:
            print("role %r · floor %sK measured · window %dK"
                  % (role, (int(recorded.get("floor") or 0)) // 1000, window // 1000),
                  file=sys.stderr)
        return 0

    path = find_transcript(args)
    if not path:
        if quiet:
            return 0
        raise OrchError("no transcript found; pass --transcript")
    scan = scan_compaction(path)
    if not scan:
        if quiet:
            return 0
        raise OrchError("no model calls found in %s" % path)

    env_window = os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW")
    window = int(env_window) if (env_window or "").strip().isdigit() else 0
    floor = effective_floor(scan)

    if repo_key and program:
        record = _load_json(compaction_path(repo_key, program))
        # Keep the worst floor ever seen for this program. A floor only grows --
        # skills and MCP servers get added, never removed mid-program -- and a
        # window sized from a lucky low reading is the failure this prevents.
        # A recorded floor is already effective -- the allowance was applied
        # when it was written -- so it goes straight into the max.
        floor = max(floor, int(record.get("floor") or 0))
        _save_json(compaction_path(repo_key, program), {
            "floor": floor,
            "floor_source": scan["floor_source"],
            "floor_is_effective": True,
            "window": recommend_window(floor),
            "observed_window": scan["observed_window"] or record.get("observed_window") or 0,
            "compactions": scan["compactions"],
            "measured_at": _now(),
            "transcript": path,
        })
    recommended = recommend_window(floor)

    advisories = compaction_advisories(scan, window, floor)

    if quiet:
        if not advisories:
            return 0
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n\n".join(advisories) + "\n"}}))
        return 0

    if args.format == "json":
        print(json.dumps({**scan, "effective_floor": floor,
                          "recommended_window": recommended,
                          "env_window": window,
                          "advisories": advisories}, indent=2))
        return 0

    print("transcript   %s" % path)
    print("floor        %dK tokens effective (%s; session-open was %dK%s)"
          % (floor // 1000, scan["floor_source"], scan["open_floor"] // 1000,
             ", + %dK summary allowance" % (SUMMARY_ALLOWANCE // 1000)
             if scan["floor_source"] != "post-compaction" else ""))
    print("peak         %dK tokens over %d model calls"
          % (scan["peak"] // 1000, scan["calls"]))
    print("compactions  %d%s" % (scan["compactions"],
                                 (" · harness fired at ~%dK"
                                  % (scan["observed_window"] // 1000))
                                 if scan["observed_window"] else ""))
    print("window       %s"
          % ("%dK (CLAUDE_CODE_AUTO_COMPACT_WINDOW)" % (window // 1000)
             if window else "not set in this session's environment"))
    print("minimum safe %dK (max of floor x %.1f and the %dK floor this tool "
          "will not go below)"
          % (recommended // 1000, FLOOR_SAFETY_RATIO, WINDOW_SAFE_MIN // 1000))
    if window and window < recommended:
        print("             ^ the window in effect (%dK) is BELOW this."
              % (window // 1000))
    for line in advisories:
        print("\n! %s" % line)
    if not advisories:
        print("\nno advisories: compaction spacing and headroom are healthy.")
    return 0


# --------------------------------------------------------------------------- #
# rotate: replace an agent without leaving a dangling one behind
# --------------------------------------------------------------------------- #
#
# Two facts make self-managed rotation fail, and both are structural rather than
# a matter of remembering to be careful:
#
#   * CLOSE interrupts the turn that calls it. An agent closing itself destroys
#     the turn making the call, so it can never observe the result -- which is
#     why the predecessor is the wrong owner of its own closure, and why the
#     rotation observed in practice left the old agent alive.
#   * The inbox claim is keyed by WORKTREE (see `_worktree_key`). A successor
#     started in a fresh worktree does not inherit the claim; it claims the same
#     target for a second worktree, and both agents then drain one inbox and
#     split its items with no sender able to tell.
#
# So the protocol here inverts ownership -- the SUCCESSOR closes the
# predecessor -- and makes the claim transfer an explicit, checked handover
# rather than a second claim that happens to use the same name.

# How long a rotation may sit unfinished before the turn-end hook calls it out.
ROTATION_STALE_MINUTES = int(os.environ.get("ORCH_ROTATION_STALE", 10))


def rotation_path(repo_key: str, program: str) -> str:
    return os.path.join(program_dir(repo_key, program), "rotation.json")


def load_rotation(repo_key: str, program: str) -> Dict[str, Any]:
    return _load_json(rotation_path(repo_key, program))


def pending_rotation_for(repo_key: str, program: str, target: str
                         ) -> Dict[str, Any]:
    """A rotation whose predecessor owned `target`, or {}."""
    rotation = load_rotation(repo_key, program)
    if rotation.get("state") in ("pending", "claimed") and \
            (rotation.get("from") or {}).get("inbox_target") == target:
        return rotation
    return {}


def _age_minutes(stamp: Any) -> Optional[float]:
    if not isinstance(stamp, str):
        return None
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 60.0


def rotation_advisory(rotation: Dict[str, Any]) -> Optional[str]:
    """The dangling-predecessor detector.

    Fires in the successor's session, because that is where someone can act: the
    predecessor is by then either interrupted or not listening.
    """
    if rotation.get("state") not in ("pending", "claimed"):
        return None
    age = _age_minutes(rotation.get("began_at"))
    if age is None or age < ROTATION_STALE_MINUTES:
        return None
    old = rotation.get("from") or {}
    return (
        "ROTATION INCOMPLETE — a rotation away from %r (agent %s) has been open "
        "for %d minutes and its predecessor was never closed. A live "
        "predecessor is a second writer on this program: it still drains the "
        "same inbox and still holds its worktree. Close it, then run "
        "`orch rotate complete --alive <live ids>`; if it is already gone, "
        "`orch rotate complete --assume-none-alive`."
        % (old.get("handle") or "?", (old.get("agent_id") or "-")[:8], age)
    )


def _successor_checklist(rotation: Dict[str, Any]) -> str:
    old = rotation.get("from") or {}
    return "\n".join([
        "Paste this into the successor's first prompt, verbatim:",
        "",
        "  You are replacing agent %s, which is still running and must not stay"
        % (old.get("agent_id") or "<predecessor agent id>"),
        "  running. Before any other work, in this order:",
        "    1. Read the handoff note at %s." % (rotation.get("handoff") or "?"),
        "    2. Load the orchestrating skill, then run:",
        "         orch rotate claim",
        "       It transfers the `%s` inbox to you and refuses if you are in the"
        % (old.get("inbox_target") or "root"),
        "       wrong worktree. Do not run `orch inbox claim` by hand.",
        "    3. CLOSE agent %s (your substrate adapter's CLOSE verb)."
        % (old.get("agent_id") or "<predecessor agent id>"),
        "    4. Run `orch rotate complete --alive <live agent ids>` to prove",
        "       it is gone. Only then start work.",
    ])


def cmd_rotate_begin(args: argparse.Namespace) -> int:
    repo_key, _, _ = repo_identity(args.repo)
    program = resolve_program(repo_key, args.program)
    existing = load_rotation(repo_key, program)
    if existing.get("state") in ("pending", "claimed") and not args.force:
        raise OrchError(
            "a rotation away from %r is already %s (began %s).\n"
            "Two rotations in flight is two successors for one lane. Finish it "
            "with `orch rotate complete`, drop it with `orch rotate abort`, or "
            "pass --force if you know this record is stale."
            % ((existing.get("from") or {}).get("handle"),
               existing.get("state"), existing.get("began_at"))
        )
    handoff = os.path.abspath(os.path.expanduser(args.handoff))
    if not os.path.isfile(handoff) or os.path.getsize(handoff) == 0:
        raise OrchError(
            "handoff note %s does not exist or is empty.\n"
            "The note is the successor's only account of what is in flight that "
            "is not already in the tracker or the plan document, and it must "
            "exist before the successor does -- exactly as a brief must."
            % handoff
        )
    worktree = _worktree_key(args.repo)
    # Deliberately NOT resolve_target(): that prefers ORCH_INBOX_TARGET, which
    # on Paseo is the agent's own id. An agent-id target is not transferable --
    # the successor is a different agent with a different id, so anything queued
    # to the old id becomes unreachable by anyone. The transferable identity is
    # the role-named claim on this worktree, which is why Step 2 claims `root`
    # rather than letting the injected default stand.
    claim = _load_claims(repo_key).get(worktree) or {}
    target = args.handle or claim.get("target")
    env_target = os.environ.get("ORCH_INBOX_TARGET")
    rotation = {
        "state": "pending",
        "began_at": _now(),
        "handoff": handoff,
        "reason": args.reason or "",
        "from": {
            "handle": target or "root",
            "agent_id": args.agent_id,
            "worktree": worktree,
            "inbox_target": target,
        },
    }
    _save_json(rotation_path(repo_key, program), rotation)
    print("rotation recorded: %r -> successor pending (program %s)"
          % (rotation["from"]["handle"], program))
    if not target:
        print("note: this worktree claims no inbox, so there is nothing to "
              "transfer. If you have been draining one, you were reading an "
              "agent-id target from the environment rather than a claim, and "
              "it cannot be transferred -- claim a role name first:\n"
              "  orch inbox claim --as root")
    elif env_target and env_target != target:
        log, cursor = inbox_paths(repo_key, program, env_target)
        orphaned, _ = _read_pending(log, cursor)
        print("WARNING: you also drain %r from ORCH_INBOX_TARGET, and that "
              "target is your own agent id -- it does NOT follow a rotation.\n"
              "%s\n"
              % (env_target,
                 ("%d item%s queued there will be unreachable once you are "
                  "closed. Re-send them to %r before spawning."
                  % (len(orphaned), "" if len(orphaned) == 1 else "s", target))
                 if orphaned else
                 "Nothing is queued there now, so nothing is lost -- but tell "
                 "senders to address %r from here on." % target))
    print("\nSPAWN the successor in THIS worktree (%s) and, on Paseo, in this\n"
          "agent's own workspace -- the inbox claim is keyed by worktree, so a\n"
          "successor elsewhere splits the inbox instead of inheriting it, and\n"
          "the same workspace is also what puts it where the old tab was.\n"
          % worktree)
    print(_successor_checklist(rotation))
    print("\nAfter spawning, do nothing further. Your closure is the "
          "successor's job: CLOSE interrupts the turn that calls it, so you "
          "cannot close yourself and observe that it worked.")
    return 0


def cmd_rotate_claim(args: argparse.Namespace) -> int:
    repo_key, _, _ = repo_identity(args.repo)
    program = resolve_program(repo_key, args.program)
    rotation = load_rotation(repo_key, program)
    if rotation.get("state") not in ("pending", "claimed"):
        raise OrchError(
            "no rotation is pending for program %r.\n"
            "If you are a fresh orchestrator rather than a successor, claim "
            "your inbox the ordinary way: `orch inbox claim --as root`."
            % program
        )
    old = rotation.get("from") or {}
    here = _worktree_key(args.repo)
    if old.get("worktree") and os.path.realpath(old["worktree"]) != here \
            and not args.force_different_worktree:
        raise OrchError(
            "this rotation's predecessor ran in\n  %s\nbut you are in\n  %s\n"
            "The inbox claim is keyed by worktree, so claiming from here would "
            "leave two worktrees claiming %r -- and while the predecessor "
            "lives, both drain it and split its items with no sender able to "
            "tell. Start the successor in the predecessor's worktree, or pass "
            "--force-different-worktree if you have already closed the "
            "predecessor and accept that queued items may have been split."
            % (old["worktree"], here, old.get("inbox_target"))
        )
    target = old.get("inbox_target")
    if target:
        # Drop the predecessor's claim first. A takeover that adds a claim
        # without removing one is the duplicate-drain bug, not a transfer.
        claims = _load_claims(repo_key)
        for worktree in [w for w, c in claims.items()
                         if c.get("target") == target and w != here]:
            claims.pop(worktree, None)
        claims[here] = {"target": target, "program": program, "at": _now(),
                        "rotated_from": old.get("worktree")}
        _write_claims(repo_key, claims)
        log, cursor = inbox_paths(repo_key, program, target)
        pending, _ = _read_pending(log, cursor)
        print("inbox %r transferred to %s (%d item%s still queued)"
              % (target, here, len(pending), "" if len(pending) == 1 else "s"))
    rotation["state"] = "claimed"
    rotation["claimed_at"] = _now()
    rotation["successor_worktree"] = here
    _save_json(rotation_path(repo_key, program), rotation)
    print("\nStill outstanding: CLOSE agent %s, then "
          "`orch rotate complete --alive <live agent ids>`.\n"
          "Until that runs, the predecessor is a second writer on this program."
          % (old.get("agent_id") or "<predecessor>"))
    return 0


def cmd_rotate_complete(args: argparse.Namespace) -> int:
    repo_key, _, _ = repo_identity(args.repo)
    program = resolve_program(repo_key, args.program)
    rotation = load_rotation(repo_key, program)
    if rotation.get("state") not in ("pending", "claimed"):
        print("no rotation in flight for %s" % program)
        return 0
    old = rotation.get("from") or {}
    agent = old.get("agent_id")
    alive = {a.strip() for a in (args.alive or "").split(",") if a.strip()}
    if not alive and not args.assume_none_alive:
        raise OrchError(
            "pass --alive <id,id,...> with the substrate's live agent ids, or "
            "--assume-none-alive.\n"
            "This is the one check that the predecessor is actually gone, and "
            "its own report cannot supply it: CLOSE interrupts the turn that "
            "calls it, so a predecessor never reports its own closure."
        )
    if agent and agent in alive:
        raise OrchError(
            "predecessor %s is still in the live set. Closing it is the point "
            "of the rotation -- a live predecessor still drains %r and still "
            "holds %s. CLOSE it, re-derive the live set, and run this again."
            % (agent[:8], old.get("inbox_target"), old.get("worktree"))
        )
    os.unlink(rotation_path(repo_key, program))
    print("rotation complete: %r replaced, predecessor %s confirmed gone"
          % (old.get("handle"), (agent or "-")[:8]))
    return 0


def cmd_rotate_status(args: argparse.Namespace) -> int:
    repo_key, _, _ = repo_identity(args.repo)
    program = resolve_program(repo_key, args.program)
    rotation = load_rotation(repo_key, program)
    if rotation.get("state") not in ("pending", "claimed"):
        print("no rotation in flight for %s" % program)
        return 3
    old = rotation.get("from") or {}
    print("rotation %s since %s" % (rotation["state"], rotation.get("began_at")))
    print("  from      %s (agent %s)" % (old.get("handle"),
                                         (old.get("agent_id") or "-")[:8]))
    print("  worktree  %s" % old.get("worktree"))
    print("  inbox     %s" % old.get("inbox_target"))
    print("  handoff   %s" % rotation.get("handoff"))
    advisory = rotation_advisory(rotation)
    if advisory:
        print("\n! %s" % advisory)
    return 0


def cmd_rotate_abort(args: argparse.Namespace) -> int:
    repo_key, _, _ = repo_identity(args.repo)
    program = resolve_program(repo_key, args.program)
    path = rotation_path(repo_key, program)
    if os.path.exists(path):
        os.unlink(path)
    print("rotation record cleared for %s. The predecessor keeps its inbox "
          "claim; nothing was closed." % program)
    return 0



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

    sp = sub.add_parser("inbox", help="queued input for a running agent")
    isub = sp.add_subparsers(dest="inbox_command", required=True)

    ip = isub.add_parser("claim",
                         help="record that this worktree drains a given target")
    ip.add_argument("--as", dest="target", required=True,
                    help="inbox name this agent answers to, e.g. root")
    ip.add_argument("--program")
    ip.add_argument("--force", action="store_true",
                    help="override an existing claim on this worktree")
    ip.set_defaults(func=cmd_inbox_claim)

    ip = isub.add_parser("send", help="append one item to a target's inbox")
    ip.add_argument("--to", required=True)
    ip.add_argument("--body", required=True)
    ip.add_argument("--kind", default="fyi", choices=INBOX_KINDS)
    ip.add_argument("--ref", help="tracker entry or item this concerns")
    ip.add_argument("--from", dest="sender")
    ip.add_argument("--program")
    ip.add_argument("--quiet", action="store_true")
    ip.set_defaults(func=cmd_inbox_send)

    ip = isub.add_parser("peek",
                         help="report pending count; exit 3 when empty")
    ip.add_argument("--to")
    ip.add_argument("--program")
    ip.add_argument("--quiet", action="store_true")
    ip.set_defaults(func=cmd_inbox_peek)

    ip = isub.add_parser("drain",
                         help="print pending items and mark them delivered")
    ip.add_argument("--to")
    ip.add_argument("--program")
    ip.add_argument("--format", default="text",
                    choices=("text", "json", "hook"))
    ip.set_defaults(func=cmd_inbox_drain)

    ip = isub.add_parser("list", help="show the inbox log")
    ip.add_argument("--to")
    ip.add_argument("--program")
    ip.add_argument("--all", action="store_true",
                    help="include already-delivered items")
    ip.set_defaults(func=cmd_inbox_list)

    sp = sub.add_parser("cost", help="what this session is spending, and why")
    sp.add_argument("--transcript", help="harness transcript (found if omitted)")
    sp.add_argument("--for", dest="for_target",
                    help="another agent's inbox target, e.g. root, whose "
                         "transcript was recorded by its own hook")
    sp.add_argument("--to", help=argparse.SUPPRESS)
    sp.add_argument("--program")
    sp.add_argument("--format", default="text", choices=("text", "json", "hook"))
    sp.set_defaults(func=cmd_cost)

    sp = sub.add_parser("resume",
                        help="print orchestration state re-derived from disk")
    sp.add_argument("--program")
    sp.add_argument("--tracker", default="root")
    sp.add_argument("--to", help=argparse.SUPPRESS)
    sp.add_argument("--format", default="text", choices=("text", "hook"))
    sp.set_defaults(func=cmd_resume)

    sp = sub.add_parser("frontdesk",
                        help="record which inbox target relays the human")
    sp.add_argument("--set", dest="target")
    sp.add_argument("--agent-id")
    sp.add_argument("--clear", action="store_true")
    sp.add_argument("--program")
    sp.set_defaults(func=cmd_frontdesk)

    sp = sub.add_parser("guard",
                        help="PreToolUse hook: note when a tool input is large")
    sp.add_argument("--format", default="hook", choices=("hook",))
    sp.set_defaults(func=cmd_guard)

    sp = sub.add_parser(
        "statusline",
        help="one line of program status for a harness status bar")
    sp.add_argument("--program")
    sp.add_argument("--to", help="inbox target to report as mine")
    sp.add_argument("--format", default="line",
                    choices=("line", "multiline", "json"))
    sp.add_argument("--color", default="auto",
                    choices=("auto", "always", "never"))
    sp.add_argument("--ascii", action="store_true",
                    help="no glyphs, for a terminal that mangles them")
    sp.add_argument("--track", default="auto", choices=("auto", "off"),
                    help="borrow agent-track's awaiting-a-human count")
    sp.add_argument("--segments",
                    help="comma-separated subset of: %s" % ",".join(STATUS_SEGMENTS))
    sp.add_argument("--stdin", default="auto", choices=("auto", "never"),
                    help="never: do not wait for a harness payload")
    sp.add_argument("--max-lanes", type=int, default=5)
    sp.add_argument("--width", type=int, default=0)
    sp.add_argument("--debug", action="store_true",
                    help="raise instead of rendering nothing")
    sp.set_defaults(func=cmd_statusline)

    sp = sub.add_parser(
        "compaction",
        help="measure this session's context floor and check the window")
    sp.add_argument("action", choices=("measure", "check", "window"),
                    help="measure: floor and recommended window · "
                         "check: SessionStart loop detector · "
                         "window: the number this program should launch with")
    sp.add_argument("--transcript",
                    help="a harness transcript; defaults to this session's")
    sp.add_argument("--program")
    sp.add_argument("--format", default="text",
                    choices=("text", "json", "hook"))
    sp.add_argument("--any-role", action="store_true",
                    help="`window`: answer even for a worker worktree")
    sp.add_argument("--explain", action="store_true",
                    help="`window`: say on stderr why, for a plugin log")
    sp.set_defaults(func=cmd_compaction)

    sp = sub.add_parser(
        "rotate",
        help="replace an agent without leaving a dangling one behind")
    rsub = sp.add_subparsers(dest="rotate_action", required=True)

    rp = rsub.add_parser("begin",
                         help="predecessor: record the handoff before spawning")
    rp.add_argument("--handoff", required=True,
                    help="path to the handoff note; must already exist")
    rp.add_argument("--agent-id", required=True,
                    help="YOUR substrate agent id, so the successor can close you")
    rp.add_argument("--handle", help="your inbox target (default: the claimed one)")
    rp.add_argument("--reason")
    rp.add_argument("--force", action="store_true",
                    help="overwrite a rotation record you know is stale")
    rp.add_argument("--to", help=argparse.SUPPRESS)
    rp.add_argument("--program")
    rp.set_defaults(func=cmd_rotate_begin)

    rp = rsub.add_parser("claim",
                         help="successor: take over the predecessor's inbox")
    rp.add_argument("--force-different-worktree", action="store_true",
                    help="accept a split inbox; only after closing the predecessor")
    rp.add_argument("--program")
    rp.set_defaults(func=cmd_rotate_claim)

    rp = rsub.add_parser("complete",
                         help="successor: prove the predecessor is gone")
    rp.add_argument("--alive", help="comma-separated live agent ids")
    rp.add_argument("--assume-none-alive", action="store_true")
    rp.add_argument("--program")
    rp.set_defaults(func=cmd_rotate_complete)

    rp = rsub.add_parser("status", help="what rotation is in flight, if any")
    rp.add_argument("--program")
    rp.set_defaults(func=cmd_rotate_status)

    rp = rsub.add_parser("abort", help="drop the record; closes nothing")
    rp.add_argument("--program")
    rp.set_defaults(func=cmd_rotate_abort)

    sp = sub.add_parser("budget", help="show or set this program's spend limit")
    sp.add_argument("--set", dest="limit", type=float,
                    help="USD; omit to show the current limit")
    sp.add_argument("--program")
    sp.set_defaults(func=cmd_budget)

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
