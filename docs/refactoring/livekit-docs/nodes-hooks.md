LiveKit docs › Logic & Structure › Pipeline nodes & hooks

---

# Pipeline nodes and hooks

> Learn how to customize the behavior of your agent with nodes and hooks in the voice pipeline.

## Overview

You can fully customize your agent's behavior at multiple **nodes** in the processing path. A node is a point in the path where one process transitions to another. Some example customizations include:

- Use a custom STT, LLM, or TTS provider without a plugin.
- Generate a custom greeting when an agent enters a session.
- Modify STT output to remove filler words before sending it to the LLM.
- Modify LLM output before sending it to TTS to customize pronunciation.
- Update the user interface when an agent or user finishes speaking.

The `Agent` supports the following nodes and hooks. Some nodes are only available for STT-LLM-TTS pipeline models, and others are only available for realtime models.

Lifecycle hooks:

- `on_enter()`: Called after the agent becomes the active agent in a session.
- `on_exit()`: Called before the agent gives control to another agent in the same session.
- `on_user_turn_completed()`: Called when the user's [turn](https://docs.livekit.io/agents/logic/turns.md) has ended, before the agent's reply.
- `on_user_turn_exceeded()`: Called when the user has been speaking long enough to exceed a configured [user turn limit](https://docs.livekit.io/agents/logic/turns.md#user-turn-limit).

STT-LLM-TTS pipeline nodes:

- `stt_node()`: Transcribe input audio to text.
- `llm_node()`: Perform inference and generate a new conversation turn (or tool call).
- `tts_node()`: Synthesize speech from the LLM text output.

Realtime model nodes:

- `realtime_audio_output_node()`: Adjust output audio before publishing to the user.

Transcription node:

- `transcription_node()`: Access transcription timestamps, or adjust pipeline or realtime model transcription before sending to the user.

The following diagrams show the processing path for STT-LLM-TTS pipeline models and realtime models.

**STT-LLM-TTS pipeline**:

![Diagram showing voice pipeline agent processing path.](/images/agents/voice-pipeline-agent.svg)

---

**Realtime model**:

![Diagram showing realtime agent processing path.](/images/agents/realtime-agent.svg)

## How to implement

Override the method within a custom `Agent` subclass, or pass hooks to `Agent.create`, to customize the behavior of your agent at a specific node in the processing path. `Agent.create` hooks receive a `ctx` object first and use `AsyncIterable` inputs and outputs for stream nodes. To use the default implementation, call `Agent.default.<node-name>()`. For instance, this code overrides the STT node while maintaining the default behavior.

**Python**:

```python
async def stt_node(self, audio: AsyncIterable[rtc.AudioFrame], model_settings: ModelSettings) -> Optional[AsyncIterable[stt.SpeechEvent]]:
    # insert custom before STT processing here
    events = Agent.default.stt_node(self, audio, model_settings)
    # insert custom after STT processing here
    return events

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const agent = voice.Agent.create({
  instructions: "You are a helpful assistant.",
  sttNode(ctx, audio, modelSettings) {
    // insert custom before STT processing here
    const events = voice.Agent.default.sttNode(ctx.agent, audio, modelSettings);
    // insert custom after STT processing here
    return events;
  },
});
```

## Lifecycle hooks

The following lifecycle hooks are available for customization.

### On enter

The `on_enter` node is called when the agent becomes the active agent in a session. Each session can have only one active agent at a time, which can be read from the `session.agent` property. Change the active agent using [Workflows](https://docs.livekit.io/agents/logic/workflows.md).

For example, to greet the user:

**Python**:

```python
async def on_enter(self):
    await self.session.generate_reply(
        instructions="Greet the user with a warm welcome",
    )

```

---

**Node.js**:

```typescript
const agent = voice.Agent.create({
  onEnter(ctx) {
    ctx.session.generateReply({
      instructions: "Greet the user with a warm welcome",
    });
  },
});
```

### On exit

The `on_exit` node is called before the agent gives control to another agent in the same session as part of a [workflow](https://docs.livekit.io/agents/logic/workflows.md). Use it to save data, say goodbye, or perform other actions and cleanup.

For example, to say goodbye:

**Python**:

```python
async def on_exit(self):
    await self.session.generate_reply(
        instructions="Tell the user a friendly goodbye before you exit.",
    )

```

---

**Node.js**:

```typescript
const agent = voice.Agent.create({
  onExit(ctx) {
    ctx.session.generateReply({
      instructions: "Tell the user a friendly goodbye before you exit.",
    });
  },
});
```

### On user turn completed

The `on_user_turn_completed` node is called when the user's [turn](https://docs.livekit.io/agents/logic/turns.md) has ended, before the agent's reply. Override this method to modify the content of the turn, cancel the agent's reply, or perform other actions.

> ℹ️ **Realtime model turn detection**
>
> To use the `on_user_turn_completed` node with a [realtime model](https://docs.livekit.io/agents/models/realtime.md), you must configure [turn detection](https://docs.livekit.io/agents/logic/turns.md) to occur in your agent instead of within the realtime model.

The node receives the following parameters:

- `turn_ctx`: The full [`ChatContext`](https://docs.livekit.io/agents/logic/chat-context.md), up to but not including the user's latest message.
- `new_message`: The user's latest message, representing their current turn.

After the node is complete, the `new_message` is added to the chat context.

One common use of this node is [retrieval-augmented generation (RAG)](https://docs.livekit.io/agents/build/external-data.md). You can retrieve context relevant to the newest message and inject it into the chat context for the LLM.

**Python**:

```python
from livekit.agents import ChatContext, ChatMessage

async def on_user_turn_completed(
    self, turn_ctx: ChatContext, new_message: ChatMessage,
) -> None:
    rag_content = await my_rag_lookup(new_message.text_content)
    turn_ctx.add_message(
        role="assistant",
        content=f"Additional information relevant to the user's next message: {rag_content}"
    )

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const agent = voice.Agent.create({
  instructions: "You are a helpful assistant.",
  async onUserTurnCompleted(ctx, chatCtx, newMessage) {
    const ragContent = await myRagLookup(newMessage.textContent);
    chatCtx.addMessage({
      role: "assistant",
      content: `Additional information relevant to the user's next message: ${ragContent}`,
    });
  },
});
```

Additional messages added in this way are not persisted beyond the current turn. To permanently add messages to the chat history, use the `update_chat_ctx` method:

**Python**:

```python
async def on_user_turn_completed(
    self, turn_ctx: ChatContext, new_message: ChatMessage,
) -> None:
    rag_content = await my_rag_lookup(new_message.text_content)
    turn_ctx.add_message(role="assistant", content=rag_content)
    await self.update_chat_ctx(turn_ctx)

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const agent = voice.Agent.create({
  instructions: "You are a helpful assistant.",
  async onUserTurnCompleted(ctx, chatCtx, newMessage) {
    const ragContent = await myRagLookup(newMessage.textContent);
    chatCtx.addMessage({
      role: "assistant",
      content: `Additional information relevant to the user's next message: ${ragContent}`,
    });
    await ctx.agent.updateChatCtx(chatCtx);
  },
});
```

You can also edit the `new_message` object to modify the user's message before it's added to the chat context. For example, you can remove offensive content or add additional context. These changes are persisted to the chat history going forward.

**Python**:

```python
async def on_user_turn_completed(
    self, turn_ctx: ChatContext, new_message: ChatMessage,
) -> None:
    new_message.content = ["... modified message ..."]

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const agent = voice.Agent.create({
  instructions: "You are a helpful assistant.",
  onUserTurnCompleted(ctx, chatCtx, newMessage) {
    newMessage.content = ["... modified message ..."];
  },
});
```

To abort generation entirely — for example, in a push-to-talk interface — you can do the following:

**Python**:

```python
async def on_user_turn_completed(
    self, turn_ctx: ChatContext, new_message: ChatMessage,
) -> None:
    if not new_message.text_content:
        # for example, raise StopResponse to stop the agent from generating a reply
        raise StopResponse()

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const agent = voice.Agent.create({
  instructions: "You are a helpful assistant.",
  onUserTurnCompleted(ctx, chatCtx, newMessage) {
    if (!newMessage.textContent) {
      // raise StopResponse to stop the agent from generating a reply
      throw new voice.StopResponse();
    }
  },
});
```

#### Fast pre-response

Use the `on_user_turn_completed` node to speak a short filler phrase, such as "let me think about that", while the main reply is still generating. A smaller, faster model produces the filler. Calling `say` without awaiting the speech handle it returns lets the two run concurrently, which reduces the perceived gap between the user's turn and the agent's response.

To implement this, override `on_user_turn_completed` to build a trimmed context for the fast model, then call `say` with `add_to_chat_ctx=False` so the filler stays out of the main reply's history:

**Python**:

```python
from livekit.agents import Agent, ChatContext, ChatMessage, inference, llm

class PreResponseAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="You are a helpful assistant.",
            llm=inference.LLM("openai/gpt-4.1-mini"),
        )
        # A smaller, faster model generates the filler phrase
        self._fast_llm = inference.LLM("openai/gpt-5.4-nano")
        self._fast_llm_prompt = llm.ChatMessage(
            role="system",
            content=[
                "Generate a short instant response to the user's message with 5 to 10 words.",
                "Do not answer the question directly. Examples: let me think about that, "
                "wait a moment, that's a good question.",
            ],
        )

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage,
    ) -> None:
        # Trim the context: drop instructions and tool-call history, keep only recent items
        fast_ctx = turn_ctx.copy(
            exclude_instructions=True,
            exclude_function_call=True,
        ).truncate(max_items=3)
        fast_ctx.items.insert(0, self._fast_llm_prompt)
        fast_ctx.items.append(new_message)

        # Speak the filler without awaiting, so the main reply generates concurrently
        self.session.say(
            self._fast_llm.chat(chat_ctx=fast_ctx).to_str_iterable(),
            add_to_chat_ctx=False,
        )

