/**
 * Where this daemon finds the tracker, and how it runs it.
 *
 * Both contributions in this plugin -- the inbox delivery hook and the status
 * RPC -- shell out to the same script, so the resolution order lives here once.
 * It is the order the skill's own turn-end hook uses, so the plugin and the hook
 * cannot disagree about which copy of `orch.py` is canonical.
 *
 * Daemon-side by construction: `orch` reads the repo's state directory and the
 * repo itself, both of which exist on the machine running the daemon and not
 * necessarily on the machine running the Paseo app.
 */

import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";

const run = promisify(execFile);

export type OrchBin = { bin: string; lead: string[] };

/**
 * The tracker ships as a Python script inside the skill, not as an `orch` binary
 * on PATH, so the default has to find it the same way the skill's turn-end hook
 * does.
 */
export function resolveOrch(): OrchBin {
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

export const ORCH = resolveOrch();

/** Runs `orch` with this plugin's arguments and returns stdout. */
export function orchRun(
  args: string[],
  options: { signal?: AbortSignal; timeout?: number; maxBuffer?: number } = {},
): Promise<{ stdout: string; stderr: string }> {
  return run(ORCH.bin, [...ORCH.lead, ...args], {
    signal: options.signal,
    timeout: options.timeout,
    maxBuffer: options.maxBuffer ?? 8 * 1024 * 1024,
    encoding: "utf8",
  });
}
