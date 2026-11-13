/**
 * orch-inbox -- server entry. Two contributions, both shelling out to `orch`:
 *
 *  - inbox delivery, on `agent.turn_ended`: the fallback for providers with no
 *    Stop hook. This is the plugin's original and primary job.
 *  - the `orch.status` RPC, for the composer pill in `index.client.tsx`. Purely
 *    read-only, and separate on purpose -- the pill is chrome a human reads, so
 *    nothing it renders is ever sent into an agent's context.
 */

import type { PluginServerContext } from "@getpaseo/plugin/server";

import { orchRun } from "./server/orch";
import { publishRecovery } from "./server/recovery";
import { handleStatusRead } from "./server/status";
import { statusRead } from "./shared/status";

// A turn ending is not the same as the human being done. Someone who starts typing
// the instant a turn ends must win the race against us, because a user-queued
// message outranks an inbox item. This delay is the whole mechanism for that.
const SETTLE_DELAY_MS = 1000;

// Set empty to disable the compaction window entirely. Any other value is
// ignored: the window is a policy decision, and `orch compaction window` owns
// it so there is one place to correct rather than two that can disagree.
const AUTOCOMPACT_ENABLED = process.env.ORCH_AUTOCOMPACT_WINDOW !== "";

// Deny by default. Only a Claude Code harness reads
// CLAUDE_CODE_AUTO_COMPACT_WINDOW; `claude-cursor` is Claude Code over the
// Cursor bridge and does read it, while `cursor` is Cursor's own agent and does
// not. Setting it for a provider that ignores it is merely useless; the reason
// this list is explicit is the reverse case -- a future Claude-family provider
// silently inheriting a window nobody measured for it.
const CLAUDE_HARNESS_PROVIDERS = new Set(
  (process.env.ORCH_AUTOCOMPACT_PROVIDERS ?? "claude,claude-cursor")
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean),
);

// The harness's own accepted range. Anything outside it is CLAMPED TO THE
// MINIMUM rather than rejected, which is the failure this bound exists to
// prevent: a window at or below a session's context floor compacts, lands back
// above the trigger, and compacts again -- a loop that hangs the agent instead
// of erroring. `orch` already refuses to recommend such a number; this is the
// second wall, because a plugin that sets a bad window breaks agents silently.
const WINDOW_MIN = 100_000;
const WINDOW_MAX = 1_000_000;

// A session open waits on this. Paseo's hook timeout is 30s and a before hook
// that fails takes the pending operation down with it, so the subprocess gets a
// small budget of its own and every failure below degrades to "set no window".
const WINDOW_TIMEOUT_MS = 5_000;

/**
 * The auto-compact window this worktree should launch with, or null for none.
 *
 * The decision is entirely `orch`'s: it gates on the worktree's claimed inbox
 * role (only a long-lived orchestrator or front desk benefits from an early
 * window) and on the measured context floor. Exit 3 means "no window for this
 * one" and is the ordinary answer, not an error.
 */
async function resolveWindow(repo: string, signal: AbortSignal): Promise<number | null> {
  let stdout = "";
  try {
    const result = await orchRun(
      ["--repo", repo, "compaction", "window", "--explain"],
      { signal, timeout: WINDOW_TIMEOUT_MS },
    );
    stdout = result.stdout;
    if (result.stderr.trim()) console.log(`[orch-inbox] ${repo}: ${result.stderr.trim()}`);
  } catch (error) {
    const code = (error as { code?: unknown }).code;
    // Exit 3 is the documented "this worktree gets no window" answer. Its
    // reasoning goes to stderr under --explain, which is worth logging once.
    const stderr = String((error as { stderr?: unknown }).stderr ?? "").trim();
    if (code === 3) {
      if (stderr) console.log(`[orch-inbox] ${repo}: ${stderr}`);
    } else {
      console.error(`[orch-inbox] no compaction window for ${repo}: ${String(error)}`);
    }
    return null;
  }
  const window = Number(stdout.trim());
  if (!Number.isInteger(window) || window < WINDOW_MIN || window > WINDOW_MAX) {
    console.error(
      `[orch-inbox] REFUSING unsafe compaction window ${JSON.stringify(stdout.trim())} for ` +
        `${repo}: not an integer in [${WINDOW_MIN}, ${WINDOW_MAX}]. The harness would clamp it ` +
        `to the minimum, which can compaction-loop the agent. Setting no window instead.`,
    );
    return null;
  }
  return window;
}

