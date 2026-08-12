LiveKit docs › Multimodality › Text & transcriptions

---

# Text and transcriptions

> Integrate realtime text features into your agent.

## Overview

LiveKit Agents supports text inputs and outputs in addition to audio, based on the [text streams](https://docs.livekit.io/transport/data/text-streams.md) feature of the LiveKit SDKs. This guide explains what's possible and how to use it in your app.

> 💡 **Modality-aware prompts**
>
> To give an agent different system prompts for voice and text input, see [modality-aware instructions](https://docs.livekit.io/agents/multimodality/instructions.md).

## Transcriptions

When an agent performs STT as part of its processing pipeline, the transcriptions are also published to the frontend in realtime. A text representation of the agent speech is also published in sync with audio playback when the agent speaks. These features are both enabled by default when using `AgentSession`.

Transcriptions use the `lk.transcription` text stream topic. They include a `lk.transcribed_track_id` attribute and the sender identity is the transcribed participant.

> ℹ️ **Migrating from TranscriptionReceived**
>
> The `TranscriptionReceived` client event and the `publish_transcription()` method are deprecated. They use a separate delivery mechanism from text streams, so writing to the `lk.transcription` text stream doesn't trigger `TranscriptionReceived`. See the [migration guide](https://docs.livekit.io/reference/migration-guides/v0-migration/python.md#transcriptions) for details.

To disable transcription output, set `text_output=False` in `RoomOptions` (Python) or `transcriptionEnabled: false` in `outputOptions` (Node.js).

### Synchronized transcription forwarding

When both voice and transcription are enabled, the agent's speech is synchronized with its transcriptions, displaying text word by word as it speaks. If the agent is interrupted, the transcription stops and is truncated to match the spoken output.

#### Disabling synchronization

To send transcriptions to the client as soon as they become available, without synchronizing to the original speech, set `sync_transcription` to False in text output options.

**Python**:

```python
from livekit.agents import room_io

await session.start(
    agent=MyAgent(),
    room=ctx.room,
    room_options=room_io.RoomOptions(
        text_output=room_io.TextOutputOptions(
            sync_transcription=False
        ),
    ),
)

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

await session.start({
  agent: voice.Agent.create({
    instructions: "You are a helpful assistant.",
  }),
  room: ctx.room,
  outputOptions: {
    syncTranscription: false,
  },
});
```

### Accessing from AgentSession

You can be notified within your agent whenever text input or output is committed to the chat history by listening to the [conversation_item_added](https://docs.livekit.io/reference/agents/events.md#conversation_item_added) event.

### TTS-aligned transcriptions

If your TTS provider supports it, you can enable TTS-aligned transcription forwarding to improve transcription synchronization to your frontend. This feature synchronizes the transcription output with the actual speech timing, enabling word-level synchronization. When using this feature, certain formatting may be lost from the original text (dependent on the TTS provider).

Currently, only the [Cartesia](https://docs.livekit.io/agents/models/tts/cartesia.md), [ElevenLabs](https://docs.livekit.io/agents/models/tts/elevenlabs.md), and [Rime](https://docs.livekit.io/agents/models/tts/rime.md) plugins support word-level transcription timing. For other providers, including LiveKit Inference, the alignment is applied at the sentence level and still improves synchronization reliability for multi-sentence turns.

To enable this feature, set `use_tts_aligned_transcript=True` in your `AgentSession` configuration:

**Python**:

```python
session = AgentSession(
    # ... stt, llm, tts, vad, etc...
    use_tts_aligned_transcript=True,
)

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const session = new voice.AgentSession({
  // ... vad, stt, tts, llm, etc.
  voiceOptions: {
    useTtsAlignedTranscript: true,
  },
});
```

To access timing information in your code, implement a [transcription_node](https://docs.livekit.io/agents/build/nodes.md#transcription-node) method in your agent. The iterator yields a `TimedString` which includes `start_time` and `end_time` for each word, in seconds relative to the start of the agent's current [turn](https://docs.livekit.io/agents/logic/turns.md).

> 🔥 **Experimental feature**
>
> The `transcription_node` and `TimedString` implementations are experimental and may change in a future version of the SDK.

**Python**:

```python
async def transcription_node(
    self, text: AsyncIterable[str | TimedString], model_settings: ModelSettings
) -> AsyncGenerator[str | TimedString, None]:
    async for chunk in text:
        if isinstance(chunk, TimedString):
            logger.info(f"TimedString: '{chunk}' ({chunk.start_time} - {chunk.end_time})")
        yield chunk

```

---

**Node.js**:

```typescript
async transcriptionNode(
  text: ReadableStream<string | TimedString>,
  modelSettings: ModelSettings,
): Promise<ReadableStream<string | TimedString> | null> {
  return new ReadableStream({
    async start(controller) {
      const reader = text.getReader();
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          if (typeof value === 'object' && 'startTime' in value) {
            console.log(`TimedString: '${value.text}' (${value.startTime} - ${value.endTime})`);
          }
          controller.enqueue(value);
        }
        controller.close();
      } finally {
        reader.releaseLock();
      }
    },
  });
}

```

#### Timed transcripts

Timestamps on each transcript chunk let frontend clients sync the display to audio playback. Common use cases include captioning, clickable transcripts where selecting a word jumps to that moment in a recording, and time-aligned post-call analysis.

By default, the agent publishes plain text to `lk.transcription`. To publish each chunk as a JSON object containing the text plus its timing data, set `json_format=True` in `TextOutputOptions` (Python) or `jsonFormat: true` in `outputOptions` (Node.js).

**Python**:

```python
from livekit.agents import room_io

await session.start(
    agent=MyAgent(),
    room=ctx.room,
    room_options=room_io.RoomOptions(
        text_output=room_io.TextOutputOptions(
            json_format=True,
            sync_transcription=True,
        ),
    ),
)

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

await session.start({
  agent: new MyAgent(),
  room: ctx.room,
  outputOptions: {
    jsonFormat: true,
    syncTranscription: true,
  },
});
```

This example assumes TTS-aligned transcripts are enabled (see [TTS-aligned transcriptions](#tts-aligned-transcriptions)) and a TTS that emits word-level timestamps.

Each chunk has the following format:

```json
{ "text": "hello", "start_time": 0.42, "end_time": 0.67 }
```

The `text` field is always present. The `start_time` and `end_time` fields appear when the underlying chunk is a `TimedString`.

Word-level timing depends on the TTS provider:

- [Cartesia](https://docs.livekit.io/agents/models/tts/cartesia.md) and [ElevenLabs](https://docs.livekit.io/agents/models/tts/elevenlabs.md) emit word-level timestamps directly.
- Non-streaming TTS providers wrapped with `StreamAdapter` emit sentence-level timestamps.
- Other providers emit JSON objects without timing fields, but the `text` field is still present.

## Text transforms

The `tts_text_transforms` option on `AgentSession` lets you modify text before it reaches the TTS. Transforms are applied in order, and each one receives the streaming text output of the previous transform.

Two built-in string transforms are available: `"filter_markdown"` strips Markdown formatting and `"filter_emoji"` removes emoji characters. When `tts_text_transforms` is not set, both are applied by default. Set `tts_text_transforms` to `None` (Python) or `null` (Node.js) to turn off all transforms.

> 🔀 **Behavior change in Node.js v1.4.2**
>
> As of `@livekit/agents@1.4.2`, `filter_markdown` and `filter_emoji` are applied by default in Node.js. In prior versions, TTS input was unfiltered. If you need raw text to reach the TTS, set `ttsTextTransforms: null`.

### Built-in replace transform

Use `text_transforms.replace()` to substitute words or phrases before they reach the TTS. This is useful for fixing pronunciation of acronyms, proper nouns, and any other terms that need phonetic overrides. The transform buffers across token boundaries so replacements work even when a term is split across streaming chunks.

**Python**:

```python
from livekit.agents import AgentSession, text_transforms

session = AgentSession(
    stt="deepgram/nova-3:en",
    llm="google/gemma-4-31b-it",
    tts="cartesia/sonic-3",
    tts_text_transforms=[
        "filter_emoji",
        "filter_markdown",
        text_transforms.replace({
            "LiveKit": "<<ˈ|l|aɪ|v>> <<ˈ|k|ɪ|t>>",
            "API": "A P I",
            "RTMP": "R T M P",
        }),
    ],
)

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const session = new voice.AgentSession({
  stt: "deepgram/nova-3:en",
  llm: "google/gemma-4-31b-it",
  tts: "cartesia/sonic-3",
  ttsTextTransforms: [
    "filter_emoji",
    "filter_markdown",
    voice.textTransforms.replace({
      LiveKit: "Lyve Kit",
      API: "A P I",
      RTMP: "R T M P",
    }),
  ],
});
```

The `replace()` function accepts a dictionary (Python) or object (Node.js) mapping source terms to their replacements, and an optional `case_sensitive` (Python) or `caseSensitive` (Node.js) flag (default: case-insensitive).

The `<<ˈ|l|aɪ|v>>` markers in the Python example are Cartesia's inline phoneme syntax: each `<<...>>` block is a pronunciation override expressed as `|`-separated IPA symbols, with `ˈ` marking primary stress. This syntax is specific to Cartesia models (such as `cartesia/sonic-3`). Other TTS providers might support phonemes or other methods of customizing pronunciation. Check provider docs before copying these replacements to a different TTS. For Cartesia specifically, see [Customizing pronunciation](https://docs.livekit.io/agents/models/tts/cartesia.md#customizing-pronunciation) on the Cartesia TTS page.

### Custom callable transforms

You can pass any callable as a transform. In Python, use the signature `Callable[[AsyncIterable[str]], AsyncIterable[str]]`. In Node.js, use `(text: ReadableStream<string>) => ReadableStream<string>`. This lets you implement custom text processing logic that operates on the streaming text.

**Python**:

```python
from collections.abc import AsyncIterable
from livekit.agents import AgentSession, text_transforms


async def redact_emails(text: AsyncIterable[str]) -> AsyncIterable[str]:
    """Replace email addresses with 'email redacted'."""
    import re
    buffer = ""
    async for chunk in text:
        buffer += chunk
        # flush everything before the last potential partial email
        safe, _, tail = buffer.rpartition(" ")
        if safe:
            safe = re.sub(r"\S+@\S+\.\S+", "email redacted", safe)
            yield safe + " "
            buffer = tail
    if buffer:
        buffer = re.sub(r"\S+@\S+\.\S+", "email redacted", buffer)
        yield buffer


session = AgentSession(
    stt="deepgram/nova-3:en",
    llm="google/gemma-4-31b-it",
    tts="inworld/inworld-tts-2",
    tts_text_transforms=[
        "filter_markdown",
        redact_emails,
        text_transforms.replace({"ACME": "Acme Corp"}),
    ],
)

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const redactEmails = (text: ReadableStream<string>): ReadableStream<string> => {
  return new ReadableStream({
    async start(controller) {
      const reader = text.getReader();
      let buffer = "";
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += value;
          // flush everything before the last potential partial email
          const lastSpace = buffer.lastIndexOf(" ");
          if (lastSpace !== -1) {
            const safe = buffer.slice(0, lastSpace + 1);
            controller.enqueue(safe.replace(/\S+@\S+\.\S+/g, "email redacted"));
            buffer = buffer.slice(lastSpace + 1);
          }
        }
        if (buffer) {
          controller.enqueue(buffer.replace(/\S+@\S+\.\S+/g, "email redacted"));
        }
        controller.close();
      } finally {
        reader.releaseLock();
      }
    },
  });
};

const session = new voice.AgentSession({
  stt: "deepgram/nova-3:en",
  llm: "google/gemma-4-31b-it",
  tts: "inworld/inworld-tts-2",
  ttsTextTransforms: [
    "filter_markdown",
    redactEmails,
    voice.textTransforms.replace({ ACME: "Acme Corp" }),
  ],
});
```

Transforms are applied in order. In the examples above, Markdown is stripped first, then emails are redacted, then text replacements are applied.

## Text input

Your agent monitors the `lk.chat` text stream topic for incoming text messages from its linked participant. The agent interrupts its current speech, if any, to process the message and generate a new response.

To disable text input, set `text_input=False` in `RoomOptions` (Python) or `textEnabled: false` in `RoomInputOptions` (Node.js).

### Sending from frontend

Use the `sendText` method to send text messages:

**JavaScript**:

```typescript
const text = "Hello how are you today?";
const info = await room.localParticipant.sendText(text, {
  topic: "lk.chat",
});
```

---

**Swift**:

```swift
let text = "Hello how are you today?"
let info = try await room.localParticipant.sendText(text, for: "lk.chat")

```

### Manual input

To insert text input and generate a response, use the `generate_reply` method of AgentSession: `session.generate_reply(user_input="...")`.

### Custom handling

You can customize how agents handle incoming text input, replacing the default behavior with custom logic, such as command processing, message filtering, or custom response generation.

To implement custom text input handling, provide a text input callback function in room options:

**Python**:

In Python, use the `TextInputOptions` parameter for `text_input` in `RoomOptions` to provide a text input callback function:

```python
from livekit.agents import AgentServer, AgentSession
from livekit.agents import room_io


def custom_text_input_handler(session: AgentSession, event: room_io.TextInputEvent) -> None:
    # Access the incoming text message
    message = event.text

    # Handle commands
    if message.startswith("/"):
        if message == "/help":
            session.say("Available commands: /help, /status")
            return
        elif message == "/status":
            session.say("Agent is running normally")
            return

    # Apply custom filtering
    if any(word in message.lower() for word in ["spam", "inappropriate"]):
        session.say("I can't respond to that type of message.")
        return

    # Default behavior: interrupt and generate reply
    session.interrupt()
    session.generate_reply(user_input=message)


server = AgentServer()

@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: JobContext):
    # Create the session
    session = AgentSession(
        # ... stt, llm, tts, etc.
    )

    # Start session with custom text input handler
    session.start(
        # other options...
        room_options=room_io.RoomOptions(
            text_input=room_io.TextInputOptions(
                text_input_cb=custom_text_input_handler
            )
        )
    )

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const customTextInputHandler = (session: voice.AgentSession, event: voice.TextInputEvent): void => {
  const message = event.text;

  if (message.startsWith("/")) {
    if (message === "/help") {
      session.say("Available commands: /help, /status");
      return;
    }
    if (message === "/status") {
      session.say("Agent is running normally");
      return;
    }
  }

  if (["spam", "inappropriate"].some((word) => message.toLowerCase().includes(word))) {
    session.say("I can't respond to that type of message.");
    return;
  }

  session.interrupt();
  session.generateReply({ userInput: message });
};

await session.start({
  agent,
  room: ctx.room,
  inputOptions: {
    textInputCallback: customTextInputHandler,
  },
});
```

## Text-only sessions

You have two options for disabling audio input and output for text-only sessions:

- Permanently: Disable audio for the entire session to prevent any audio tracks from being published to the room.
- Temporarily: Toggle audio input and output dynamically for hybrid sessions.

Turn off audio input and output for a text-only session, or dynamically, using the `session.input.set_audio_enabled()` and `session.output.set_audio_enabled()` methods.

### Disable audio for the entire session

You can turn off audio input or output for the entire session when you start a session. When audio output is disabled, the agent does not publish audio tracks to the room. Text responses are sent without the `lk.transcribed_track_id` attribute and without speech synchronization.

**Python**:

In Python, you can turn off audio input and output in `RoomOptions` when you start a session:

```python
session.start(
    # ... agent, room
    room_options=RoomOptions(
      audio_input=False,
      audio_output=False,
    ),
)

```

---

**Node.js**:

In Node.js, you can turn off audio input and output in `inputOptions` and `outputOptions` when you start a session:

```typescript
await session.start({
  // ... agent, room
  inputOptions: {
    audioEnabled: false,
  },
  outputOptions: {
    audioEnabled: false,
  },
});
```

### Toggle audio input and output

For hybrid sessions where audio input and output might be used, such as when a user toggles an audio switch, you can allow the agent to toggle audio input and output dynamically using `session.input.set_audio_enabled()` and `session.output.set_audio_enabled()`. This still publishes the audio track to the room.

**Python**:

```python
session = AgentSession(...)

# start with audio disabled
session.input.set_audio_enabled(False)
session.output.set_audio_enabled(False)
await session.start(...)

# user toggles audio switch
@room.local_participant.register_rpc_method("toggle_audio")
async def on_toggle_audio(data: rtc.RpcInvocationData) -> None:
    session.input.set_audio_enabled(not session.input.audio_enabled)
    session.output.set_audio_enabled(not session.output.audio_enabled)

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const session = new voice.AgentSession({
  // ... configuration
});

// start with audio disabled
session.input.setAudioEnabled(false);
session.output.setAudioEnabled(false);
await session.start({
  agent,
  room: ctx.room,
});

// user toggles audio switch
ctx.room.localParticipant.registerRpcMethod("toggle_audio", async (data) => {
  session.input.setAudioEnabled(!session.input.audioEnabled);
  session.output.setAudioEnabled(!session.output.audioEnabled);
});
```

You can also temporarily pause audio input to prevent speech from being queued for response. This is useful when an agent needs to run non-verbal jobs and you want to stop the agent from listening to any input. This prevents the audio track from being published to the room.

> 💡 **Tip**
>
> This is different from [manual turn control](https://docs.livekit.io/agents/logic/turns.md#manual) which is used for interfaces such as push-to-talk.

**Python**:

```python
# if currently speaking, stop first so states don't overlap
session.interrupt()

session.input.set_audio_enabled(False) # stop listening
try:
    await do_job()  # your non-verbal job
finally:
    session.input.set_audio_enabled(True) # start listening again

```

---

**Node.js**:

```typescript
try {
  // if currently speaking, stop first so states don't overlap
  session.interrupt();

  session.input.setAudioEnabled(false); // stop listening
  await doJob(); // your non-verbal job
} finally {
  session.input.setAudioEnabled(true); // start listening again
}

async function doJob() {
  // placeholder for actual work
  return new Promise((resolve) => setTimeout(resolve, 7000));
}
```

## Frontend rendering

LiveKit client SDKs have native support for text streams. For more information, see the [text streams](https://docs.livekit.io/transport/data/text-streams.md) documentation.

### Receiving text streams

> ℹ️ **Replaces TranscriptionReceived**
>
> `registerTextStreamHandler` replaces the deprecated `TranscriptionReceived` event. In React, use [`useTranscriptions`](https://docs.livekit.io/reference/components/react/hook/usetranscriptions.md) instead of the deprecated `useTrackTranscriptions` hook.

Use the `registerTextStreamHandler` method to receive incoming transcriptions or text.

When an audio track is transcribed, the speech is split into segments. For each segment, two streams are produced:

- `interim_stream`: while the segment is being processed
- `final_stream`: when the segment is complete

> 💡 **Tip**
>
> Use the `lk.transcription_final` value to determine if the stream is interim (`false`) or final (`true`).

These streams share the same `segment_id` and `transcribed_track_id`, so logging every message can produce duplicates. Tracking `interim_stream` is only recommended for use cases that require live typing updates. Replace interim messages with the final message when `lk.transcription_final` is `true`.

For React development, use the [`useTranscriptions`](https://docs.livekit.io/reference/components/react/hook/usetranscriptions.md) hook.

**Android**:

```kotlin
// Register a text stream handler for transcription
room.registerTextStreamHandler("lk.transcription") { reader, participantIdentity ->
    // Launch a coroutine to handle the async reading
    scope.launch {
        try {
            // Read all the text data from the stream
            val messages = reader.readAll()
            val fullMessage = messages.joinToString("")

            val isFinal = reader.info.attributes["lk.transcription_final"] == "true"
            // Check if this is a transcription by looking at the stream attributes
            val isTranscription = reader.info.attributes["lk.transcribed_track_id"] != null
            val segmentId = reader.info.attributes["lk.segment_id"]

            if (isTranscription) {
                Log.d("TextStream", "New transcription from $participantIdentity [final=$isFinal, segment=$segmentId]: $fullMessage")
            } else {
                Log.d("TextStream", "New message from $participantIdentity: $fullMessage")
            }
        } catch (e: Exception) {
            Log.e("TextStream", "Error reading text stream", e)
        }
    }
}

```

---

**Flutter**:

```dart
room.registerTextStreamHandler('lk.transcription', (TextStreamReader reader, String participantIdentity) async {
  final message = await reader.readAll();

  final isTranscription = reader.info?.attributes['lk.transcribed_track_id'] != null;
  final isFinal = reader.info?.attributes['lk.transcription_final'] == 'true';
  final segmentId = reader.info?.attributes['lk.segment_id']

  if (isTranscription) {
    print('New transcription from $participantIdentity [final=$isFinal, segment=$segmentId]: $message');
  } else {
    print('New message from $participantIdentity: $message');
  }
});

```

---

**JavaScript**:

```typescript
room.registerTextStreamHandler("lk.transcription", async (reader, participantInfo) => {
  const message = await reader.readAll();
  if (reader.info.attributes["lk.transcribed_track_id"]) {
    console.log(`New transcription from ${participantInfo.identity}: ${message}`);
  } else {
    console.log(`New message from ${participantInfo.identity}: ${message}`);
  }
});
```

---

**Swift**:

```swift
try await room.registerTextStreamHandler(for: "lk.transcription") { reader, participantIdentity in
    let message = try await reader.readAll()
    if let transcribedTrackId = reader.info.attributes["lk.transcribed_track_id"] {
        print("New transcription from \(participantIdentity): \(message)")
    } else {
        print("New message from \(participantIdentity): \(message)")
    }
}

```

---

This document was rendered at 2026-08-12T04:22:38.345Z.
For the latest version of this document, see [https://docs.livekit.io/agents/multimodality/text.md](https://docs.livekit.io/agents/multimodality/text.md).

To explore all LiveKit documentation, see [llms.txt](https://docs.livekit.io/llms.txt).
