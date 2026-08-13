"""Story seed driver — drive the real Memora agent through Pak Budi's story.

Impersonates the dummy device over LiveKit (same path as
apps/dashboard/src/components/device-harness.tsx) and sends each Pak Budi turn as a
`prompt`-topic data message. The real agent dispatch spins up the real entrypoint, so
Gemini runs with the real system prompt + real tool registry — register_person,
search_person, create_reminder, search_memory — and seeds the stores itself. This is
NOT a direct DB insert; the data flows through the real agent → tools → extraction
pipeline, exactly as manual use.

The intro (name + Depok + 2008) was already seeded manually and is stripped from turn 1
to avoid duplicates. The family monologue (Andi, Sinta, Rina, Nadia, Milo, Pak Hasan,
Dimas, …) is kept — that's where the people are introduced.

    uv run python scripts/seed/story_driver.py            # live run (needs stack up)
    uv run python scripts/seed/story_driver.py --dry-run   # parse-check only

Self-check: asserts the story parses to >=4 turns, turn 1 has the intro stripped.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import timedelta
from pathlib import Path

# Ensure backend packages are importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
# packages/config (the `env` package) lives outside apps/backend; uv run adds it, but
# be explicit so the script also works under plain `python`.
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "config"))

from env import get_settings  # noqa: E402

DISPLAY_TOPIC = "display"
AGENT_LOG_TOPIC = "agent_log"
PROMPT_TOPIC = "prompt"
REPLY_TIMEOUT_S = 45.0
AGENT_JOIN_TIMEOUT_S = 30.0
TRAILING_FLUSH_S = 3.0

# The two sentences already seeded manually (session ce0800db…, 2026-08-12). Strip
# from turn 1 so we don't duplicate the Budi Santoso / Depok / 2008 facts.
SKIP_INTRO_SUBSTR = (
    "Nama saya Budi Santoso. Saya tinggal di Depok, di rumah yang sudah saya tempati "
    "sejak sekitar tahun 2008. "
)

STORY = """\
Memora, hari ini saya mau cerita sedikit tentang keluarga saya. Saya kadang suka lupa nama orang, terutama kalau sudah lama tidak bertemu.

Nama saya Budi Santoso. Saya tinggal di Depok, di rumah yang sudah saya tempati sejak sekitar tahun 2008. Rumahnya tidak terlalu besar, tapi cukup untuk saya dan keluarga. Rumah saya dekat dengan sebuah minimarket yang namanya Indomaret, dan kalau jalan kaki mungkin sekitar lima menit. Di depan rumah juga ada pohon mangga yang dulu saya tanam bersama anak saya.

Saya punya dua anak. Anak pertama saya namanya Andi Santoso. Andi sekarang bekerja sebagai software engineer di Jakarta. Dia biasanya berangkat kerja pagi-pagi dan pulang cukup malam. Andi itu anak saya yang paling sering membantu saya kalau ada masalah dengan komputer atau handphone. Dia suka sekali teknologi dan dulu waktu kecil juga sering membongkar barang elektronik di rumah.

Anak kedua saya namanya Sinta Santoso. Sinta tinggal di Bandung karena bekerja di sana. Dia bekerja sebagai guru sekolah dasar. Kalau dibandingkan Andi, Sinta lebih suka memasak dan lebih sering menelepon saya. Biasanya dia menelepon saya pada hari Minggu sore.

Oh iya, Andi menikah dengan Rina. Rina adalah menantu saya. Mereka tinggal di Jakarta Selatan. Mereka punya anak perempuan bernama Nadia, jadi Nadia itu cucu pertama saya. Nadia sekarang masih sekolah dasar dan dia sangat suka menggambar. Kalau saya bertemu Nadia, biasanya dia suka menunjukkan gambar-gambarnya kepada saya.

Sinta belum menikah. Dia punya seekor kucing bernama Milo. Milo warnanya putih dengan sedikit warna abu-abu di bagian ekornya. Saya sebenarnya tidak terlalu suka kucing masuk ke kamar saya, tapi Milo selalu mengikuti saya kalau saya datang ke Bandung.

