/**
 * The Paseo SDK spellings, in one file.
 *
 * `index.client.tsx` is the only importer. Everything else under `client/`
 * takes what it needs through `createUseStatus(sdk)`, so when a subpath moves
 * between Paseo generations -- `useRpc` was on the package root in 0.7.2 -- this
 * file is the whole change. A wrong subpath of an external package builds clean
 * and fails at load, which is exactly the kind of failure worth concentrating.
 */

import { useAgent, useRpc } from "@getpaseo/plugin/client";

import { createUseStatus, type StatusSdk } from "./use-status";

const sdk: StatusSdk = { useRpc, useAgent };

export const useStatus = createUseStatus(sdk);