```

---

**Node.js**:

```typescript
import { inference, llm, toStream, voice } from "@livekit/agents";

const FAST_LLM_PROMPT =
  "Generate a short instant response to the user's message with 5 to 10 words. " +
  "Do not answer the question directly. Examples: let me think about that, " +
  "wait a moment, that's a good question.";

// A smaller, faster model generates the filler phrase
const fastLLM = new inference.LLM({ model: "openai/gpt-5.4-nano" });

const agent = voice.Agent.create({
  instructions: "You are a helpful assistant.",
  llm: new inference.LLM({ model: "openai/gpt-4.1-mini" }),
  onUserTurnCompleted(ctx, turnCtx, newMessage) {
    // Trim the context: drop instructions and tool-call history, keep only recent items
    const fastCtx = turnCtx
      .copy({ excludeInstructions: true, excludeFunctionCall: true })
      .truncate(3);
    fastCtx.items.unshift(llm.ChatMessage.create({ role: "system", content: FAST_LLM_PROMPT }));
    fastCtx.items.push(newMessage);

    // Stream the filler text from the fast model
    async function* fillerText() {
      for await (const chunk of fastLLM.chat({ chatCtx: fastCtx })) {
        if (chunk.delta?.content) yield chunk.delta.content;
      }
    }

    // Speak the filler without awaiting, so the main reply generates concurrently
    // say() takes a ReadableStream, so wrap the async generator with toStream()
    ctx.session.say(toStream(fillerText()), { addToChatCtx: false });
  },
});
```

### On user turn exceeded

The `on_user_turn_exceeded` node is called when the user has been speaking long enough to trip a configured [user turn limit](https://docs.livekit.io/agents/logic/turns.md#user-turn-limit). The node lets the agent step in when a caller keeps talking past the configured `max_words` or `max_duration` threshold. The node is only invoked when at least one threshold is set in `turn_handling.user_turn_limit`.

The node receives a `UserTurnExceededEvent` with the following fields:

- `transcript`: Transcript from the current uncommitted user turn. Previous turns in the accumulation window are already in the chat context.
- `accumulated_transcript`: Full transcript since the user started speaking in the current accumulation window. In Node.js, this field is `accumulatedTranscript`.
- `accumulated_word_count`: Total word count across the accumulation window. In Node.js, this field is `accumulatedWordCount`.
- `duration`: Wall-clock duration of the accumulation window. Python uses seconds and Node.js uses milliseconds.

The default implementation calls `session.generate_reply` with `allow_interruptions=False` and `tool_choice="none"` to respond with a short reply. The user cannot interrupt the default reply.

Override the node to customize the behavior. For example, to deliver a prewritten response with `say` instead of generating a new reply:

**Python**:

```python
from livekit.agents import Agent, UserTurnExceededEvent

