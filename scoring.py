"""
SentryCare Lite - the triage rulebook.

This file decides WHO the nurse should see first. It uses simple, fixed
rules (no AI), so every score can be checked by hand and explained.

Think of it as a points table: each warning sign adds points, and warning
signs from *different* machines about the *same* patient add bonus points,
because small problems showing up together often mean real decline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. The points table. Change the numbers here to tune the ranking.
#    key in the data file -> (plain-language label, points)
# ---------------------------------------------------------------------------
ALERT_RULES: dict[str, tuple[str, int]] = {
    "fall_detected": ("Fall detected", 70),
    "spo2_low": ("Low oxygen level", 50),
    "missed_critical_dose": ("Missed high-risk medicine dose", 40),
    "bp_abnormal": ("Blood pressure out of range", 30),
    "hr_abnormal": ("Heart rate out of range", 25),
    "fever": ("Fever", 25),
    "missed_dose": ("Missed medicine dose", 20),
    "vitals_drift": ("Vitals slowly getting worse", 20),
    "bed_exit": ("Got out of bed alone", 15),
    "call_bell": ("Call bell pressed", 10),
}
UNKNOWN_RULE = ("Other alert", 10)  # used if the data has a type not listed above

REPEAT_POINTS = 5  # each extra time the same warning sign repeats
COMPOUND_POINTS = 20  # for each extra *different* system flagging the patient
COMPOUND_WINDOW = timedelta(hours=6)

# Priority bands: a score at or above the number gets that band.
ACT_NOW = 70
CHECK_SOON = 40


# ---------------------------------------------------------------------------
# 2. The shapes of our data.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Alert:
    """One alarm from one machine or system."""

    time: datetime
    bed: str
    patient: str
    source: str  # which system sent it, e.g. "Vitals monitor"
    type: str  # one of the ALERT_RULES keys
    detail: str  # short plain-language detail, e.g. "oxygen level 89%"


@dataclass(frozen=True)
class Reason:
    """One line of the 'why is this patient here?' explanation."""

    text: str  # shown on screen
    points: int


@dataclass(frozen=True)
class PatientPriority:
    """One row of the ranked queue: a patient, their score, and why."""

    bed: str
    patient: str
    score: int
    band: str
    reasons: list[Reason]
    alerts: list[Alert]
    latest: datetime


@dataclass(frozen=True)
class Ward:
    """Everything loaded from the data file."""

    name: str
    shift: str
    keyterms: list[str]  # names and medicine words to help speech-to-text
    alerts: list[Alert]


# ---------------------------------------------------------------------------
# 3. Loading the data file.
# ---------------------------------------------------------------------------
def load_ward(path: Path) -> Ward:
    """Read the ward's alerts from a JSON file."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    alerts = [
        Alert(
            time=datetime.fromisoformat(item["time"]),
            bed=str(item["bed"]),
            patient=item["patient"],
            source=item["source"],
            type=item["type"],
            detail=item["detail"],
        )
        for item in raw["alerts"]
    ]
    return Ward(
        name=raw.get("ward", "Ward"),
        shift=raw.get("shift", ""),
        keyterms=raw.get("keyterms", []),
        alerts=alerts,
    )


# ---------------------------------------------------------------------------
# 4. The ranking itself.
# ---------------------------------------------------------------------------
def band_for(score: int) -> str:
    if score >= ACT_NOW:
        return "Act now"
    if score >= CHECK_SOON:
        return "Check soon"
    return "Routine"


def score_patient(alerts: list[Alert]) -> PatientPriority:
    """Score one patient's alerts and explain every point."""
    alerts = sorted(alerts, key=lambda a: a.time)
    reasons: list[Reason] = []

    # (a) Points for each kind of warning sign (repeats add a little more).
    by_type: dict[str, list[Alert]] = {}
    for alert in alerts:
        by_type.setdefault(alert.type, []).append(alert)

    for alert_type, same_kind in by_type.items():
        label, base_points = ALERT_RULES.get(alert_type, UNKNOWN_RULE)
        points = base_points + REPEAT_POINTS * (len(same_kind) - 1)
        if len(same_kind) == 1:
            only = same_kind[0]
            text = f"{label} at {only.time:%H:%M}"
            if only.detail and only.detail.lower() != label.lower():
                text += f": {only.detail}"
        else:
            times = ", ".join(f"{a.time:%H:%M}" for a in same_kind)
            text = f"{label}, {len(same_kind)} times ({times})"
        reasons.append(Reason(text=text, points=points))

    # (b) Bonus when different systems flag the same patient close together.
    latest = alerts[-1].time
    recent_sources = sorted({a.source for a in alerts if latest - a.time <= COMPOUND_WINDOW})
    if len(recent_sources) > 1:
        bonus = COMPOUND_POINTS * (len(recent_sources) - 1)
        hours = int(COMPOUND_WINDOW.total_seconds() // 3600)
        text = (
            f"{len(recent_sources)} different systems flagged this patient within "
            f"{hours} hours ({', '.join(recent_sources)}), so small signs may be adding up"
        )
        reasons.append(Reason(text=text, points=bonus))

    score = sum(r.points for r in reasons)
    first = alerts[0]
    return PatientPriority(
        bed=first.bed,
        patient=first.patient,
        score=score,
        band=band_for(score),
        reasons=sorted(reasons, key=lambda r: r.points, reverse=True),
        alerts=alerts,
        latest=latest,
    )


def rank_patients(alerts: list[Alert]) -> list[PatientPriority]:
    """Group alerts by bed, score each patient, highest score first."""
    by_bed: dict[str, list[Alert]] = {}
    for alert in alerts:
        by_bed.setdefault(alert.bed, []).append(alert)

    ranked = [score_patient(group) for group in by_bed.values()]
    # Highest score first; if two are equal, the most recent alarm goes first.
    return sorted(ranked, key=lambda p: (p.score, p.latest), reverse=True)


def spoken_summary(patient: PatientPriority) -> str:
    """A short, speakable explanation (no point numbers) for translate + read aloud."""
    lines = [f"Bed {patient.bed}, {patient.patient}. Priority: {patient.band.lower()}."]
    lines += [f"{reason.text}." for reason in patient.reasons]
    return " ".join(lines)
