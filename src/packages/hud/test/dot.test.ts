import { test } from "node:test";
import assert from "node:assert/strict";
import { restingAgents, layoutMarks } from "../src/resting-agents.ts";
import { agentArtworkKey, agentVendorName } from "../src/agent-artwork.ts";
import { dotConnectionLabel } from "../src/dot-status.ts";

test("enabled Dot is a distinct HUD and flight endpoint without quota data", () => {
  const snapshot = {
    quotas: [],
    billing: [],
    providers: [
      { id: "codex", detected: true, enabled: true },
      { id: "dot", detected: true, enabled: true },
    ],
  };
  for (const mode of ["notch", "simple"] as const) {
    assert.deepEqual(restingAgents(snapshot as never, mode), ["codex", "dot"]);
    assert.equal(agentArtworkKey("dot"), "dot");
    assert.equal(agentVendorName("dot"), "Dot");
    assert.equal(
      layoutMarks([{ key: "openai" }, { key: "dot" }], {
        hud: { agents: ["dot"] },
      })[0].key,
      "dot",
    );
    snapshot.providers[1].enabled = false;
    assert.deepEqual(restingAgents(snapshot as never, mode), ["codex"]);
    snapshot.providers[1].enabled = true;
  }
});

test("Dot shows connection instead of quota or usage", () => {
  const status = {
    supported: true,
    enabled: true,
    running: true,
    ready: true,
    subscribed: true,
  };
  assert.equal(dotConnectionLabel(status, "zh"), "已连接 Luo");
  assert.equal(
    dotConnectionLabel({ ...status, subscribed: false }, "en"),
    "Awaiting subscription",
  );
  assert.equal(
    dotConnectionLabel({ ...status, ready: false }, "zh"),
    "连接隧道",
  );
  assert.equal(
    dotConnectionLabel({ ...status, running: false }, "en"),
    "Starting",
  );
  assert.equal(
    dotConnectionLabel({ ...status, enabled: false }, "zh"),
    "已关闭",
  );
});
