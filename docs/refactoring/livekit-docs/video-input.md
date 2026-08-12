LiveKit docs › Multimodality › Images & video › Video

---

# Video

> Sample video frames, enable live video input, and add virtual avatars for video output.

## Overview

LiveKit Agents supports video as both input and output. On the input side, you can sample video frames from an STT-LLM-TTS pipeline or enable live video input with a supported realtime model. On the output side, you can add a virtual avatar for lifelike video output.

## Sample video frames

LLMs can process video in the form of still images, but many LLMs are not trained for this use case and can produce suboptimal results in understanding motion and other changes through a video feed. Realtime models, like [Gemini Live](https://docs.livekit.io/agents/models/realtime/plugins/gemini.md), are trained on video and you can enable [live video input](#live-video-input) for automatic support.

If you're using an STT-LLM-TTS pipeline, you can still work with video by sampling frames at suitable times. In the following example, the agent includes the latest video frame for each user turn by injecting it into the [chat context](https://docs.livekit.io/agents/logic/chat-context.md), providing additional context without overwhelming the model or requiring it to process multiple sequential frames.

** Filename: `agent.py`**

```python
class Assistant(Agent):
    def __init__(self) -> None:
        self._latest_frame = None
        self._video_stream = None
        self._tasks = []
        super().__init__(instructions="You are a helpful voice AI assistant.")

    async def on_enter(self):
        room = get_job_context().room

        # Find the first video track (if any) from the remote participant
        if room.remote_participants:
            remote_participant = list(room.remote_participants.values())[0]
            video_tracks = [publication.track for publication in list(remote_participant.track_publications.values()) if publication.track and publication.track.kind == rtc.TrackKind.KIND_VIDEO]
            if video_tracks:
                self._create_video_stream(video_tracks[0])

        # Watch for new video tracks not yet published
        @room.on("track_subscribed")
        def on_track_subscribed(track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
            if track.kind == rtc.TrackKind.KIND_VIDEO:
                self._create_video_stream(track)

    async def on_user_turn_completed(self, turn_ctx: ChatContext, new_message: ChatMessage) -> None:
        # Add the latest video frame, if any, to the new message
        if self._latest_frame:
            new_message.content.append(ImageContent(image=self._latest_frame))
            self._latest_frame = None

    # Helper method to buffer the latest video frame from the user's track
    def _create_video_stream(self, track: rtc.Track):
        # Close any existing stream (we only want one at a time)
        if self._video_stream is not None:
            old = self._video_stream
            self._video_stream = None
            asyncio.create_task(old.aclose())

        # Create a new stream to receive frames
        self._video_stream = rtc.VideoStream(track)
        async def read_stream():
            async for event in self._video_stream:
                # Store the latest frame for use later
                self._latest_frame = event.frame

        # Store the async task
        task = asyncio.create_task(read_stream())
        task.add_done_callback(lambda t: self._tasks.remove(t))
        self._tasks.append(task)

```

** Filename: `Required imports`**

```python
import asyncio
from livekit import rtc
from livekit.agents import Agent, get_job_context, ChatContext, ChatMessage
from livekit.agents.llm import ImageContent

```

** Filename: `agent.ts`**

```typescript
function createAssistant() {
  let latestFrame: VideoFrame | null = null;
  let videoStream: VideoStream | null = null;
  const tasks: Set<Task<void>> = new Set();

  const createVideoStream = (track: Track): void => {
    // Close any existing stream (we only want one at a time)
    if (videoStream !== null) {
      videoStream.cancel();
    }

    // Create a new stream to receive frames
    videoStream = new VideoStream(track);

    const readStream = async (controller: AbortController): Promise<void> => {
      if (!videoStream) return;

      for await (const event of videoStream) {
        if (controller.signal.aborted) return;
        // Store the latest frame for use later
        latestFrame = event.frame;
      }
    };

    // Store the async task
    const task = Task.from((controller) => readStream(controller));
    task.result.finally(() => tasks.delete(task));
    tasks.add(task);
  };

  return voice.Agent.create({
    instructions: "You are a helpful voice AI assistant.",
    onEnter() {
      const room = getJobContext().room;

      // Find the first video track (if any) from the remote participant
      const remoteParticipants = Array.from(room.remoteParticipants.values());

      if (remoteParticipants.length > 0) {
        const remoteParticipant = remoteParticipants[0]!;
        const videoTracks = Array.from(remoteParticipant.trackPublications.values())
          .filter((pub) => pub.track?.kind === TrackKind.KIND_VIDEO)
          .map((pub) => pub.track!)
          .filter((track) => track !== undefined);

        if (videoTracks.length > 0) {
          createVideoStream(videoTracks[0]!);
        }
      }

      // Watch for new video tracks not yet published
      room.on(RoomEvent.TrackSubscribed, (track: Track) => {
        if (track.kind === TrackKind.KIND_VIDEO) {
          createVideoStream(track);
        }
      });
    },
    onUserTurnCompleted(ctx, chatCtx, newMessage) {
      // Add the latest video frame, if any, to the new message
      if (latestFrame !== null) {
        newMessage.content.push(
          llm.createImageContent({
            image: latestFrame,
          }),
        );
        latestFrame = null;
      }
    },
  });
}
```

** Filename: `Required imports`**

```typescript
import { Task, getJobContext, llm, voice } from "@livekit/agents";
import type { Track, VideoFrame } from "@livekit/rtc-node";
import { RoomEvent, TrackKind, VideoStream } from "@livekit/rtc-node";
```

### Video frame encoding

By default, `ImageContent` encodes video frames as JPEGs at their native size. To adjust the size of the encoded frames, set the `inference_width` and `inference_height` parameters. Each frame is resized to fit within the provided dimensions while maintaining the original aspect ratio. For more control, use the `encode` method of the `livekit.agents.utils.images` module and pass the result as a data URL:

** Filename: `agent.py`**

```python
image_bytes = encode(
    event.frame,
    EncodeOptions(
        format="PNG",
        resize_options=ResizeOptions(
            width=512,
            height=512,
            strategy="scale_aspect_fit"
        )
    )
)
image_content = ImageContent(
    image=f"data:image/png;base64,{base64.b64encode(image_bytes).decode('utf-8')}"
)

```

** Filename: `Required imports`**

```python
import base64
from livekit.agents.utils.images import encode, EncodeOptions, ResizeOptions

```

## Live video input

Available in:

- [ ] Node.js
- [x] Python

Live video input requires a realtime model with video support. Not all [realtime models](https://docs.livekit.io/agents/models/realtime.md) support video input. The following models support live video:

- [Gemini Live API](https://docs.livekit.io/agents/models/realtime/plugins/gemini.md#video-input)
- [OpenAI Realtime API](https://docs.livekit.io/agents/models/realtime/plugins/openai.md#video-input)

> ℹ️ **Video input with audio-only models**
>
> Enabling `video_input` with an audio-only realtime model silently ignores the video frames — no error is raised but the model won't process video.

To start receiving video frames, set the `video_input` parameter to `True` in `RoomOptions`. Your agent automatically receives frames from the user's [camera](https://docs.livekit.io/transport/media/publish.md) or [screen sharing](https://docs.livekit.io/transport/media/screenshare.md) tracks, if available. Only the single most recently published video track is used.

By default, the agent samples one frame per second while the user speaks and one frame every three seconds otherwise. Each frame is resized to 1024x1024 and encoded to JPEG. To override the frame rate, set `video_sampler` on the `AgentSession` with a custom instance.

Video input is passive and has no effect on [turn detection](https://docs.livekit.io/agents/logic/turns.md). To leverage live video input in a non-conversational context, use [manual turn control](https://docs.livekit.io/agents/logic/turns.md#manual) and trigger LLM responses or tool calls on a timer or other schedule.

### Considerations

Both models consume tokens for each video frame, so higher frame rates increase cost. The two supported models handle video frames differently:

- **Gemini Live** streams video frames natively within its realtime protocol. Frames are encoded and sent inline alongside the audio session. Each frame is tokenized based on its dimensions. See [Gemini token counting](https://ai.google.dev/gemini-api/docs/tokens) for details.
- **OpenAI Realtime API** sends each video frame as an image message in the conversation context. Each frame consumes input tokens and counts against the context window. See [OpenAI image token calculation](https://developers.openai.com/docs/guides/images-vision#calculating-costs) for details.

### Examples

- **[Gemini Live video input](https://docs.livekit.io/agents/models/realtime/plugins/gemini.md#video-input)**: Use live video input with Gemini Live.

- **[OpenAI Realtime video input](https://docs.livekit.io/agents/models/realtime/plugins/openai.md#video-input)**: Enable video input with OpenAI Realtime API.

## Video output

Virtual avatars add lifelike video output for your voice AI agents. An avatar provider joins the LiveKit room as a secondary participant and publishes synchronized audio and video tracks, giving your agent a visual presence.

The `AgentSession` sends its audio output to the avatar worker instead of directly to the room. The avatar worker uses this audio to generate synchronized lip movements and gestures, then publishes the resulting audio and video tracks to the room.

### Adding an avatar to your agent

To add a virtual avatar:

1. Install the avatar plugin and set up API keys for your chosen provider.
2. Create an `AgentSession` as in the [voice AI quickstart](https://docs.livekit.io/agents/start/voice-ai.md).
3. Create an `AvatarSession` and configure it as necessary.
4. Start the avatar session, passing in the `AgentSession` instance.

The following example uses [Anam](https://docs.livekit.io/agents/models/avatar/plugins/anam.md):

** Filename: `agent.py`**

```python
server = AgentServer()

@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: agents.JobContext):
   session = AgentSession(
      # ... stt, llm, tts, etc.
   )

   avatar = anam.AvatarSession(
      persona_config=anam.PersonaConfig(
         name="...",  # Name of the avatar to use.
         avatarId="...",  # ID of the avatar to use.
      ),
   )

   # Start the avatar and wait for it to join
   await avatar.start(session, room=ctx.room)

   # Start your agent session with the user
   await session.start(
      # ... room, agent, room_options, etc....
   )

```

** Filename: `Required imports`**

```python
from livekit import agents
from livekit.agents import AgentServer, AgentSession
from livekit.plugins import anam

```

** Filename: `agent.ts`**

```typescript
export default defineAgent({
  entry: async (ctx: JobContext) => {
    await ctx.connect();

    const agent = voice.Agent.create({
      instructions: "You are a helpful assistant.",
    });

    const session = new voice.AgentSession({
      // ... llm, stt, tts, etc.
    });

    await session.start({
      agent,
      room: ctx.room,
    });

    const avatar = new bey.AvatarSession({
      avatarId: "...", // ID of the avatar to use
    });
    await avatar.start(session, ctx.room);
  },
});
```

** Filename: `Required imports`**

```typescript
import { type JobContext, defineAgent, voice } from "@livekit/agents";
import * as bey from "@livekit/agents-plugin-bey";
```

### Frontend integration

In your frontend, distinguish between the agent (your Python or Node.js program) and the avatar worker. You can identify an avatar worker as an `agent` participant with the attribute `lk.publish_on_behalf`:

**JavaScript**:

In React apps, use the [useVoiceAssistant hook](https://docs.livekit.io/reference/components/react/hook/usevoiceassistant.md) to get the correct audio and video tracks automatically:

```typescript
const {
  agent, // The agent participant
  audioTrack, // the worker's audio track
  videoTrack, // the worker's video track
} = useVoiceAssistant();
```

With the lower-level SDK, find participants by kind and attribute:

```typescript
const participants = Array.from(room.remoteParticipants.values());
const agent = participants.find(
  (p) => p.kind === ParticipantKind.AGENT && !p.attributes["lk.publish_on_behalf"],
);
const avatarWorker = participants.find(
  (p) =>
    p.kind === ParticipantKind.AGENT && p.attributes["lk.publish_on_behalf"] === agent?.identity,
);
```

---

**Swift**:

```swift
let agent = room.remoteParticipants.values.first {
    $0.kind == .agent && $0.attributes["lk.publish_on_behalf"] == nil
}
let avatarWorker = room.remoteParticipants.values.first {
    $0.kind == .agent && $0.attributes["lk.publish_on_behalf"] == agent?.identity?.stringValue
}

```

---

**Android**:

```kotlin
val agent = room.remoteParticipants.values.firstOrNull {
    it.kind == Participant.Kind.AGENT &&
        it.agentAttributes.lkPublishOnBehalf == null
}
val avatarWorker = room.remoteParticipants.values.firstOrNull {
    it.kind == Participant.Kind.AGENT &&
        it.agentAttributes.lkPublishOnBehalf == agent?.identity?.value
}

```

---

**Flutter**:

```dart
final agent = room.remoteParticipants.values.firstWhereOrNull(
  (p) => p.kind == ParticipantKind.AGENT &&
      (p.attributes['lk.publish_on_behalf'] == null ||
       p.attributes['lk.publish_on_behalf']!.isEmpty),
);
final avatarWorker = room.remoteParticipants.values.firstWhereOrNull(
  (p) => p.kind == ParticipantKind.AGENT &&
      p.attributes['lk.publish_on_behalf'] == agent?.identity,
);

```

For more details on building frontends with avatars, see [Virtual avatars](https://docs.livekit.io/frontends/build/virtual-avatars.md) in the frontends section. For step-by-step setup guides for each avatar provider, see [Virtual avatar models](https://docs.livekit.io/agents/models/avatar.md).

---

This document was rendered at 2026-08-12T04:22:35.800Z.
For the latest version of this document, see [https://docs.livekit.io/agents/multimodality/vision/video.md](https://docs.livekit.io/agents/multimodality/vision/video.md).

To explore all LiveKit documentation, see [llms.txt](https://docs.livekit.io/llms.txt).
