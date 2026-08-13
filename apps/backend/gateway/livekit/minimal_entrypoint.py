"""Audio-only LiveKit entrypoint for isolating realtime turn latency.

This deliberately omits every Memora subsystem: stores, tools, memory context,
extraction, planner, observations, face recognition, scene understanding, and video.
"""

from __future__ import annotations

import asyncio
import logging

from livekit import rtc
from livekit.agents import Agent, AgentSession, JobContext, room_io
from livekit.agents.llm import ChatMessage
from livekit.plugins import google

from gateway.livekit.agent_log import AgentLog
from reasoning.response.display import Display

log = logging.getLogger(__name__)


def _is_gemini_31(model: str) -> bool:
    return model.startswith("gemini-3.1-")


async def minimal_entrypoint(ctx: JobContext) -> None:
    """Run the LiveKit realtime quickstart shape with dashboard-only adapters."""
    room = ctx.room
    log.warning(
        "MINIMAL MODE: audio + Gemini + dashboard events only; all Memora subsystems disabled"
    )

    display = Display(room)
    agent_log = AgentLog(room)
    from env import get_settings

    settings = get_settings()
    is_gemini_31 = _is_gemini_31(settings.gemini_live_model)
    session = AgentSession(
        llm=google.realtime.RealtimeModel(
            model=settings.gemini_live_model,
            voice="Puck",
            api_key=settings.gemini_api_key,
        )
    )

    @session.on("conversation_item_added")
    def _on_conversation_item(ev):
        item = ev.item
        if not isinstance(item, ChatMessage):
            return
        text = item.text_content or ""
        log.info(
            "minimal conversation_item_added: role=%s text=%r interrupted=%s",
            item.role,
            text[:200],
            item.interrupted,
        )
        if not text:
            return
        if item.role == "assistant":
            asyncio.create_task(display.show(text))
            asyncio.create_task(agent_log.emit("assistant", text))
        elif item.role == "user":
            asyncio.create_task(agent_log.emit("user", text))

    @room.on("data_received")
    def _on_data(packet: rtc.DataPacket):
        if packet.topic != "prompt":
            return
        text = bytes(packet.data).decode("utf-8", errors="replace")
        log.info("minimal prompt received: %r", text[:200])
        asyncio.create_task(agent_log.emit("user", f"[prompt] {text}"))
        if is_gemini_31:
            log.warning("minimal prompt dropped: Gemini 3.1 does not support generate_reply()")
            return
        try:
            session.generate_reply(user_input=text)
        except RuntimeError:
            log.warning("minimal prompt received but AgentSession is not running; dropping")

    await session.start(
        room=room,
        agent=Agent(
            instructions=(
                "Kamu adalah agen uji audio. Jawab singkat dalam Bahasa Indonesia. "
                "Jangan mengaku menyimpan, mengetahui, atau mengambil memori pengguna."
            )
        ),
        room_options=room_io.RoomOptions(
            video_input=False,
            audio_input=True,
            audio_output=True,
        ),
    )
    log.info(
        "minimal agent session started: model=%s video_input=False, tools=0",
        settings.gemini_live_model,
    )
    if is_gemini_31:
        log.info("minimal greeting skipped: Gemini 3.1 does not support generate_reply()")
    else:
        await session.generate_reply(instructions="Sapa pengguna dengan singkat.")

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        log.info("minimal job cancelled for room %s", room.name)
    finally:
        await session.aclose()
        log.info("minimal room session torn down for %s", room.name)
