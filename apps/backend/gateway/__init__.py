"""Gateway layer — LiveKit realtime transport wiring.

entrypoint.py is the JobContext job; track_handler.py wires InsightFace video.
"""

from gateway.livekit.entrypoint import entrypoint

__all__ = ["entrypoint"]
