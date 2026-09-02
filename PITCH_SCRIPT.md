# Pitch Script (~5 minutes)

Razorpay AI Buildathon 2026 — Track 02: AI Risk Manager.

Every number and quote below came from actually running this project's
code (see the commands next to each section) — nothing here is invented
for the pitch. Read it in first person, aloud, timing yourself once
before recording.

---

## 0:00 – 0:35 — The problem, in plain language

> A customer disputes a charge with their bank — a chargeback. The
> merchant's money gets pulled back *immediately*, before anyone checks
> whether the dispute is legitimate. The merchant can contest it by
> submitting evidence, but contesting costs time and a filing fee, and
> losing a contest recovers nothing. Every merchant handling disputes at
> volume needs to decide, dispute by dispute: contest, accept the loss,
> or send it to a human — and doing that badly at scale is expensive in
> both directions.

## 0:35 – 1:00 — What this is, and what it deliberately isn't

> This is a scoring-and-policy pipeline: one dispute in, one decision
> out — `AUTO-CONTEST`, `HUMAN REVIEW`, or `ACCEPT LOSS`. It's not an
> agent. It never browses, negotiates, or acts on its own initiative,
> and nothing it produces is ever submitted anywhere automatically —
> every contest it recommends comes out as a draft for a human to
> review, never a live submission.

## 1:00 – 1:45 — Architecture, fast

*(Show `ARCHITECTURE.md`'s diagram on screen.)*

> Evidence goes through a rule-based, reason-code-aware scorer, then a
> deterministic policy engine. The policy engine has two safety checks
> that run *unconditionally*, before the model's probability is even
> read: a monetary ceiling, and an evidence-completeness gate. Every
> decision is written once to a SQLite audit log — resubmitting the same
> dispute replays the original decision instead of recomputing it. And
> when the decision is to contest, a mock adapter generates a draft
> evidence submission in Razorpay's real API shape — structurally
> incapable of producing anything but a draft.

## 1:45 – 3:45 — Three real cases, run live

Run these three ahead of time (or live) — output is exact, copied from
a real run, not written by hand:

```bash
python -c "
from local_pipeline import score_dispute_locally
r = score_dispute_locally({
    'dispute_id': 'DEMO_EASY_WIN', 'reason_code': 'item_not_received', 'amount': 2400.0,
    'has_tracking_number': True, 'has_delivery_confirmation': True, 'has_signature_confirmation': True,
})
print(r['action'], r['win_probability'], r['reason'])
"
```

**Case 1 — easy win.** Tracking number, delivery confirmation, and
signature confirmation all present. Raw probability **0.924**.
Calibrated: **0.762** — the calibration layer is honest that "92%
confident" from the raw scorer doesn't mean 92% actually win, based on
what really happened in the dev set. Either way: `AUTO-CONTEST`, and a
ready-to-review draft evidence submission comes back with it, in
Razorpay's real field shapes — never auto-submitted.

**Case 2 — genuinely ambiguous.** One field confirmed, one confirmed
absent, one unknown. They cancel out exactly: probability **0.50**,
right in the dead center between the two thresholds. `HUMAN REVIEW` — no
draft is generated, because there's nothing confident enough to draft.

**Case 3 — the one that matters most.** Identical evidence to Case 1.
Same raw probability, **0.924**. Same calibrated probability, **0.762**.
The only thing that changed is the amount: Rs 7,25,000 instead of
Rs 2,400. Result: `HUMAN REVIEW` — *"Amount 725000.00 exceeds monetary
ceiling 50000.00 — always routed to a human regardless of model
confidence."* This is the single most important property in the whole
project: no matter how confident the model is, a large dispute always
goes to a human. It's proven with a 2000-case fuzz test, not just this
one example.

## 3:45 – 4:20 — The honest numbers

> On a held-out synthetic test set — 900 disputes, never touched during
> design — the scorer's AUC is 0.688. Precision on auto-contest calls is
> 0.703, recall 0.569. The number that matters most for an *autonomous*
> system is false-positive cost: this pipeline's wrong auto-contests cost
> Rs 18,300 total, versus Rs 58,800 for a naive "contest everything"
> baseline — about a third of the cost, by design, not by accident. And
> the calibration layer measurably improves the probability estimate
> itself: mean calibration error drops from 0.1218 to 0.0849 on data it
> never saw while fitting.

## 4:20 – 4:45 — Where AI actually is in this

> A trained Logistic Regression model was built and evaluated honestly
> against the same test set — it tied the rule-based scorer's AUC
> exactly, which was investigated rather than shrugged off. The
> autonomous decision stays rule-based, because it performs identically
> and is fully explainable. The AI that *is* in the live path is a
> data-fit isotonic calibration layer, correcting the probability shown
> to a human — used deliberately where it measurably helps, kept out of
> where an unexplainable model would be a liability.

## 4:45 – 5:00 — Honest limitations, then close

> This is measured inside a synthetic evaluation environment — not a
> claim about real-world chargeback outcomes. The Razorpay integration is
> mock-only; there are no live credentials, and the field-shape mapping
> is my own best-effort match to their public docs, not something they
> verified. Both of those are stated plainly in the README, not hidden.
> That honesty, and the fact that every safety property here is proven
> with a real test rather than just claimed, is the actual pitch.

---

## Recording checklist

- [ ] Time yourself once, unrecorded, before the real take.
- [ ] Have the three case commands ready in a terminal, or pre-run and
      screenshotted, so nothing hangs live.
- [ ] Show `ARCHITECTURE.md`'s diagram on screen during the 1:00–1:45 section.
- [ ] Show the README's Results table on screen during 3:45–4:20.
- [ ] Don't round the false-positive-cost or calibration numbers further
      than they're written above — they're exact, and a follow-up
      question checking your math should hold up.
