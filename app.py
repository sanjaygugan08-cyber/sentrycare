"""
SentryCare Lite - the screen nurses see.

Start it from a terminal in this folder with:
    streamlit run app.py

Three tabs:
    1. Priority queue  - who to see first, and why (rules, no AI)
    2. Voice update    - speak a note in any Indian language (Sarvam Saaras)
    3. Shift handoff   - AI-drafted brief, translated and read aloud (Sarvam)

Actions and notes live in the shared logbook (store.py), so anything a nurse
says into a clip-on badge (badge_server.py) appears here within a few seconds.
"""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

import store
from handoff import HANDOFF_INSTRUCTIONS, build_handoff_facts, latest_status
from sarvam_service import LANGUAGES, VOICES, SarvamError, SarvamService
from scoring import PatientPriority, Ward, load_ward, rank_patients, spoken_summary

DATA_FILE = Path(__file__).parent / "sample_alerts.json"
BAND_COLOURS = {"Act now": "red", "Check soon": "orange", "Routine": "gray"}
ACTIONS = store.ACTIONS
LIVE_REFRESH_SECONDS = 3  # how often the screen checks the logbook for badge updates

# The team's demo languages. Sarvam supports 11 (see LANGUAGES in sarvam_service.py);
# to offer another one, copy its exact name from there into this list.
DEMO_LANGUAGES = ["తెలుగు · Telugu"]

st.set_page_config(page_title="SentryCare Lite", page_icon="🩺", layout="wide")

# Memory for this browser tab only. Actions and notes are NOT kept here: they
# live in the shared logbook (store.py) so the badges and the screen agree.
st.session_state.setdefault("pending_note", None)
st.session_state.setdefault("brief", None)  # {"text": ..., "facts": facts it was written from}
st.session_state.setdefault("explanations", {})  # bed -> {"language", "voice", "text", "clips"}


# ---------------------------------------------------------------------------
# Cached helpers: asking the same thing twice costs nothing the second time.
# (A leading underscore tells Streamlit not to use that argument in the cache key.)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def get_ward(path: Path, last_saved: float) -> Ward:
    """Load the ward file. `last_saved` makes it reload whenever you save the file."""
    return load_ward(path)


@st.cache_resource(show_spinner=False)
def get_service(api_key: str) -> SarvamService:
    return SarvamService(api_key)


@st.cache_data(show_spinner=False)
def translated(_service: SarvamService, text: str, target: str) -> str:
    return _service.translate(text, target, source="en-IN")


@st.cache_data(show_spinner=False)
def spoken(_service: SarvamService, text: str, language_code: str, voice: str) -> list[bytes]:
    return _service.speak(text, language_code, voice)


def play(clips: list[bytes]) -> None:
    for clip in clips:
        st.audio(clip, format="audio/wav" if clip[:4] == b"RIFF" else "audio/mpeg")


# ---------------------------------------------------------------------------
# Sidebar: key, language, voice
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Settings")
    api_key = os.environ.get("SARVAM_API_KEY", "")
    if api_key:
        st.success("Using the Sarvam key saved on this computer.")
    else:
        api_key = st.text_input(
            "Sarvam API key",
            type="password",
            help="From dashboard.sarvam.ai → API keys. Stays on this computer.",
        ).strip()
    # Only the team's demo languages; the first one (Tamil) opens by default.
    language_name = st.selectbox("Nurse's language", DEMO_LANGUAGES)
    language_code = LANGUAGES[language_name]
    voice = VOICES[st.radio("Voice", list(VOICES), horizontal=True)]
    st.divider()
    live_updates = st.toggle(
        "Live badge updates",
        value=True,
        help=f"Checks every {LIVE_REFRESH_SECONDS} seconds for actions and notes spoken into a badge.",
    )
    if st.button("Reset demo", help="Clears all actions and voice notes for a fresh run."):
        store.clear_shift()
        st.session_state.brief = None
        st.rerun()
    st.divider()
    st.caption("Demo with made-up patients only. Never type real patient details here.")

service = get_service(api_key) if api_key else None


def need_key() -> bool:
    """Show a friendly note and return True if there is no API key yet."""
    if service is None:
        st.info("Paste your Sarvam API key in the sidebar (left) to turn this on.")
        return True
    return False


def explain_aloud(patient: PatientPriority) -> None:
    """Translate the 'why' into the nurse's language, read it aloud, and remember it.

    Remembering it means the explanation stays on screen when other buttons are pressed.
    """
    text = spoken_summary(patient)
    with st.spinner(f"Translating to {language_name} and recording voice…"):
        try:
            local_text = text if language_code == "en-IN" else translated(service, text, language_code)
            clips = spoken(service, local_text, language_code, voice)
        except SarvamError as error:
            st.error(str(error))
            return
    st.session_state.explanations[patient.bed] = {
        "language": language_code,
        "voice": voice,
        "text": local_text,
        "clips": clips,
    }


def show_saved_explanation(bed: str) -> None:
    """Show this patient's last explanation, if it matches the current language and voice."""
    saved = st.session_state.explanations.get(bed)
    if saved and saved["language"] == language_code and saved["voice"] == voice:
        st.info(saved["text"])
        play(saved["clips"])


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
ward = get_ward(DATA_FILE, DATA_FILE.stat().st_mtime)
ranked = rank_patients(ward.alerts)
actions = store.list_actions()
notes = store.list_notes()
status = latest_status(actions)


@st.fragment(run_every=LIVE_REFRESH_SECONDS if live_updates else None)
def watch_logbook(seen: tuple[int, int]) -> None:
    """Quietly re-check the logbook; redraw the page only when a badge added something."""
    if (len(store.list_actions()), len(store.list_notes())) != seen:
        st.rerun(scope="app")


