"""
SentryCare - the badge server.

Clip-on badges (and the hold-to-talk test page) send a short voice recording
here. The server:

    1. turns the speech into text with Sarvam (any Indian language),
    2. works out what the nurse meant with fixed rules (badge_commands.py),
    3. writes the action or note into the shared logbook (store.py),
       so it appears on the nurses' screen,
    4. replies out loud, in the nurse's language, through the badge speaker.

Start it from this folder with (the key must be saved first, see README):
    uvicorn badge_server:app --host 0.0.0.0 --port 8000

Test page without any hardware:  http://localhost:8000/badge/simulator
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import wave
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

import store
from badge_commands import parse_command, reply_for
from sarvam_service import LANGUAGES, SarvamError, SarvamService
from scoring import load_ward, rank_patients

DATA_FILE = Path(__file__).parent / "sample_alerts.json"
SIMULATOR_PAGE = Path(__file__).parent / "badge_simulator.html"
MIN_AUDIO_BYTES = 4000  # anything shorter is a button tap, not speech
SUPPORTED_LANGUAGES = set(LANGUAGES.values())

app = FastAPI(title="SentryCare badge server")


@lru_cache(maxsize=1)
def get_service() -> SarvamService:
    api_key = os.environ.get("SARVAM_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(503, "SARVAM_API_KEY is not set on the laptop running the badge server.")
    return SarvamService(api_key)


def join_wavs(clips: list[bytes]) -> bytes:
    """Glue WAV clips (same format) into one plain WAV file.

    Always rewritten, even for a single clip, so the file starts with a standard
    44-byte header: the badge firmware skips exactly that and streams the rest.
    """
    frames, params = [], None
    for clip in clips:
        with wave.open(io.BytesIO(clip)) as part:
            params = params or part.getparams()
            frames.append(part.readframes(part.getnframes()))
    out = io.BytesIO()
    with wave.open(out, "wb") as joined:
        joined.setparams(params)
        for chunk in frames:
            joined.writeframes(chunk)
    return out.getvalue()


def handle_utterance(
    audio: bytes,
    content_type: str,
    badge: str,
    language: str,
    voice: str,
    sample_rate: int,
) -> dict:
    """The whole badge round trip. Returns what was heard, the reply, and the reply audio."""
    service = get_service()
    ward = load_ward(DATA_FILE)
    ranked = rank_patients(ward.alerts)

    heard = service.transcribe(audio, "unknown", ward.keyterms, content_type)
    command = parse_command(heard.english)
    known_bed = command.bed in {patient.bed for patient in ranked}

    if command.kind in ("action", "note") and known_bed:
        store.add_note(command.bed, heard.text, heard.english, source=badge)
        if command.action:
            store.add_action(command.bed, command.action, source=badge)

    latest = {action["bed"]: action["action"] for action in store.list_actions()}
    reply_english = reply_for(command, ranked, latest)
    reply_local = service.translate(reply_english, language) if language != "en-IN" else reply_english
    reply_audio = join_wavs(service.speak(reply_local, language, voice, sample_rate=sample_rate))

    print(f"[{badge}] heard: {heard.english!r} -> {command.kind} {command.bed or ''} {command.action or ''}")
    print(f"[{badge}] reply: {reply_english!r}")
    return {
        "heard": heard.text,
        "heard_english": heard.english,
        "command": command.kind,
        "bed": command.bed,
        "action": command.action,
        "reply": reply_local,
        "reply_english": reply_english,
        "audio": reply_audio,
    }


@app.get("/health")
def health() -> dict:
    """Quick check that the server is up (open it in a browser)."""
    return {"ok": True, "sarvam_key_set": bool(os.environ.get("SARVAM_API_KEY", "").strip())}


@app.post("/badge/talk")
async def badge_talk(
    request: Request,
    badge: str = "badge-1",
    lang: str = "te-IN",
    voice: str = "ishita",
    sample_rate: int = 8000,
    format: str = "wav",
):
    """Receive one recording, act on it, and answer.

    format=wav  (badges): the reply is a WAV file to play straight away.
    format=json (test page): the reply also carries the words heard and said.
    """
    if lang not in SUPPORTED_LANGUAGES:
        raise HTTPException(400, f"Unknown language {lang!r}. Use one of {sorted(SUPPORTED_LANGUAGES)}.")
    audio = await request.body()
    if len(audio) < MIN_AUDIO_BYTES:
        raise HTTPException(400, "Recording too short. Hold the button while you speak.")
    content_type = request.headers.get("content-type", "audio/wav")

    try:
        result = await asyncio.to_thread(
            handle_utterance, audio, content_type, badge, lang, voice, sample_rate
        )
    except SarvamError as error:
        print(f"[{badge}] Sarvam problem: {error}")
        raise HTTPException(502, str(error)) from error

    if format == "json":
        result["audio"] = base64.b64encode(result["audio"]).decode()
        return JSONResponse(result)
    return Response(result["audio"], media_type="audio/wav")


@app.get("/badge/simulator", response_class=HTMLResponse)
def simulator() -> str:
    """A hold-to-talk page that behaves exactly like a badge (backup for demos)."""
    return SIMULATOR_PAGE.read_text(encoding="utf-8")
