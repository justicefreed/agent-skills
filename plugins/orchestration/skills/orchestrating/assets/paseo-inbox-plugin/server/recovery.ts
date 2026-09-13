import { orchRun } from "./orch";
import { recoveryTimelineSchema } from "../shared/status";

export type RecoveryKind = "cursor_root_envelope_limit" | "cursor_blob_capacity";

export type RecoveryClassification = {
  kind: RecoveryKind;
  action: string;
  limitation: string;
};

type Failure = {
  code?: unknown;
  message?: unknown;
};

const ROOT_FALLBACK_PHRASES = [
  "maximum context window exceeded",
  "prompt exceeds context window",
  "context window exceeded",
] as const;

const BLOB_FALLBACK_PHRASES = [
  "blob capacity exceeded",
  "input blob capacity exceeded",
  "request body too large",
] as const;

const ROOT: RecoveryClassification = {
  kind: "cursor_root_envelope_limit",
  action: "Rotate from durable artifacts before continuing.",
  limitation: "The failed prompt will not be replayed automatically.",
};

const BLOB: RecoveryClassification = {
  kind: "cursor_blob_capacity",
  action: "Wait for blob expiry/eviction, or perform an operator-managed restart.",
  limitation: "The plugin will not recursively rotate or replay the failed prompt.",
};

const normalize = (value: unknown): string =>
  typeof value === "string" ? value.trim().toLowerCase() : "";

const hasPhrase = (message: string, phrases: readonly string[]): boolean =>
  phrases.some((phrase) => message.includes(phrase));

/**
 * Classify only Cursor's two known recovery failures. Structured codes win;
 * fallback matching is deliberately restricted to exact documented phrases,
 * rather than treating every "too large" error as a context failure.
 */
export function classifyCursorFailure(failure: Failure): RecoveryClassification | null {
  const code = normalize(failure.code);
  if (code === ROOT.kind) return ROOT;
  if (code === BLOB.kind) return BLOB;

  const message = normalize(failure.message);
  if (hasPhrase(message, ROOT_FALLBACK_PHRASES)) return ROOT;
  if (hasPhrase(message, BLOB_FALLBACK_PHRASES)) return BLOB;
  return null;
}

export type RecoveryRecord = {
  id: string;
  generation: string;
  agentId: string;
  turnId: string;
  kind: RecoveryKind;
  action: string;
  limitation: string;
};

const recorded = new Set<string>();

const compactBody = (record: RecoveryRecord): string =>
  JSON.stringify({
    recovery: record.id,
    generation: record.generation,
    agent: record.agentId,
    turn: record.turnId,
    kind: record.kind,
    action: record.action,
    limitation: record.limitation,
  });

/**
 * Persist through orch's durable inbox log. The preflight list makes replay of
 * the same generation idempotent across plugin reloads without changing orch.
 */
export async function persistRecovery(repo: string, target: string, record: RecoveryRecord): Promise<void> {
  if (recorded.has(record.id)) return;
  const existing = await orchRun(["--repo", repo, "inbox", "list", "--to", target, "--all"]);
  if (existing.stdout.includes(`"recovery":"${record.id}"`)) {
    recorded.add(record.id);
    return;
  }
  await orchRun([
    "--repo",
    repo,
    "inbox",
    "send",
    "--to",
    target,
    "--kind",
    "fyi",
    "--ref",
    record.turnId,
    "--body",
    compactBody(record),
    "--quiet",
  ]);
  recorded.add(record.id);
}

export function recoveryRecord(
  agentId: string,
  turnId: string,
  classification: RecoveryClassification,
): RecoveryRecord {
  const generation = `${agentId}:${turnId}`;
  return {
    id: `${generation}:${classification.kind}`,
    generation,
    agentId,
    turnId,
    kind: classification.kind,
    action: classification.action,
    limitation: classification.limitation,
  };
}

export async function publishRecovery(
  repo: string,
  target: string,
  agentId: string,
  turnId: string,
  failure: Failure,
  paseo: { agents: { ref(id: string): { timeline: { append(input: unknown): Promise<unknown> } } } },
): Promise<boolean> {
  const classification = classifyCursorFailure(failure);
  if (!classification) return false;
  const record = recoveryRecord(agentId, turnId, classification);
  await persistRecovery(repo, target, record);
  const timeline = recoveryTimelineSchema.parse({
    generation: record.generation,
    kind: record.kind,
    action: record.action,
    limitation: record.limitation,
  });
  await paseo.agents.ref(agentId).timeline.append({
    type: "plugin",
    id: `recovery:${record.id}`,
    kind: "recovery-guard",
    version: 1,
    data: timeline,
  });
  return true;
}
