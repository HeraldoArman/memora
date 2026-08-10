"""Postgres repositories — one per aggregate."""

from __future__ import annotations

from postgres.repositories.conversation_repo import ConversationRepo
from postgres.repositories.event_repo import EventRepo
from postgres.repositories.fact_repo import FactRepo
from postgres.repositories.reminder_repo import ReminderRepo
from postgres.repositories.shopping_repo import ShoppingRepo
from postgres.repositories.system_repo import SystemRepo
from postgres.repositories.transcript_repo import TranscriptRepo

__all__ = [
    "ConversationRepo",
    "EventRepo",
    "FactRepo",
    "ReminderRepo",
    "ShoppingRepo",
    "SystemRepo",
    "TranscriptRepo",
]