// Deliveries already in flight. A second delivery for the same agent would `send`
// while the first send's turn is still running, and a prompt landing mid-turn
// destroys that turn on Paseo.
const delivering = new Set<string>();

// The target an agent addresses itself by, learned at session_open. Kept because
// `agent.turn_ended` carries no env, and an agent may have been handed an explicit
// ORCH_INBOX_TARGET that is not its agent id.
const targets = new Map<string, string>();

/** Resolves true if the delay elapsed, false if the hook was aborted meanwhile. */
function settle(signal: AbortSignal): Promise<boolean> {
  if (signal.aborted) return Promise.resolve(false);
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve(true);
    }, SETTLE_DELAY_MS);
    function onAbort() {
      clearTimeout(timer);
      resolve(false);
    }
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

// No peek first. A drain on an empty inbox prints nothing and advances nothing,
// so peeking only buys a second process spawn on every turn of every agent --
// and the common case is an empty inbox. It would also introduce a window where
// peek says yes and drain then returns nothing.
async function drain(repo: string, target: string, signal: AbortSignal): Promise<string> {
  const { stdout } = await orchRun(
    ["--repo", repo, "inbox", "drain", "--to", target, "--format", "text"],
    { signal },
  );
  return stdout.trim();
}

// Hook payload types are owned by @getpaseo/plugin. The callbacks below annotate
// them as `any` so this file also typechecks standalone, and narrow to the few
// fields actually used at the point of use.
type HookContext = {
  paseo: {
    agents: {
      ref(id: string): {
        send(text: string): Promise<unknown>;
        refresh(): Promise<unknown>;
        timeline: { append(input: unknown): Promise<unknown> };
      };
    };
  };
  signal: AbortSignal;
};

// Paseo times a lifecycle hook out at 30s (observed: "Plugin RPC timed out"),
// and this runs after the settle delay and an inbox drain. Measured, `due` reads
// a 23MB transcript in 0.2s, so this is a ceiling, not an expectation.
const COMPACT_TIMEOUT_MS = 10_000;

/** One `orch compaction <action>` call: its stdout, or null for "no". */
async function compactionAsk(
  action: "due" | "followup",
  agentId: string,
  repo: string,
  sessionId: string | undefined,
  signal: AbortSignal,
): Promise<string | null> {
  const argv = ["--repo", repo, "compaction", action, "--explain"];
  if (sessionId) argv.push("--session-id", sessionId);
  try {
    const result = await orchRun(argv, { signal, timeout: COMPACT_TIMEOUT_MS });
    if (result.stderr.trim()) console.log(`[orch-inbox] ${agentId}: ${result.stderr.trim()}`);
    return result.stdout.trim() || null;
  } catch (error) {
    // Exit 3 is the ordinary "no". Its reason is logged only for an agent that
    // could ever get a yes -- a worker's "not a long-lived role" would be one
    // line per turn of every lane, and "not owed" is every quiet turn.
    const code = (error as { code?: unknown }).code;
    const stderr = String((error as { stderr?: unknown }).stderr ?? "").trim();
    if (code !== 3) {
      console.error(`[orch-inbox] compaction ${action} failed for ${agentId}: ${String(error)}`);
    } else if (action === "due" && stderr && !stderr.includes("long-lived role")
               && !stderr.includes("no program")) {
      console.log(`[orch-inbox] ${agentId}: ${stderr}`);
    }
    return null;
  }
}

