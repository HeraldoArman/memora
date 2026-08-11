"""Gateway layer — LiveKit realtime transport wiring.

entrypoint.py is the JobContext job; track_handler.py + data_channel.py wire perception
in; session.py holds per-room state (agent + working memory + observation engine).
"""

from gateway.livekit.entrypoint import entrypoint
from gateway.session import RoomSession

__all__ = ["entrypoint", "RoomSession"]