class MyAgent(Agent):
    async def on_user_turn_exceeded(self, ev: UserTurnExceededEvent) -> None:
        await self.session.say("Sorry to jump in. Can I help with anything specific?")

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

class MyAgent extends voice.Agent {
  async onUserTurnExceeded(ev: voice.UserTurnExceededEvent): Promise<void> {
    await this.session.say("Sorry to jump in. Can I help with anything specific?");
  }
}
```

The framework skips the `on_user_turn_exceeded` callback if the agent enters the `speaking` state before the threshold fires. This happens when the user pauses long enough for end-of-utterance detection to end their turn naturally and the agent's normal reply starts playing.

## STT-LLM-TTS pipeline nodes

The following nodes are available for STT-LLM-TTS pipeline models.

### STT node

The `stt_node` transcribes audio frames into speech events, converting user audio input into text for the LLM. By default, this node uses the Speech-To-Text (STT) capability from the current agent. If the STT implementation doesn't support streaming natively, a Voice Activity Detection (VAD) mechanism wraps the STT.

You can override this node to implement:

- Custom pre-processing of audio frames
- Additional buffering mechanisms
- Alternative STT strategies
- Post-processing of the transcribed text

To use the default implementation, call `Agent.default.stt_node()`.

This example adds a noise filtering step:

**Python**:

```python
from livekit import rtc
from livekit.agents import ModelSettings, stt, Agent
from typing import AsyncIterable, Optional