Kalau soal makanan, saya paling suka makanan yang sederhana. Saya suka soto ayam, nasi goreng, dan gado-gado. Tapi kalau harus memilih satu makanan favorit, mungkin soto ayam. Biasanya saya makan soto ayam pada hari Sabtu pagi. Ada warung soto yang cukup dekat dari rumah, namanya Soto Pak Jaya. Letaknya kira-kira sepuluh menit dari rumah naik motor.

Saya kurang suka makanan yang terlalu pedas. Jadi kalau makan sambal biasanya hanya sedikit. Saya juga suka minum teh hangat setelah makan. Kopi sebenarnya saya suka, tetapi kalau minum kopi terlalu sore biasanya saya susah tidur malamnya.

Untuk kegiatan sehari-hari, biasanya saya bangun sekitar jam enam pagi. Setelah bangun saya minum air putih, kemudian sarapan. Kalau hari Senin sampai Jumat, saya biasanya membaca berita di ruang tamu setelah sarapan. Saya punya kursi favorit di sebelah jendela ruang tamu. Kursi itu berwarna cokelat dan sudah cukup lama.

Setelah itu biasanya saya pergi ke pasar atau minimarket kalau ada yang perlu dibeli. Saya sering membeli roti, telur, susu, dan buah. Buah yang paling sering saya beli adalah pisang dan apel.

Kalau hari Minggu, biasanya lebih santai. Kadang Andi datang bersama Rina dan Nadia. Kalau mereka datang, kami biasanya makan siang bersama di rumah. Saya paling suka kalau Nadia datang karena rumah jadi lebih ramai.

Ada satu hal yang jangan saya lupakan. Ulang tahun Nadia tanggal 14 September. Tahun lalu kami merayakannya di rumah Andi. Saya memberikan Nadia satu set pensil warna karena dia suka menggambar. Dia senang sekali waktu menerima hadiah itu.

Oh, saya juga punya teman lama bernama Pak Hasan. Saya kenal Pak Hasan sejak kuliah. Kami dulu sering bermain bulu tangkis bersama. Sekarang Pak Hasan tinggal di Bogor. Kami tidak terlalu sering bertemu, mungkin hanya beberapa bulan sekali, tetapi kami masih sering berkomunikasi lewat WhatsApp.

Pak Hasan punya anak bernama Dimas. Dimas sekarang kuliah di Bandung. Saya pernah bertemu Dimas beberapa kali ketika dia masih kecil.

Kalau saya lupa sesuatu nanti, tolong ingatkan saya ya, Memora. Terutama tentang keluarga saya.

Misalnya kalau saya bertanya, "Siapa anak saya yang tinggal di Bandung?", jawabannya Sinta. Kalau saya bertanya siapa yang bekerja sebagai software engineer, jawabannya Andi. Kalau saya bertanya siapa cucu saya, jawabannya Nadia.

Dan kalau saya bertanya tentang Milo, jangan bilang dia anak saya ya. Milo itu kucingnya Sinta.
|||EXPECTED|||
Baik, Pak Budi. Saya akan membantu mengingat informasi tentang keluarga, tempat, kebiasaan, dan hal-hal penting yang Bapak ceritakan.
|||PAK_BUDI|||
Nah, bagus. Saya juga mau cerita sedikit tentang masa lalu.

Dulu ketika Andi masih kecil, saya sering mengajaknya pergi ke taman pada Minggu pagi. Taman yang paling sering kami datangi namanya Taman Kota Depok. Waktu itu Andi suka sekali bermain sepeda. Saya masih ingat dia pernah jatuh dari sepeda karena terlalu cepat turun dari jalan yang agak menurun.

Setelah itu saya membawanya pulang dan membersihkan lukanya. Tidak parah sebenarnya, hanya lecet di lutut. Tapi Andi waktu itu menangis cukup lama.

Kalau dengan Sinta berbeda. Sinta waktu kecil lebih suka membaca buku. Dia sering duduk di ruang tamu sambil membaca buku cerita. Saya masih menyimpan beberapa buku lamanya di lemari kamar.

Sekarang kalau dipikir-pikir, anak-anak saya sudah besar semua.

