import { test } from "node:test";
import assert from "node:assert/strict";
import { agentOrderBlocks } from "../src/agent-order-blocks.ts";
import { layoutMarks } from "../src/resting-agents.ts";

test("Dot without a quota or balance is offered once beside measured sources", () => {
  const blocks = agentOrderBlocks({
    quotas: [{ vendor: "codex" }, { vendor: "codex" }],
    billing: [{ vendor: "deepseek" }],
    providers: [
      { id: "codex", detected: true, enabled: true },
      { id: "chatgpt", detected: true, enabled: true },
      { id: "deepseek", detected: true, enabled: true },
      { id: "dot", detected: true, enabled: true },
    ],
  } as never);
  assert.deepEqual(blocks, [
    { id: "codex", source: "codex", balance: false },
    { id: "api:deepseek", source: "deepseek", balance: true },
    { id: "dot", source: "dot", balance: false },
  ]);
  const order = ["dot", "codex", "api:deepseek"];
  assert.deepEqual(
    layoutMarks(
      ["openai", "deepseek", "dot"].map((key) => ({ key })),
      { order },
    ).map((row) => row.key),
    ["dot", "openai", "deepseek"],
  );
});

test("disabled and undetected providers stay absent while existing reading rows remain", () => {
  assert.deepEqual(
    agentOrderBlocks({
      quotas: [{ vendor: "codex" }],
      billing: [],
      providers: [
        { id: "dot", detected: true, enabled: false },
        { id: "cursor", detected: false, enabled: true },
      ],
    } as never),
    [{ id: "codex", source: "codex", balance: false }],
  );
});
