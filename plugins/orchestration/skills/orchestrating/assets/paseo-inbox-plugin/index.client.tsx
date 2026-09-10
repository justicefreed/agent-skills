/**
 * orch-inbox -- client entry. Contributes the status surface only; inbox
 * delivery is entirely daemon-side in `index.server.ts`.
 *
 * Two registrations and one toggle:
 *
 *  - an agent-context panel, the roster;
 *  - a composer pill per agent, whose one line is what `orch statusline` prints
 *    into a terminal status bar, and which opens the panel when pressed;
 *  - `/orch [program]` and a Command Center item, which pin or unpin that pill.
 *
 * Why the pill is pinned by hand rather than appearing on every agent: a pill
 * needs a `workspaceId` and an `agentId`, and the only places a client callback
 * is handed both are a Command Center item and a slash command. The constraint
 * matches the intent anyway -- program status is worth composer space on the one
 * or two agents actually orchestrating, not on all fifteen lanes.
 *
 * Deliberately absent: any path that writes into an agent's context. Everything
 * here is chrome the human reads and the model never pays for.
 */

import type { PluginClientContext } from "@getpaseo/plugin/client";

import { useStatus } from "./client/sdk";
import { createStatusPanel } from "./client/status-panel";
import { createStatusPill } from "./client/status-pill";

const PANEL_ID = "orch-status";
/** Plugin-local, and the same on every agent: pill ids are scoped per target. */
const PILL_ID = "orch-status";

/**
 * The program `/orch <program>` chose for an agent, when a repo has more than
 * one and `orch` refuses to guess. Read when a surface mounts, so re-pinning is
 * what applies a change -- which is what the slash command does.
 */
const programs = new Map<string, string>();
const programOf = (agentId: string): string | undefined => programs.get(agentId);

/** Pinned pills, by workspace and agent. The value is Paseo's own remover. */
const pinned = new Map<string, () => void>();

const keyOf = (workspaceId: string, agentId: string): string => `${workspaceId}/${agentId}`;

const StatusPanel = createStatusPanel(useStatus, programOf);
const StatusPill = createStatusPill(useStatus, programOf);

export default function contribute(client: PluginClientContext) {
  client.addWorkspacePanel({
    id: PANEL_ID,
    title: "orch status",
    icon: "Radar",
    context: "agent",
    Component: StatusPanel,
  });

  /**
   * Pin or unpin one agent's pill. Pressing `/orch` twice removes it, which is
   * the only affordance a pill needs -- there is no per-agent settings screen.
   */
  function toggle(workspaceId: string, agentId: string, program: string | undefined): void {
    const key = keyOf(workspaceId, agentId);
    const remove = pinned.get(key);
    if (remove) {
      remove();
      pinned.delete(key);
      programs.delete(agentId);
      return;
    }
    if (program) programs.set(agentId, program);
    pinned.set(
      key,
      client.addComposerPill({
        id: PILL_ID,
        // Accessible label and tooltip. The visible text is the Component's.
        title: "orch program status",
        workspaceId,
        agentId,
        Component: StatusPill,
        onPress() {
          client.openPanel(PANEL_ID, { workspaceId, agentId });
        },
      }),
    );
  }

  client.addSlashCommand({
    name: "orch",
    description: "Pin or unpin the orch program status pill on this agent",
    argumentHint: "[program]",
    context: "agent",
    onSubmit({ args, workspace, agent }) {
      toggle(workspace.id, agent.id, args.trim() || undefined);
    },
  });

  client.addCommandCenterItem({
    id: "open-orch-status",
    title: "Open orch status",
    icon: "Radar",
    keywords: ["orch", "orchestration", "lanes", "roster", "dispatch", "inbox", "budget"],
    context: "agent",
    onSelect({ openPanel }) {
      openPanel(PANEL_ID);
    },
  });

  client.addCommandCenterItem({
    id: "toggle-orch-pill",
    title: "Toggle orch status pill",
    icon: "Radar",
    keywords: ["orch", "pill", "composer", "status"],
    context: "agent",
    onSelect({ workspace, agent }) {
      toggle(workspace.id, agent.id, undefined);
    },
  });

  return () => {
    // Paseo removes outstanding registrations itself, but the maps are ours.
    for (const remove of pinned.values()) remove();
    pinned.clear();
    programs.clear();
  };
}
