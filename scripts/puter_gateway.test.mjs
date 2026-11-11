import test from "node:test";
import assert from "node:assert/strict";

import { startGateway, toOpenAICompletion, toPuterOptions } from "./puter_gateway.mjs";

test("Puter request mapping preserves tools and uses test mode", () => {
  const tool = { type: "function", function: { name: "done", parameters: { type: "object" } } };
  const result = toPuterOptions({
    model: "openai/gpt-5.4-nano",
    messages: [{ role: "user", content: "hi" }],
    tools: [tool],
    tool_choice: "auto",
    max_tokens: 32,
    temperature: 0,
  }, true);

  assert.deepEqual(result, {
    messages: [{ role: "user", content: "hi" }],
    testMode: true,
    options: {
      model: "openai/gpt-5.4-nano",
      fallback: true,
      normalize: true,
      stream: false,
      max_tokens: 32,
      temperature: 0,
      tools: [tool],
      toolChoice: "auto",
    },
  });
});

test("Puter response mapping returns OpenAI chat completion and usage", () => {
  const completion = toOpenAICompletion({
    model: "openai/gpt-5.4-nano",
    message: { role: "assistant", content: "ok" },
    usageDetails: { inputTokens: 7, outputTokens: 3 },
  }, "openai/gpt-5.4-nano");

  assert.equal(completion.object, "chat.completion");
  assert.deepEqual(completion.choices[0].message, { role: "assistant", content: "ok" });
  assert.deepEqual(completion.usage, { prompt_tokens: 7, completion_tokens: 3, total_tokens: 10 });
});

test("Puter tool calls retain OpenAI tool-call shape", () => {
  const toolCall = { id: "call_1", type: "function", function: { name: "done", arguments: "{}" } };
  const completion = toOpenAICompletion({
    message: { role: "assistant", content: null, tool_calls: [toolCall] },
  }, "openai/gpt-5.4-nano");

  assert.deepEqual(completion.choices[0].message.tool_calls, [toolCall]);
  assert.equal(completion.choices[0].finish_reason, "tool_calls");
});

test("local gateway serves health and maps a chat completion", async () => {
  const received = [];
  const server = await startGateway({
    port: 0,
    testMode: true,
    sdk: {
      getAuthToken: async () => "test-only",
      init: () => ({
        ai: {
          chat: async (messages, testMode, options) => {
            received.push({ messages, testMode, options });
            return { message: { role: "assistant", content: "test response" } };
          },
        },
      }),
    },
  });
  const address = server.address();

  try {
    const health = await fetch(`http://127.0.0.1:${address.port}/health`);
    assert.deepEqual(await health.json(), { status: "ready", test_mode: true });

    const response = await fetch(`http://127.0.0.1:${address.port}/v1/chat/completions`, {
      method: "POST",
      headers: {
        authorization: "Bearer puter-local",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: "openai/gpt-5.4-nano",
        messages: [{ role: "user", content: "reply briefly" }],
        max_tokens: 8,
      }),
    });
    const body = await response.json();

    assert.equal(response.status, 200);
    assert.equal(body.choices[0].message.content, "test response");
    assert.equal(received[0].testMode, true);
    assert.equal(received[0].options.model, "openai/gpt-5.4-nano");
  } finally {
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});

test("billable mode requires explicit opt-in", async () => {
  const previous = process.env.PUTER_ALLOW_BILLABLE_USAGE;
  delete process.env.PUTER_ALLOW_BILLABLE_USAGE;
  try {
    await assert.rejects(
      startGateway({ testMode: false, sdk: { getAuthToken: async () => "unused", init: () => ({}) } }),
      /PUTER_ALLOW_BILLABLE_USAGE=1/,
    );
  } finally {
    if (previous === undefined) delete process.env.PUTER_ALLOW_BILLABLE_USAGE;
    else process.env.PUTER_ALLOW_BILLABLE_USAGE = previous;
  }
});
