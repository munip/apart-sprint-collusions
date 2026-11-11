import { createServer } from "node:http";
import { randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";
import { getAuthToken, init } from "@heyputer/puter.js/src/init.cjs";

const MAX_BODY_BYTES = 1_000_000;

export function toPuterOptions(body, testMode) {
  const options = {
    model: body.model,
    fallback: true,
    normalize: true,
    stream: false,
  };
  if (typeof body.max_tokens === "number") options.max_tokens = body.max_tokens;
  if (typeof body.temperature === "number") options.temperature = body.temperature;
  if (typeof body.top_p === "number") options.top_p = body.top_p;
  if (Array.isArray(body.tools)) options.tools = body.tools;
  if (body.tool_choice !== undefined) options.toolChoice = body.tool_choice;
  return { messages: body.messages, testMode, options };
}

export function toOpenAICompletion(result, requestedModel) {
  const message = result?.message;
  if (!message || typeof message !== "object") {
    throw new TypeError("Puter returned a response without a message");
  }

  const rawContent = message.content;
  const content = typeof rawContent === "string" || rawContent === null
    ? rawContent
    : Array.isArray(rawContent)
      ? rawContent.filter((part) => part?.type === "text").map((part) => part.text).join("")
      : null;
  const toolCalls = Array.isArray(message.tool_calls) ? message.tool_calls : undefined;
  const usage = result.usage ?? {};
  const details = result.usageDetails ?? {};
  const promptTokens = usage.prompt_tokens ?? usage.input_tokens ?? details.inputTokens ?? 0;
  const completionTokens = usage.completion_tokens ?? usage.output_tokens ?? details.outputTokens ?? 0;

  return {
    id: result.id ?? `puter-${randomUUID()}`,
    object: "chat.completion",
    created: Math.floor(Date.now() / 1000),
    model: result.model ?? requestedModel,
    choices: [{
      index: 0,
      message: {
        role: message.role ?? "assistant",
        content,
        ...(toolCalls ? { tool_calls: toolCalls } : {}),
      },
      finish_reason: result.finish_reason ?? (toolCalls?.length ? "tool_calls" : "stop"),
    }],
    usage: {
      prompt_tokens: promptTokens,
      completion_tokens: completionTokens,
      total_tokens: usage.total_tokens ?? promptTokens + completionTokens,
    },
  };
}

async function readJsonBody(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) {
      const error = new Error("Request body is too large");
      error.statusCode = 413;
      throw error;
    }
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    const error = new Error("Invalid JSON request body");
    error.statusCode = 400;
    throw error;
  }
}

function sendJson(response, statusCode, body) {
  response.writeHead(statusCode, {
    "content-type": "application/json",
    "cache-control": "no-store",
  });
  response.end(JSON.stringify(body));
}

function statusCodeFor(error) {
  const status = error?.statusCode ?? error?.response?.status;
  return Number.isInteger(status) && status >= 400 && status <= 599 ? status : 502;
}

export async function startGateway({
  port = Number(process.env.PUTER_PORT ?? 3800),
  testMode = process.env.PUTER_TEST_MODE !== "0",
  sdk = { getAuthToken, init },
} = {}) {
  if (!testMode && process.env.PUTER_ALLOW_BILLABLE_USAGE !== "1") {
    throw new Error("Set PUTER_ALLOW_BILLABLE_USAGE=1 to enable non-test Puter requests");
  }

  const token = process.env.PUTER_AUTH_TOKEN || await sdk.getAuthToken();
  if (typeof token !== "string" || !token) {
    throw new Error("Puter browser authentication did not return an auth token");
  }
  const puter = sdk.init(token);

  const server = createServer(async (request, response) => {
    if (request.method === "GET" && request.url === "/health") {
      return sendJson(response, 200, { status: "ready", test_mode: testMode });
    }
    if (request.method !== "POST" || request.url !== "/v1/chat/completions") {
      return sendJson(response, 404, { error: { message: "Not found", type: "not_found" } });
    }
    if (request.headers.authorization !== "Bearer puter-local") {
      return sendJson(response, 401, { error: { message: "Gateway authorization required", type: "authentication_error" } });
    }
    if (!request.headers["content-type"]?.toLowerCase().startsWith("application/json")) {
      return sendJson(response, 415, { error: { message: "JSON content type required", type: "invalid_request_error" } });
    }
    const origin = request.headers.origin;
    if (origin && !/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(origin)) {
      return sendJson(response, 403, { error: { message: "Local origin required", type: "forbidden" } });
    }

    try {
      const body = await readJsonBody(request);
      if (!Array.isArray(body.messages) || !body.messages.length || typeof body.model !== "string") {
        return sendJson(response, 400, { error: { message: "model and messages are required", type: "invalid_request_error" } });
      }
      if (body.stream) {
        return sendJson(response, 400, { error: { message: "Streaming is not supported by this local bridge", type: "invalid_request_error" } });
      }
      const { messages, options } = toPuterOptions(body, testMode);
      const result = await puter.ai.chat(messages, testMode, options);
      return sendJson(response, 200, toOpenAICompletion(result, body.model));
    } catch (error) {
      const status = statusCodeFor(error);
      console.error(`Puter request failed (${status}, ${error?.name ?? "Error"})`);
      return sendJson(response, status, {
        error: {
          message: status === 429 ? "Puter rate limit reached" : "Puter request failed",
          type: status === 429 ? "rate_limit_error" : "upstream_error",
        },
      });
    }
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", resolve);
  });
  const boundPort = server.address().port;
  console.log(`Puter local gateway ready on http://127.0.0.1:${boundPort}/v1 (${testMode ? "test mode" : "billable mode"})`);
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  startGateway().catch((error) => {
    console.error(`Puter gateway did not start (${error?.name ?? "Error"})`);
    process.exitCode = 1;
  });
}
