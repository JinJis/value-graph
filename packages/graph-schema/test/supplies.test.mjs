import assert from "node:assert/strict";
import { test } from "node:test";

import { ENTITY_NAMES, validate, validateSupplies } from "../src/validate.mjs";

// A fully-specified, valid SUPPLIES edge (PRD §5.3).
function validSupplies() {
  return {
    supplier: "INTC",
    customer: "HPQ",
    product_ref: "cpu",
    trade_value: 1000,
    currency: "USD",
    supplier_rev_share: 21,
    customer_cost_share: 9.5,
    cost_bucket: "COGS",
    confidence: "derived",
    confidence_interval: { low: 8, high: 11 },
    as_of_date: "2026-03-31",
    next_expected_update: "2026-08-15",
    freshness: "fresh",
    gap: false,
  };
}

test("canonical schema exposes the core entities", () => {
  for (const name of ["SuppliesEdge", "Company", "Claim", "Source"]) {
    assert.ok(ENTITY_NAMES.includes(name), `missing entity: ${name}`);
  }
});

test("a fully-specified SUPPLIES edge validates", () => {
  const { valid, errors } = validateSupplies(validSupplies());
  assert.equal(valid, true, JSON.stringify(errors));
});

// PRD §5.3: every quantitative SUPPLIES figure MUST carry these.
const REQUIRED_53 = [
  "as_of_date",
  "next_expected_update",
  "confidence",
  "confidence_interval",
  "freshness",
];

for (const field of REQUIRED_53) {
  test(`SUPPLIES missing required field "${field}" is rejected (PRD §5.3)`, () => {
    const edge = validSupplies();
    delete edge[field];
    const { valid } = validateSupplies(edge);
    assert.equal(valid, false, `expected rejection when "${field}" is absent`);
  });
}

for (const field of ["supplier", "customer"]) {
  test(`SUPPLIES missing identity field "${field}" is rejected`, () => {
    const edge = validSupplies();
    delete edge[field];
    assert.equal(validateSupplies(edge).valid, false);
  });
}

test("a gap edge (no trade_value) still validates when quality fields are present", () => {
  const edge = validSupplies();
  edge.trade_value = null;
  edge.supplier_rev_share = null;
  edge.customer_cost_share = null;
  edge.confidence = "estimated";
  edge.freshness = "gap";
  edge.gap = true;
  assert.equal(validateSupplies(edge).valid, true);
});

test("an out-of-enum confidence tier is rejected", () => {
  const edge = validSupplies();
  edge.confidence = "guess";
  assert.equal(validateSupplies(edge).valid, false);
});

test("an unknown field is rejected (additionalProperties: false)", () => {
  const edge = validSupplies();
  edge.expected_upside = 0.2; // forecasting fields are out of scope and unschema'd
  assert.equal(validateSupplies(edge).valid, false);
});

test("validate() rejects an unknown entity name", () => {
  assert.throws(() => validate("NotAnEntity", {}));
});