async def stt_node(
    self, audio: AsyncIterable[rtc.AudioFrame], model_settings: ModelSettings
) -> Optional[AsyncIterable[stt.SpeechEvent]]:
    async def filtered_audio():
        async for frame in audio:
            # insert custom audio preprocessing here
            yield frame

    async for event in Agent.default.stt_node(self, filtered_audio(), model_settings):
        # insert custom text postprocessing here
        yield event

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const agent = voice.Agent.create({
  instructions: "You are a helpful assistant.",
  async *sttNode(ctx, audio, modelSettings) {
    // Create a transformed audio stream
    async function* filteredAudio() {
      for await (const frame of audio) {
        // insert custom audio preprocessing here
        yield frame;
      }
    }

    const events = await voice.Agent.default.sttNode(ctx.agent, filteredAudio(), modelSettings);
    if (!events) return;

    for await (const event of events) {
      // insert custom text postprocessing here
      yield event;
    }
  },
});
```

### LLM node

The `llm_node` is responsible for performing inference based on the current chat context and creating the agent's response or tool calls. It may yield plain text (as `str`) for straightforward text generation, or `llm.ChatChunk` objects that can include text and optional tool calls. `ChatChunk` is helpful for capturing more complex outputs such as function calls, usage statistics, or other metadata.

You can override this node to:

- Customize how the LLM is used
- Modify the chat context prior to inference
- Adjust how tool invocations and responses are handled
- Implement a custom LLM provider without a plugin

To use the default implementation, call `Agent.default.llm_node()`.

**Python**:

```python
from livekit.agents import ModelSettings, llm, FunctionTool, Agent
from typing import AsyncIterable