/**
 * Compaction for a long-lived role, at a quiet turn end. Two sends, each on its
 * own turn end:
 *
 *  1. `/compact <orchestrator prompt>`, when `orch compaction due` says so.
 *  2. After that compaction's own turn ends, the follow-up prompt from
 *     `orch compaction followup`. A compaction leaves the agent idle -- unlike a
 *     rotation, nothing starts its next turn -- so without this the summary's
 *     "Do first" list waits for the human.
 *
 * An agent cannot run `/compact` on itself: a prompt it sends through Paseo
 * arrives wrapped as an agent message and is read as plain text, and one that
 * lands mid-turn kills that turn. A plugin send arrives as a user prompt, and a
 * turn end is the one moment nothing is in flight. Verified: a multi-line
 * `/compact <instructions>` sent from here compacts, the summarizer honours
 * every line, and the compaction runs as an ordinary turn with its own
 * turn_started / turn_ended. Every decision lives in `orch`; this only carries
 * the text it prints.
 */
async function compactionTurnEnd(agentId: string, repo: string, context: HookContext): Promise<void> {
  const ref = context.paseo.agents.ref(agentId);
  let sessionId: string | undefined;
  try {
    const snap: any = await ref.refresh();
    const a = snap?.agent ?? snap;
    // A pending question or permission means the human is mid-decision; a
    // compaction now would summarise the question out from under them.
    if (Array.isArray(a?.pendingPermissions) && a.pendingPermissions.length) return;
    // Already running again: a human or a delivery got in first, and a send now
    // would land mid-turn and kill that turn.
    if (a?.status && a.status !== "idle") {
      console.log(`[orch-inbox] compaction check skipped for ${agentId}: status ${a.status}`);
      return;
    }
    sessionId = a?.persistence?.sessionId ?? a?.runtimeInfo?.sessionId ?? undefined;
  } catch (error) {
    console.error(`[orch-inbox] compaction check skipped for ${agentId}: ${String(error)}`);
    return;
  }

  // The follow-up first: a turn end right after a requested compaction is
  // that compaction's own, and it is owed its first turn before anything else.
  const followup = await compactionAsk("followup", agentId, repo, sessionId, context.signal);
  const compact = followup
    ? null
    : await compactionAsk("due", agentId, repo, sessionId, context.signal);
  const text = followup ?? (compact?.startsWith("/compact") ? compact : null);
  if (!text || context.signal.aborted) return;
  try {
    await ref.send(text);
    console.log(`[orch-inbox] sent ${followup ? "post-compaction follow-up" : "/compact"} to ${agentId}`);
  } catch (error) {
    console.error(`[orch-inbox] compaction send failed for ${agentId}: ${String(error)}`);
  }
}

