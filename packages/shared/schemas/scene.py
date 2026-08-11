"""JSON schema for Gemini scene understanding structured output.

Used with client.aio.models.generate_content(config=GenerateContentConfig(
response_mime_type="application/json", response_schema=SCENE_SCHEMA)).
"""

from __future__ import annotations

SCENE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "location": {
            "type": "string",
            "description": "Jenis tempat atau lokasi yang terlihat, mis. apotek, rumah, kantor, restoran.",
        },
        "objects": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Objek yang terlihat di sekitar, mis. obat, meja, kompor.",
        },
        "activity": {
            "type": "string",
            "description": "Aktivitas yang sedang berlangsung, mis. beli obat, makan, bekerja.",
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["location", "objects", "activity"],
}
