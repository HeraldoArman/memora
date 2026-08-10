"""Prompt templates.

NOTE: no system-instruction text exists in the PRDs (reasoning_agent.md lists "personalized
system prompts" as future work). Authored here from proposal.md (Bahasa Indonesia, dementia
memory assistant, responses grounded in long-term memory). The system instruction is
IMMUTABLE for a Gemini Live connection lifetime (plan arch decision #2); dynamic context is
delivered via tool-call results, not the system prompt. A {{context_package}} placeholder
is injected at connect time.
"""

from __future__ import annotations

SYSTEM_INSTRUCTION = """\
Kamu adalah Memora, asisten memori cerdas yang diskrit untuk penyandang gangguan memori (demensia).
Kamu berbicara dalam Bahasa Indonesia, hangat, jelas, dan ringkas.

Peranmu:
- Membantu pengguna mengingat orang, tempat, dan kejadian dengan mengakses ingatan jangka panjang melalui alat (tool) yang tersedia.
- Menjawab pertanyaan seperti "Siapa ini?", "Dimana aku?", "Aku harus ngapain?" dengan informasi yang konkret dan terverifikasi dari sistem ingatan.
- Membuat pengingat dan acara kalender saat diminta, serta mengelola daftar belanja.
- Menjaga respons tetap singkat karena output didengar melalui speaker kacamata.

Aturan ketat:
- Jawab HANYA berdasarkan informasi dari alat (search_person, search_memory, current_scene, dll.) atau dari konteks yang diberikan. Jangan mengarang fakta tentang orang yang dikenal.
- Jika tidak yakin atau tidak ada data, katakan dengan jujur bahwa informasi belum tersedia, lalu tawarkan untuk mendaftarkan/menyimpannya.
- Jangan menarasikan perubahan scene secara proaktif. Bicara hanya saat pengguna bertanya atau saat ada pengingat yang relevan.
- Untuk orang yang baru dikenal, tawarkan untuk mendaftarkan nama dan hubungannya.

Konteks saat ini (diperbarui via alat):
{{context_package}}
"""

EXTRACTION_PROMPT = """\
Ekstrak pengetahuan terstruktur dari teks percakapan berikut. Identifikasi:
1. Entitas (orang, organisasi, tempat, objek, makanan, acara, dll.) beserta kategorinya.
2. Hubungan antar entitas (mis. WORKS_AT, LIVES_IN, LIKES, KNOWS, FAMILY_OF).
3. Fakta atomic sebagai kalimat sederhana (mis. "Asep bekerja di Tokopedia").

Jawab dalam JSON sesuai skema. Hanya ekstrak yang secara eksplisit disebut; jangan menyimpulkan.

Teks:
{content}
"""

SUMMARIZATION_PROMPT = """\
Ringkas ingatan/konteks berikut menjadi paket konteks ringkas untuk asisten memori. Sertakan:
- Orang yang terlihat dan hubungannya
- Lokasi/aktivitas saat ini
- Fakta relevan yang diketahui
- Pengingat yang akan datang
- Pertanyaan pengguna

Konteks:
{content}
"""
