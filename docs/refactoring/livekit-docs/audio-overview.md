LiveKit docs › Multimodality › Speech & audio › Overview

---

# Agent speech and audio

> Speech and audio capabilities for LiveKit agents.

## Overview

Speech capabilities are a core feature of LiveKit agents, enabling them to interact with users through voice. This guide covers the various speech features and functionalities available for agents.

LiveKit Agents provide a unified interface for controlling agents using both the STT-LLM-TTS pipeline and realtime models.

## In this section

This page covers core speech control features like initiating speech, managing speech handles, and handling interruptions. The following pages in this section cover additional topics:

| Topic | Description |
| [Audio customization](https://docs.livekit.io/agents/multimodality/audio/customization.md) | Cache TTS responses, customize pronunciation, and adjust speech volume. |
| [Background audio](https://docs.livekit.io/agents/multimodality/audio/background-audio.md) | Add ambient sounds, thinking sounds, and on-demand audio playback. |
| [Custom voices](https://docs.livekit.io/agents/models/tts/custom-voices.md) | Create voice clones from short audio samples for use with supported TTS providers. |
| [Wakeword detection](https://docs.livekit.io/agents/multimodality/audio/wakeword.md) | Detect a spoken trigger phrase on the client to activate the agent hands-free. |

To learn more and see usage examples, see the following topics:

- **[Text-to-speech (TTS)](https://docs.livekit.io/agents/models/tts.md)**: TTS is a synthesis process that converts text into audio, giving AI agents a "voice."

- **[Speech-to-speech](https://docs.livekit.io/agents/models/realtime.md)**: Multimodal, realtime APIs can understand speech input and generate speech output directly.

## Instant connect

The instant connect feature reduces perceived connection time by capturing microphone input before the agent connection is established. This pre-connect audio buffer sends speech as context to the agent, avoiding awkward gaps between a user's connection and their ability to interact with an agent.

Microphone capture begins locally while the agent is connecting. Once the connection is established, the speech and metadata is sent over a byte stream with the topic `lk.agent.pre-connect-audio-buffer`. If no agent connects before timeout, the buffer is discarded.

You can enable this feature using `withPreconnectAudio`:

**JavaScript**:

In the Javascript SDK, this functionality is exposed via `TrackPublishOptions`.

```typescript
await room.localParticipant.setMicrophoneEnabled(!enabled, undefined, {
  preConnectBuffer: true,
});
```

---

**Swift**:

```swift
try await room.withPreConnectAudio(timeout: 10) {
  try await room.connect(url: serverURL, token: token)
} onError: { err in
  print("Pre-connect audio send failed:", err)
}

```

---

**Android**:

```kotlin
try {
  room.withPreconnectAudio {
      // Audio is being captured automatically
      // Perform other async setup
      val (url, token) = tokenService.fetchConnectionDetails()
      room.connect(
          url = url,
          token = token,
      )
      room.localParticipant.setMicrophoneEnabled(true)
  }
} catch (e: Throwable) {
  Log.e(TAG, "Error!")
}

```

---

**Flutter**:

```dart
try {
  await room.withPreConnectAudio(() async {
    // Audio is being captured automatically, perform other async setup
    // Get connection details from token service etc.
    final connectionDetails = await tokenService.fetchConnectionDetails();
    await room.connect(
      connectionDetails.serverUrl,
      connectionDetails.participantToken,
    );
    // Mic already enabled
  });
} catch (error) {
  print("Error: $error");
}

```

## Automatic gain control

Available in:

- [ ] Node.js
- [x] Python

The Agents framework normalizes incoming audio levels using a built-in audio processing module. This is helpful when participants are at different distances from their microphones or have different gain settings. This feature is enabled by default.

To turn off, set `auto_gain_control=False` on `AudioInputOptions`:

```python
from livekit.agents import room_io

room_options = room_io.RoomOptions(
    audio_input=room_io.AudioInputOptions(
        auto_gain_control=False,
    ),
)

```

## Preemptive speech generation

**Preemptive generation** speculatively starts an LLM response before the user's end of turn is confirmed, reducing perceived latency in back-and-forth conversation. It's enabled by default. Only the LLM runs preemptively — TTS waits until the turn is confirmed. For the lowest possible latency, enable `preemptive_tts` to also run TTS speculatively, at the cost of higher wasted compute when the response is discarded.

If the chat context or tools change in the `on_user_turn_completed` [node](https://docs.livekit.io/agents/build/nodes.md#on_user_turn_completed), the speculative response is discarded and regenerated. This means preemptive generation increases LLM token usage, and the tradeoff is less favorable when users speak for extended periods (dictation, storytelling) since the speculative response is more likely to be discarded. Consider disabling it in those scenarios.

### Configuration

Configure preemptive generation using the `preemptive_generation` key in `turn_handling`. For a full list of options, see the [PreemptiveGenerationOptions](https://docs.livekit.io/reference/agents/turn-handling-options.md#preemptivegenerationoptions) reference.

**Python**:

```python
session = AgentSession(
    turn_handling={
        "preemptive_generation": {
            "preemptive_tts": True,       # also run TTS before turn confirmation
            "max_speech_duration": 10.0,  # skip if user speaks longer than 10s
            "max_retries": 3,             # max preemptive attempts per turn
        },
    },
    # ... STT, LLM, TTS, etc.
)

```

---

**Node.js**:

```typescript
const session = new voice.AgentSession({
  // ... llm, stt, etc.
  turnHandling: {
    preemptiveGeneration: {
      preemptiveTts: true, // also run TTS before turn confirmation
      maxSpeechDuration: 10_000, // skip if user speaks longer than 10s (ms)
      maxRetries: 3, // max preemptive attempts per turn
    },
  },
});
```

To disable preemptive generation entirely:

**Python**:

```python
session = AgentSession(
    turn_handling={
        "preemptive_generation": {"enabled": False},
    },
    # ... STT, LLM, TTS, etc.
)

```

---

**Node.js**:

```typescript
const session = new voice.AgentSession({
  // ... llm, stt, etc.
  turnHandling: {
    preemptiveGeneration: { enabled: false },
  },
});
```

## Initiating speech

By default, the agent waits for user input before responding — the Agents framework automatically handles response generation.

In some cases, though, the agent might need to initiate the conversation. For example, it might greet the user at the start of a session or check in after a period of silence. For fixed phrases like these, you can [cache TTS and use pre-synthesized audio](https://docs.livekit.io/agents/multimodality/audio/customization.md#caching-tts) to avoid redundant TTS calls and reduce latency.

### session.say

To have the agent speak a predefined message, use `session.say()`. This triggers the configured TTS to synthesize speech and play it back to the user.

You can also optionally provide pre-synthesized audio for playback. This skips the TTS step and reduces response time.

> 💡 **Realtime models and TTS**
>
> The `say` method requires a TTS plugin. If you're using a realtime model, you need to add a TTS plugin to your session or use the [`generate_reply()`](#manually-interrupt-and-generate-responses) method instead.

**Python**:

```python
await session.say(
   "Hello. How can I help you today?",
   allow_interruptions=False,
)

```

---

**Node.js**:

```typescript
await session.say("Hello. How can I help you today?", {
  allowInterruptions: false,
});
```

#### Parameters

You can call `session.say()` with the following options:

- `text` only: Synthesizes speech using TTS, which is added to the transcript and chat context (unless `add_to_chat_ctx=False`).
- `audio` only: Plays audio, which is not added to the transcript or chat context.
- `text` + `audio`: Plays the provided audio and the `text` is used for the transcript and chat context.

- **`text`** _(str | AsyncIterable[str])_ (optional): Text for TTS playback, added to the transcript and by default to the chat context.

- **`audio`** _(AsyncIterable[rtc.AudioFrame])_ (optional): Pre-synthesized audio to play. If used without `text`, nothing is added to the transcript or chat context.

- **`allow_interruptions`** _(boolean)_ (optional) - Default: `True`: If `True`, allow the user to interrupt the agent while speaking.

- **`add_to_chat_ctx`** _(boolean)_ (optional) - Default: `True`: If `True`, add the text to the agent's chat context after playback. Has no effect if `text` is not provided.

#### Returns

Returns a [`SpeechHandle`](#speechhandle) object.

#### Events

This method triggers a [`speech_created`](https://docs.livekit.io/reference/agents/events.md#speech_created) event.

### generate_reply

To make conversations more dynamic, use `session.generate_reply()` to prompt the LLM to generate a response.

There are two ways to use `generate_reply`:

1. give the agent instructions to generate a response

**Python**:

```python
session.generate_reply(
   instructions="greet the user and ask where they are from",
)

```

---

**Node.js**:

```typescript
session.generateReply({
  instructions: "greet the user and ask where they are from",
});
```

2. provide the user's input via text

**Python**:

```python
session.generate_reply(
   user_input="how is the weather today?",
)

```

---

**Node.js**:

```typescript
session.generateReply({
  userInput: "how is the weather today?",
});
```

#### How instructions interact with session-level instructions

The `instructions` parameter acts as extra instructions for that reply. The agent's session-level instructions (`Agent(instructions=...)`) remain active — `generate_reply` instructions don't replace them.

How the extra instructions are delivered to the model depends on the model type:

- **STT-LLM-TTS pipeline**: `instructions` are added as a separate system message at the end of the chat context, after the conversation history. For providers that don't natively support mid-conversation system messages (Anthropic, Google, AWS Bedrock), the framework automatically converts them to user messages wrapped in `<instructions>` tags.

For full control over the instructions used for a reply, [use a custom chat context](#custom-chat-context) (available in Python).

- **Realtime models**: the delivery method is provider-specific.

- OpenAI receives them as per-response instructions, scoped to that reply only. The framework prepends session-level instructions to preserve them.
- Gemini and Phonic receive them as a model message.
- Ultravox receives them as a user message wrapped in `<instructions>` tags.
  For Gemini, Phonic, and Ultravox, `instructions` are added to the chat context and may influence future turns.

#### Using a custom chat context

For pipeline agents, you can use the `chat_ctx` parameter to `generate_reply` to fully control the context used for that reply, including replacing the agent's session-level instructions entirely rather than appending to them.

This is useful when the `instructions` parameter isn't enough. For example, if you need to switch contexts for a specific reply, exclude certain messages from the conversation history, or inject additional context before the LLM call. Pass a custom chat context and omit the `instructions` parameter.

The following example uses a modified copy of the agent's chat context:

**Python**:

```python
# Copy the current chat context to modify for this reply
ctx = session.current_agent.chat_ctx.copy()
# Modify context as needed: replace instructions, trim history, inject context, etc.
# Then pass the modified context to generate_reply without instructions
await session.generate_reply(chat_ctx=ctx)

```

---

**Node.js**:

```ts
// Copy the current chat context to modify for this reply
const ctx = session.currentAgent.chatCtx.copy();
// Modify context as needed: replace instructions, trim history, inject context, etc.
// Then pass the modified context to generateReply without instructions
await session.generateReply({ chatCtx: ctx });
```

For more details on working with `ChatContext`, see [Chat context](https://docs.livekit.io/agents/logic/chat-context.md).

#### Per-response tools and tool choice

Use `tools` and `tool_choice` to control which tools the agent can call for a single reply, without permanently changing what's registered on the agent. This is useful for staged workflows like surfacing a payment tool only during checkout or restricting destructive actions until identity is verified.

The `tools` parameter (Python only) takes a list of tool IDs that map to the agent's registered function tools and toolsets. For a function tool, the ID is the function name. For a toolset, it's the ID set at construction.

Both parameters apply only to the current reply, but the underlying behavior depends on the model:

- **OpenAI Realtime** and **STT-LLM-TTS pipelines**: `tools` and `tool_choice` are passed directly to the single LLM call for this reply.
- **Other realtime models** (Google, AWS Nova Sonic, Phonic, Ultravox, xAI): the framework swaps the realtime session's tools and tool choice for this reply, then restores the originals when it completes.

#### Parameters

The `generate_reply()` method accepts the following parameters. For a full list of parameters, see the [Python reference](https://docs.livekit.io/reference/python/livekit/agents.md#livekit.agents.AgentSession.generate_reply) and [Node.js reference](https://docs.livekit.io/reference/agents-js/classes/agents.voice.AgentSession.html.md#generateReply).

- **`user_input`** _(string)_ (optional): The user input to respond to.

- **`instructions`** _(string)_ (optional): Instructions for the agent to use for the reply.

- **`tool_choice`** _(ToolChoice)_ (optional): Controls how the LLM selects a tool for this reply: `"auto"`, `"required"`, `"none"`, or a named function `{ type: "function", function: { name: "..." } }`. If `generate_reply` is invoked from inside a function tool, defaults to `"none"`. To learn more, see [Per-response tools and tool choice](#per-response-tools).

- **`tools`** _(list[str])_ (optional): Available in:
- [ ] Node.js
- [x] Python

List of tool IDs to make available for this reply. When set, only the listed tools can be used. IDs must match registered tools on the agent. To learn more, see [Per-response tools and tool choice](#per-response-tools).

- **`allow_interruptions`** _(boolean)_ (optional): If `True`, allow the user to interrupt the agent while speaking. (default `True`)

- **`chat_ctx`** _(ChatContext)_ (optional): The chat context to use for generating the reply. Defaults to the agent's current chat context. Pass a modified copy to fully control the context for this reply. To learn more, see [Using a custom chat context](#custom-chat-context).

#### Returns

Returns a [`SpeechHandle`](#speechhandle) object.

#### Events

This method triggers a [`speech_created`](https://docs.livekit.io/reference/agents/events.md#speech_created) event.

## Controlling agent speech

You can control agent speech using the `SpeechHandle` object returned by the `say()` and `generate_reply()` methods, and allowing user interruptions.

### SpeechHandle

The `say()` and `generate_reply()` methods return a `SpeechHandle` object, which lets you track the state of the agent's speech. This can be useful for coordinating follow-up actions, for example, notifying the user before ending the call.

**Python**:

```python
# The following is a shortcut for:
# handle = session.say("Goodbye for now.", allow_interruptions=False)
# await handle.wait_for_playout()
await session.say("Goodbye for now.", allow_interruptions=False)

```

---

**Node.js**:

```typescript
// The following is a shortcut for:
// const handle = session.say('Goodbye for now.', { allowInterruptions: false });
// await handle;
await session.say("Goodbye for now.", { allowInterruptions: false });
```

You can wait for the agent to finish speaking before continuing:

**Python**:

```python
handle = session.generate_reply(instructions="Tell the user we're about to run some slow operations.")

# perform an operation that takes time
...

await handle # finally wait for the speech

```

---

**Node.js**:

```typescript
const handle = session.generateReply({
  instructions: "Tell the user we're about to run some slow operations."
});

// perform an operation that takes time
...

await handle; // finally wait for the speech

```

The following example makes a web request for the user, and cancels the request when the user interrupts:

**Python**:

```python
async with aiohttp.ClientSession() as client_session:
    web_request = client_session.get('https://api.example.com/data')
    handle = await session.generate_reply(instructions="Tell the user we're processing their request.")
    if handle.interrupted:
        # if the user interrupts, cancel the web_request too
        web_request.cancel()

```

---

**Node.js**:

```typescript
import { Task } from "@livekit/agents";

const webRequestTask = Task.from(async (controller) => {
  const response = await fetch("https://api.example.com/data", {
    signal: controller.signal,
  });
  return response.json();
});

const handle = await session.generateReply({
  instructions: "Tell the user we're processing their request.",
});

if (handle.interrupted) {
  // if the user interrupts, cancel the web_request too
  webRequestTask.cancel();
}
```

`SpeechHandle` has an API similar to `asyncio.Future`, allowing you to add a callback:

**Python**:

```python
handle = session.say("Hello world")
handle.add_done_callback(lambda _: print("speech done"))

```

---

**Node.js**:

```typescript
const handle = session.say("Hello world");
handle.then(() => console.log("speech done"));
```

### Getting the current speech handle

The agent session's active speech handle, if any, is available with the `current_speech` property. If no speech is active, this property returns `None`. Otherwise, it returns the active `SpeechHandle`.

Use the active speech handle to coordinate with the speaking state. For instance, you can ensure that a hang up occurs only after the current speech has finished, rather than mid-speech:

**Python**:

```python
# to hang up the call as part of a function call
@function_tool
async def end_call(self, ctx: RunContext):
   """Use this tool when the user has signaled they wish to end the current call. The session ends automatically after invoking this tool."""
   await ctx.wait_for_playout() # let the agent finish speaking


   # call API to delete_room
   ...

```

---

**Node.js**:

```typescript
const endCall = llm.tool({
  name: "endCall",
  description: "End the call.",
  parameters: z.object({
    reason: z
      .enum(["assistant-ended-call", "sip-call-transferred", "user-ended-call", "unknown-error"])
      .describe("The reason to end the call"),
  }),
  execute: async ({ reason }, { ctx }) => {
    await ctx.session.generateReply({
      userInput: `You are about to end the call due to ${reason}, notify the user with one last message`,
    });

    ctx.session.shutdown({ reason });
  },
});
```

### Interruptions

By default, the agent stops speaking when it detects that the user has started speaking. You can customize this behavior. To learn more, see [Interruptions](https://docs.livekit.io/agents/logic/turns.md#interruptions) in the Turn detection topic.

## Additional resources

To learn more, see the following resources.

- **[Audio customization](https://docs.livekit.io/agents/multimodality/audio/customization.md)**: Customize pronunciation, adjust speech volume, and cache TTS responses.

- **[Background audio](https://docs.livekit.io/agents/multimodality/audio/background-audio.md)**: Add ambient sounds, thinking sounds, and on-demand audio playback.

- **[Voice AI quickstart](https://docs.livekit.io/agents/start/voice-ai.md)**: Use the quickstart as a starting base for adding audio code.

- **[Speech related event](https://docs.livekit.io/agents/build/events.md#speech_created)**: Learn more about the `speech_created` event, triggered when new agent speech is created.

- **[Text-to-speech (TTS)](https://docs.livekit.io/agents/models/tts.md)**: TTS models for pipeline agents.

- **[Speech-to-speech](https://docs.livekit.io/agents/models/realtime.md)**: Realtime models that understand speech input and generate speech output directly.

- **[Custom voices](https://docs.livekit.io/agents/models/tts/custom-voices.md)**: Create voice clones from short audio samples.

---

This document was rendered at 2026-08-12T04:22:37.436Z.
For the latest version of this document, see [https://docs.livekit.io/agents/multimodality/audio.md](https://docs.livekit.io/agents/multimodality/audio.md).

To explore all LiveKit documentation, see [llms.txt](https://docs.livekit.io/llms.txt).