Saya juga punya beberapa benda yang penting bagi saya. Di kamar ada sebuah jam tangan lama pemberian ayah saya. Jam itu sudah tidak terlalu bagus, tetapi saya masih menyimpannya karena punya nilai sentimental. Ada juga album foto keluarga di lemari ruang tamu. Kalau saya sedang lupa wajah seseorang, mungkin foto-foto itu bisa membantu.

Memora, kalau nanti saya melihat seseorang yang wajahnya saya kenal tetapi saya lupa namanya, coba bantu saya. Saya ingin tahu siapa orang tersebut dan hubungan dia dengan saya.
|||EXPECTED|||
Tentu, Pak Budi. Jika orang tersebut sudah tersimpan di memori dan wajahnya dapat dikenali, saya akan mencoba membantu mengingatkan Bapak.
|||PAK_BUDI|||
Terima kasih.

Oh, satu lagi. Kalau nanti Andi datang, ingatkan saya bahwa saya mau memberikan dia obeng listrik yang dulu dia minta. Saya taruh obeng itu di lemari kecil di garasi.

Dan kalau Sinta datang, saya mau memberinya buku resep lama milik ibu saya. Bukunya ada di rak paling atas di ruang kerja.

Saya rasa cukup dulu ceritanya. Banyak juga ternyata yang saya ceritakan.

Tapi kalau nanti saya lupa, saya bisa bertanya lagi kepada kamu kan?
|||EXPECTED|||
Tentu, Pak Budi. Bapak bisa bertanya kapan saja.
|||PAK_BUDI|||
Baik. Kalau begitu, saya mau istirahat dulu.

Tapi sebelum itu, coba kamu ingat satu hal.

Siapa cucu saya?
|||EXPECTED|||
Cucu Bapak adalah Nadia.
|||PAK_BUDI|||
Benar.

