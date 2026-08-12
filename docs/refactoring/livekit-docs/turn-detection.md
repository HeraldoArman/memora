LiveKit docs › Logic & Structure › Turn detection & interruptions › Overview

---

# Turns overview

> Guide to managing conversation turns in voice AI.

## Overview

Turn detection is the process of determining when a user begins or ends their "turn" in a conversation. This lets the agent know when to start listening and when to respond.

Most turn detection techniques rely on voice activity detection (VAD) to detect periods of silence in user input. The agent applies heuristics to the VAD data to perform phrase endpointing, which determines the end of a sentence or thought. The agent can use endpoints alone or apply a model that understands the meaning of speech to determine when a turn is complete.

Effective turn detection and interruption management is essential to great voice AI experiences.

This page covers user-side detection and interruption handling. Turn-taking is also affected by features that live in other parts of the agent pipeline (preemptive generation, background voice cancellation, and agent-side speech scheduling) that don't fit cleanly into either category. For a recommended starting config that combines all of these, plus a troubleshooting matrix, see [Turn-taking tuning](https://docs.livekit.io/agents/logic/turns/tuning.md).

## Turn detection

Turn detection determines when the user has finished speaking (so the agent can respond) and when the user starts speaking mid-response (so the agent can yield).

LiveKit supports multiple detection strategies and optional features that work together to make turn-taking feel natural:

- **Detection modes**: Choose how the session determines when a user turn is complete. For most agents, use LiveKit's [turn detector model](#turn-detector-model). It's the default, and it handles the widest range of conversations. The other modes are for specific situations:

