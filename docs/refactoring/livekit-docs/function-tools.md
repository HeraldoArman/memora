LiveKit docs › Logic & Structure › Tool definition & use › Function tools

---

# Function tools

> How to design and register custom tools for your agent.

## Overview

The LLM has access to any tools you add to your agent class. This page covers how to define them, call HTTP APIs, use RunContext, handle speech and interruptions, add tools dynamically, and surface errors.

## Tool definition

**Python**:

Add tools to your agent class with the `@function_tool` decorator.

```python
from typing import Any
from livekit.agents import function_tool, Agent, RunContext


class MyAgent(Agent):
    @function_tool()
    async def lookup_weather(
        self,
        context: RunContext,
        location: str,
    ) -> dict[str, Any]:
        """Look up weather information for a given location.

        Args:
            location: The location to look up weather information for.
        """

        return {"weather": "sunny", "temperature_f": 70}
```

---

**Node.js**:

Add tools to your agent class with the `llm.tool` function. This example uses [Zod](https://zod.dev) to make it easy to provide a typed, annotated tool definition.

```typescript
import { voice, llm } from "@livekit/agents";
import { z } from "zod";

const agent = voice.Agent.create({
  instructions: "You are a helpful assistant.",
  tools: [
    llm.tool({
      name: "lookupWeather",
      description: "Look up weather information for a given location.",
      parameters: z.object({
        location: z.string().describe("The location to look up weather information for."),
      }),
      execute: async ({ location }, { ctx }) => {
        return { weather: "sunny", temperatureF: 70 };
      },
    }),
  ],
});
```

You can also define the tool parameters as a [JSON schema](https://json-schema.org/). For example, the tool in the example above can be defined as follows:

```typescript
parameters: {
  type: "object",
  properties: {
    location: {
      type: "string",
      description: "The location to look up weather information for."
    }
  }
}

```

When using Zod, `parameters` must be a `z.object({...})` — other top-level types like `z.discriminatedUnion()` aren't supported because LLM tool-calling APIs require a JSON object. Use optional or nullable fields within the object to model variant behavior. If you use OpenAI with strict mode, prefer `.nullable()` over `.optional()`.

> 💡 **Best practices**
>
> A good tool definition is key to reliable tool use from your LLM. Be specific about what the tool does, when it should or should not be used, what the arguments are for, and what type of return value to expect.

> ℹ️ **Note**
>
> In Node.js, `tool`, `Agent`, and the other `voice` / `llm` exports are available directly from `@livekit/agents` (for example `import { Agent, tool } from '@livekit/agents'`), so the `voice.` / `llm.` prefixes are optional. The namespaced form shown throughout these docs works too.

### Decorator parameters

Tool decorators transform regular functions into tools the LLM can call. The `@function_tool` decorator in Python and `llm.tool()` function in Node.js accept optional parameters to control how a tool is presented to the LLM and when it's available:

**Python**:

| Parameter | Type | Default | Description |
| `name` | `str` | `None` | Override the tool name sent to the LLM. Defaults to the function name. |
| `description` | `str` | `None` | Override the tool description sent to the LLM. Defaults to the function docstring. |
| `raw_schema` | `dict` | `None` | A raw JSON function-calling schema. See [Creating tools from raw schema](#creating-tools-from-raw-schema). |
| `flags` | `ToolFlag` | `ToolFlag.NONE` | Behavior flags that control when the tool is available. See [Tool flags](#tool-flags). |

---

**Node.js**:

| Parameter | Type | Default | Description |
| `name` | `string` | — | The tool name sent to the LLM. Required. |
| `description` | `string` | — | The tool description sent to the LLM. Required. |
| `parameters` | `ZodSchema` or `JSONSchema` | — | Schema for the tool's input parameters. |
| `execute` | `Function` | — | The function called when the LLM invokes the tool. |
| `flags` | `number` | `ToolFlag.NONE` | Behavior flags that control when the tool is available. See [Tool flags](#tool-flags). |

### Tool flags

Tool flags control how a tool behaves at runtime. Set them using the `flags` parameter.

| Flag | Description |
| `NONE` | Default. No special behavior. |
| `IGNORE_ON_ENTER` | Excludes the tool from any `generate_reply` calls made inside the agent's `on_enter` method. |
| `CANCELLABLE` | Lets the LLM cancel the tool while it's running. See [Cancellation](https://docs.livekit.io/agents/logic/tools/async.md#cancellation). |

`IGNORE_ON_ENTER` is useful for tools that shouldn't be called during the agent's initial greeting. For example, a "confirm address" tool should not be available until the user has actually provided an address:

**Python**:

```python
from livekit.agents import Agent, RunContext, function_tool
from livekit.agents.llm.tool_context import ToolFlag


class AddressAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="You help users provide their address.",
        )

    async def on_enter(self) -> None:
        self.session.generate_reply(instructions="Ask the user to provide their address.")

    @function_tool(flags=ToolFlag.IGNORE_ON_ENTER)
    async def confirm_address(self, ctx: RunContext) -> None:
        """Confirm the address provided by the user."""
        # This tool is NOT available during on_enter,
        # preventing the LLM from confirming before the user speaks.
        ...
```

---

**Node.js**:

```typescript
import { voice, llm } from "@livekit/agents";
import { z } from "zod";

const addressAgent = voice.Agent.create({
  instructions: "You help users provide their address.",
  tools: [
    llm.tool({
      name: "confirmAddress",
      description: "Confirm the address provided by the user.",
      flags: llm.ToolFlag.IGNORE_ON_ENTER,
      execute: async (_, { ctx }) => {
        // This tool is NOT available during onEnter,
        // preventing the LLM from confirming before the user speaks.
      },
    }),
  ],
  onEnter(ctx) {
    ctx.session.generateReply({
      instructions: "Ask the user to provide their address.",
    });
  },
});
```

> ℹ️ **Note**
>
> In Node.js, the `tools: [ ... ]` array syntax is preferred and is required for Toolsets and provider tools. For backward compatibility, function tools can also use the legacy object syntax (`tools: { lookupWeather: llm.tool({ ... }) }`); in that form, the object key supplies the tool name internally.

### Tool IDs

Available in:

- [x] Node.js
- [x] Python

Every tool has a stable `id` property that uniquely identifies it. For function tools, the ID defaults to the function name or the explicit `name` parameter:

**Python**:

```python
@function_tool()
async def lookup_weather(context: RunContext, location: str) -> str:
    """Look up weather for a location."""
    return "sunny"


lookup_weather.id  # "lookup_weather"


@function_tool(name="get_weather")
async def my_func(context: RunContext, location: str) -> str:
    return "sunny"


my_func.id  # "get_weather"
```

---

**Node.js**:

```typescript
const lookupWeather = llm.tool({
  name: "lookupWeather",
  description: "Look up weather for a location.",
  parameters: z.object({
    location: z.string(),
  }),
  execute: async ({ location }) => {
    return "sunny";
  },
});

lookupWeather.id; // "lookupWeather"
```

For `FunctionTool` in Node.js, `id === name`. Provider tools also expose IDs so they can be added, removed, and tracked consistently. Use `agent.toolCtx.hasTool(id)` to check whether a tool is currently available. Tool names must be unique across an agent's tool context; registering two different function tools with the same name raises an error.

Tool IDs are used for deduplication when calling `update_tools()` or `updateTools()`. IDs also enable tracking tool changes in conversation history through [`AgentConfigUpdate`](#tracking-configuration-changes).

### Arguments

Tool arguments are automatically inferred from the function signature. Parameter names and type hints are sent to the LLM as part of the tool schema.

To provide additional information about arguments beyond the type hints, include it in the tool description or use `raw_schema` for full control over the [argument schema](#creating-tools-from-raw-schema).

### Return value

The tool return value is automatically converted to a string before being sent to the LLM. The LLM generates a new reply or additional tool calls based on the return value. Return `None` or nothing at all to complete the tool silently without requiring a reply from the LLM.

You can use the return value to initiate a [handoff](https://docs.livekit.io/agents/logic/agents-handoffs.md#tool-handoff) to a different Agent within a workflow. Optionally, you can return a tool result to the LLM as well. The tool call and subsequent LLM reply are completed prior to the handoff.

In Python, return a tuple that includes both the `Agent` instance and the result. If there is no tool result, you can return the new `Agent` instance by itself.

In Node.js, return an instance of `llm.handoff`, which specifies the new `Agent` instance and the tool's return value, if any.

When a handoff occurs, prompt the LLM to inform the user:

**Python**:

```python
@function_tool()
async def my_tool(context: RunContext):
    return SomeAgent(), "Transferring the user to SomeAgent"
```

---

**Node.js**:

```typescript
const myTool = llm.tool({
  name: "myTool",
  description: "Example tool that hands off to another agent",
  execute: async (_, { ctx }) => {
    return llm.handoff({
      agent: createSomeAgent(),
      returns: "Transferring the user to SomeAgent",
    });
  },
});
```

### Structured output

Some LLMs can return structured JSON payloads that define behavior like TTS style separately from the spoken text.

In this example, the LLM streams a JSON object that has both TTS style directives and a spoken response. The TTS style is applied once per message and the spoken response is stripped out for downstream processing. The example contains two code blocks: the format of the JSON and the parsing logic, and an implementation example in an agent workflow.

> 💡 **Tip**
>
> This example uses a `cast` for the LLM and TTS instances. It's specifically built to work with OpenAI (or OpenAI-compatible) APIs. Read more in the [OpenAI Structured Outputs docs](https://developers.openai.com/docs/guides/structured-outputs).

#### Core components: Definition and parsing

This code block has two components: the `ResponseEmotion` schema definition and the `process_structured_output` parsing function.

- `ResponseEmotion`: Defines the structure of the JSON object, with both the TTS style directives (`voice_instructions`) and the spoken `response`.
- `process_structured_output`: Incrementally parses the JSON object, optionally applies a callback for TTS style directives, and only streams the spoken `response`.

```python
class ResponseEmotion(TypedDict):
    voice_instructions: Annotated[
        str,
        Field(..., description="Concise TTS directive for tone, emotion, intonation, and speed"),
    ]
    response: str


async def process_structured_output(
    text: AsyncIterable[str],
    callback: Optional[Callable[[ResponseEmotion], None]] = None,
) -> AsyncIterable[str]:
    last_response = ""
    acc_text = ""
    async for chunk in text:
        acc_text += chunk
        try:
            resp: ResponseEmotion = from_json(acc_text, allow_partial="trailing-strings")
        except ValueError:
            continue

        if callback:
            callback(resp)

        if not resp.get("response"):
            continue

        new_delta = resp["response"][len(last_response) :]
        if new_delta:
            yield new_delta
        last_response = resp["response"]
```

#### Agent method implementation

This agent implementation example overrides default behavior with custom logic using the LLM and TTS nodes: [`llm_node`](https://docs.livekit.io/agents/build/nodes.md#llm_node) and [`tts_node`](https://docs.livekit.io/agents/build/nodes.md#tts_node).

- `llm_node`: Casts the LLM instance to the OpenAI type, streams the output using the `ResponseEmotion` schema, and parses it into structured JSON.
- `tts_node`: Processes the streamed JSON with a callback that applies the TTS style directives (`voice_instructions`), then streams the audio from the `response`.

```python
async def llm_node(
    self, chat_ctx: ChatContext, tools: list[FunctionTool], model_settings: ModelSettings
):
    # not all LLMs support structured output, so we need to cast to the specific LLM type
    llm = cast(openai.LLM, self.llm)
    tool_choice = model_settings.tool_choice if model_settings else NOT_GIVEN
    async with llm.chat(
        chat_ctx=chat_ctx,
        tools=tools,
        tool_choice=tool_choice,
        response_format=ResponseEmotion,
    ) as stream:
        async for chunk in stream:
            yield chunk


async def tts_node(self, text: AsyncIterable[str], model_settings: ModelSettings):
    instruction_updated = False

    def output_processed(resp: ResponseEmotion):
        nonlocal instruction_updated
        if resp.get("voice_instructions") and resp.get("response") and not instruction_updated:
            # when the response isn't empty, we can assume voice_instructions is complete.
            # (if the LLM sent the fields in the right order)
            instruction_updated = True
            logger.info(
                f"Applying TTS instructions before generating response audio: "
                f'"{resp["voice_instructions"]}"'
            )

            tts = cast(openai.TTS, self.tts)
            tts.update_options(instructions=resp["voice_instructions"])

    # process_structured_output strips the TTS instructions and only synthesizes the verbal part
    # of the LLM output
    return Agent.default.tts_node(
        self, process_structured_output(text, callback=output_processed), model_settings
    )
```

### RunContext

Tools include support for a special `context` argument. This contains access to the current `session`, `function_call`, `speech_handle`, and `userdata`. Consult the documentation on [speech](https://docs.livekit.io/agents/build/audio.md) and [state within workflows](https://docs.livekit.io/agents/logic/workflows.md) for more information about how to use these features.

### Using speech in tool calls

You can generate agent speech from within a tool using `session.say()` or `session.generate_reply()` like normal. Use `ctx.wait_for_playout()` to wait for any pre-tool speech to finish.

**Python**:

```python
@function_tool()
async def process_order(self, context: RunContext, order_id: str):
    """Process an order and notify the user."""

    # Generate speech and await it
    await self.session.generate_reply(
        instructions=f"Processing order {order_id}. This may take a moment."
    )

    # Now perform the actual order processing
    result = await process_order_internal(order_id)
    return result
```

---

**Node.js**:

```typescript
const processOrder = llm.tool({
  name: "processOrder",
  description: "Process an order and notify the user.",
  parameters: z.object({
    orderId: z.string(),
  }),
  execute: async ({ orderId }, { ctx }) => {
    // Notify the user and wait for speech to finish
    await ctx.session.generateReply({
      instructions: `Processing order ${orderId}. This may take a moment.`,
    });

    // Now perform the actual order processing
    const result = await processOrderInternal(orderId);
    return result;
  },
});
```

### Interruptions

By default, tools can be interrupted if the user speaks. When interrupted, the tool call is removed from the history and its result is ignored. The tool's code keeps running in the background until it returns. Interrupting discards the result, it doesn't cancel the work.

The default works for most tools. When you do, a tool that blocks the agent's turn (one the agent waits on before responding) gives you two options: handle the interruption (cancel your in-flight work when the user speaks, instead of letting it finish and discarding the result) or prevent it (keep the tool running and the agent speaking for actions that can't be rolled back).

> 💡 **Tip**
>
> For work that takes more than a few seconds, don't block the turn at all. Use an [async tool](https://docs.livekit.io/agents/logic/tools/async.md) so the agent can keep talking and send progress updates while the tool runs.

#### Handle interruptions

To regain control when the user interrupts so you can cancel your in-flight work instead of letting it finish: in Python, call `speech_handle.wait_if_not_interrupted()` to wait for your task, then check `speech_handle.interrupted` to decide whether to return the result or cancel it. In Node.js, use the `abortSignal` passed to `execute`, which is aborted when the tool is interrupted. Forward it to your async work so the work is cancelled too. Both approaches suit a short, read-only lookup whose result the agent needs before it can respond, such as checking an order status or account balance:

**Python**:

```python
import asyncio

from livekit.agents import Agent, RunContext, function_tool


class MyAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="You are a voice agent.")

    @function_tool
    async def get_order_status(self, order_id: str, run_ctx: RunContext) -> str | None:
        """Look up the status of an order when the user asks about it.

        Args:
            order_id: The ID of the order to look up.
        """
        # Start the lookup and wait for it to finish or be interrupted
        wait_for_result = asyncio.ensure_future(self._lookup_order(order_id))
        await run_ctx.speech_handle.wait_if_not_interrupted([wait_for_result])

        if run_ctx.speech_handle.interrupted:
            # The user spoke first: cancel the lookup and skip the reply by returning None.
            # The return value is ignored because the tool no longer exists from the LLM's perspective.
            wait_for_result.cancel()
            return None

        # The lookup finished without interruption: return its result to the LLM
        return wait_for_result.result()

    async def _lookup_order(self, order_id: str) -> str:
        # Simulate a short lookup, such as a database or API query
        await asyncio.sleep(2)
        return f"Order {order_id} shipped and arrives tomorrow"
```

---

**Node.js**:

```typescript
const getOrderStatus = llm.tool({
  name: "getOrderStatus",
  description: "Look up the status of an order when the user asks about it.",
  parameters: z.object({ orderId: z.string() }),
  execute: async ({ orderId }, { abortSignal }) => {
    // The abortSignal is aborted if the user interrupts. Forwarding it to
    // fetch cancels the request instead of letting it run to completion.
    const response = await fetch(`https://api.example.com/orders/${encodeURIComponent(orderId)}`, {
      signal: abortSignal,
    });
    return await response.json();
  },
});
```

In Python, because the work isn't canceled for you, cancel it explicitly when an interruption occurs, as the example does before returning `None`. Otherwise the task runs to completion in the background and produces a result the agent discards. In Node.js, the `abortSignal` is always provided, so you don't need to guard it with `if (abortSignal)`. It is currently aborted only on the main voice pipeline. Tool calls on other paths receive a signal that never aborts.

#### Prevent interruptions

If your tool takes external actions that can't be rolled back, disable interruptions by calling `run_ctx.disallow_interruptions()` (Python) or setting `ctx.speechHandle.allowInterruptions = false` (Node.js) at the start of your tool so user speech won't interrupt the agent's task.

For best practices on providing feedback to the user during long-running tool calls, see the section on [user feedback](https://docs.livekit.io/agents/build/external-data.md#user-feedback) in the External data and RAG guide.

To play a pre-synthesized hold message (such as "let me check that for you") while a tool executes, see [Using cached TTS in a tool call](https://docs.livekit.io/agents/multimodality/audio/customization.md#cached-tts-in-tools). This avoids TTS latency during tool execution and lets you cancel the message early if the external API returns quickly.

### Calling HTTP APIs

Most tools call an external HTTP API to fetch data or trigger actions. In Python, use the shared `aiohttp` session described below. In Node.js, use the built-in `fetch` API.

#### Best practices

Keep these recommendations in mind when calling external APIs from tools:

- **Reuse the shared HTTP session (Python).** Call `utils.http_context.http_session()` to get a shared session that's bound to the job, pools and reuses connections across calls, and closes automatically when the job ends. Outside a job context (tests or scripts), it raises `RuntimeError`. Wrap that code in `async with utils.http_context.open():` or pass your own session. (Node.js needs no equivalent: the global `fetch` already reuses connections.)
- **Disable interruptions for mutating calls.** By default, tools can be [interrupted](#interruptions) by user speech. For read-only requests this is fine — the result is simply discarded. But if your tool writes data (placing an order, scheduling an appointment, sending a message), an interruption can leave the operation partially complete with no way to roll back. Call `context.disallow_interruptions()` (Python) or set `ctx.speechHandle.allowInterruptions = false` (Node.js) at the start of any tool that mutates external state.
- **Raise `ToolError` on failure.** This returns the error message to the LLM so it can inform the user rather than crashing the tool. See [error handling](#error-handling) for more details.
- **Store credentials in environment variables.** For APIs that require authentication, pass headers to your request and load API keys from environment variables rather than hard-coding them.
- **Set timeouts.** External services can be slow or unresponsive. Set explicit timeouts on your HTTP requests to avoid blocking the agent indefinitely. See the section on [user feedback](https://docs.livekit.io/agents/build/external-data.md#user-feedback) for ways to keep the user informed during long-running calls.

#### Example: Fetching data from an API

The following example defines a tool that fetches a realtime stock quote from an external API. The tool takes a ticker symbol as input, makes a GET request, and returns structured data to the LLM:

**Python**:

```python
from livekit.agents import Agent, RunContext, function_tool, utils
from livekit.agents.llm import ToolError


class StockAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="You are a helpful stock market assistant.",
        )

    @function_tool()
    async def get_stock_price(
        self,
        context: RunContext,
        symbol: str,
    ) -> dict:
        """Get the current stock price for a given ticker symbol.

        Args:
            symbol: The stock ticker symbol, for example AAPL or GOOGL.
        """
        url = f"https://livekit-stock-api.vercel.app/api/quote?symbol={symbol}"
        session = utils.http_context.http_session()
        async with session.get(url) as response:
            if response.status != 200:
                raise ToolError(f"Could not fetch stock price for {symbol}.")
            data = await response.json()
            return {
                "symbol": data["symbol"],
                "price": data["price"],
                "volume": data["volume"],
                "latest_trading_day": data["latestTradingDay"],
            }
```

---

**Node.js**:

```typescript
import { voice, llm } from "@livekit/agents";
import { z } from "zod";

const stockAgent = voice.Agent.create({
  instructions: "You are a helpful stock market assistant.",
  tools: [
    llm.tool({
      name: "getStockPrice",
      description: "Get the current stock price for a given ticker symbol.",
      parameters: z.object({
        symbol: z.string().describe("The stock ticker symbol, for example AAPL or GOOGL."),
      }),
      execute: async ({ symbol }) => {
        const url = `https://livekit-stock-api.vercel.app/api/quote?symbol=${encodeURIComponent(symbol)}`;
        const response = await fetch(url);
        if (!response.ok) {
          throw new llm.ToolError(`Could not fetch stock price for ${symbol}.`);
        }
        const data = await response.json();
        return {
          symbol: data.symbol,
          price: data.price,
          volume: data.volume,
          latestTradingDay: data.latestTradingDay,
        };
      },
    }),
  ],
});
```

#### Example: Mutating an external API

When a tool performs a write operation such as placing an order or updating a record, disable interruptions to prevent partial execution:

**Python**:

```python
@function_tool()
async def place_order(
    self,
    context: RunContext,
    item: str,
    quantity: int,
) -> str:
    """Place an order for an item.

    Args:
        item: The item to order.
        quantity: The number of items to order.
    """
    # Prevent user speech from interrupting this tool mid-request
    context.disallow_interruptions()

    session = utils.http_context.http_session()
    async with session.post(
        "https://api.example.com/orders",
        json={"item": item, "quantity": quantity},
        headers={"Authorization": f"Bearer {os.environ['API_KEY']}"},
    ) as response:
        if response.status != 201:
            raise ToolError("Failed to place order. Please try again.")
        data = await response.json()
        return f"Order {data['order_id']} placed successfully."
```

---

**Node.js**:

```typescript
const placeOrder = llm.tool({
  name: "placeOrder",
  description: "Place an order for an item.",
  parameters: z.object({
    item: z.string().describe("The item to order."),
    quantity: z.number().describe("The number of items to order."),
  }),
  execute: async ({ item, quantity }, { ctx }) => {
    // Prevent user speech from interrupting this tool mid-request
    ctx.speechHandle.allowInterruptions = false;

    const response = await fetch("https://api.example.com/orders", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${process.env.API_KEY}`,
      },
      body: JSON.stringify({ item, quantity }),
    });
    if (!response.ok) {
      throw new llm.ToolError("Failed to place order. Please try again.");
    }
    const data = await response.json();
    return `Order ${data.orderId} placed successfully.`;
  },
});
```

### Adding tools dynamically

You can exercise more control over the tools available by setting the `tools` argument directly.

To share a tool between multiple agents, define it outside of their class and then provide it to each. The `RunContext` is especially useful for this purpose to access the current session, agent, and state.

Tools set in the `tools` value are available alongside any registered within the class using the `@function_tool` decorator.

**Python**:

```python
from livekit.agents import function_tool, Agent, RunContext


@function_tool()
async def lookup_user(
    context: RunContext,
    user_id: str,
) -> dict:
    """Look up a user's information by ID."""

    return {"name": "John Doe", "email": "john.doe@example.com"}


class AgentA(Agent):
    def __init__(self):
        super().__init__(
            tools=[lookup_user],
            # ...
        )


class AgentB(Agent):
    def __init__(self):
        super().__init__(
            tools=[lookup_user],
            # ...
        )
```

---

**Node.js**:

```typescript
import { voice, llm } from "@livekit/agents";
import { z } from "zod";

const lookupUser = llm.tool({
  name: "lookupUser",
  description: "Look up a user's information by ID.",
  parameters: z.object({
    userId: z.string(),
  }),
  execute: async ({ userId }, { ctx }) => {
    return { name: "John Doe", email: "john.doe@example.com" };
  },
});

const agentA = voice.Agent.create({
  tools: [lookupUser],
  // ...
});

const agentB = voice.Agent.create({
  tools: [lookupUser],
  // ...
});
```

Use `agent.update_tools()` (Python) or `agent.updateTools()` (Node.js) to update available tools after creating an agent. This replaces _all_ tools, including those registered automatically within the agent class. To reference existing tools before replacement, access `agent.tools` in Python or `agent.toolCtx.tools` in Node.js:

**Python**:

```python
# add a tool
await agent.update_tools(agent.tools + [tool_a])

# remove a tool
await agent.update_tools([t for t in agent.tools if t.id != tool_a.id])

# replace all tools
await agent.update_tools([tool_a, tool_b])
```

---

**Node.js**:

```typescript
// add a tool
await agent.updateTools([...agent.toolCtx.tools, toolA]);

// remove a tool
await agent.updateTools(agent.toolCtx.tools.filter((t) => t.id !== "toolA"));

// replace all tools
await agent.updateTools([toolA, toolB]);
```

### Creating tools programmatically

To create a tool on the fly, use `function_tool` as a function rather than as a decorator. You must supply a name, description, and callable function. This is useful to compose specific tools based on the same underlying code or load them from external sources such as a database or Model Context Protocol (MCP) server.

In the following example, the app has a single function to set any user profile field but gives the agent one tool per field for improved reliability:

**Python**:

```python
from livekit.agents import function_tool, RunContext


class Assistant(Agent):
    def _set_profile_field_func_for(self, field: str):
        async def set_value(context: RunContext, value: str):
            # custom logic to set input
            return f"field {field} was set to {value}"

        return set_value

    def __init__(self):
        super().__init__(
            tools=[
                function_tool(
                    self._set_profile_field_func_for("phone"),
                    name="set_phone_number",
                    description="Call this function when user has provided their phone number.",
                ),
                function_tool(
                    self._set_profile_field_func_for("email"),
                    name="set_email",
                    description="Call this function when user has provided their email.",
                ),
                # ... other tools ...
            ],
            # instructions, etc ...
        )
```

---

**Node.js**:

```typescript
import { voice, llm } from "@livekit/agents";
import { z } from "zod";

function createSetProfileFieldTool(name: string, field: string) {
  return llm.tool({
    name,
    description: `Call this function when user has provided their ${field}.`,
    parameters: z.object({
      value: z.string().describe(`The ${field} value to set`),
    }),
    execute: async ({ value }, { ctx }) => {
      // custom logic to set input
      return `field ${field} was set to ${value}`;
    },
  });
}

const assistant = voice.Agent.create({
  tools: [
    createSetProfileFieldTool("setPhoneNumber", "phone number"),
    createSetProfileFieldTool("setEmail", "email"),
    // ... other tools ...
  ],
  // instructions, etc ...
});
```

### Creating tools from raw schema

For advanced use cases, you can create tools directly from a [raw function calling schema](https://developers.openai.com/docs/guides/function-calling?api-mode=responses). This is useful when integrating with existing function definitions, loading tools from external sources, or working with schemas that don't map cleanly to Python function signatures.

Use the `raw_schema` parameter in the `@function_tool` decorator to provide the full function schema:

**Python**:

```python
from livekit.agents import function_tool, RunContext

raw_schema = {
    "type": "function",
    "name": "get_weather",
    "description": "Get weather for a given location.",
    "parameters": {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City and country e.g. New York"}
        },
        "required": ["location"],
        "additionalProperties": False,
    },
}


@function_tool(raw_schema=raw_schema)
async def get_weather(raw_arguments: dict[str, object], context: RunContext):
    location = raw_arguments["location"]

    # Your implementation here
    return f"The weather of {location} is ..."
```

---

**Node.js**:

```typescript
import { voice, llm } from "@livekit/agents";

const rawSchema = {
  type: "object",
  properties: {
    location: {
      type: "string",
      description: "City and country e.g. New York",
    },
  },
  required: ["location"],
  additionalProperties: false,
};

const getWeather = llm.tool({
  name: "getWeather",
  description: "Get weather for a given location.",
  parameters: rawSchema,
  execute: async ({ location }, { ctx }) => {
    // Your implementation here
    return `The weather of ${location} is ...`;
  },
});
```

When using raw schemas, function parameters are passed to your handler as a dictionary named `raw_arguments`. You can extract values from this dictionary using the parameter names defined in your schema.

You can also create tools programmatically using `function_tool` as a function with raw schemas:

**Python**:

```python
from livekit.agents import function_tool


def create_database_tool(table_name: str, operation: str):
    schema = {
        "type": "function",
        "name": f"{operation}_{table_name}",
        "description": f"Perform {operation} operation on {table_name} table",
        "parameters": {
            "type": "object",
            "properties": {
                "record_id": {"type": "string", "description": f"ID of the record to {operation}"}
            },
            "required": ["record_id"],
        },
    }

    async def handler(raw_arguments: dict[str, object], context: RunContext):
        record_id = raw_arguments["record_id"]
        # Perform database operation
        return f"Performed {operation} on {table_name} for record {record_id}"

    return function_tool(handler, raw_schema=schema)


# Create tools dynamically
user_tools = [
    create_database_tool("users", "read"),
    create_database_tool("users", "update"),
    create_database_tool("users", "delete"),
]


class DataAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="You are a database assistant.",
            tools=user_tools,
        )
```

---

**Node.js**:

```typescript
import { voice, llm } from "@livekit/agents";
import { z } from "zod";

function createDatabaseTool(name: string, tableName: string, operation: string) {
  return llm.tool({
    name,
    description: `Perform ${operation} operation on ${tableName} table`,
    parameters: z.object({
      recordId: z.string().describe(`ID of the record to ${operation}`),
    }),
    execute: async ({ recordId }, { ctx }) => {
      // Perform database operation
      return `Performed ${operation} on ${tableName} for record ${recordId}`;
    },
  });
}

// Create tools dynamically
const dataAgent = voice.Agent.create({
  instructions: "You are a database assistant.",
  tools: [
    createDatabaseTool("readUsers", "users", "read"),
    createDatabaseTool("updateUsers", "users", "update"),
    createDatabaseTool("deleteUsers", "users", "delete"),
  ],
});
```

## Toolsets

To bundle related tools under a single ID and add or remove them as a group, use a [Toolset](https://docs.livekit.io/agents/logic/tools/toolsets.md). Python also includes the built-in [MCPToolset](https://docs.livekit.io/agents/logic/tools/mcp.md) and beta `ToolSearchToolset` and `ToolProxyToolset` for [dynamic tool discovery](https://docs.livekit.io/agents/logic/tools/toolsets.md#dynamic-tool-discovery), which are built on this primitive.

## Tracking configuration changes

Available in:

- [x] Node.js
- [x] Python

When an agent starts with configured tools or instructions, or when you update an agent's tools or instructions at runtime, an `AgentConfigUpdate` is automatically added to the conversation history. This record includes:

- **`instructions`**: The updated instructions, if changed.
- **`tools_added` / `toolsAdded`**: Names of any tools that were added.
- **`tools_removed` / `toolsRemoved`**: Names of any tools that were removed.

**Python**:

```python
# Tool changes are tracked automatically
await agent.update_tools([new_tool_a, new_tool_b])

# Instruction changes are also tracked
await agent.update_instructions("You are now a support agent.")
```

---

**Node.js**:

```typescript
// Tool changes are tracked automatically
await agent.updateTools([newToolA, newToolB]);

// Instruction changes are also tracked
await agent.updateInstructions("You are now a support agent.");
```

This gives the LLM visibility into configuration changes, which is useful in [multi-agent workflows](https://docs.livekit.io/agents/logic/workflows.md) where agents switch and have different tool sets. For example, after the calls above, the conversation history includes records like:

**Python**:

```python
# agent.chat_ctx.items
[
    ChatMessage(role="user", content=["What's the weather?"]),
    ChatMessage(role="assistant", content=["Let me check..."]),
    AgentConfigUpdate(
        tools_added=["new_tool_a", "new_tool_b"],
        tools_removed=["old_tool"],
    ),
    AgentConfigUpdate(
        instructions="You are now a support agent.",
    ),
]
```

---

**Node.js**:

```typescript
const configUpdates = session.history.items.filter((item) => item.type === "agent_config_update");

for (const item of configUpdates) {
  console.log(item.toolsAdded, item.toolsRemoved, item.instructions);
}
```

To exclude configuration updates when copying or serializing conversation history, use `exclude_config_update` (Python) or `excludeConfigUpdate` (Node.js):

**Python**:

```python
ctx_copy = chat_ctx.copy(exclude_config_update=True)
```

---

**Node.js**:

```typescript
const ctxCopy = chatCtx.copy({ excludeConfigUpdate: true });
```

## Error handling

Raise the `ToolError` exception to return an error to the LLM in place of a response. You can include a custom message to describe the error and/or recovery options.

**Python**:

```python
@function_tool()
async def lookup_weather(
    self,
    context: RunContext,
    location: str,
) -> dict:
    if location == "mars":
        raise ToolError(
            "This location is coming soon. Please join our mailing list to stay updated."
        )
    else:
        return {"weather": "sunny", "temperature_f": 70}
```

---

**Node.js**:

```typescript
import { llm } from "@livekit/agents";
import { z } from "zod";

const lookupWeather = llm.tool({
  name: "lookupWeather",
  description: "Look up weather information for a location",
  parameters: z.object({
    location: z.string().describe("The location to get weather for"),
  }),
  execute: async ({ location }, { ctx }) => {
    if (location === "mars") {
      throw new llm.ToolError(
        "This location is coming soon. Please join our mailing list to stay updated.",
      );
    }
    return { weather: "sunny", temperatureF: 70 };
  },
});
```

If a tool raises an unexpected exception, the framework returns a generic internal-error message to the LLM instead, so server-side details don't leak into the conversation. It still logs the original error for you to debug.

If the LLM calls a tool with arguments that fail parsing or schema validation, the framework forwards the failure to the LLM as a `ToolError`, including the tool name and the validator's message. The LLM can correct the call and retry without any handling on your part.

---

This document was rendered at 2026-08-12T04:22:35.490Z.
For the latest version of this document, see [https://docs.livekit.io/agents/logic/tools/definition.md](https://docs.livekit.io/agents/logic/tools/definition.md).

To explore all LiveKit documentation, see [llms.txt](https://docs.livekit.io/llms.txt).
