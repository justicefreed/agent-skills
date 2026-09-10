/**
 * The roster behind the pill: an agent-context panel, opened by pressing the
 * pill or from the Command Center.
 *
 * The pill's line answers "is anything wrong". This answers "what, exactly" --
 * the lanes and who holds them, who is waiting on whom, what the program has
 * spent, and which advisories are live. Same JSON, same collector; only the
 * layout is new.
 *
 * What it deliberately does *not* render: work items, gates, or a critical
 * path. That is agent-track's job, and duplicating it here would give a repo
 * two disagreeing answers about what is blocked. The one number borrowed from
 * it is `awaiting a human`, which `orch` reads through the `track` CLI and
 * caches; everything else about tasks lives in agent-track's own surfaces.
 *
 * All colours come from `theme.colors`; every Text sets one explicitly, so the
 * panel follows the active Paseo theme rather than React Native's default
 * black. No Paseo SDK imports -- hooks arrive through `createStatusPanel(sdk)`.
 */

import { useMemo } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";

import type { LaneEntry, Status } from "../shared/status";
import type { UseStatus } from "./use-status";

/** The subset of `PluginTheme` this panel reads. Structural, not imported. */
export type PanelTheme = {
  colors: {
    surface0: string;
    surface2: string;
    foreground: string;
    foregroundMuted: string;
    border: string;
    statusDanger: string;
    statusWarning: string;
    statusSuccess: string;
  };
};

/** `PluginAgentPanelProps`, spelled out. */
export type StatusPanelProps = {
  theme: PanelTheme;
  layout: { compact: boolean };
  workspaceId: string;
  agentId: string;
};

/** The human is looking at it, so poll faster than the pill does. */
const PANEL_POLL_MS = 5_000;

const money = (value: number | null | undefined): string | null =>
  typeof value === "number" ? `$${value < 10 ? value.toFixed(2) : Math.round(value)}` : null;

/** Long enough to identify a lane, short enough not to wrap. */
const shortId = (id: string): string => (id.length > 8 ? id.slice(0, 8) : id);

const laneWho = (entry: LaneEntry): string =>
  entry.session_name || (entry.agent_id ? shortId(entry.agent_id) : "unassigned");

/**
 * What each advisory means, in the human's words. The codes come from
 * `orch.py`, which uses these same thresholds for its turn-end warnings -- so
 * the terminal and this panel cannot disagree about whether something is wrong.
 */
const ALERT_TEXT: Record<string, string> = {
  rotate: "rotate this session",
  ctx: "context is deep",
  budget: "at or over the spend limit",
  fanout: "more lanes than the fan-out guide",
  unrecorded: "running lanes with no recorded agent id",
  brief: "a brief file is missing",
};

/**
 * No `ComponentType<StatusPanelProps>` return annotation, on purpose: that type
 * admits a class component, whose `defaultProps` makes props invariant, and
 * Paseo's own props would then have to match this file's narrowed theme
 * exactly. Returning the function component leaves props contravariant, which
 * is what makes "reads eight of the eleven theme colours" legal.
 */
