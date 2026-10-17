"""
SentryCare Lite - the shift handoff brief.

We collect the facts ourselves (ranked patients, what nurses did, their
voice notes) and hand them to the AI with strict instructions: use only
these facts, no guessing, no diagnosis. The AI is the writer, not the doctor.
"""

from __future__ import annotations

from scoring import PatientPriority, Ward

HANDOFF_INSTRUCTIONS = """You help hospital nurses hand over at the end of a shift.
Write a short handoff brief using ONLY the facts given. Never guess, diagnose,
or suggest medicines or doses. If something is unclear, say "check with nurse".

Use exactly these three headings:
TOP PRIORITIES - up to 3 lines, most urgent first, each line starting with the bed number.
WHAT CHANGED THIS SHIFT - up to 3 lines.
WATCH NEXT SHIFT - up to 3 lines.

Plain, simple English. Under 150 words. No markdown symbols like * or #."""


def latest_status(actions: list[dict]) -> dict[str, str]:
    """The most recent action (Acknowledged / Resolved / Escalated) for each bed."""
    status: dict[str, str] = {}
    for action in actions:  # actions are stored oldest first
        status[action["bed"]] = f'{action["action"]} at {action["time"]}'
    return status


def build_handoff_facts(
    ward: Ward,
    ranked: list[PatientPriority],
    actions: list[dict],
    notes: list[dict],
) -> str:
    """Write out every fact the AI is allowed to use, as plain text."""
    status = latest_status(actions)
    lines = [
        f"Ward: {ward.name}. Shift: {ward.shift}.",
        "",
        "Patients in priority order (ranked by fixed rules, not by AI):",
    ]
    for position, patient in enumerate(ranked, start=1):
        lines.append(
            f"{position}. Bed {patient.bed}, {patient.patient}: {patient.band}. "
            f"Nurse action: {status.get(patient.bed, 'not yet seen')}."
        )
        lines += [f"   - {reason.text}" for reason in patient.reasons]

    lines += ["", "Nurse voice notes this shift (translated to English):"]
    if notes:
        lines += [f'- {note["time"]}, Bed {note["bed"]}: {note["english"]}' for note in notes]
    else:
        lines.append("- None recorded.")
    return "\n".join(lines)
