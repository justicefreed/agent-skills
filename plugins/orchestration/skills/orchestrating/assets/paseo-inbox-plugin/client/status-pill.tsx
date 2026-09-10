/**
 * The composer pill: one line of program status, beside Tasks and Subagents.
 *
 * The line is not formatted here. It is the string `orch statusline` prints
 * into a terminal status bar, rendered verbatim -- one collector, one
 * formatter, two surfaces that cannot drift apart. Everything this file decides
 * is colour, truncation, and what to say while the first read is in flight.
 *
 * It is chrome: nothing here is ever sent to the agent, which is exactly why it
 * can update every fifteen seconds without costing the model anything. The same
 * status narrated into chat would be re-read as input on every later turn.
 *
 * No Paseo SDK imports; hooks arrive through `createStatusPill(sdk)`.
 */

import { Text, View } from "react-native";

import type { UseStatus } from "./use-status";

/** The subset of `PluginTheme` this pill reads. Structural, not imported. */
export type PillTheme = {
  colors: {
    foreground: string;
    foregroundMuted: string;
    statusWarning: string;
    statusDanger: string;
  };
};

/** `PluginComposerPillProps`, spelled out. */
export type StatusPillProps = {
  theme: PillTheme;
  layout: { compact: boolean };
  workspaceId: string;
  agentId: string;
};

/** Slow on purpose: a program changes on human timescales, and every tick is a
 * short-lived Python process on the daemon. */
const PILL_POLL_MS = 15_000;

/** Unannotated return: see the note in `status-panel.tsx`. */
export function createStatusPill(
  useStatus: UseStatus,
  programOf: (agentId: string) => string | undefined,
) {
  return function StatusPill({ theme, layout, agentId }: StatusPillProps) {
    const { cwd, query } = useStatus(agentId, programOf(agentId), PILL_POLL_MS);
    const result = query.data;
    const c = theme.colors;

    let text: string;
    let color: string;
    if (!cwd) {
      text = "orch";
      color = c.foregroundMuted;
    } else if (query.isLoading) {
      text = "orch: reading";
      color = c.foregroundMuted;
    } else if (!result || (!result.ok && !result.error)) {
      text = "orch: unavailable";
      color = c.statusDanger;
    } else if (!result.ok) {
      // The error text belongs in the panel, where there is room to read it.
      text = "orch: unavailable";
      color = c.statusDanger;
    } else if (!result.line) {
      // The collector's way of saying no program has ever run in this repo. The
      // human pinned the pill deliberately, so say so rather than show nothing.
      text = "orch: no program";
      color = c.foregroundMuted;
    } else {
      text = result.line;
      color = result.status?.alerts?.length ? c.statusWarning : c.foreground;
    }

    return (
      <View style={{ maxWidth: layout.compact ? 200 : 320 }}>
        <Text numberOfLines={1} style={{ color, fontSize: layout.compact ? 13 : 12 }}>
          {text}
        </Text>
      </View>
    );
  };
}