| Mode | When to use it |
| [Turn detector model](#turn-detector-model) | **Recommended for most agents, and the default.** Predicts end of turn from both the meaning of speech and its acoustic properties, on top of VAD. |
| [Realtime models](#realtime-models) | When using a realtime LLM (for example, the OpenAI Realtime API or Gemini Live API), rely on its built-in server-side detection or pair it with the turn detector model. |
| [VAD only](#vad-only) | When you need minimal latency, or support for a spoken language the turn detector model doesn't cover. |
| [STT endpointing](#stt-endpointing) | When you're already using an STT with its own turn detection (for example, AssemblyAI or Deepgram Flux). |
| [Manual turn control](#manual) | For push-to-talk or fully explicit control over turn boundaries. |

- **Supporting features**: Regardless of detection mode, you can tune behavior with additional turn handling options. The following features are available in addition to turn detection modes to make turn-taking feel natural:

| Feature | Description |
| [Endpointing delay](#endpointing-configuration) | Controls how long the agent waits after speech (or after an STT end-of-utterance signal) before treating the turn as complete. Use fixed `min_delay` and `max_delay`, or dynamic endpointing (Python only) to adapt the delay based on session pause statistics. |
| [Adaptive interruption handling](#adaptive-interruption-handling) | Controls how the agent detects and reacts when the user speaks while the agent is talking. Adaptive interruption handling can distinguish true interruptions from conversational backchanneling. |
| [VAD](https://docs.livekit.io/agents/logic/turns/vad.md) | Use VAD in addition to turn detection modes to improve end-of-turn timing and interruption responsiveness. |
| [Noise cancellation](#noise-cancellation) | Enhanced noise cancellation improves the quality of turn detection and speech-to-text (STT) for voice AI apps by reducing background noise. |

### Turn detector model

The turn detector model is the recommended way to achieve the natural behavior of an agent that listens while the user speaks and replies after they finish their thought. It's also the default: `AgentSession` enables the [audio turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector.md#audio-turn-detector) automatically, so most agents need no turn-detection configuration at all.

It's built for the STT-LLM-TTS pipeline alongside a VAD:

- **[LiveKit turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector.md)**: Audio and text models that detect end of turn from the meaning of speech.

- **[Silero VAD](https://docs.livekit.io/agents/logic/turns/vad.md)**: Silero VAD model for voice activity detection.

The following example uses the recommended [audio turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector.md#audio-turn-detector):

**Python**:

```python
from livekit.agents import AgentSession, TurnHandlingOptions, inference

session = AgentSession(
    turn_handling=TurnHandlingOptions(
        turn_detection=inference.TurnDetector(),
    ),
    # ... stt, tts, llm, etc.
)
```

---

**Node.js**:

```typescript
import { inference, voice } from "@livekit/agents";

const session = new voice.AgentSession({
  turnHandling: {
    turnDetection: new inference.TurnDetector(),
  },
  // ... stt, tts, llm, etc.
});
```

See the [Voice AI quickstart](https://docs.livekit.io/agents/start/voice-ai.md) for a complete example.

### Realtime models

Realtime models include built-in turn detection options based on VAD and other techniques. Set the `turn_detection` parameter to `"realtime_llm"` and configure the realtime model's turn detection options directly.

You can also use the [LiveKit turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector.md) with realtime models.

- **[OpenAI Realtime API turn detection](https://docs.livekit.io/agents/models/realtime/plugins/openai.md#turn-detection)**: Turn detection options for the OpenAI Realtime API.

- **[Gemini Live API turn detection](https://docs.livekit.io/agents/models/realtime/plugins/gemini.md#turn-detection)**: Turn detection options for the Gemini Live API.

#### Interruption in realtime mode

When you use a realtime model with server-side turn detection, the model decides when the user is interrupting. The agent forwards user audio to the model unchanged and reacts to the model's interruption signal directly. As a result, [InterruptionOptions](https://docs.livekit.io/reference/agents/turn-handling-options.md#interruptionoptions) mostly does not apply: `enabled` must remain `True`, `discard_audio_if_uninterruptible` still gates buffered audio, and every other field is ignored. Tune interruption on the model itself instead. For example, the OpenAI Realtime API exposes `threshold`, `prefix_padding_ms`, and `silence_duration_ms` on its server VAD `TurnDetection` object (and `eagerness` and `interrupt_response` for semantic VAD).

> 🔥 **Disabling interruptions is a hard error**
>
> With a realtime model that has server-side turn detection enabled, the SDK rejects `turn_handling.interruption.enabled=False` at session start with a `ValueError`. To disable user interruptions for a realtime model, set the model's own `turn_detection=None` and use VAD on the `AgentSession` instead.

`discard_audio_if_uninterruptible` controls whether buffered user audio is forwarded to the realtime session while the agent is in a non-interruptible utterance.

The following telephony-friendly configuration uses server VAD with a higher threshold for noisy phone audio and a tighter silence window for quicker turn closing.

**Python**:

```python
from livekit.agents import AgentSession
from livekit.plugins.openai import realtime
from openai.types.beta.realtime.session import TurnDetection

session = AgentSession(
    llm=realtime.RealtimeModel(
        turn_detection=TurnDetection(
            type="server_vad",
            threshold=0.7,  # less sensitive (better for noisy phone audio)
            prefix_padding_ms=300,
            silence_duration_ms=400,  # tighter silence window for snappier turn closing
        ),
    ),
    # ... tts, etc.
)
```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";
import * as openai from "@livekit/agents-plugin-openai";

const session = new voice.AgentSession({
  llm: new openai.realtime.RealtimeModel({
    turnDetection: {
      type: "server_vad",
      threshold: 0.7,
      prefix_padding_ms: 300,
      silence_duration_ms: 400,
    },
  }),
  // ... tts, etc.
});
```

For the full set of provider-side options, see [OpenAI Realtime API turn detection](https://docs.livekit.io/agents/models/realtime/plugins/openai.md#turn-detection) or [Gemini Live API turn detection](https://docs.livekit.io/agents/models/realtime/plugins/gemini.md#turn-detection).

### VAD only

Use VAD-only detection when you need minimal latency or support for a spoken language the [turn detector model](#turn-detector-model) doesn't cover. To use VAD alone, set `turn_detection="vad"`.

**Python**:

```python
session = AgentSession(
    turn_handling=TurnHandlingOptions(
        turn_detection="vad",
    ),
    # ... stt, tts, llm, etc.
)
```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const session = new voice.AgentSession({
  turnHandling: {
    turnDetection: "vad",
  },
  // ... stt, tts, llm, etc.
});
```

### STT endpointing

Some STT providers, such as [AssemblyAI](https://docs.livekit.io/agents/models/stt/assemblyai.md) and [Deepgram Flux](https://docs.livekit.io/agents/models/stt/deepgram.md), include their own turn detection. If you're already using one, you can rely on it directly instead of the [turn detector model](#turn-detector-model).

The session's bundled VAD continues to handle interruption detection, so the agent stays responsive while the STT determines turn boundaries.

To use STT endpointing, set `turn_detection="stt"` and provide an STT plugin.

**Python**:

```python
session = AgentSession(
    turn_handling=TurnHandlingOptions(
        turn_detection="stt",
    ),
    stt=assemblyai.STT(),  # AssemblyAI is the recommended STT plugin for STT-based endpointing
    # ... tts, llm, etc.
)
```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";
import * as assemblyai from "@livekit/agents-plugin-assemblyai";

const session = new voice.AgentSession({
  stt: new assemblyai.STT(), // AssemblyAI is the recommended STT plugin for STT-based endpointing
  turnHandling: {
    turnDetection: "stt",
  },
  // ... tts, llm, etc.
});
```

#### Additional endpointing configuration options

You can configure additional endpointing behavior using the `endpointing` key in the turn handling options. By default, the agent uses fixed endpointing and always uses the configured `min_delay` and `max_delay`. With dynamic endpointing, the agent adapts the delay within that range based on session pause statistics, so turn-taking can feel more responsive over time.

To learn more, see the [EndpointingOptions](https://docs.livekit.io/reference/agents/turn-handling-options.md#endpointingoptions) reference.

### Manual turn control

For push-to-talk or fully explicit control over turn boundaries, disable automatic turn detection by setting `turn_detection="manual"` in the turn handling options for the `AgentSession`.

You can control the user's turn with `session.interrupt()`, `session.clear_user_turn()`, and `session.commit_user_turn()` methods.

> 💡 **Manual control vs. text-only sessions**
>
> This is different from toggling audio input/output for [text-only sessions](https://docs.livekit.io/agents/build/text.md#text-only-sessions).

For instance, you can use this to implement a push-to-talk interface. Here is a simple example using [RPC](https://docs.livekit.io/transport/data/rpc.md) methods that the frontend can call:

**Python**:

```python
session = AgentSession(
    turn_handling=TurnHandlingOptions(
        turn_detection="manual",
    ),
    # ... stt, tts, llm, etc.
)

# Disable audio input at the start
session.input.set_audio_enabled(False)


# When user starts speaking
@ctx.room.local_participant.register_rpc_method("start_turn")
async def start_turn(data: rtc.RpcInvocationData):
    session.interrupt()  # Stop any current agent speech
    session.clear_user_turn()  # Clear any previous input
    session.input.set_audio_enabled(True)  # Start listening


# When user finishes speaking
@ctx.room.local_participant.register_rpc_method("end_turn")
async def end_turn(data: rtc.RpcInvocationData):
    session.input.set_audio_enabled(False)  # Stop listening
    session.commit_user_turn()  # Process the input and generate response


# When user cancels their turn
@ctx.room.local_participant.register_rpc_method("cancel_turn")
async def cancel_turn(data: rtc.RpcInvocationData):
    session.input.set_audio_enabled(False)  # Stop listening
    session.clear_user_turn()  # Discard the input
```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

const session = new voice.AgentSession({
  turnHandling: {
    turnDetection: "manual",
  },
  // ... stt, tts, llm, etc.
});

// Disable audio input at the start
session.input.setAudioEnabled(false);

// When user starts speaking
ctx.room.localParticipant.registerRpcMethod("start_turn", async (data) => {
  session.interrupt(); // Stop any current agent speech
  session.clearUserTurn(); // Clear any previous input
  session.input.setAudioEnabled(true); // Start listening
  return "ok";
});

// When user finishes speaking
ctx.room.localParticipant.registerRpcMethod("end_turn", async (data) => {
  session.input.setAudioEnabled(false); // Stop listening
  session.commitUserTurn(); // Process the input and generate response
  return "ok";
});

// When user cancels their turn
ctx.room.localParticipant.registerRpcMethod("cancel_turn", async (data) => {
  session.input.setAudioEnabled(false); // Stop listening
  session.clearUserTurn(); // Discard the input
  return "ok";
});
```

These RPC methods map to the user pressing and releasing a talk button on the frontend:

- `start_turn`: interrupts the agent, clears any buffered input, and starts listening to the user.
- `end_turn`: stops listening and commits the turn so the agent generates a reply.
- `cancel_turn`: stops listening and discards the turn without a reply.

#### Capture the turn transcript

Available in:

- [ ] Node.js
- [x] Python

Both SDKs commit a turn with `commit_user_turn()`, but only the Python SDK returns the transcript. In Python, `commit_user_turn()` returns an `asyncio.Future[str]` that resolves with the user's transcript once speech-to-text (STT) completes. Await it to capture what the user said:

```python
@ctx.room.local_participant.register_rpc_method("end_turn")
async def end_turn(data: rtc.RpcInvocationData):
    session.input.set_audio_enabled(False)  # Stop listening
    transcript = await session.commit_user_turn(
        # How long to wait for the final transcript after committing the turn.
        # Increase this value if your STT is slow to return final results.
        transcript_timeout=5.0,
        # Silence appended to the STT stream to flush the buffer and force a final transcript.
        stt_flush_duration=2.0,
    )
    logger.info(f"user said: {transcript}")
```

Both `transcript_timeout` and `stt_flush_duration` default to `2.0` seconds.

#### Commit a turn without a reply

Available in:

- [ ] Node.js
- [x] Python

In Python, pass `skip_reply=True` to `commit_user_turn()` to commit and transcribe the user's turn without generating a reply. This is useful when you only need the transcript, or when your app decides separately when the agent should speak:

```python
transcript = await session.commit_user_turn(skip_reply=True)
```

#### Listen to a specific participant

Available in:

- [ ] Node.js
- [x] Python

In a room with multiple participants, route audio input to whoever started the turn so the agent only listens to that caller. Use the caller identity from the RPC invocation:

```python
@ctx.room.local_participant.register_rpc_method("start_turn")
async def start_turn(data: rtc.RpcInvocationData):
    session.interrupt()
    session.clear_user_turn()
    # Listen to the participant who started the turn.
    session.room_io.set_participant(data.caller_identity)
    session.input.set_audio_enabled(True)
```

#### Ignore empty turns

If a user commits a turn without speaking, you can stop the agent from replying by overriding the [`on_user_turn_completed`](https://docs.livekit.io/agents/logic/nodes.md#on_user_turn_completed) node and raising `StopResponse` when the transcript is empty:

**Python**:

```python
from livekit.agents.llm import ChatContext, ChatMessage, StopResponse


class MyAgent(Agent):
    async def on_user_turn_completed(self, turn_ctx: ChatContext, new_message: ChatMessage) -> None:
        if not new_message.text_content:
            raise StopResponse()
```

---

**Node.js**:

```typescript
import { llm, voice } from "@livekit/agents";

const agent = voice.Agent.create({
  async onUserTurnCompleted(ctx, chatCtx, newMessage) {
    if (!newMessage.textContent || newMessage.textContent.length === 0) {
      throw new voice.StopResponse();
    }
  },
});
```

### Reducing background noise

[Enhanced noise cancellation](https://docs.livekit.io/transport/media/noise-cancellation.md) is available in LiveKit Cloud and improves the quality of turn detection and speech-to-text (STT) for voice AI apps. You can add background noise and voice cancellation to your agent by adding it to the [room options](https://docs.livekit.io/agents/logic/sessions.md#room-options) when you start your agent session. To learn how to enable it, see the [Voice AI quickstart](https://docs.livekit.io/agents/start/voice-ai.md).

## Interruptions

The framework pauses the agent's speech whenever it detects user speech in the input audio, ensuring the agent feels responsive. The user can interrupt the agent at any time, either by speaking (with automatic turn detection) or via the `session.interrupt()` method. When interrupted, the agent stops speaking and automatically truncates its conversation history to include only the portion of the speech that the user heard before interruption.

> ℹ️ **Disabling interruptions**
>
> You can disable user interruptions when [scheduling speech](https://docs.livekit.io/agents/build/audio.md#manual) using the `say()` or `generate_reply()` methods by setting `turn_handling.interruption.enabled` to `false`. To learn more, see [Interruption mode](#interruption-mode).

To explicitly interrupt the agent, call the `interrupt()` method on the handle or session at any time. This can be performed even when interruption is disabled in the turn handling options.

**Python**:

```python
handle = session.say("Hello world")
handle.interrupt()

# or from the session
session.interrupt()
```

---

**Node.js**:

```typescript
const handle = session.say("Hello world");
handle.interrupt();

// or from the session
session.interrupt();
```

> 💡 **Long-running tool calls**
>
> See the section on tool [interruptions](https://docs.livekit.io/agents/build/tools.md#interruptions) for more information on handling interruptions during long-running tool calls.

### Interruption mode

The interruption options control whether the agent can be interrupted and how interruptions are detected. Key settings:

- `enabled`: When `True`, the agent can be interrupted by user speech; when `False`, the agent cannot be interrupted.
- `mode`: Determines how the framework detects interruptions. Only applies when `enabled` is `True`. The following modes are available:- `"adaptive"`: Adaptive interruption handling. This is the default mode for agents deployed to LiveKit Cloud, when used with most STT providers. To learn more see [Adaptive interruption handling](#adaptive-interruption-handling).
- `"vad"`: Use [VAD](https://docs.livekit.io/agents/logic/turns/vad.md) for interruption detection. Interruption detection is based on speech start and stop cues.

For realtime models with server-side turn detection, see [Interruption in realtime mode](#interruption-in-realtime-mode) for which of these fields are ignored.

To learn more, see the [InterruptionOptions](https://docs.livekit.io/reference/agents/turn-handling-options.md#interruptionoptions) reference.

### Adaptive interruption handling

Adaptive interruption handling enables your agent to intelligently detect when users interrupt mid-response. Rather than using fixed thresholds, adaptive interruption handling analyzes the audio signals to determine whether an interruption is intentional.

- **[Adaptive interruption handling](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling.md)**: Use adaptive interruption handling to distinguish between true interruptions and conversational backchanneling.

### False interruptions

In some cases, the framework detects human speech audio and interrupts the agent, but the transcription comes up empty as no actual words are spoken. In these cases, the VAD-based interruption is considered a false positive. By default, the agent resumes speaking from where it left off after a false interruption. You can configure this behavior using the `resume_false_interruption` and `false_interruption_timeout` parameters.

- `false_interruption_timeout`: If an interruption is detected, but the user is silent, this is the duration of silence to wait after an interruption before emitting an `agent_false_interruption` event. Python uses seconds (for example, `2.0`); Node.js uses milliseconds (for example, `2000`).
- `resume_false_interruption`: Whether to resume the agent's speech after a false interruption is detected. If `True`, the agent continues speaking from where it left off after the `false_interruption_timeout` period has passed with no user transcription.

Set these parameters in the `interruption` key of the turn handling options. For example, the following configuration resumes the agent's speech after a false interruption is detected after 2 seconds of silence. Pass it to the `turn_handling` parameter of `AgentSession`:

**Python**:

```python
turn_handling = {
    "interruption": {
        "false_interruption_timeout": 2.0,
        "resume_false_interruption": True,
        # ... other interruption parameters
    },
}
```

---

**Node.js**:

```typescript
const session = new voice.AgentSession({
  turnHandling: {
    interruption: {
      falseInterruptionTimeout: 2000,
      resumeFalseInterruption: true,
      // ... other interruption parameters
    },
  },
  // ... other parameters
});
```

For more information on these parameters, see the [InterruptionOptions](https://docs.livekit.io/reference/agents/turn-handling-options.md#interruptionoptions) reference.

### Additional configuration options

For a complete list of interruption options, see the [InterruptionOptions](https://docs.livekit.io/reference/agents/turn-handling-options.md#interruptionoptions) reference.

The following additional parameters are available in the `interruption` options object `InterruptionOptions`:

- `discard_audio_if_uninterruptible`: When `True`, drop buffered audio if the agent is speaking and cannot be interrupted.
- `min_duration`: Minimum duration of speech (in seconds) to register as an interruption.
- `min_words`: Minimum number of words to be considered as an interruption. Only used if STT is enabled. Set to a value greater than `0` to require actual speech content before triggering interruptions.

To learn more about these parameters, see the [InterruptionOptions](https://docs.livekit.io/reference/agents/turn-handling-options.md#interruptionoptions) reference.

## User turn limit

User turn limits cap how long a user can speak before the agent interrupts. This is useful for voicebot scenarios where a caller might monopolize the turn: long-form callers, voicemail greetings, or users reading off a list. Unlike [interruptions](#interruptions), which are user-initiated, user turn limits are agent-initiated.

Configure user turn limits in the `user_turn_limit` key of the turn handling options. Set `max_words`, `max_duration`, or both. Both default to disabled, so the feature is off until you opt in. Pass the options to the `turn_handling` parameter of `AgentSession`:

**Python**:

```python
session = AgentSession(
    turn_handling={
        "user_turn_limit": {
            "max_words": 100,
            "max_duration": 30.0,
        },
    },
    # ... other parameters
)
```

---

**Node.js**:

```typescript
const session = new voice.AgentSession({
  turnHandling: {
    userTurnLimit: {
      maxWords: 100,
      maxDuration: 30_000,
    },
  },
  // ... other parameters
});
```

Python uses seconds for `max_duration`. Node.js uses milliseconds for `maxDuration`.

Word count and duration accumulate across consecutive user turns and reset only when the agent transitions to the `speaking` state. A user who pauses briefly mid-monologue still trips the threshold.

When a threshold is crossed, the framework calls the agent's [`on_user_turn_exceeded`](https://docs.livekit.io/agents/logic/nodes.md#on_user_turn_exceeded) hook with a `UserTurnExceededEvent`. The default implementation calls `generate_reply` with `allow_interruptions=False` and `tool_choice="none"` to politely cut in. Override the hook to customize the behavior:

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

const agent = voice.Agent.create({
  async onUserTurnExceeded(ctx, ev) {
    await ctx.session.say("Sorry to jump in. Can I help with anything specific?");
  },
});
```

> ℹ️ **Default reply cannot be interrupted**
>
> The default `on_user_turn_exceeded` implementation calls `generate_reply` with `allow_interruptions=False`, so the user cannot cut in while the agent is delivering the cut-in reply. Override the hook if you need different interruption semantics.

The framework skips the `on_user_turn_exceeded` callback if the agent enters the `speaking` state before the threshold fires. This happens when the user pauses long enough for end-of-utterance detection to end their turn naturally and the agent's normal reply starts playing.

To learn more, see the [UserTurnLimitOptions](https://docs.livekit.io/reference/agents/turn-handling-options.md#userturnlimitoptions) reference and the [`on_user_turn_exceeded`](https://docs.livekit.io/agents/logic/nodes.md#on_user_turn_exceeded) hook docs.

## Session events

The `AgentSession` emits events for turn handling. For a list of all available events, see the [Events](https://docs.livekit.io/reference/agents/events.md) reference.

### Interruption events

The `AgentSession` exposes interruption events to monitor the flow of a conversation:

**Python**:

```python
@session.on("user_interruption_detected")
def on_interruption(ev):
    print(f"User interrupted at: {ev.timestamp}")
    print(f"Interruption probability: {ev.probability}")


@session.on("agent_false_interruption")
def on_false_interruption(ev):
    print("False interruption detected, resuming speech")
```

---

**Node.js**:

```typescript
session.on("user_interruption_detected", (ev) => {
  console.log(`User interrupted at: ${ev.timestamp}`);
  console.log(`Interruption probability: ${ev.probability}`);
});

session.on("agent_false_interruption", () => {
  console.log("False interruption detected, resuming speech");
});
```

### Turn-taking events

The `AgentSession` exposes user and agent state events to monitor the flow of a conversation:

**Python**:

```python
from livekit.agents import UserStateChangedEvent, AgentStateChangedEvent


@session.on("user_state_changed")
def on_user_state_changed(ev: UserStateChangedEvent):
    if ev.new_state == "speaking":
        print("User started speaking")
    elif ev.new_state == "listening":
        print("User stopped speaking")
    elif ev.new_state == "away":
        print("User is not present (e.g. disconnected)")


@session.on("agent_state_changed")
def on_agent_state_changed(ev: AgentStateChangedEvent):
    if ev.new_state == "initializing":
        print("Agent is starting up")
    elif ev.new_state == "idle":
        print("Agent is ready but not processing")
    elif ev.new_state == "listening":
        print("Agent is listening for user input")
    elif ev.new_state == "thinking":
        print("Agent is processing user input and generating a response")
    elif ev.new_state == "speaking":
        print("Agent started speaking")
```

---

**Node.js**:

```typescript
import { voice } from "@livekit/agents";

session.on(voice.AgentSessionEventTypes.UserStateChanged, (ev) => {
  if (ev.newState === "speaking") {
    console.log("User started speaking");
  } else if (ev.newState === "listening") {
    console.log("User stopped speaking");
  } else if (ev.newState === "away") {
    console.log("User is not present (e.g. disconnected)");
  }
});

session.on(voice.AgentSessionEventTypes.AgentStateChanged, (ev) => {
  if (ev.newState === "initializing") {
    console.log("Agent is starting up");
  } else if (ev.newState === "idle") {
    console.log("Agent is ready but not processing");
  } else if (ev.newState === "listening") {
    console.log("Agent is listening for user input");
  } else if (ev.newState === "thinking") {
    console.log("Agent is processing user input and generating a response");
  } else if (ev.newState === "speaking") {
    console.log("Agent started speaking");
  }
});
```

## Additional resources

- **[Agent speech](https://docs.livekit.io/agents/build/audio.md)**: Guide to agent speech and related methods.

- **[Pipeline nodes](https://docs.livekit.io/agents/build/nodes.md)**: Monitor input and output as it flows through the voice pipeline.

- **[Turn-taking tuning](https://docs.livekit.io/agents/logic/turns/tuning.md)**: Recommended configs and a troubleshooting guide for turn-taking knobs.

- **[Turn handling options](https://docs.livekit.io/reference/agents/turn-handling-options.md)**: Reference documentation for turn detection, endpointing, and interruption handling options for your agent session.

---

This document was rendered at 2026-08-12T04:22:51.375Z.
For the latest version of this document, see [https://docs.livekit.io/agents/logic/turns.md](https://docs.livekit.io/agents/logic/turns.md).

To explore all LiveKit documentation, see [llms.txt](https://docs.livekit.io/llms.txt).
