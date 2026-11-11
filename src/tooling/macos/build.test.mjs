import assert from "node:assert/strict";
import { test } from "node:test";
import { buildPlan, executePlan } from "../build.mjs";

const options = {
  component: "desktop",
  platform: "macos",
  bundle: true,
  debug: false,
};

test("personal Mac bundles defer signing until every nested resource is present", () => {
  const plan = buildPlan(options, {
    APPLE_SIGNING_IDENTITY: "Apple Development: fixture",
    PYTHON: "/fixture/python",
    CARGO_TARGET_DIR: "/fixture/target",
  });
  assert.deepEqual(plan.commands[0].args.slice(-3), [
    "--no-sign",
    "--bundles",
    "app",
  ]);
  assert.equal(plan.commands[1].command, "/fixture/python");
  assert.match(plan.commands[1].args[0], /macos[/\\]sign-bundle\.py$/);
  assert.match(
    plan.commands[1].args[2],
    /release[/\\]bundle[/\\]macos[/\\]Agent HUD\.app$/,
  );
  assert.equal(
    JSON.stringify(plan).includes("Apple Development: fixture"),
    false,
  );
});

test("Windows, unsigned Mac, ad-hoc Mac and component builds keep their prior commands", () => {
  for (const [settings, env, host] of [
    [
      { ...options, platform: "windows" },
      { APPLE_SIGNING_IDENTITY: "Apple Development: fixture" },
      "win32",
    ],
    [options, {}, "darwin"],
    [options, { APPLE_SIGNING_IDENTITY: "-" }, "darwin"],
    [
      options,
      { APPLE_SIGNING_IDENTITY: "Developer ID Application: fixture" },
      "darwin",
    ],
    [
      { ...options, bundle: false },
      { APPLE_SIGNING_IDENTITY: "Apple Development: fixture" },
      "darwin",
    ],
  ]) {
    const plan = buildPlan(settings, env, host);
    assert.equal(plan.commands.length, 1);
    assert.equal(plan.commands[0].args.includes("--no-sign"), false);
    assert.equal(plan.commands[0].shell, host === "win32");
  }
});

test("a failed native build never starts the signer", () => {
  const plan = buildPlan(options, {
    APPLE_SIGNING_IDENTITY: "Apple Development: fixture",
  });
  let calls = 0;
  assert.equal(
    executePlan(plan, () => {
      calls += 1;
      return { status: 7 };
    }),
    7,
  );
  assert.equal(calls, 1);
});
