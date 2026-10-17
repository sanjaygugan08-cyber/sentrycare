"""
Checks for the triage rulebook. Run from the project folder with:  pytest

If you change the points in scoring.py, some of these numbers will change too.
That's expected: update the test so it describes the new rule.
"""

from datetime import datetime, timedelta
from pathlib import Path

from scoring import (
    COMPOUND_POINTS,
    COMPOUND_WINDOW,
    Alert,
    load_ward,
    rank_patients,
    score_patient,
)

SAMPLE = Path(__file__).resolve().parent.parent / "sample_alerts.json"
T0 = datetime(2026, 10, 16, 20, 0)


def make_alert(minutes: int, source: str, alert_type: str, bed: str = "1") -> Alert:
    return Alert(T0 + timedelta(minutes=minutes), bed, "Test Patient", source, alert_type, "detail")


def test_weak_signals_from_different_systems_add_up():
    patient = score_patient([
        make_alert(0, "Medicine cabinet", "missed_dose"),  # 20
        make_alert(150, "Vitals monitor", "vitals_drift"),  # 20
        make_alert(310, "Bed sensor", "bed_exit"),  # 15
    ])
    assert patient.score == 20 + 20 + 15 + 2 * COMPOUND_POINTS
    assert patient.band == "Act now"


def test_same_system_twice_gets_no_bonus():
    patient = score_patient([
        make_alert(0, "Vitals monitor", "hr_abnormal"),
        make_alert(0, "Vitals monitor", "fever"),
    ])
    assert patient.score == 25 + 25


def test_repeated_call_bell_adds_only_a_little():
    patient = score_patient([make_alert(m, "Call bell", "call_bell") for m in (0, 90, 180, 300)])
    assert patient.score == 10 + 3 * 5
    assert patient.band == "Routine"


def test_alerts_far_apart_are_not_combined():
    hours_apart = int(COMPOUND_WINDOW.total_seconds() // 60) + 60
    patient = score_patient([
        make_alert(0, "Medicine cabinet", "missed_dose"),
        make_alert(hours_apart, "Bed sensor", "bed_exit"),
    ])
    assert patient.score == 20 + 15


def test_unknown_alert_type_still_counts():
    assert score_patient([make_alert(0, "Lab", "something_new")]).score == 10


def test_sample_ward_ranking():
    ranked = rank_patients(load_ward(SAMPLE).alerts)
    assert [p.bed for p in ranked[:2]] == ["2", "7"]  # the fall, then the hidden decline
    assert all(earlier.score >= later.score for earlier, later in zip(ranked, ranked[1:]))
