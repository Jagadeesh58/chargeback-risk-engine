# Demo

## Primary experience

Run:

```bash
streamlit run apps/app_deployed.py
```

The main screen shows:

- case ID, reason and amount
- final decision
- model risk estimate and calibrated view
- evidence PASS/WARN/FAIL
- deterministic reasons
- expected recovery and expected net value
- graph signal
- counterfactual result
- model, feature and policy versions
- audit ID
- contest draft when the action is `AUTO-CONTEST`

The Proof tab runs the same engine against the held-out synthetic test set without adding those evaluation cases to the normal audit database.

## API

```bash
uvicorn apps.api:app --reload
```

Then send a case to:

```text
POST /decision
```

The compatibility `/score` route is hidden from the OpenAPI schema and calls the same canonical engine.

## Exactly five CLI scenarios

Run:

```bash
python scripts/demo.py
```

The script demonstrates exactly five deterministic scenarios:

1. **AUTO-CONTEST** — strong evidence and positive expected net value.
2. **HUMAN-REVIEW** — incomplete evidence prevents automation.
3. **ACCEPT-LOSS** — low model estimate makes contesting unattractive; a single evidence change is shown as a risk/decision counterfactual.
4. **ADVERSARIAL** — contradictory evidence and an ignored prompt-injection string remain safely in human review.
5. **COUNTERFACTUAL** — one valid evidence flip changes the actual policy decision.

Idempotency is validated by the API regression suite rather than represented as a sixth demo scenario.

## Observed demo behavior

The current deterministic run produces:

| Scenario | Decision | Counterfactual result |
|---|---|---|
| AUTO-CONTEST | AUTO-CONTEST | Risk changed, decision unchanged |
| HUMAN-REVIEW | HUMAN-REVIEW | No unsafe automation |
| ACCEPT-LOSS | ACCEPT-LOSS | Tracking number can move it to HUMAN-REVIEW |
| ADVERSARIAL | HUMAN-REVIEW | Contradictory evidence blocks automation |
| COUNTERFACTUAL | AUTO-CONTEST | Tracking number removal changes the decision to HUMAN-REVIEW |

These are synthetic demo cases, not production examples.

## Integration scope

The Razorpay-compatible adapter creates a **contest draft**. The demo never submits a real dispute externally and does not require credentials.
