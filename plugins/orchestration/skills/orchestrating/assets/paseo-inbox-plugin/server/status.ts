/**
 * The status RPC's handler: one `orch statusline --format json` per call.
 *
 * A subprocess per poll is the right trade here. The collector reads only small
 * JSON state files -- the transcript-reading cost report writes a snapshot for
 * it, so nothing in this path opens a megabyte -- and a poll every fifteen
 * seconds against a program that changes on human timescales does not justify a
 * cache with its own staleness bugs. Where a cache *is* warranted, it already
 * exists inside `orch.py`: the borrowed agent-track count is TTL-cached there.
 *
 * `--stdin never` matters. The collector reads a harness payload from stdin when
 * one is offered, and `execFile` leaves the child's stdin open; without the flag
 * the child would wait out its select() timeout on every single poll.
 */

import type { RpcInput } from "@getpaseo/plugin";

import { statusPayloadSchema, statusRead, type StatusResult } from "../shared/status";
import { orchRun } from "./orch";

/** Generous: a cold Python start on a loaded machine, not a hung one. */
const TIMEOUT_MS = 10_000;

const failed = (error: string): StatusResult => ({
  ok: false,
  error,
  line: "",
  lines: [],
  status: null,
});

export async function handleStatusRead(
  input: RpcInput<typeof statusRead>,
): Promise<StatusResult> {
  const args = ["--repo", input.cwd, "statusline", "--format", "json", "--stdin", "never"];
  if (input.program) args.push("--program", input.program);
  if (input.to) args.push("--to", input.to);
  if (input.segments) args.push("--segments", input.segments);

  let stdout: string;
  try {
    ({ stdout } = await orchRun(args, { timeout: TIMEOUT_MS }));
  } catch (error) {
    // Almost always one of: no `orch.py` on this machine, no `python3`, or the
    // cwd is not a git repo. All three are the human's to fix, and all three
    // must reach the pill as text rather than as an empty status.
    return failed(String((error as { message?: string })?.message ?? error));
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    // `statusline` prints nothing at all on an internal failure -- by design,
    // since a renderer that reports its own errors into a status bar is a
    // renderer that gets switched off. An empty stdout is therefore normal-ish;
    // report it as "quiet", not as a parse error the human should act on.
    return stdout.trim()
      ? failed("orch statusline printed unparseable output")
      : { ok: true, error: null, line: "", lines: [], status: null };
  }

  const result = statusPayloadSchema.safeParse(parsed);
  if (!result.success) return failed("orch statusline output did not match the contract");

  const { line, lines, ...status } = result.data;
  return { ok: true, error: null, line, lines, status };
}
