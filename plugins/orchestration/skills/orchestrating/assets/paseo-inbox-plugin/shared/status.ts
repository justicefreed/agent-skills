/**
 * The one RPC this plugin's status surface talks through, and the shape of what
 * comes back.
 *
 * The shape is not designed here. It is `orch statusline --format json`, which
 * is also what the Claude Code status line renders from -- one collector, two
 * surfaces, so the terminal and the composer pill cannot disagree about what a
 * program is doing. Zod strips unknown keys, so a future field in the Python
 * collector is inert here until this file names it.
 *
 * Two deliberate choices, both borrowed from `orch.py`'s own rules:
 *
 *  - Failures are *return values*. A handler that throws crosses the plugin IPC
 *    boundary with no guarantee its message survives, and a status surface that
 *    renders nothing is indistinguishable from a program that is idle. So every
 *    result carries `ok`, and a broken `orch` says so on the pill.
 *  - `line: ""` means *say nothing*. A repo that never ran a program has no
 *    status, and the correct amount of chrome for it is none.
 *
 * The bare specifier, not `/server` or `/client`: 0.8 rejects a `shared/`
 * module that imports a runtime-specific subpath.
 */

import { defineRpc } from "@getpaseo/plugin";
import { z } from "zod";

/** One dispatch entry, as the tracker records it. */
export const laneEntrySchema = z.object({
  tracker: z.string(),
  entry: z.string().nullish(),
  status: z.string(),
  title: z.string().nullish(),
  agent_id: z.string().nullish(),
  session_name: z.string().nullish(),
  worktree: z.string().nullish(),
  archetype: z.string().nullish(),
  model: z.string().nullish(),
  child_tracker: z.string().nullish(),
  /** `no-agent-id`, `msg-queued`, `brief-missing`. */
  flags: z.array(z.string()).default([]),
});
export type LaneEntry = z.output<typeof laneEntrySchema>;

export const statusSchema = z.object({
  repo: z.string().nullish(),
  repo_path: z.string().nullish(),
  program: z.string().nullish(),
  programs: z.array(z.string()).default([]),
  /** Several programs in this repo and none chosen. `orch` refuses to guess. */
  ambiguous: z.boolean().nullish(),
  at: z.string().nullish(),
  lanes: z
    .object({
      counts: z.record(z.string(), z.number()).default({}),
      flags: z.record(z.string(), z.number()).default({}),
      total: z.number().default(0),
      entries: z.array(laneEntrySchema).default([]),
      plan_doc: z.string().nullish(),
    })
    .nullish(),
  inbox: z
    .object({
      target: z.string().nullish(),
      /** Items addressed to this session. `null` when no target resolves. */
      pending: z.number().nullish(),
      others: z.array(z.object({ name: z.string(), pending: z.number() })).default([]),
      others_pending: z.number().default(0),
    })
    .nullish(),
  frontdesk: z.string().nullish(),
  cost: z
    .object({
      program: z.number().nullish(),
      session: z.number().nullish(),
      per_step: z.number().nullish(),
      limit: z.number().nullish(),
      measured_targets: z.number().default(0),
      /** The turn-end cost hook has not written a snapshot in a while. */
      stale: z.boolean().default(false),
      age_s: z.number().nullish(),
    })
    .nullish(),
  context: z
    .object({
      percent: z.number().nullish(),
      tokens: z.number().nullish(),
      window: z.number().nullish(),
    })
    .nullish(),
  /** `rotate`, `ctx`, `budget`, `fanout`, `unrecorded`, `brief`. */
  alerts: z.array(z.string()).default([]),
  /** Borrowed from agent-track, when that repo uses it. Absent otherwise. */
  track: z.object({ awaiting: z.number() }).nullish(),
});
export type Status = z.output<typeof statusSchema>;

/**
 * What the collector prints. `line` and `lines` are pre-rendered by the same
 * Python that renders the terminal status line, so the pill's label is
 * byte-identical to the one in the shell -- no second formatter to drift.
 */
export const statusPayloadSchema = statusSchema.extend({
  line: z.string().default(""),
  lines: z.array(z.string()).default([]),
});

export const statusResultSchema = z.object({
  ok: z.boolean(),
  error: z.string().nullish(),
  line: z.string().default(""),
  lines: z.array(z.string()).default([]),
  status: statusSchema.nullish(),
});
export type StatusResult = z.output<typeof statusResultSchema>;

/** Compact, model-independent data for the recovery-guard timeline row. */
export const recoveryTimelineSchema = z.object({
  generation: z.string(),
  kind: z.enum(["cursor_root_envelope_limit", "cursor_blob_capacity"]),
  action: z.string(),
  limitation: z.string(),
});
export type RecoveryTimeline = z.output<typeof recoveryTimelineSchema>;

export const statusRead = defineRpc({
  name: "orch.status",
  input: z.object({
    /**
     * The repo to report on -- the agent's own cwd. Sent by the client because
     * the agent snapshot already carries it and an agent's cwd cannot change;
     * the daemon does not have to keep a second copy in sync.
     */
    cwd: z.string(),
    program: z.string().optional(),
    /** Inbox target to count as "mine". Defaults to `orch`'s own resolution. */
    to: z.string().optional(),
    /**
     * Comma-separated subset of the renderer's segments, for a surface with
     * less room than a terminal. Formatting stays in Python: a second
     * formatter in TypeScript is a second thing to keep in agreement.
     */
    segments: z.string().optional(),
  }),
  output: statusResultSchema,
});

export type StatusInput = z.input<typeof statusRead.input>;