export default function contribute(server: PluginServerContext) {
  // The status surface. Read-only, and the only thing in this plugin the human
  // drives directly: the client pins a composer pill whose label is the same
  // line `orch statusline` prints into a terminal status bar.
  server.handle(statusRead, handleStatusRead);

  server.before("agent.session_open", async ({ request }: { request: any }, context: HookContext) => {
    // Everything in here is wrapped, because a before hook that throws fails the
    // session open -- a misconfigured tracker must not make agents unlaunchable.
    try {
      // Lets a worker address its own inbox without the parent having to tell it its id.
      const existing = request.env?.ORCH_INBOX_TARGET;
      const target = existing ?? request.agentId;
      targets.set(request.agentId, target);

      const env: Record<string, string> = { ...request.env };
      let changed = false;
      if (!existing) {
        env.ORCH_INBOX_TARGET = target;
        changed = true;
      }

      // Compaction is the cheap rotation. Measured, the same orchestrator cost
      // 5.9x more per model call at 668K of context than at 88K, and the harness
      // only compacts near the window limit unless told otherwise. But an early
      // window is not free and not universally safe: below about three times a
      // session's context floor it loops, and a worker's context dies with its
      // task anyway. So this asks rather than assumes, and sets nothing unless a
      // safe number comes back for an agent that will actually benefit.
      if (AUTOCOMPACT_ENABLED && CLAUDE_HARNESS_PROVIDERS.has(request.provider) && request.cwd) {
        const window = await resolveWindow(request.cwd, context.signal);
        // RAISE ONLY. Paseo injects a default window of its own, so "leave it
        // alone if something already set it" would make this hook a no-op
        // exactly where it is needed -- an inherited default is the most likely
        // source of a too-low window, not a deliberate choice. We move it up
        // toward safety and never down: a window someone raised on purpose is
        // theirs to keep, and lowering one is the direction that loops.
        // `ORCH_AUTOCOMPACT_WINDOW=` empty opts out of all of this.
        const inherited = Number(env.CLAUDE_CODE_AUTO_COMPACT_WINDOW ?? "");
        if (window && !(Number.isFinite(inherited) && inherited >= window)) {
          if (inherited) {
            console.log(
              `[orch-inbox] raising compaction window ${inherited} -> ${window} for ${request.cwd}`,
            );
          }
          env.CLAUDE_CODE_AUTO_COMPACT_WINDOW = String(window);
          changed = true;
        }
      }
      return changed ? { ...request, env } : undefined;
    } catch (error) {
      console.error(`[orch-inbox] session_open hook failed, launching unchanged: ${String(error)}`);
      return undefined;
    }
  });

  server.on("agent.turn_ended", async (event: any, context: HookContext) => {
    const agent = event.agent as { id: string; cwd?: string | null; provider?: string };

    // A cancelled turn means a human interrupted and is driving this agent right
    // now. Delivering here would contend with them.
    if (event.outcome.kind === "canceled") return;

    if (delivering.has(agent.id)) return;
    delivering.add(agent.id);
    try {
      if (!(await settle(context.signal))) return;

      const repo = agent.cwd;
      if (!repo) return;
      const target = targets.get(agent.id) ?? agent.id;

      if (event.outcome?.kind === "failed") {
        try {
          await publishRecovery(
            repo,
            target,
            agent.id,
            String(event.turnId ?? "unknown"),
            event.outcome.error ?? {},
            context.paseo,
          );
        } catch (error) {
          console.error(`[orch-inbox] recovery guard failed for agent ${agent.id}: ${String(error)}`);
        }
      }

      // Drain then send, never the reverse: an item drained without delivery is
      // gone, so the send must be the very next thing we do.
      const text = await drain(repo, target, context.signal);
      if (!text) {
        // Nothing to deliver, so this turn end is a quiet seam: the place to
        // compact a long-lived role on purpose. Delivery wins when both apply --
        // the delivered turn ends too, and the check runs again then.
        if (event.outcome?.kind === "completed" && CLAUDE_HARNESS_PROVIDERS.has(agent.provider ?? "")) {
          await compactionTurnEnd(agent.id, repo, context);
        }
        return;
      }

      try {
        await context.paseo.agents.ref(agent.id).send(text);
      } catch (error) {
        // The items are already drained. The cursor has advanced, so this plugin
        // cannot recover them; only the log below preserves the content.
        console.error(
          `[orch-inbox] LOST INBOX ITEMS for agent ${agent.id} (target ${target}): ` +
            `drained but send failed, and drained items are not recoverable by this plugin. ` +
            `Error: ${String(error)}\n--- unsent inbox text ---\n${text}\n--- end ---`,
        );
      }
    } catch (error) {
      // Logged once and dropped. Retrying a delivery is how a plugin livelocks an
      // agent, so there is deliberately no retry loop here.
      console.error(`[orch-inbox] delivery aborted for agent ${agent.id}: ${String(error)}`);
    } finally {
      delivering.delete(agent.id);
    }
  });

  server.on("agent.archived", (event: any) => {
    // Bound the map; an archived agent will never take another turn.
    targets.delete(event.agent.id);
  });

  return () => {
    delivering.clear();
    targets.clear();
  };
}
