import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import type { PluginServerContext } from "@getpaseo/plugin/server";

const run = promisify(execFile);

// The tracker ships as a Python script inside the skill, not as an `orch` binary
// on PATH, so the default has to find it the same way the skill's turn-end hook
// does. Same candidate order, so both paths agree about which copy is canonical.
function resolveOrch(): { bin: string; lead: string[] } {
  const override = process.env.ORCH_INBOX_ORCH_BIN;
  if (override) return { bin: override, lead: [] };
  const candidates = [
    process.env.ORCH_SKILL_DIR,
    join(homedir(), ".claude", "skills", "orchestrating"),
    join(homedir(), ".agents", "skills", "orchestrating"),
  ];
  for (const dir of candidates) {
    if (!dir) continue;
    const script = join(dir, "scripts", "orch.py");
    if (existsSync(script)) return { bin: "python3", lead: [script] };
  }
  // Nothing found. Fall back to a PATH lookup so the failure names `orch`
  // rather than a guessed path that was never going to exist.
  return { bin: "orch", lead: [] };
}

// A turn ending is not the same as the human being done. Someone who starts typing
// the instant a turn ends must win the race against us, because a user-queued
// message outranks an inbox item. This delay is the whole mechanism for that.
const SETTLE_DELAY_MS = 1000;

const ORCH = resolveOrch();

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
  const { stdout } = await run(
    ORCH.bin,
    [...ORCH.lead, "--repo", repo, "inbox", "drain", "--to", target, "--format", "text"],
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
  server.before("agent.session_open", ({ request }: { request: any }) => {
    // Lets a worker address its own inbox without the parent having to tell it its id.
    const existing = request.env?.ORCH_INBOX_TARGET;
    const target = existing ?? request.agentId;
    targets.set(request.agentId, target);
    if (existing) return undefined;
    return { ...request, env: { ...request.env, ORCH_INBOX_TARGET: target } };
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
