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
import { handleStatusRead } from "./server/status";
import { statusRead } from "./shared/status";

// A turn ending is not the same as the human being done. Someone who starts typing
// the instant a turn ends must win the race against us, because a user-queued
// message outranks an inbox item. This delay is the whole mechanism for that.
const SETTLE_DELAY_MS = 1000;

// Tokens. Empty string disables. Must be a plain integer between 100000 and
// 1000000; the harness clamps anything else to its minimum.
const AUTOCOMPACT_WINDOW = process.env.ORCH_AUTOCOMPACT_WINDOW ?? "200000";

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
  paseo: { agents: { ref(id: string): { send(text: string): Promise<unknown> } } };
  signal: AbortSignal;
};

export default function contribute(server: PluginServerContext) {
  // The status surface. Read-only, and the only thing in this plugin the human
  // drives directly: the client pins a composer pill whose label is the same
  // line `orch statusline` prints into a terminal status bar.
  server.handle(statusRead, handleStatusRead);

  server.before("agent.session_open", ({ request }: { request: any }) => {
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
    // Compaction is the cheap rotation. Measured, the same orchestrator cost 5.9x
    // more per model call at 668K of context than at 88K, and the harness only
    // compacts near the window limit unless told otherwise. A low window makes
    // every Claude agent rotate before the tax bites; a worker with a brief and a
    // progress artifact loses nothing to it.
    if (AUTOCOMPACT_WINDOW && !env.CLAUDE_CODE_AUTO_COMPACT_WINDOW && request.provider === "claude") {
      env.CLAUDE_CODE_AUTO_COMPACT_WINDOW = AUTOCOMPACT_WINDOW;
      changed = true;
    }
    return changed ? { ...request, env } : undefined;
  });

  server.on("agent.turn_ended", async (event: any, context: HookContext) => {
    const agent = event.agent as { id: string; cwd?: string | null };

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

      // Drain then send, never the reverse: an item drained without delivery is
      // gone, so the send must be the very next thing we do.
      const text = await drain(repo, target, context.signal);
      if (!text) return;

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