async def llm_node(
    self,
    chat_ctx: llm.ChatContext,
    tools: list[FunctionTool],
    model_settings: ModelSettings
) -> AsyncIterable[llm.ChatChunk]:
    # Insert custom preprocessing here
    async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
        # Insert custom postprocessing here
        yield chunk

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const agent = voice.Agent.create({
  instructions: "You are a helpful assistant.",
  async *llmNode(ctx, chatCtx, toolCtx, modelSettings) {
    // Insert custom preprocessing here
    const stream = await voice.Agent.default.llmNode(ctx.agent, chatCtx, toolCtx, modelSettings);
    if (!stream) return;

    for await (const chunk of stream) {
      // Insert custom postprocessing here
      yield chunk;
    }
  },
});
```

#### Send an early response to TTS

By default, the agent waits for the LLM node to finish before sending its output to the TTS node. Sometimes you want to flush part of a response to TTS right away — for example, a filler phrase like "One moment" while a slow tool call completes in the background.

To do this, emit a `FlushSentinel` from your LLM node. `FlushSentinel` is a marker that acts as a segment boundary. In Python it's a class you instantiate (`FlushSentinel()`); in Node.js it's a symbol you yield directly (`FlushSentinel`). When the pipeline encounters one in the stream, it immediately sends all text produced so far to the TTS node for synthesis without waiting for the node to finish. Any text produced after the sentinel begins a new speech segment.

> ℹ️ **Each segment plays out independently**
>
> A `FlushSentinel` creates a hard playout boundary. Each section of the reply is synthesized in a separate TTS pass, played as a separate audio segment, and emitted as a separate transcript segment. Segments are synthesized sequentially, with the next segment starting while the previous one is still playing. Without a `FlushSentinel`, the entire reply is a single segment.

In this example, the LLM node checks whether the model responded with only a `get_weather` tool call and no accompanying text. Without the filler, the user would hear silence until the tool finishes. The flush sends a spoken acknowledgment to TTS immediately while the tool result is still being processed:

**Python**:

```python
import asyncio
from collections.abc import AsyncIterable

from livekit.agents import Agent, FlushSentinel, ModelSettings, llm

async def llm_node(
    self,
    chat_ctx: llm.ChatContext,
    tools: list[llm.FunctionTool],
    model_settings: ModelSettings,
) -> AsyncIterable[llm.ChatChunk | FlushSentinel]:
    called_tools: list[llm.FunctionToolCall] = []
    has_text_message = False
    async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
        if isinstance(chunk, llm.ChatChunk) and chunk.delta:
            if chunk.delta.content:
                has_text_message = True
            if chunk.delta.tool_calls:
                called_tools.extend(chunk.delta.tool_calls)
        yield chunk

    # If the model only called get_weather (with no text of its own), speak a
    # filler phrase right away instead of waiting for the tool result.
    tool_names = [tool.name for tool in called_tools]
    if not has_text_message and "get_weather" in tool_names:
        yield "One moment while I look that up. "
        # Send the filler phrase to TTS immediately, ending the current
        # segment and starting a new one.
        yield FlushSentinel()

        # Simulate additional processing, then speak the rest.
        await asyncio.sleep(3)
        yield "Okay, I found what you were looking for. "

```

---

**Node.js**:

```typescript
import { FlushSentinel, delay, voice } from "@livekit/agents";

