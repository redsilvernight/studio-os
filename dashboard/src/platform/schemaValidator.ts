/**
 * Minimal JSON Schema validator for the keyword subset the P1 export uses
 * (type, enum, const, pattern, min/max*, items, properties, required,
 * additionalProperties, anyOf, $ref to local $defs, format date-time/uuid).
 *
 * It validates the generated bridge schemas at the Desktop boundary. An
 * unsupported keyword or an unresolved $ref throws: this validator fails
 * closed rather than silently accepting what it cannot check.
 */

export interface SchemaIssue {
  path: string;
  message: string;
}

type Schema = Record<string, unknown>;

const KNOWN = new Set([
  "$defs",
  "$ref",
  "additionalProperties",
  "anyOf",
  "const",
  "default",
  "description",
  "enum",
  "format",
  "items",
  "maxItems",
  "maxLength",
  "maximum",
  "minItems",
  "minLength",
  "minimum",
  "pattern",
  "properties",
  "required",
  "title",
  "type",
]);

const DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/;
const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function typeMatches(type: string, value: unknown): boolean {
  switch (type) {
    case "string":
      return typeof value === "string";
    case "integer":
      return typeof value === "number" && Number.isInteger(value);
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    case "boolean":
      return typeof value === "boolean";
    case "null":
      return value === null;
    case "array":
      return Array.isArray(value);
    case "object":
      return isObject(value);
    default:
      throw new Error(`unsupported schema type: ${type}`);
  }
}

function resolveRef(root: Schema, ref: string): Schema {
  const m = /^#\/\$defs\/([A-Za-z0-9_]+)$/.exec(ref);
  const defs = root.$defs;
  const target = m && isObject(defs) ? defs[m[1] as string] : undefined;
  if (!isObject(target)) throw new Error(`unresolved $ref: ${ref}`);
  return target;
}

function check(root: Schema, schema: Schema, value: unknown, path: string, out: SchemaIssue[]): void {
  for (const key of Object.keys(schema)) {
    if (!KNOWN.has(key)) throw new Error(`unsupported schema keyword: ${key}`);
  }
  if (typeof schema.$ref === "string") {
    check(root, resolveRef(root, schema.$ref), value, path, out);
    return;
  }
  if (Array.isArray(schema.anyOf)) {
    const branches = schema.anyOf as Schema[];
    const ok = branches.some((b) => {
      const sub: SchemaIssue[] = [];
      check(root, b, value, path, sub);
      return sub.length === 0;
    });
    if (!ok) out.push({ path, message: "matches none of the allowed shapes" });
    return;
  }
  if ("const" in schema && value !== schema.const) {
    out.push({ path, message: `must equal ${JSON.stringify(schema.const)}` });
    return;
  }
  if (Array.isArray(schema.enum) && !schema.enum.includes(value)) {
    out.push({ path, message: "is not one of the allowed values" });
    return;
  }
  if (typeof schema.type === "string" && !typeMatches(schema.type, value)) {
    out.push({ path, message: `must be of type ${schema.type}` });
    return;
  }
  if (typeof value === "string") {
    if (typeof schema.minLength === "number" && value.length < schema.minLength) {
      out.push({ path, message: "is too short" });
    }
    if (typeof schema.maxLength === "number" && value.length > schema.maxLength) {
      out.push({ path, message: "is too long" });
    }
    if (typeof schema.pattern === "string" && !new RegExp(schema.pattern, "u").test(value)) {
      out.push({ path, message: "does not match the required pattern" });
    }
    if (schema.format === "date-time" && !DATE_TIME.test(value)) {
      out.push({ path, message: "is not an RFC 3339 date-time" });
    }
    if (schema.format === "uuid" && !UUID.test(value)) {
      out.push({ path, message: "is not a UUID" });
    }
  }
  if (typeof value === "number") {
    if (typeof schema.minimum === "number" && value < schema.minimum) {
      out.push({ path, message: `must be >= ${schema.minimum}` });
    }
    if (typeof schema.maximum === "number" && value > schema.maximum) {
      out.push({ path, message: `must be <= ${schema.maximum}` });
    }
  }
  if (Array.isArray(value)) {
    if (typeof schema.minItems === "number" && value.length < schema.minItems) {
      out.push({ path, message: "has too few items" });
    }
    if (typeof schema.maxItems === "number" && value.length > schema.maxItems) {
      out.push({ path, message: "has too many items" });
    }
    if (isObject(schema.items)) {
      const items = schema.items;
      value.forEach((item, i) => check(root, items, item, `${path}[${i}]`, out));
    }
  }
  if (isObject(value)) {
    const props = isObject(schema.properties) ? schema.properties : {};
    const required = Array.isArray(schema.required) ? (schema.required as string[]) : [];
    for (const key of required) {
      if (!(key in value)) out.push({ path: `${path}.${key}`, message: "is required" });
    }
    for (const [key, item] of Object.entries(value)) {
      const sub = props[key];
      if (isObject(sub)) {
        check(root, sub, item, `${path}.${key}`, out);
      } else if (schema.additionalProperties === false) {
        out.push({ path: `${path}.${key}`, message: "is not an allowed field" });
      } else if (isObject(schema.additionalProperties)) {
        check(root, schema.additionalProperties, item, `${path}.${key}`, out);
      }
    }
  }
}

/** Validate `value` against the bundled schema `root`. Empty result = valid. */
export function validateSchema(root: unknown, value: unknown): SchemaIssue[] {
  if (!isObject(root)) throw new Error("schema must be an object");
  const out: SchemaIssue[] = [];
  check(root, root, value, "$", out);
  return out;
}
