import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

// Scaffolding smoke test ([M0-REPO-01]): proves the package is wired into the
// pnpm workspace and runnable. Real schema-validation tests land in [M0-SCHEMA-03].
test('graph-schema package manifest is wired into the workspace', () => {
  const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url)));
  assert.equal(pkg.name, '@valuegraph/graph-schema');
});
