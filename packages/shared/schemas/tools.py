"""Gemini Live function declarations — the tool surface.

Built as a list of function-declaration dicts for LiveConnectConfig(tools=[...]).
Immutable for the connection lifetime (plan arch decision #2), so the full surface is
declared up front. Each declaration: {name, description, parameters: {JSON schema}}.
Parameters are intentionally loose (type/string) — the tool modules validate strictly.
"""

from __future__ import annotations

from constants import ToolName


def _decl(name: ToolName, description: str, params: dict | None = None) -> dict:
    d: dict = {"name": name.value, "description": description}
    if params is not None:
        d["parameters"] = params
    return d


def _str_param(desc: str, required: bool = False) -> dict:
    p: dict = {"type": "string", "description": desc}
    return p


# --- Person tools ---
PERSON_TOOLS = [
    _decl(
        ToolName.SEARCH_PERSON,
        "Cari informasi seseorang berdasarkan nama. (Search a person by name.)",
        {
            "type": "object",
            "properties": {"query": _str_param("Nama orang / person name")},
            "required": ["query"],
        },
    ),
    _decl(
        ToolName.SEARCH_PERSON_BY_FACE,
        "Identifikasi orang dari wajah yang terlihat saat ini. (Identify the visible person by face.)",
        {"type": "object", "properties": {}},
    ),
    _decl(
        ToolName.REGISTER_PERSON,
        "Daftarkan orang baru dengan nama. (Register a new person by name.)",
        {
            "type": "object",
            "properties": {"name": _str_param("Nama orang baru")},
            "required": ["name"],
        },
    ),
    _decl(
        ToolName.REGISTER_FACE,
        "Hubungkan wajah yang terlihat dengan orang yang sudah ada. (Enroll the visible face to an existing person.)",
        {
            "type": "object",
            "properties": {"person_id": _str_param("ID orang")},
            "required": ["person_id"],
        },
    ),
    _decl(
        ToolName.UPDATE_PERSON,
        "Perbarui informasi/catatan seseorang. (Update a person's profile/notes.)",
        {
            "type": "object",
            "properties": {
                "person_id": _str_param("ID orang"),
                "notes": _str_param("Catatan tambahan"),
            },
            "required": ["person_id"],
        },
    ),
]

# --- Memory tools ---
MEMORY_TOOLS = [
    _decl(
        ToolName.SEARCH_MEMORY,
        "Cari ingatan episodik/semantik dengan query. (Search memories by query.)",
        {
            "type": "object",
            "properties": {"query": _str_param("Query pencarian")},
            "required": ["query"],
        },
    ),
    _decl(
        ToolName.RECENT_MEMORIES,
        "Ingatan terbaru. (Recent memories.)",
        {"type": "object", "properties": {"limit": {"type": "integer"}}},
    ),
    _decl(
        ToolName.SIMILAR_MEMORIES,
        "Ingatan mirip dengan query. (Memories similar to a query.)",
        {"type": "object", "properties": {"query": _str_param("Query")}, "required": ["query"]},
    ),
    _decl(
        ToolName.MEMORY_TIMELINE,
        "Garis waktu ingatan. (Memory timeline for a person/topic.)",
        {"type": "object", "properties": {"person_id": _str_param("ID orang (opsional)")}},
    ),
]

# --- Reminder tools ---
REMINDER_TOOLS = [
    _decl(
        ToolName.CREATE_REMINDER,
        "Buat pengingat. (Create a reminder.)",
        {
            "type": "object",
            "properties": {
                "title": _str_param("Judul pengingat"),
                "due_at": _str_param("Waktu jatuh tempo ISO 8601"),
                "note": _str_param("Catatan"),
            },
            "required": ["title"],
        },
    ),
    _decl(
        ToolName.UPDATE_REMINDER,
        "Perbarui pengingat. (Update a reminder.)",
        {
            "type": "object",
            "properties": {
                "reminder_id": _str_param("ID pengingat"),
                "title": _str_param("Judul pengingat"),
                "due_at": _str_param("Waktu jatuh tempo ISO 8601"),
                "note": _str_param("Catatan"),
                "completed": {"type": "boolean", "description": "Tandai selesai"},
            },
            "required": ["reminder_id"],
        },
    ),
    _decl(
        ToolName.DELETE_REMINDER,
        "Hapus pengingat. (Delete a reminder.)",
        {
            "type": "object",
            "properties": {"reminder_id": _str_param("ID pengingat")},
            "required": ["reminder_id"],
        },
    ),
    _decl(
        ToolName.SEARCH_REMINDERS,
        "Cari pengingat. (Search reminders.)",
        {"type": "object", "properties": {"query": _str_param("Query")}},
    ),
    _decl(
        ToolName.TODAY_REMINDERS,
        "Pengingat hari ini. (Today's reminders.)",
        {"type": "object", "properties": {}},
    ),
]

