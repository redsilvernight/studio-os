/**
 * The Dashboard side of the `studio.local/v1` boundary.
 *
 * Everything here is derived from the generated P1 export: the closed command
 * table, the bundled schemas and the types. The Dashboard builds requests and
 * checks answers through these helpers only, and fails closed: an answer that
 * does not validate, or one that speaks another protocol, is never returned as
 * data.
 */
import {
  LOCAL_COMMANDS,
  LOCAL_PROTOCOL,
  LOCAL_SCHEMAS,
  type BridgeCommand,
  type BridgeErrorMessage,
  type BridgeRequest,
  type BridgeResponse,
  type LocalCommandSpec,
} from "./generated/local-contracts.generated";
import { validateSchema } from "./schemaValidator";

export { LOCAL_PROTOCOL };
export type { BridgeCommand, BridgeErrorMessage, BridgeRequest, BridgeResponse };

export type BridgeAnswer =
  | { ok: true; command: BridgeCommand; response: BridgeResponse }
  | { ok: false; error: BridgeErrorMessage["error"] };

const SPECS = new Map<string, LocalCommandSpec>(LOCAL_COMMANDS.map((c) => [c.command, c]));

/** The frozen list of commands the P1 contract allows. */
export function knownCommands(): string[] {
  return [...SPECS.keys()];
}

export function commandSpec(command: string): LocalCommandSpec | undefined {
  return SPECS.get(command);
}

let counter = 0;
function nextId(prefix: string): string {
  counter += 1;
  return `${prefix}-${Date.now().toString(36)}-${counter}`;
}

/** Build a P1 `BridgeRequest`; throws for a command outside the allowlist. */
export function buildRequest(
  command: BridgeCommand,
  payload: Record<string, unknown> = {},
  now: Date = new Date(),
): BridgeRequest {
  const spec = SPECS.get(command);
  if (!spec) throw new Error(`command not in the studio.local/v1 allowlist: ${command}`);
  const request: BridgeRequest = {
    kind: "request",
    protocol: LOCAL_PROTOCOL,
    message_id: nextId("dash-req"),
    correlation_id: nextId("dash-cor"),
    sent_at: now.toISOString().replace(/\.\d{3}Z$/, "Z"),
    command,
    payload,
    deadline_ms: null,
  };
  const size = new TextEncoder().encode(JSON.stringify(request)).length;
  if (size > spec.max_request_bytes) throw new Error(`request exceeds ${spec.max_request_bytes} bytes`);
  const issues = validateSchema(LOCAL_SCHEMAS.BridgeRequest, request);
  if (issues.length) throw new Error(`invalid request: ${issues[0]?.path} ${issues[0]?.message}`);
  // The payload must match the P1 request model of this command.
  const payloadSchema = LOCAL_SCHEMAS[spec.request];
  if (!payloadSchema) throw new Error(`no schema bundled for ${spec.request}`);
  const payloadIssues = validateSchema(payloadSchema, payload);
  if (payloadIssues.length) {
    throw new Error(`invalid payload: ${payloadIssues[0]?.path} ${payloadIssues[0]?.message}`);
  }
  return request;
}

function invalidAnswer(message: string): BridgeAnswer {
  return {
    ok: false,
    error: {
      code: "internal_error",
      component: "bridge",
      message,
      retryable: false,
      correlation_id: null,
      details: {},
    },
  };
}

/**
 * Validate what came back over the bridge against the request it answers.
 * Never returns unchecked data: wrong protocol, wrong correlation, wrong
 * command or a payload that does not match the P1 model all become errors.
 */
export function parseAnswer(request: BridgeRequest, raw: unknown): BridgeAnswer {
  const kind = (raw as { kind?: unknown } | null)?.kind;
  if (kind === "error") {
    const issues = validateSchema(LOCAL_SCHEMAS.BridgeErrorMessage, raw);
    if (issues.length) return invalidAnswer("The local peer sent a malformed error.");
    const err = raw as BridgeErrorMessage;
    if (err.protocol !== LOCAL_PROTOCOL) return invalidAnswer("The local peer speaks another protocol.");
    return { ok: false, error: err.error };
  }
  if (kind !== "response") return invalidAnswer("The local peer sent an unknown message kind.");
  if (validateSchema(LOCAL_SCHEMAS.BridgeResponse, raw).length) {
    return invalidAnswer("The local peer sent a malformed response.");
  }
  const response = raw as BridgeResponse;
  if (response.protocol !== LOCAL_PROTOCOL) return invalidAnswer("The local peer speaks another protocol.");
  if (
    response.correlation_id !== request.correlation_id ||
    response.request_id !== request.message_id ||
    response.command !== request.command
  ) {
    return invalidAnswer("The local peer answered a different request.");
  }
  const spec = SPECS.get(response.command);
  const model = spec?.response;
  const schema = model ? LOCAL_SCHEMAS[model] : undefined;
  // Only models bundled for the commands the Dashboard actually uses can be
  // checked; anything else is refused instead of trusted.
  if (!schema) return invalidAnswer("No schema is bundled to validate this answer.");
  if (validateSchema(schema, response.payload).length) {
    return invalidAnswer("The local peer sent a payload that violates the contract.");
  }
  return { ok: true, command: response.command, response };
}
