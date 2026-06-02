// Type surface for ./validate.mjs (runtime validators). The validators are
// canonical-schema-driven (ajv); these types describe their shape for consumers.

/** A single ajv validation error (subset of ajv's ErrorObject). */
export interface ValidationError {
  instancePath: string;
  schemaPath: string;
  keyword: string;
  message?: string;
  params: Record<string, unknown>;
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
}

/** The canonical ValueGraph JSON Schema document (PRD §5). */
export declare const schema: Record<string, unknown>;

/** Names of every entity ($def) defined by the canonical schema. */
export declare const ENTITY_NAMES: readonly string[];

/** Validate `data` against the named entity ($def) in the canonical schema. */
export declare function validate(
  entity: string,
  data: unknown,
): ValidationResult;

/** Validate a SUPPLIES edge (core v1 relationship; PRD §5.3 required figures). */
export declare function validateSupplies(data: unknown): ValidationResult;