const agent = voice.Agent.create({
  instructions: "You are a helpful assistant.",
  async *llmNode(ctx, chatCtx, toolCtx, modelSettings) {
    const stream = await voice.Agent.default.llmNode(ctx.agent, chatCtx, toolCtx, modelSettings);
    if (!stream) return;

    const calledTools: string[] = [];
    let hasTextMessage = false;
    for await (const chunk of stream) {
      if (typeof chunk !== "string" && chunk !== FlushSentinel && chunk.delta) {
        if (chunk.delta.content) hasTextMessage = true;
        if (chunk.delta.toolCalls) {
          calledTools.push(...chunk.delta.toolCalls.map((toolCall) => toolCall.name));
        }
      }
      yield chunk;
    }

    // If the model only called getWeather (with no text of its own), speak a
    // filler phrase right away instead of waiting for the tool result.
    if (!hasTextMessage && calledTools.includes("getWeather")) {
      yield "One moment while I look that up. ";
      // Send the filler phrase to TTS immediately, ending the current
      // segment and starting a new one.
      yield FlushSentinel;

      // Simulate additional processing, then speak the rest.
      await delay(3000);
      yield "Okay, I found what you were looking for. ";
    }
  },
});
```

Although the reply plays out as separate segments, the agent records it as a single assistant message in the conversation history. Interruptions are handled per segment: if the user interrupts, segments that already finished playing are kept, and the segment in progress is truncated at the point of interruption. The whole reply remains one `SpeechHandle`, so the `speech_created` event fires once regardless of how many segments the reply contains.

> 🔀 **Behavior change: Flushed replies**
>
> Per-segment playout was introduced in `livekit-agents` 1.6.0 (Python) and `@livekit/agents` 1.4.6 (Node.js). In earlier versions, a flushed reply played as one continuous audio stream with a single transcript segment.

### TTS node

The `tts_node` synthesizes audio from text segments, converting the LLM output into speech. By default, this node uses the Text-To-Speech capability from the agent. If the TTS implementation doesn't support streaming natively, it uses a sentence tokenizer to split text for incremental synthesis.

You can override this node to:

- Provide different text chunking behavior
- Implement a custom TTS engine
- [Add custom pronunciation rules](https://docs.livekit.io/agents/multimodality/audio/customization.md#pronunciation)
- [Adjust the volume of the audio output](https://docs.livekit.io/agents/multimodality/audio/customization.md#volume)
- Apply any other specialized audio processing

To use the default implementation, call `Agent.default.tts_node()`.

**Python**:

```python
from livekit import rtc
from livekit.agents import ModelSettings, Agent
from typing import AsyncIterable

async def tts_node(
    self, text: AsyncIterable[str], model_settings: ModelSettings
) -> AsyncIterable[rtc.AudioFrame]:
    # Insert custom text processing here
    async for frame in Agent.default.tts_node(self, text, model_settings):
        # Insert custom audio processing here
        yield frame

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";
import type { AudioFrame } from "@livekit/rtc-node";

const agent = voice.Agent.create({
  instructions: "You are a helpful assistant.",
  async *ttsNode(ctx, text, modelSettings) {
    const audioStream = await voice.Agent.default.ttsNode(ctx.agent, text, modelSettings);
    if (!audioStream) return;

    for await (const frame of audioStream) {
      // Insert custom audio processing here
      yield frame;
    }
  },
});
```

#### Speeding up output audio

You can modify the agent's output audio before its playout by adding a processor to the `tts_node`. For example, you can speed up the agent's speech by time-stretching the audio without changing its pitch. The same processor also works for the realtime audio output node when using a realtime model.

The following example time stretches the audio by a configurable speed factor. A speed factor greater than `1.0` speeds up the speech, while a value less than `1.0` slows it down.

**Python**:

> ℹ️ **Install librosa**
>
> This example uses [`librosa`](https://librosa.org/) for time stretching. Install it with `pip install librosa`.

The frames are buffered into 100 ms chunks with `AudioByteStream` before processing:

```python
from collections.abc import AsyncIterable

import librosa
import numpy as np

from livekit import rtc
from livekit.agents import Agent, ModelSettings, utils


