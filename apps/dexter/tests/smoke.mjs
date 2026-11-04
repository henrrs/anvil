import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { freshState, modules, screens } from "../src/data.js";
import { renderScreen } from "../src/views.js";

const appSource = await readFile(new URL("../src/app.js", import.meta.url), "utf8");
const handledActions = new Set([...appSource.matchAll(/case\s+"([^"]+)"/g)].map(match => match[1]));
const renderedActions = new Set();
const rendered = new Map();

assert.equal(screens.length, 33, "The complete screen inventory should stay present");
assert.equal(new Set(screens.map(screen => screen.id)).size, screens.length, "Screen IDs must be unique");
assert.equal(modules.filter(module => module.id !== "settings").length, 8, "The shell should expose the eight main product modules");

for (const screen of screens) {
  const state = freshState();
  state.screen = screen.id;
  const html = renderScreen(state);
  assert.ok(html.length > 100, `${screen.id} should render useful content`);
  assert.ok(!html.includes("[object Object]"), `${screen.id} should not leak serialized objects`);
  assert.ok(!html.includes("undefined"), `${screen.id} should not render undefined values`);
  for (const match of html.matchAll(/data-action="([^"]+)"/g)) renderedActions.add(match[1]);
  rendered.set(screen.id, html);
}

const unhandled = [...renderedActions].filter(action => !handledActions.has(action));
assert.deepEqual(unhandled, [], `Rendered actions need handlers: ${unhandled.join(", ")}`);

const state = freshState();
const assetIds = new Set(state.assets.map(asset => asset.id));
const pipelineIds = new Set(state.pipelines.map(pipeline => pipeline.id));
for (const workspace of state.workspaces) {
  assert.ok(workspace.assets.every(id => assetIds.has(id)), `${workspace.name} references only shared catalog assets`);
  assert.ok(workspace.pipelineIds.every(id => pipelineIds.has(id)), `${workspace.name} references only shared pipelines`);
}
for (const product of state.products) {
  assert.ok(product.assets.every(id => assetIds.has(id)), `${product.name} references only shared catalog assets`);
  assert.ok(product.pipelines.every(id => pipelineIds.has(id)), `${product.name} references only shared pipelines`);
}
for (const pipeline of state.pipelines) {
  const nodeIds = new Set(pipeline.nodes.map(node => node.id));
  assert.ok(pipeline.edges.every(([from, to]) => nodeIds.has(from) && nodeIds.has(to)), `${pipeline.name} edges reference existing nodes`);
}

assert.match(rendered.get("sql-workspace"), /8 assets/, "SQL catalog count is data-driven");
assert.doesNotMatch(rendered.get("sql-workspace"), /\$\{state\.assets\.length\}/, "SQL catalog count must not display a template literal");
assert.match(rendered.get("pipeline-studio"), /dependency edges/, "Pipeline screen describes the graph edge count");
assert.match(rendered.get("orchestration"), /3 tasks · 2 dependencies/, "Orchestration is based on the seeded task graph");
assert.match(rendered.get("lab-composer"), /Database|STREAMING|API|PROCESSING/, "Lab Composer exposes service composition");
assert.match(rendered.get("product-builder"), /Compose product assets/, "Data Product Builder composes shared assets");

console.log(`PASS ${screens.length} screens render; ${renderedActions.size} rendered actions have handlers; shared workspace, product, and pipeline references are valid.`);
