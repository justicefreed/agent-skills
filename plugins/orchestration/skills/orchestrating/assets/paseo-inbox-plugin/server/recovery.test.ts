import test from "node:test";
import assert from "node:assert/strict";

import { classifyCursorFailure } from "./recovery";

test("classifies structured Cursor recovery codes", () => {
  assert.equal(classifyCursorFailure({ code: "cursor_root_envelope_limit" })?.kind, "cursor_root_envelope_limit");
  assert.equal(classifyCursorFailure({ code: "cursor_blob_capacity" })?.kind, "cursor_blob_capacity");
});

test("classifies exact fallback families without conflating them", () => {
  assert.equal(classifyCursorFailure({ message: "maximum context window exceeded" })?.kind, "cursor_root_envelope_limit");
  assert.equal(classifyCursorFailure({ message: "request body too large" })?.kind, "cursor_blob_capacity");
  assert.equal(classifyCursorFailure({ message: "request too large" }), null);
  assert.equal(classifyCursorFailure({ code: "cursor_blob_capacity", message: "maximum context window exceeded" })?.kind, "cursor_blob_capacity");
});