export function createStatusPanel(
  useStatus: UseStatus,
  programOf: (agentId: string) => string | undefined,
) {
  return function StatusPanel({ theme, layout, agentId }: StatusPanelProps) {
    const { cwd, query } = useStatus(agentId, programOf(agentId), PANEL_POLL_MS);
    const compact = layout.compact;
    const c = theme.colors;

    const styles = useMemo(
      () => ({
        root: { flex: 1, backgroundColor: c.surface0, padding: 12, gap: 8 },
        head: { flexDirection: "row" as const, alignItems: "center" as const, gap: 8 },
        title: { color: c.foreground, fontWeight: "600" as const, fontSize: compact ? 15 : 14, flexShrink: 1 },
        muted: { color: c.foregroundMuted, fontSize: compact ? 13 : 12 },
        line: { color: c.foreground, fontSize: compact ? 14 : 13 },
        alertRow: { flexDirection: "row" as const, flexWrap: "wrap" as const, gap: 6 },
        chip: {
          borderWidth: 1,
          borderColor: c.statusWarning,
          borderRadius: 4,
          paddingHorizontal: 6,
          paddingVertical: 2,
        },
        chipText: { color: c.statusWarning, fontSize: compact ? 12 : 11 },
        rows: { flex: 1 },
        row: { borderTopWidth: 1, borderTopColor: c.border, paddingVertical: 6, gap: 2 },
        rowHead: { flexDirection: "row" as const, alignItems: "center" as const, gap: 6 },
        entry: { color: c.foregroundMuted, fontSize: compact ? 13 : 12 },
        state: { fontSize: compact ? 12 : 11 },
        rowTitle: { color: c.foreground, fontSize: compact ? 14 : 13 },
        flags: { color: c.statusWarning, fontSize: compact ? 12 : 11 },
        footer: {
          borderTopWidth: 1,
          borderTopColor: c.border,
          paddingTop: 8,
          flexDirection: "row" as const,
          alignItems: "center" as const,
          gap: 8,
        },
        button: { backgroundColor: c.surface2, borderRadius: 4, paddingHorizontal: 10, paddingVertical: 5 },
        buttonText: { color: c.foreground, fontSize: compact ? 13 : 12 },
        error: { color: c.statusDanger, fontSize: compact ? 13 : 12 },
      }),
      [c, compact],
    );

    const stateColor = (state: string): string =>
      state === "running"
        ? c.statusSuccess
        : state === "harvested"
          ? c.foregroundMuted
          : c.statusWarning;

    if (!cwd) {
      return (
        <View style={styles.root}>
          <Text style={styles.error}>
            This agent has no working directory on this client yet, so there is no repo to report on.
          </Text>
        </View>
      );
    }

    const result = query.data;
    const status: Status | null | undefined = result?.status;

    return (
      <View style={styles.root}>
        <View style={styles.head}>
          <Text style={styles.title} numberOfLines={1}>
            {status?.program ? `orch: ${status.program}` : "orch"}
          </Text>
          {status?.repo ? (
            <Text style={styles.muted} numberOfLines={1}>
              {status.repo}
            </Text>
          ) : null}
          {query.isFetching ? <ActivityIndicator color={c.foregroundMuted} /> : null}
        </View>

        {query.error ? <Text style={styles.error}>{String(query.error)}</Text> : null}
        {result && !result.ok ? (
          <Text style={styles.error}>{result.error || "orch could not be run on this machine."}</Text>
        ) : null}
        {result?.ok && !result.line ? (
          <Text style={styles.muted}>No orch program has ever run in this repo.</Text>
        ) : null}
        {status?.ambiguous ? (
          <Text style={styles.muted}>
            {`Several programs here (${status.programs.join(", ")}). Re-pin the pill with /orch <program> to choose one.`}
          </Text>
        ) : null}

        {status?.alerts?.length ? (
          <View style={styles.alertRow}>
            {status.alerts.map((alert) => (
              <View key={alert} style={styles.chip}>
                <Text style={styles.chipText}>{ALERT_TEXT[alert] ?? alert}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {status?.lanes ? (
          <Text style={styles.line}>
            {status.lanes.total
              ? Object.entries(status.lanes.counts)
                  .filter(([, n]) => n > 0)
                  .map(([state, n]) => `${n} ${state}`)
                  .join(" · ")
              : "No open dispatch entries."}
            {status.lanes.plan_doc ? ` · plan: ${status.lanes.plan_doc}` : ""}
          </Text>
        ) : null}

        {status?.lanes?.entries?.length ? (
          <ScrollView style={styles.rows}>
            {status.lanes.entries.map((entry) => (
              <View key={`${entry.tracker}:${entry.entry}`} style={styles.row}>
                <View style={styles.rowHead}>
                  <Text style={styles.entry}>{entry.entry ?? "?"}</Text>
                  <Text style={[styles.state, { color: stateColor(entry.status) }]}>{entry.status}</Text>
                  <Text style={styles.muted} numberOfLines={1}>
                    {laneWho(entry)}
                  </Text>
                  {entry.archetype ? <Text style={styles.muted}>{entry.archetype}</Text> : null}
                </View>
                {entry.flags.length ? <Text style={styles.flags}>{entry.flags.join(" · ")}</Text> : null}
                <Text style={styles.rowTitle} numberOfLines={2}>
                  {entry.title || "(untitled)"}
                </Text>
              </View>
            ))}
          </ScrollView>
        ) : null}

        {status?.inbox ? (
          <Text style={styles.muted}>
            {[
              typeof status.inbox.pending === "number"
                ? `inbox: ${status.inbox.pending} for this session`
                : "inbox: no target for this session",
              ...status.inbox.others.map((other) => `${other.pending} for ${other.name}`),
              status.frontdesk ? `front desk: ${shortId(status.frontdesk)}` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </Text>
        ) : null}

        {status?.cost ? (
          <Text style={styles.muted}>
            {[
              money(status.cost.program) ? `program ${money(status.cost.program)}` : null,
              money(status.cost.limit) ? `of ${money(status.cost.limit)}` : null,
              money(status.cost.session) ? `this session ${money(status.cost.session)}` : null,
              money(status.cost.per_step) ? `${money(status.cost.per_step)}/step` : null,
              status.cost.stale ? "(snapshots stale — is the turn-end cost hook running?)" : null,
            ]
              .filter(Boolean)
              .join(" · ") || "No cost recorded yet."}
          </Text>
        ) : null}

        {status?.context?.percent != null ? (
          <Text style={styles.muted}>
            {`context ${status.context.percent}% of ${Math.round((status.context.window ?? 0) / 1000)}K`}
          </Text>
        ) : null}

        {status?.track ? (
          <Text style={styles.muted}>{`agent-track: ${status.track.awaiting} awaiting a human`}</Text>
        ) : null}

        <View style={styles.footer}>
          <Pressable style={styles.button} onPress={() => void query.refetch()} accessibilityRole="button">
            <Text style={styles.buttonText}>Refresh</Text>
          </Pressable>
          {status?.at ? <Text style={styles.muted}>{`read ${status.at}`}</Text> : null}
        </View>
      </View>
    );
  };
}