watch_logbook((len(actions), len(notes)))

st.title("SentryCare Lite")
st.caption(f"{ward.name} · {ward.shift} · {len(ward.alerts)} alarms from 4 systems → 1 list")

counts = {band: sum(p.band == band for p in ranked) for band in BAND_COLOURS}
for column, (band, count) in zip(st.columns(3), counts.items()):
    column.metric(band, count, border=True)

queue_tab, voice_tab, handoff_tab = st.tabs(["① Priority queue", "② Voice update", "③ Shift handoff"])

# ---------------------------------------------------------------------------
# Tab 1: Priority queue (works without a key: the ranking is plain rules)
# ---------------------------------------------------------------------------
with queue_tab:
    from_badges = [a for a in actions if a["source"] != "screen"][-3:]
    from_badges += [n for n in notes if n["source"] != "screen"][-3:]
    if from_badges:
        with st.expander("📟 Latest from badges", expanded=True):
            for item in sorted(from_badges, key=lambda x: x["time"], reverse=True):
                what = item.get("action") or f'note: "{item["english"]}"'
                st.markdown(f'**{item["time"]}** · {item["source"]} · Bed {item["bed"]} · {what}')
    for position, patient in enumerate(ranked, start=1):
        with st.container(border=True):
            info, buttons = st.columns([4, 1])
            with info:
                st.subheader(f"#{position} · Bed {patient.bed} · {patient.patient}")
                badges = st.container(horizontal=True)
                badges.badge(patient.band, color=BAND_COLOURS[patient.band])
                badges.badge(f"score {patient.score}", color="gray")
                if patient.bed in status:
                    badges.badge(status[patient.bed], color="blue")
                for reason in patient.reasons:
                    st.markdown(f"- {reason.text} **(+{reason.points})**")
            with buttons:
                for action in ACTIONS:
                    if st.button(action, key=f"{action}-{patient.bed}", width="stretch"):
                        store.add_action(patient.bed, action, source="screen")
                        st.rerun()
            if st.button(f"🔊 Explain in {language_name}", key=f"explain-{patient.bed}"):
                if not need_key():
                    explain_aloud(patient)
            show_saved_explanation(patient.bed)

# ---------------------------------------------------------------------------
# Tab 2: Voice update - speak, see the text, save it to the patient
# ---------------------------------------------------------------------------
with voice_tab:
    st.write("Pick the patient, press the mic, and speak naturally in any Indian language (mixing English is fine).")
    labels = {f"Bed {p.bed} · {p.patient}": p.bed for p in ranked}
    chosen = st.selectbox("Patient", list(labels))
    # English is included because nurses often mix it in or speak it outright.
    spoken_language = st.selectbox("Language you will speak", ["Auto-detect", *DEMO_LANGUAGES, "English"])
    recording = st.audio_input("Record your update")

    if recording and st.button("Turn speech into text", type="primary") and not need_key():
        with st.spinner("Listening…"):
            try:
                result = service.transcribe(
                    recording.getvalue(),
                    language_code=LANGUAGES.get(spoken_language, "unknown"),
                    keyterms=ward.keyterms,
                )
                st.session_state.pending_note = {"bed": labels[chosen], "result": result}
            except SarvamError as error:
                st.error(str(error))

    pending = st.session_state.pending_note
    if pending:
        result = pending["result"]
        with st.container(border=True):
            st.markdown(f"**You said** ({result.language_code or 'language not detected'}):")
            st.write(result.text)
            st.markdown("**English for the record:**")
            st.write(result.english)
            if st.button(f"Save to Bed {pending['bed']}"):
                store.add_note(pending["bed"], result.text, result.english, source="screen")
                st.session_state.pending_note = None
                st.toast("Saved")
                st.rerun()

    st.subheader("Notes this shift")
    if notes:
        st.dataframe(notes, hide_index=True)
    else:
        st.caption("No voice notes yet.")

# ---------------------------------------------------------------------------
# Tab 3: Shift handoff - AI drafts, nurse checks, then translate + read aloud
# ---------------------------------------------------------------------------
with handoff_tab:
    facts = build_handoff_facts(ward, ranked, actions, notes)
    with st.expander("What the AI is given (nothing else)"):
        st.text(facts)

    if st.button("✍️ Write handoff brief", type="primary") and not need_key():
        with st.spinner("Writing the brief…"):
            try:
                st.session_state.brief = {
                    "text": service.write(HANDOFF_INSTRUCTIONS, facts),
                    "facts": facts,
                }
            except SarvamError as error:
                st.error(str(error))

    saved_brief = st.session_state.brief
    brief_is_current = saved_brief is not None and saved_brief["facts"] == facts
    brief = saved_brief["text"] if brief_is_current else None
    if saved_brief and not brief_is_current:
        # A nurse acted or saved a note after the brief was written: don't show stale facts.
        st.info("Something changed since the last brief (a nurse action or voice note). Press **Write handoff brief** again.")
    if brief:
        st.warning("AI-written draft. The nurse handing over must read and correct it before use.")
        st.text(brief)
        if st.button(f"🔊 Read it in {language_name}") and not need_key():
            with st.spinner("Translating and recording…"):
                try:
                    local_brief = brief if language_code == "en-IN" else translated(service, brief, language_code)
                    clips = spoken(service, local_brief, language_code, voice)
                except SarvamError as error:
                    st.error(str(error))
                else:
                    st.text(local_brief)
                    play(clips)