# --- Knowledge tools ---
KNOWLEDGE_TOOLS = [
    _decl(
        ToolName.SEARCH_ENTITY,
        "Cari entitas di knowledge graph. (Search entity in knowledge graph.)",
        {
            "type": "object",
            "properties": {"query": _str_param("Nama entitas")},
            "required": ["query"],
        },
    ),
    _decl(
        ToolName.ENTITY_RELATIONSHIPS,
        "Hubungan sebuah entitas. (Relationships of an entity.)",
        {
            "type": "object",
            "properties": {"entity": _str_param("Nama entitas")},
            "required": ["entity"],
        },
    ),
    _decl(
        ToolName.SEARCH_PREFERENCES,
        "Preferensi pengguna. (User preferences.)",
        {
            "type": "object",
            "properties": {"person_id": _str_param("ID orang")},
            "required": ["person_id"],
        },
    ),
    _decl(
        ToolName.RELATED_PEOPLE,
        "Orang yang berhubungan. (People related to a person.)",
        {
            "type": "object",
            "properties": {"person_id": _str_param("ID orang")},
            "required": ["person_id"],
        },
    ),
    _decl(
        ToolName.KNOWLEDGE_GRAPH,
        "Subgraph di sekitar entitas. (Subgraph around an entity.)",
        {
            "type": "object",
            "properties": {"entity": _str_param("Nama entitas")},
            "required": ["entity"],
        },
    ),
]

# --- Calendar / shopping ---
CALENDAR_TOOLS = [
    _decl(
        ToolName.CREATE_EVENT,
        "Buat acara kalender. (Create a calendar event.)",
        {
            "type": "object",
            "properties": {
                "title": _str_param("Judul acara"),
                "starts_at": _str_param("Mulai ISO 8601"),
                "location": _str_param("Lokasi"),
            },
            "required": ["title", "starts_at"],
        },
    ),
    _decl(
        ToolName.SEARCH_SCHEDULE,
        "Cari jadwal. (Search schedule.)",
        {"type": "object", "properties": {"query": _str_param("Query jadwal")}},
    ),
    _decl(
        ToolName.SHOPPING_LIST,
        "Kelola daftar belanja. (Manage shopping list.)",
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "remove", "check", "list"]},
                "item": _str_param("Nama item"),
            },
            "required": ["action"],
        },
    ),
]

# --- Observation tools ---
OBSERVATION_TOOLS = [
    _decl(
        ToolName.CURRENT_SCENE,
        "Scene saat ini. (Current scene/location/activity.)",
        {"type": "object", "properties": {}},
    ),
    _decl(
        ToolName.VISIBLE_PEOPLE,
        "Orang yang terlihat. (Currently visible people.)",
        {"type": "object", "properties": {}},
    ),
    _decl(
        ToolName.CURRENT_ACTIVITY,
        "Aktivitas saat ini. (Current activity.)",
        {"type": "object", "properties": {}},
    ),
    _decl(
        ToolName.CONVERSATION_SUMMARY,
        "Ringkasan percakapan terbaru. (Recent conversation summary.)",
        {"type": "object", "properties": {"limit": {"type": "integer"}}},
    ),
]

# --- System tools ---
SYSTEM_TOOLS = [
    _decl(
        ToolName.BATTERY_STATUS,
        "Status baterai perangkat. (Battery status.)",
        {"type": "object", "properties": {}},
    ),
    _decl(
        ToolName.NETWORK_STATUS,
        "Status jaringan. (Network status.)",
        {"type": "object", "properties": {}},
    ),
    _decl(
        ToolName.DEVICE_INFORMATION,
        "Informasi perangkat. (Device information.)",
        {"type": "object", "properties": {}},
    ),
    _decl(
        ToolName.FIRMWARE_VERSION,
        "Versi firmware. (Firmware version.)",
        {"type": "object", "properties": {}},
    ),
]

ALL_FUNCTION_DECLARATIONS: list[dict] = (
    PERSON_TOOLS
    + MEMORY_TOOLS
    + REMINDER_TOOLS
    + KNOWLEDGE_TOOLS
    + CALENDAR_TOOLS
    + OBSERVATION_TOOLS
    + SYSTEM_TOOLS
)

# The tools block for LiveConnectConfig(tools=[TOOLS_BLOCK]).
TOOLS_BLOCK: dict = {"function_declarations": ALL_FUNCTION_DECLARATIONS}

# name → declaration, for the tool router to look up parameters schema.
DECLARATIONS_BY_NAME: dict[str, dict] = {d["name"]: d for d in ALL_FUNCTION_DECLARATIONS}