class MyAgent(Agent):
    def __init__(self, *, speed_factor: float = 1.2) -> None:
        super().__init__(
            instructions="You are a helpful voice AI assistant.",
        )
        self.speed_factor = speed_factor

    async def tts_node(self, text: AsyncIterable[str], model_settings: ModelSettings):
        return self._process_audio_stream(
            Agent.default.tts_node(self, text, model_settings)
        )

    async def realtime_audio_output_node(
        self, audio: AsyncIterable[rtc.AudioFrame], model_settings: ModelSettings
    ) -> AsyncIterable[rtc.AudioFrame]:
        return self._process_audio_stream(
            Agent.default.realtime_audio_output_node(self, audio, model_settings)
        )

    async def _process_audio_stream(
        self, audio: AsyncIterable[rtc.AudioFrame]
    ) -> AsyncIterable[rtc.AudioFrame]:
        stream: utils.audio.AudioByteStream | None = None
        async for frame in audio:
            if stream is None:
                stream = utils.audio.AudioByteStream(
                    sample_rate=frame.sample_rate,
                    num_channels=frame.num_channels,
                    samples_per_channel=frame.sample_rate // 10,  # 100ms
                )
            for f in stream.push(frame.data):
                yield self._process_audio(f)

        for f in stream.flush():
            yield self._process_audio(f)

    def _process_audio(self, frame: rtc.AudioFrame) -> rtc.AudioFrame:
        # time-stretch without pitch change
        audio_data = np.frombuffer(frame.data, dtype=np.int16)
        stretched = librosa.effects.time_stretch(
            audio_data.astype(np.float32) / np.iinfo(np.int16).max,
            rate=self.speed_factor,
        )
        stretched = (stretched * np.iinfo(np.int16).max).astype(np.int16)
        return rtc.AudioFrame(
            data=stretched.tobytes(),
            sample_rate=frame.sample_rate,
            num_channels=frame.num_channels,
            samples_per_channel=stretched.shape[-1],
        )

```

---

**Node.js**:

> ℹ️ **Install soundtouchjs**
>
> This example uses [`soundtouchjs`](https://www.npmjs.com/package/soundtouchjs) for time stretching. Install it with `pnpm add soundtouchjs`.

`SoundTouch` buffers audio internally and emits stretched frames as they become ready. It processes interleaved stereo floats, so each mono frame is converted to floats for processing and back to 16-bit PCM afterward:

```typescript
import { voice } from "@livekit/agents";
import { AudioFrame } from "@livekit/rtc-node";
import { SoundTouch } from "soundtouchjs";

function createAgent(speedFactor = 1.2) {
  async function* processAudioStream(source: AsyncIterable<AudioFrame>): AsyncIterable<AudioFrame> {
    const soundTouch = new SoundTouch();
    soundTouch.tempo = speedFactor;
    let sampleRate = 24000;
    let channels = 1;

    // pull every stretched frame SoundTouch has buffered so far
    function* drain() {
      const output = soundTouch.outputBuffer;
      while (output.frameCount > 0) {
        const frames = output.frameCount;
        const interleaved = new Float32Array(frames * 2);
        output.receiveSamples(interleaved, frames);

        const data = new Int16Array(frames);
        for (let f = 0; f < frames; f++) {
          const sample = Math.max(-1, Math.min(1, interleaved[f * 2]));
          data[f] = Math.round(sample * 0x7fff);
        }
        yield new AudioFrame(data, sampleRate, channels, frames);
      }
    }

    for await (const frame of source) {
      sampleRate = frame.sampleRate;
      channels = frame.channels;

      // duplicate the mono channel into interleaved stereo floats
      const samples = frame.samplesPerChannel;
      const stereo = new Float32Array(samples * 2);
      for (let f = 0; f < samples; f++) {
        const sample = frame.data[f] / 0x8000;
        stereo[f * 2] = sample;
        stereo[f * 2 + 1] = sample;
      }

      soundTouch.inputBuffer.putSamples(stereo, 0, samples);
      soundTouch.process();
      yield* drain();
    }

    soundTouch.process();
    yield* drain();
  }

  return voice.Agent.create({
    instructions: "You are a helpful voice AI assistant.",
    async ttsNode(ctx, text, modelSettings) {
      const source = await voice.Agent.default.ttsNode(ctx.agent, text, modelSettings);
      return source ? processAudioStream(source) : null;
    },
    async realtimeAudioOutputNode(ctx, audio, modelSettings) {
      const source = await voice.Agent.default.realtimeAudioOutputNode(
        ctx.agent,
        audio,
        modelSettings,
      );
      return source ? processAudioStream(source) : null;
    },
  });
}
```

## Realtime model nodes

The following nodes are available for realtime models.

### Realtime audio output node

The `realtime_audio_output_node` is called when a realtime model outputs speech. This allows you to modify the audio output before it's sent to the user. For example, you can [adjust the volume of the audio output](https://docs.livekit.io/agents/multimodality/audio/customization.md#volume).

To use the default implementation, call `Agent.default.realtime_audio_output_node()`.

**Python**:

```python
from livekit.agents import ModelSettings, rtc, Agent
from typing import AsyncIterable

