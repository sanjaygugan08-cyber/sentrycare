# SentryCare Lite: 2-hour demo with Sarvam

One ranked list of patients instead of four separate alarm systems. You can
speak an update in any Indian language, and the app reads alerts and the
shift handoff aloud in the nurse's own language.

**This demo uses made-up patients only. Never put real patient data in it.**

## Run it

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      Mac:  source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

A browser tab opens. The priority queue works straight away. Paste your
Sarvam API key (from https://dashboard.sarvam.ai) into the sidebar to turn on
voice, translation and the handoff brief.

To avoid pasting the key every time, save it before running the app (optional):
- Windows (PowerShell): `$env:SARVAM_API_KEY="your-key"`
- Mac: `export SARVAM_API_KEY="your-key"`

## What each file does

| File | Job | Analogy |
|---|---|---|
| `app.py` | The screen: tabs, buttons, lists | The nurses' station |
| `scoring.py` | Ranks patients with fixed, explainable rules (no AI) | The triage rulebook |
| `sarvam_service.py` | Every call to Sarvam, in one place | The phone line to the lab |
| `handoff.py` | Gathers facts and instructions for the AI handoff brief | The handoff checklist |
| `sample_alerts.json` | Made-up alarms for one night shift | Tonight's alarm log |
| `tests/` | Automatic checks for the rulebook (`pytest`) | Quality control |

## Make it yours

- **Change the ward:** edit `sample_alerts.json` (beds, times, alert types).
- **Change how urgent things are:** edit the points in `ALERT_RULES` at the top of `scoring.py`.
- **Help it hear names and medicine words:** add them to `keyterms` in `sample_alerts.json`.

## Credits

New Sarvam accounts get ₹100 of free credits, which is enough for a demo.
Clicking the same button twice reuses the first answer, so repeat clicks cost nothing.
