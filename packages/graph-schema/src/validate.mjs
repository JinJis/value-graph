// Runtime schema validation for ValueGraph entities (Node side).
//
// Loads the canonical JSON Schema (the single source of truth) and exposes ajv
// validators. This is a Node module (reads the schema from disk); the browser-safe
// surface of @valuegraph/graph-schema is the generated *types* (main entry), which
// are erased at compile time. Import validators explicitly from
// "@valuegraph/graph-schema/validate".
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const schemaPath = fileURLToPath(
  new URL("../schema/valuegraph.schema.json", import.meta.url),
);

/** The canonical ValueGraph JSON Schema (PRD §5). */
export const schema = JSON.parse(readFileSync(schemaPath, "utf8"));

/** Names of every entity ($def) defined by the canonical schema. */
export const ENTITY_NAMES = Object.freeze(Object.keys(schema.$defs));

const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);
ajv.addSchema(schema);

function validatorFor(entity) {
  const validator = ajv.getSchema(`${schema.$id}#/$defs/${entity}`);
  if (!validator) {
    throw new Error(`Unknown ValueGraph schema entity: "${entity}"`);
  }
  return validator;
}

/**
 * Validate `data` against the named entity ($def) in the canonical schema.
 * @param {string} entity e.g. "SuppliesEdge", "Company", "Claim"
 * @param {unknown} data
 * @returns {{ valid: boolean, errors: object[] }}
 */
export function validate(entity, data) {
  const validator = validatorFor(entity);
  const valid = validator(data);
  return { valid, errors: valid ? [] : (validator.errors ?? []) };
}

/**
 * Validate a SUPPLIES edge — the core v1 relationship. Enforces the PRD §5.3
 * required figures (as_of_date, next_expected_update, confidence,
 * confidence_interval, freshness) in addition to the supplier/customer identity.
 * @param {unknown} data
 * @returns {{ valid: boolean, errors: object[] }}
 */
export function validateSupplies(data) {
  return validate("SuppliesEdge", data);
}
