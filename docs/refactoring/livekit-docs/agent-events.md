LiveKit docs › Agents framework › Events and error handling

---

# Events and error handling

> Guides and reference for events and error handling in LiveKit Agents.

## Events

`AgentSession` emits events to notify you of state changes and errors that may occur during a session. Each event is emitted with an event object as its sole argument. To configure automatic fallback to backup providers when model calls fail, see [Fallback strategies](https://docs.livekit.io/agents/logic/fallback-strategies.md).

### user_input_transcribed

A `UserInputTranscribedEvent` is emitted when user transcription is available.

#### Properties

- `transcript`: str - The transcribed text
- `is_final`: bool - Whether this is a final transcription
- `speaker_id`: str | None - Only available if speaker diarization is supported in your STT plugin
- `language`: str | None - The detected language of the transcription

#### Example

**Python**:

```python
from livekit.agents import UserInputTranscribedEvent

@session.on("user_input_transcribed")
def on_user_input_transcribed(event: UserInputTranscribedEvent):
    print(f"User input transcribed: {event.transcript}, "
          f"language: {event.language}, "
          f"final: {event.is_final}, "
          f"speaker id: {event.speaker_id}")

```

---

**Node.js**:

```ts
import { voice } from "@livekit/agents";

session.on(voice.AgentSessionEventTypes.UserInputTranscribed, (event) => {
  console.log(
    `User input transcribed: ${event.transcript}, language: ${event.language}, final: ${event.isFinal}, speaker id: ${event.speakerId}`,
  );
});
```

### conversation_item_added

A `ConversationItemAddedEvent` is emitted when an item is committed to the chat history. This event is emitted for both user and agent items.

#### Properties

- `item`: [ChatMessage](https://github.com/livekit/agents/blob/3ee369e7783a2588cffecc0725e582cac10efa39/livekit-agents/livekit/agents/llm/chat_context.py#L105) — includes a `metrics` field with per-turn latency data. See [Per-turn latency](https://docs.livekit.io/deploy/observability/data.md#per-turn-latency).

#### Example

**Python**:

```python
from livekit.agents import ConversationItemAddedEvent
from livekit.agents.llm import ChatMessage, ImageContent, AudioContent

...

@session.on("conversation_item_added")
def on_conversation_item_added(event: ConversationItemAddedEvent):
    if not isinstance(event.item, ChatMessage):
        return
    print(f"Conversation item added from {event.item.role}: {event.item.text_content}. interrupted: {event.item.interrupted}")
    # to iterate over all types of content:
    for content in event.item.content:
        if isinstance(content, str):
            print(f" - text: {content}")
        elif isinstance(content, ImageContent):
            # image is either a rtc.VideoFrame or URL to the image
            print(f" - image: {content.image}")
        elif isinstance(content, AudioContent):
            # frame is a list[rtc.AudioFrame]
            print(f" - audio: {content.frame}, transcript: {content.transcript}")

```

---

**Node.js**:

```ts
import { voice, llm } from "@livekit/agents";

// ...

session.on(voice.AgentSessionEventTypes.ConversationItemAdded, (event) => {
  if (!(event.item instanceof llm.ChatMessage)) {
    return;
  }
  console.log(
    `Conversation item added from ${event.item.role}: ${event.item.textContent}. interrupted: ${event.item.interrupted}`,
  );

  // to iterate over all types of content:
  for (const content of event.item.content) {
    switch (typeof content === "string" ? "string" : content.type) {
      case "string":
        console.log(` - text: ${content}`);
        break;
      case "image_content":
        // image is either a VideoFrame or URL to the image
        console.log(` - image: ${content.image}`);
        break;
      case "audio_content":
        // frame is an array of AudioFrame
        console.log(` - audio: ${content.frame}, transcript: ${content.transcript}`);
        break;
    }
  }
});
```

### function_tools_executed

`FunctionToolsExecutedEvent` is emitted after all function tools have been executed for a given user input.

#### Methods

- `zipped()` returns a list of tuples of function calls and their outputs.
- `cancel_tool_reply()` cancels the automatic reply after tool execution.
- `cancel_agent_handoff()` cancels any pending agent handoff.

#### Properties

- `function_calls`: list[[FunctionCall](https://docs.livekit.io/reference/python/v1/livekit/agents/llm/index.html.md#livekit.agents.llm.FunctionCall)]
- `function_call_outputs`: list[[FunctionCallOutput](https://docs.livekit.io/reference/python/v1/livekit/agents/llm/index.html.md#livekit.agents.llm.FunctionCallOutput)]
- `has_tool_reply`: bool - Whether a tool reply is required
- `has_agent_handoff`: bool - Whether an agent handoff is required

### session_usage_updated

A `SessionUsageUpdatedEvent` is emitted whenever new per-model usage data is available. Use it for cost estimation or billing exports. For more information, see [Session usage](https://docs.livekit.io/deploy/observability/data.md#session-usage).

#### Properties

- `usage`: AgentSessionUsage — contains a `model_usage` list of per-model usage summaries (LLM, TTS, STT, and interruption). Each entry includes provider, model, token counts, and duration fields. See [Session usage](https://docs.livekit.io/deploy/observability/data.md#session-usage) for field details.

#### Example

**Python**:

```python
from livekit.agents import SessionUsageUpdatedEvent

@session.on("session_usage_updated")
def on_session_usage_updated(ev: SessionUsageUpdatedEvent):
    for usage in ev.usage.model_usage:
        print(f"{usage.provider}/{usage.model}: {usage}")

```

---

**Node.js**:

```ts
import { voice } from "@livekit/agents";

session.on(voice.AgentSessionEventTypes.SessionUsageUpdated, (ev) => {
  for (const usage of ev.usage.modelUsage) {
    console.log(`${usage.provider}/${usage.model}:`, usage);
  }
});
```

### metrics_collected (deprecated)

> 🔥 **Deprecated**
>
> The session-level `metrics_collected` event is deprecated. Use [`session_usage_updated`](#session_usage_updated) for usage tracking and [`ChatMessage.metrics`](https://github.com/livekit/agents/blob/3ee369e7783a2588cffecc0725e582cac10efa39/livekit-agents/livekit/agents/llm/chat_context.py#L105) for per-turn latency. Per-plugin `metrics_collected` events are not deprecated.

`MetricsCollectedEvent` is emitted when new metrics are available to be reported. Metrics include STT, LLM, TTS, VAD, EOU, and when [adaptive interruption handling](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling.md) is enabled, [InterruptionMetrics](https://docs.livekit.io/deploy/observability/data.md#interruptionmetrics) for barge-in detection latency and request volume. For more information on metrics, see [Metrics and usage data](https://docs.livekit.io/deploy/observability/data.md#metrics).

#### Properties

- `metrics`: Union[STTMetrics, LLMMetrics, TTSMetrics, VADMetrics, EOUMetrics, InterruptionMetrics]

### speech_created

`SpeechCreatedEvent` is emitted when new agent speech is created. Speech could be created for any of the following reasons:

- the user has provided input
- `session.say` is used to create agent speech
- `session.generate_reply` is called to create a reply

#### Properties

- `user_initiated`: str - True if speech was created using public methods like `say` or `generate_reply`
- `source`: str - "say", "generate_reply", or "tool_response"
- `speech_handle`: [SpeechHandle](https://docs.livekit.io/agents/build/audio.md#speechhandle) - handle to track speech playout.

### agent_state_changed

`AgentStateChangedEvent` is emitted when the agent's state changes. The `lk.agent.state` attribute on the agent participant is updated to reflect the new state, allowing frontend code to easily respond to changes.

#### Properties

- `old_state`: AgentState
- `new_state`: AgentState

#### AgentState

The agent could be in one of the following states:

- `initializing` - agent is starting up. This should be brief.
- `idle` - agent is ready but not actively processing
- `listening` - agent is waiting for user input
- `thinking` - agent is processing user input
- `speaking` - agent is speaking

### user_state_changed

`UserStateChangedEvent` is emitted when the user's state changes. This change is driven by the VAD module running on the user's audio input.

#### Properties

- `old_state`: UserState
- `new_state`: UserState

#### UserState

The user's state can be one of the following:

- `speaking` - VAD detected user has started speaking
- `listening` - VAD detected the user has stopped speaking
- `away` - The user hasn't responded for a while (default: 15s). Specify a custom timeout with `AgentSession(user_away_timeout=...)`.

#### Example

- **[Handling inactive users](https://docs.livekit.io/agents/logic/sessions.md#handling-inactive-users)**: Detect idle users, prompt them to check in, and end the session if they don't respond.

### overlapping_speech

`OverlappingSpeechEvent` with type `overlapping_speech` is emitted when adaptive interruption handling is enabled and user speech is detected. The `is_interruption` property indicates whether the speech is an interruption.

#### Properties

- `type`: str - "overlapping_speech".
- `detected_at`: float - Timestamp (in seconds) when the event was fired.
- `is_interruption`: bool - Whether interruption is detected.
- `total_duration`: float - Round trip time (RTT) taken to perform the inference, in seconds.
- `prediction_duration`: float - Time taken to perform the inference from the model side, in seconds.
- `detection_delay`: float - Total time from the onset of the speech to the final prediction, in seconds.
- `overlap_started_at`: float | None - Timestamp (in seconds) when the overlap speech started.
- `speech_input`: array[int16] | None - The audio input that was used for the inference.
- `probabilities`: array[float32] | None - The raw probabilities for the interruption detection.
- `probability`: float - The conservative estimated probability of the interruption event.
- `num_requests`: int - Number of requests sent to the interruption detection model for this event.

### agent_false_interruption

`AgentFalseInterruptionEvent` is emitted when the agent detects a [false interruption](https://docs.livekit.io/agents/logic/turns.md#false-interruptions), that is, user speech that initially appeared to interrupt the agent, but is determined not to be a true interruption.

#### Properties

- `type`: str - The type of false interruption: "agent_false_interruption".
- `resumed`: bool - Whether the false interruption was resumed automatically.
- `created_at`: datetime - The timestamp when the false interruption was created.

### close

The `CloseEvent` is emitted when the AgentSession has closed and the agent is no longer running. This can occur for several reasons:

- The user ended the conversation
- `session.aclose()` was called
- The room was deleted, disconnecting the agent
- An unrecoverable error occurred during the session

#### Properties

- `error`: LLMError | STTError | TTSError | RealtimeModelError | None - The error that caused the session to close, if applicable
- `reason`: CloseReason - The reason why the session closed

#### CloseReason

The close reason can be one of the following:

- `error` - Session closed due to an error
- `job_shutdown` - Agent job was shut down
- `participant_disconnected` - Participant disconnected from the room
- `user_initiated` - User explicitly closed the session
- `task_completed` - Task was completed successfully

## Handling errors

In addition to state changes, it's important to handle errors that occur during a session. In realtime voice conversations, a model API failure can leave the agent unable to continue. To automatically fail over to backup providers when an error occurs, see [Fallback strategies](https://docs.livekit.io/agents/logic/fallback-strategies.md). For manual control over how the session responds to errors, use the `error` event.

### Error event

`AgentSession` emits `ErrorEvent` when an STT, LLM, TTS, or realtime model error occurs. Each error has a `recoverable` field that indicates whether the session retries the failed operation automatically.

- If `recoverable` is `True`, the event is informational and the session continues normally.
- If `recoverable` is `False` (for example, after exhausting retries), the session closes unless you intervene.

#### Properties

The `ErrorEvent` includes the error itself and the pipeline component that raised it:

- `error`: LLMError | STTError | TTSError | RealtimeModelError - the error that occurred. The `recoverable` field is a property of this object.
- `source`: LLM | STT | TTS | RealtimeModel - the source object responsible for the error.

#### Basic error handling

Listen for the `error` event and check the `recoverable` field to decide how to respond. For unrecoverable errors, use `session.say()` to notify the user before the session closes:

**Python**:

```python
from livekit.agents import ErrorEvent

@session.on("error")
def on_error(ev: ErrorEvent):
    if ev.error.recoverable:
        return

    logger.error(f"Unrecoverable error from {type(ev.source).__name__}: {ev.error}")

    session.say(
        "I'm having trouble connecting right now. Please try again shortly.",
        allow_interruptions=False,
    )

```

---

**Node.js**:

```ts
import { voice } from "@livekit/agents";

session.on(voice.AgentSessionEventTypes.Error, (ev) => {
  if (ev.error.recoverable) {
    return;
  }

  logger.error(`Unrecoverable error: ${ev.error}`);

  session.say("I'm having trouble connecting right now. Please try again shortly.", {
    allowInterruptions: false,
  });
});
```

### Pre-recorded audio fallback

When TTS fails, calling `session.say()` with only text doesn't work because TTS is unavailable. To handle this, pre-record a fallback audio file and pass it to `session.say()` with the `audio` parameter. The session plays the audio directly, bypassing TTS entirely:

**Python**:

```python
from livekit.agents.utils.audio import audio_frames_from_file
from livekit.agents import ErrorEvent

custom_audio = "path/to/error_message.ogg"

@session.on("error")
def on_error(ev: ErrorEvent):
    if ev.error.recoverable:
        return

    # Bypass TTS by providing pre-recorded audio frames
    session.say(
        "I'm sorry, I'm having trouble connecting right now. Please try again shortly.",
        audio=audio_frames_from_file(custom_audio),
        allow_interruptions=False,
    )

```

---

**Node.js**:

```ts
import { audioFramesFromFile, voice } from "@livekit/agents";

const customAudio = "path/to/error_message.ogg";

session.on(voice.AgentSessionEventTypes.Error, (ev) => {
  if (ev.error.recoverable) {
    return;
  }

  // Bypass TTS by providing pre-recorded audio frames
  session.say("I'm sorry, I'm having trouble connecting right now. Please try again shortly.", {
    audio: audioFramesFromFile(customAudio),
    allowInterruptions: false,
  });
});
```

### Continue after an error

By default, an unrecoverable error closes the session. To keep the session alive, set `error.recoverable` to `True` inside your error handler. The recovery strategy depends on which component failed:

- **LLM, TTS, and realtime model errors** are safe to mark as recoverable because these components are recreated for each response. The next user turn gets a fresh instance.
- **STT errors** require resetting the agent because the STT stream persists for the entire session. Call `update_agent` with the current agent to restart the stream.

**Python**:

```python
from livekit.agents import ErrorEvent, llm, multimodal, stt, tts

@session.on("error")
def on_error(ev: ErrorEvent):
    if ev.error.recoverable:
        return

    # LLM, TTS, and realtime model are recreated each response — safe to continue
    if isinstance(ev.source, (tts.TTS, llm.LLM, multimodal.RealtimeModel)):
        ev.error.recoverable = True
        return

    # STT persists for the session — reset the agent to restart the stream
    if isinstance(ev.source, stt.STT):
        session.update_agent(session.current_agent)
        ev.error.recoverable = True
        return

```

---

**Node.js**:

```ts
import { voice, stt, tts, llm, multimodal } from "@livekit/agents";

session.on(voice.AgentSessionEventTypes.Error, (ev) => {
  if (ev.error.recoverable) {
    return;
  }

  // LLM, TTS, and realtime model are recreated each response — safe to continue
  if (
    ev.source instanceof tts.TTS ||
    ev.source instanceof llm.LLM ||
    ev.source instanceof multimodal.RealtimeModel
  ) {
    ev.error.recoverable = true;
    return;
  }

  // STT persists for the session — reset the agent to restart the stream
  if (ev.source instanceof stt.STT) {
    session.updateAgent(session.currentAgent);
    ev.error.recoverable = true;
    return;
  }
});
```

---

This document was rendered at 2026-08-12T04:22:51.167Z.
For the latest version of this document, see [https://docs.livekit.io/reference/agents/events.md](https://docs.livekit.io/reference/agents/events.md).

To explore all LiveKit documentation, see [llms.txt](https://docs.livekit.io/llms.txt).
