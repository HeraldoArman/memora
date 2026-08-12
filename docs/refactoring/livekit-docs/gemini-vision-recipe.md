LiveKit docs › Vision › Gemini Vision Assistant

---

# Gemini Realtime Agent with Live Vision

> Minimal Gemini Realtime model agent setup with live vision capabilities

This example demonstrates how to start a Gemini Realtime agent that can see video from the call. The session uses Google's realtime model with proactivity enabled.

## Prerequisites

- Add a `.env.local` in this directory with your LiveKit and Google credentials:```
  LIVEKIT_URL=your_livekit_url
  LIVEKIT_API_KEY=your_api_key
  LIVEKIT_API_SECRET=your_api_secret
  GOOGLE_API_KEY=your_google_api_key

````
- Install dependencies:```bash
pip install "livekit-agents[google,images]" python-dotenv

````

**Step 1.**

## Load environment, logging, and define an AgentServer

Start by importing the required modules and setting up logging. The `AgentServer` wraps your application and manages the worker lifecycle.

```python
import logging
from dotenv import load_dotenv
from livekit.agents import JobContext, Agent, AgentSession, AgentServer, cli, room_io
from livekit.plugins import google

load_dotenv(".env.local")

logger = logging.getLogger("gemini-live-vision")
logger.setLevel(logging.INFO)

server = AgentServer()
```

---

**Step 2.**

## Create a simple vision-capable agent

Keep the agent minimal — just add instructions that acknowledge its vision capabilities. The actual video processing comes from the session configuration with `RoomOptions`.

```python
import logging
from dotenv import load_dotenv
from livekit.agents import JobContext, Agent, AgentSession, AgentServer, cli
from livekit.plugins import google

load_dotenv(".env.local")

logger = logging.getLogger("gemini-live-vision")
logger.setLevel(logging.INFO)

server = AgentServer()
```

```python
class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="You are a helpful voice AI assistant that can see the world around you."
        )
```

---

**Step 3.**

## Define the RTC session entrypoint

Configure the Gemini Realtime model with proactivity and affective dialog enabled. Proactivity lets the model speak when it has something relevant to say. Enable video in `RoomOptions` so the agent receives video frames from the room. After starting and connecting, call `generate_reply()` to have the agent greet the caller.

```python
import logging
from dotenv import load_dotenv
from livekit.agents import JobContext, Agent, AgentSession, AgentServer, cli, room_io
from livekit.plugins import google

load_dotenv(".env.local")

logger = logging.getLogger("gemini-live-vision")
logger.setLevel(logging.INFO)

server = AgentServer()


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="You are a helpful voice AI assistant that can see the world around you."
        )
```

```python
@server.rtc_session(agent_name="my-agent")
async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    session = AgentSession(
        llm=google.beta.realtime.RealtimeModel(
            model="gemini-2.5-flash-native-audio-preview-12-2025",
            proactivity=True,
            enable_affective_dialog=True,
        ),
    )

    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_options=room_io.RoomOptions(
            video_input=True,
        ),
    )
    await ctx.connect()

    await session.generate_reply()
```

---

**Step 4.**

## Run the server

The `cli.run_app()` function starts the agent server and manages connections to LiveKit.

```python
import logging
from dotenv import load_dotenv
from livekit.agents import JobContext, Agent, AgentSession, AgentServer, cli, room_io
from livekit.plugins import google

load_dotenv(".env.local")

logger = logging.getLogger("gemini-live-vision")
logger.setLevel(logging.INFO)

server = AgentServer()


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="You are a helpful voice AI assistant that can see the world around you."
        )


@server.rtc_session(agent_name="my-agent")
async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    session = AgentSession(
        llm=google.beta.realtime.RealtimeModel(
            model="gemini-2.5-flash-native-audio-preview-12-2025",
            proactivity=True,
            enable_affective_dialog=True,
        ),
    )

    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_options=room_io.RoomOptions(
            video_input=True,
        ),
    )
    await ctx.connect()

    await session.generate_reply()
```

```python
if __name__ == "__main__":
    cli.run_app(server)
```

---

## Run it

```bash
lk agent console gemini_live_vision.py

```

## How it works

1. The session uses Gemini Realtime as the LLM with proactivity turned on.
2. `RoomOptions(video_input=True)` lets the agent receive video frames.
3. An initial `generate_reply()` greets the caller; the model can incorporate vision context in responses.

## Full example

```python
import logging
from dotenv import load_dotenv
from livekit.agents import JobContext, Agent, AgentSession, AgentServer, cli, room_io
from livekit.plugins import google

load_dotenv(".env.local")

logger = logging.getLogger("gemini-live-vision")
logger.setLevel(logging.INFO)


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="You are a helpful voice AI assistant that can see the world around you."
        )


server = AgentServer()


@server.rtc_session(agent_name="my-agent")
async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    session = AgentSession(
        llm=google.beta.realtime.RealtimeModel(
            model="gemini-2.5-flash-native-audio-preview-12-2025",
            proactivity=True,
            enable_affective_dialog=True,
        ),
    )

    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_options=room_io.RoomOptions(
            video_input=True,
        ),
    )
    await ctx.connect()

    await session.generate_reply()


if __name__ == "__main__":
    cli.run_app(server)
```

---

This document was rendered at 2026-08-12T04:22:36.498Z.
For the latest version of this document, see [https://docs.livekit.io/reference/recipes/gemini_live_vision.md](https://docs.livekit.io/reference/recipes/gemini_live_vision.md).

To explore all LiveKit documentation, see [llms.txt](https://docs.livekit.io/llms.txt).