Kalau begitu saya tenang.
"""


def parse_story(md: str) -> tuple[list[str], list[str]]:
    """Split STORY on |||PAK_BUDI||| / |||EXPECTED||| markers.

    Structure: <PB1> |||EXPECTED||| <exp1> |||PAK_BUDI||| <PB2> |||EXPECTED||| <exp2> ...
    The opening block (before the first marker) is Pak Budi turn 1. `expected` entries
    are aligned by turn for a post-run side-by-side log; never sent to the agent.
    """
    # Split on |||EXPECTED||| → [PB1, exp1+PB2, exp2+PB3, ...]
    chunks = md.split("|||EXPECTED|||")
    user_turns: list[str] = []
    expected: list[str] = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            user_turns.append(chunk.strip())
        else:
            # chunk = <expected reply> [|||PAK_BUDI||| <next turn>]
            sub = chunk.split("|||PAK_BUDI|||", 1)
            expected.append(sub[0].strip())
            if len(sub) > 1:
                user_turns.append(sub[1].strip())
    # Strip the already-seeded intro from turn 1.
    if user_turns and SKIP_INTRO_SUBSTR in user_turns[0]:
        user_turns[0] = user_turns[0].replace(SKIP_INTRO_SUBSTR, "", 1).strip()
    return user_turns, expected


async def main(*, dry_run: bool = False) -> None:
    user_turns, expected = parse_story(STORY)
    if dry_run:
        print(f"parsed {len(user_turns)} Pak Budi turns, {len(expected)} expected replies")
        for i, t in enumerate(user_turns):
            print(f"\n--- turn {i + 1} ({len(t)} chars) ---")
            print(t[:300] + ("…" if len(t) > 300 else ""))
            if i < len(expected) and expected[i]:
                print(f"  [expected] {expected[i][:120]}")
        assert len(user_turns) >= 4, f"expected >=4 turns, got {len(user_turns)}"
        assert all(t.strip() for t in user_turns), "empty turn found"
        assert SKIP_INTRO_SUBSTR not in user_turns[0], "intro not stripped from turn 1"
        print("\ndry-run OK")
        return

    settings = get_settings()
    from livekit import api, rtc

    # Unique room — matches token/route.ts uniqueRoom() pattern.
    room_name = f"memora-seed-{int(time.time())}"
    identity = "dummy-device"
    http_url = settings.livekit_url.replace("wss://", "https://").replace("ws://", "http://")

    # Mint token (mirrors apps/dashboard/src/app/api/token/route.ts).
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .with_ttl(timedelta(hours=2))
        .to_jwt()
    )

    # Dispatch the real agent to our room (mirrors token/route.ts:64). The Python
    # SDK takes a CreateAgentDispatchRequest, not positional args.
    from livekit.protocol import agent_dispatch as ad_proto

    lkapi = api.LiveKitAPI(http_url, settings.livekit_api_key, settings.livekit_api_secret)
    try:
        dispatch = await lkapi.agent_dispatch.create_dispatch(
            ad_proto.CreateAgentDispatchRequest(room=room_name, agent_name=settings.agent_name)
        )
        print(f"agent dispatched: id={dispatch.id} room={room_name} agent={settings.agent_name}")
    except Exception as e:  # noqa: BLE001
        print(f"WARN: agent dispatch failed: {e}", file=sys.stderr)
    await lkapi.aclose()

    room = rtc.Room()
    display_q: asyncio.Queue[str] = asyncio.Queue()
    turn_logs: list[list[str]] = [[] for _ in user_turns]  # per-turn agent_log lines
    # Map agent_log timestamps to turns: the most recent turn index sent.
    current_turn = [-1]

    def _on_data(packet: rtc.DataPacket) -> None:
        topic = packet.topic or ""
        data = bytes(packet.data)
        if topic == DISPLAY_TOPIC:
            text = data.decode("utf-8", errors="replace")
            display_q.put_nowait(text)
        elif topic == AGENT_LOG_TOPIC:
            text = data.decode("utf-8", errors="replace")
            ti = current_turn[0]
            if 0 <= ti < len(turn_logs):
                turn_logs[ti].append(text)

    room.on("data_received", _on_data)

    print(f"connecting to {settings.livekit_url} room={room_name} …")
    await room.connect(settings.livekit_url, token)
    print("connected")

    # Wait for the agent participant to join.
    print("waiting for agent participant…")
    deadline = time.monotonic() + AGENT_JOIN_TIMEOUT_S
    while time.monotonic() < deadline:
        if room.remote_participants:
            for p in room.remote_participants.values():
                print(f"  participant: {p.identity}")
            break
        await asyncio.sleep(0.5)
    else:
        print("WARN: no participant joined within timeout — continuing anyway")

    # Drive each turn.
    for i, turn in enumerate(user_turns):
        current_turn[0] = i
        print(f"\n=== turn {i + 1}/{len(user_turns)} ({len(turn)} chars) ===")
        print(f"send: {turn[:120].replace(chr(10), ' ')}{'…' if len(turn) > 120 else ''}")
        await room.local_participant.publish_data(
            turn.encode("utf-8"), reliable=True, topic=PROMPT_TOPIC
        )
        try:
            reply = await asyncio.wait_for(display_q.get(), timeout=REPLY_TIMEOUT_S)
            print(f"display ← {reply[:200]!r}")
        except TimeoutError:
            print("no reply (timeout — agent may have stayed silent on a pure statement)")
        if turn_logs[i]:
            for line in turn_logs[i][:6]:
                print(f"  [log] {line[:160]}")
        if i < len(expected) and expected[i]:
            print(f"  [expected] {expected[i][:160]}")

    print(f"\nsleeping {TRAILING_FLUSH_S}s to let extraction flush…")
    await asyncio.sleep(TRAILING_FLUSH_S)
    await room.disconnect()
    print("disconnected — done")


def _self_check() -> None:  # pragma: no cover
    user_turns, expected = parse_story(STORY)
    assert len(user_turns) >= 4, f"expected >=4 turns, got {len(user_turns)}"
    assert all(t.strip() for t in user_turns), "empty turn"
    assert SKIP_INTRO_SUBSTR not in user_turns[0], "intro not stripped"
    assert "Andi" in user_turns[0], "family monologue missing from turn 1"
    assert "Siapa cucu saya" in user_turns[-1], "retrieval test missing from last turn"
    print(f"story_driver self-check OK: {len(user_turns)} turns, intro stripped")


if __name__ == "__main__":  # pragma: no cover
    if "--self-check" in sys.argv:
        _self_check()
        sys.exit(0)
    parser = argparse.ArgumentParser(
        description="Drive the real Memora agent through the Pak Budi story."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="parse + print turns, no LiveKit connection"
    )
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
