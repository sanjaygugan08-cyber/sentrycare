"""
SentryCare Lite - the phone line to Sarvam.

Every call to Sarvam's servers lives in this one file, so the rest of the
app never needs to know the details. If Sarvam renames a model, this is the
only file to edit.

What each Sarvam model does for us:
    Saaras          -> the EARS:   speech in any Indian language -> text
    Sarvam-Translate-> the INTERPRETER: English <-> Indian languages
    Bulbul          -> the MOUTH:  text -> natural speech
    Sarvam-105B     -> the WRITER: drafts the shift handoff brief
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass

from sarvamai import SarvamAI
from sarvamai.core.api_error import ApiError

# Model names (check https://docs.sarvam.ai/api/getting-started/models for newer ones)
STT_MODEL = "saaras:v4"
TRANSLATE_MODEL = "sarvam-translate:v1"
AUTO_DETECT_TRANSLATE_MODEL = "mayura:v1"  # used only when the source language is unknown
TTS_MODEL = "bulbul:v3"
CHAT_MODEL = "sarvam-105b"

# Sarvam's size limits per request (characters). We split longer text.
TRANSLATE_CHAR_LIMIT = 2000
TTS_CHAR_LIMIT = 2500
MAX_KEYTERMS = 50

# The 11 languages Sarvam can both translate AND speak aloud.
LANGUAGES: dict[str, str] = {
    "English": "en-IN",
    "हिन्दी · Hindi": "hi-IN",
    "తెలుగు · Telugu": "te-IN",
    "தமிழ் · Tamil": "ta-IN",
    "ಕನ್ನಡ · Kannada": "kn-IN",
    "മലയാളം · Malayalam": "ml-IN",
    "मराठी · Marathi": "mr-IN",
    "বাংলা · Bengali": "bn-IN",
    "ગુજરાતી · Gujarati": "gu-IN",
    "ਪੰਜਾਬੀ · Punjabi": "pa-IN",
    "ଓଡ଼ିଆ · Odia": "od-IN",
}

# Two voices that Sarvam documents across all 11 languages.
VOICES: dict[str, str] = {"Female (Ishita)": "ishita", "Male (Shubh)": "shubh"}


class SarvamError(Exception):
    """A problem talking to Sarvam, with a message a non-coder can act on."""


@dataclass(frozen=True)
class Transcript:
    text: str  # exactly what was said, in the language it was said
    english: str  # English version for the record
    language_code: str | None


def _friendly_message(error: Exception) -> str:
    """Turn a technical error into a plain instruction."""
    if isinstance(error, ApiError):
        status = error.status_code
        if status in (401, 403):
            return "Sarvam rejected the API key. Re-copy it from dashboard.sarvam.ai and paste it again."
        if status == 402:
            return "Your Sarvam credits have run out. Add credits on dashboard.sarvam.ai."
        if status == 429:
            return "Too many requests in a short time. Wait one minute and try again."
        if status in (400, 422):
            return f"Sarvam could not process this request (code {status}): {error.body}"
        return f"Sarvam had a problem (code {status}). Try again in a moment."
    return f"Could not reach Sarvam. Check your internet connection. ({type(error).__name__})"


def _split_text(text: str, limit: int) -> list[str]:
    """Split long text into pieces under `limit`, cutting at sentence ends."""
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[.!?।\n])\s+", text)
    pieces, current = [], ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > limit:
            pieces.append(current)
            current = ""
        while len(sentence) > limit:  # a single very long sentence: hard cut
            pieces.append(sentence[:limit])
            sentence = sentence[limit:]
        current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


class SarvamService:
    """One object that knows how to ask Sarvam for each job."""

    def __init__(self, api_key: str) -> None:
        self._client = SarvamAI(api_subscription_key=api_key)

    # --- EARS: speech -> text -------------------------------------------------
    def transcribe(
        self,
        audio_bytes: bytes,
        language_code: str = "unknown",
        keyterms: list[str] | None = None,
    ) -> Transcript:
        """Turn a voice note into text, plus an English copy for the record.

        `language_code="unknown"` lets Sarvam detect the language itself.
        `keyterms` are names and medicine words it should listen out for.
        """
        request = {
            "file": ("voice-note.wav", audio_bytes, "audio/wav"),
            "model": STT_MODEL,
            "mode": "transcribe",
            "language_code": language_code,
        }
        terms = (keyterms or [])[:MAX_KEYTERMS]
        try:
            if terms:
                try:
                    response = self._client.speech_to_text.transcribe(**request, keyterms=terms)
                except ApiError as error:
                    # If key terms are not accepted here, retry once without them.
                    if error.status_code not in (400, 422):
                        raise
                    response = self._client.speech_to_text.transcribe(**request)
            else:
                response = self._client.speech_to_text.transcribe(**request)
        except Exception as error:  # noqa: BLE001 - shown to the user as plain text
            raise SarvamError(_friendly_message(error)) from error

        text = (response.transcript or "").strip()
        detected = response.language_code
        if not text:
            raise SarvamError("No speech was heard. Hold the phone closer and try again.")
        if detected and detected.startswith("en"):
            english = text
        else:
            english = self.translate(text, "en-IN", source=detected or "auto")
        return Transcript(text=text, english=english, language_code=detected)

    # --- INTERPRETER: text -> text in another language ------------------------
    def translate(self, text: str, target: str, source: str = "en-IN") -> str:
        """Translate text. Returns the text unchanged if no translation is needed."""
        if not text.strip() or source == target:
            return text
        model = AUTO_DETECT_TRANSLATE_MODEL if source == "auto" else TRANSLATE_MODEL
        try:
            pieces = [
                self._client.text.translate(
                    input=piece,
                    source_language_code=source,
                    target_language_code=target,
                    model=model,
                ).translated_text
                for piece in _split_text(text, TRANSLATE_CHAR_LIMIT)
            ]
        except Exception as error:  # noqa: BLE001
            raise SarvamError(_friendly_message(error)) from error
        return "\n".join(pieces)

    # --- MOUTH: text -> speech ------------------------------------------------
    def speak(self, text: str, language_code: str, voice: str) -> list[bytes]:
        """Read text aloud. Returns one or more audio clips (long text is split)."""
        clips: list[bytes] = []
        try:
            for piece in _split_text(text, TTS_CHAR_LIMIT):
                response = self._client.text_to_speech.convert(
                    text=piece,
                    language_code=language_code,
                    speaker=voice,
                    model=TTS_MODEL,
                )
                clips += [base64.b64decode(audio) for audio in response.audios]
        except Exception as error:  # noqa: BLE001
            raise SarvamError(_friendly_message(error)) from error
        return clips

    # --- WRITER: instructions + facts -> short text ---------------------------
    def write(self, instructions: str, facts: str) -> str:
        """Ask Sarvam-105B to write something using only the facts given."""
        try:
            response = self._client.chat.completions(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": facts},
                ],
                temperature=0.2,  # low = steady, less "creative"
                max_tokens=2000,  # room for its thinking + the answer
                reasoning_effort="low",
            )
        except Exception as error:  # noqa: BLE001
            raise SarvamError(_friendly_message(error)) from error

        content = response.choices[0].message.content or ""
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        if not content:
            raise SarvamError("The AI sent back an empty answer. Press the button again.")
        return content
