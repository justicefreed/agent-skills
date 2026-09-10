/**
 * The one read both client surfaces share.
 *
 * The pill and the panel ask the same question about the same agent, so they
 * ask it through the same query key: React Query then serves the panel from the
 * pill's cache the moment it opens, and the two can never show different
 * numbers at the same instant. The panel simply asks for a shorter interval,
 * and React Query polls at the shortest one any live observer wants.
 *
 * The repo comes from `useAgent(agentId, …).cwd`, not from anything this plugin
 * stores: the agent snapshot already has it, an agent's cwd cannot change, and
 * a cached copy is one more thing that can be wrong.
 *
 * This module imports no Paseo SDK module -- `useRpc` and `useAgent` arrive
 * through `createUseStatus(sdk)`. See `client/sdk.ts` for why.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import type { input as ZodInput, output as ZodOutput } from "zod";

import { statusRead, type StatusResult } from "../shared/status";

export type StatusSdk = {
  useRpc(
    contract: typeof statusRead,
  ): (input: ZodInput<typeof statusRead.input>) => Promise<ZodOutput<typeof statusRead.output>>;
  useAgent<Selection>(agentId: string, selector: (agent: { cwd: string }) => Selection): Selection | null;
};

export type StatusQuery = {
  /** `null` while the agent snapshot has not reached this client yet. */
  cwd: string | null;
  query: UseQueryResult<StatusResult>;
};

export type UseStatus = (agentId: string, program: string | undefined, pollMs: number) => StatusQuery;

export function createUseStatus(sdk: StatusSdk): UseStatus {
  return function useStatus(agentId, program, pollMs) {
    const read = sdk.useRpc(statusRead);
    const cwd = sdk.useAgent(agentId, (agent) => agent.cwd);
    const query = useQuery<StatusResult>({
      queryKey: ["orch-status", agentId, program ?? ""],
      enabled: Boolean(cwd),
      refetchInterval: pollMs,
      // The collector reports failures as values, so a failed read is data, not
      // a rejected query. Retrying it would only re-spawn a doomed subprocess.
      retry: false,
      queryFn: () => read({ cwd: cwd as string, ...(program ? { program } : {}) }),
    });
    return { cwd, query };
  };
}