async def realtime_audio_output_node(
    self, audio: AsyncIterable[rtc.AudioFrame], model_settings: ModelSettings
) -> AsyncIterable[rtc.AudioFrame]:
    # Insert custom audio preprocessing here
    async for frame in Agent.default.realtime_audio_output_node(self, audio, model_settings):
        # Insert custom audio postprocessing here
        yield frame

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const agent = voice.Agent.create({
  instructions: "You are a helpful assistant.",
  async *realtimeAudioOutputNode(ctx, audio, modelSettings) {
    // Insert custom audio preprocessing here
    const outputStream = await voice.Agent.default.realtimeAudioOutputNode(
      ctx.agent,
      audio,
      modelSettings,
    );

    if (!outputStream) return;

    for await (const frame of outputStream) {
      // Insert custom audio postprocessing here
      yield frame;
    }
  },
});
```

## Transcription node

The `transcription_node` is part of the forwarding path for [agent transcriptions](https://docs.livekit.io/agents/build/text.md#transcriptions) and can be used to adjust or post-process text coming from an LLM (or any other source) into a final transcribed form. It may also be used to access [transcription timestamps](https://docs.livekit.io/agents/build/text.md#tts-aligned-transcriptions) for TTS-aligned transcriptions.

By default, the node simply passes the transcription to the task that forwards it to the designated output. You can override this node to:

- Clean up formatting
- Fix punctuation
- Strip unwanted characters
- Perform any other text transformations
- Access [transcription timestamps](https://docs.livekit.io/agents/build/text.md#tts-aligned-transcriptions) for TTS-aligned transcriptions

To use the default implementation, call `Agent.default.transcription_node()`.

**Python**:

```python
from livekit.agents import ModelSettings
from typing import AsyncIterable

async def transcription_node(self, text: AsyncIterable[str], model_settings: ModelSettings) -> AsyncIterable[str]:
    async for delta in text:
        yield delta.replace("😘", "")

```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const agent = voice.Agent.create({
  instructions: "You are a helpful assistant.",
  async *transcriptionNode(ctx, text, modelSettings) {
    for await (const chunk of text) {
      // chunk may be a plain string or a TimedString (for TTS-aligned transcriptions)
      yield typeof chunk === "string" ? chunk.replace("😘", "") : chunk;
    }
  },
});
```

## Examples

The following examples demonstrate advanced usage of nodes and hooks:

- **[Restaurant Agent](https://docs.livekit.io/reference/recipes/restaurant-agent.md)**: A restaurant front-of-house agent demonstrates the `on_enter` and `on_exit` lifecycle hooks.

- **[LLM Output Replacement](https://docs.livekit.io/reference/recipes/replacing_llm_output.md)**: Remove chain-of-thought reasoning from the LLM stream so it doesn't reach TTS or chat history.

- **[Keyword Detection](https://github.com/livekit-examples/python-agents-examples/blob/main/docs/examples/keyword-detection/keyword_detection.py)**: Use the `stt_node` to detect keywords in the user's speech.

- **[LLM Content Filter](https://docs.livekit.io/reference/recipes/llm_powered_content_filter.md)**: Implement content filtering in the `llm_node`.

---

This document was rendered at 2026-08-12T04:22:36.235Z.
For the latest version of this document, see [https://docs.livekit.io/agents/logic/nodes.md](https://docs.livekit.io/agents/logic/nodes.md).

To explore all LiveKit documentation, see [llms.txt](https://docs.livekit.io/llms.txt).
