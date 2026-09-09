# Chargeback Risk Engine — Competitive Scorecard

| Dimension | Score | Evidence |
|---|---:|---|
| Problem clarity | 5/5 | Single routing decision: AUTO-CONTEST / HUMAN-REVIEW / ACCEPT-LOSS. |
| Technical depth | 4/5 | Risk, reason-aware evidence, relationship graph, economics, AI analyst, policy and audit are wired into one path. |
| Chargeback specificity | 5/5 | Evidence fields and policy gates are selected by chargeback reason code. |
| Risk modeling | 4/5 | Live Logistic Regression; held-out PR-AUC 0.723. |
| Evidence | 5/5 | PASS/WARN/FAIL evidence scoring and missing/contradictory evidence safety gates are tested. |
| Graph intelligence | 4/5 | Temporal relationship graph exposes shared identifiers and cluster/ring risk without a separate graph service. |
| Economics | 5/5 | Expected recovery, costs and net value are computed explicitly; candidate held-out expected net value ₹4,607,325. |
| AI usefulness | 4/5 | Structured evidence analyst returns supporting, contradicting, missing evidence and dispute-argument suggestions. |
| AI safety | 5/5 | AI is advisory; deterministic policy remains authoritative and offline fallback is implemented and tested. |
| False-positive management | 4/5 | Candidate auto-contest precision 75.9%; false-positive count 359. |
| Review optimization | 4/5 | 1%, 5%, 10%, and 20% review-budget outputs are generated from ranked HUMAN-REVIEW cases. |
| Security | 5/5 | API validation, monetary limits, prompt-injection boundary, replay/idempotency and retry safety are covered by tests. |
| Auditability | 5/5 | SQLite audit records carry versions, economic/evidence/graph/AI metadata, request ID and a SHA-256 hash chain. |
| Evaluation credibility | 3/5 | Bundled data is explicitly synthetic; train/dev/test separation is documented and test metrics are generated automatically. |
| Latency | 4/5 | Local p95 decision latency 2.51 ms in the generated benchmark. |
| Demo quality | 4/5 | One Streamlit dashboard and five deterministic case inputs. |
| Reproducibility | 5/5 | make judge runs tests, benchmark and report generation; artifacts are generated from repository data/code. |
| Documentation | 4/5 | README, architecture, security, data dictionary, evaluation and generated proof artifacts describe the same decision path. |

**Total:** 79/90

**Limitations:** The bundled evaluation is synthetic, the AI endpoint is optional, and the local latency benchmark is not a production SLO. The scorecard is an engineering self-assessment, not a ranking claim.
