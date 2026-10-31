# Architectural Decisions Record (ADR)

This document records the five most critical architectural and engineering decisions in the **Chargeback Risk Engine**, the alternatives evaluated, the trade-offs, and the rationale for the choices made.

---

## Decision 1: Deterministic Policy Authority Over Pure Machine Learning

### Context
In automated financial decision systems, machine learning models (e.g., Logistic Regression, Gradient Boosted Trees, Neural Networks) and Large Language Models (LLMs) estimate likelihoods based on statistical correlations. However, financial actions have non-negotiable legal, compliance, and fiduciary consequences.

### Alternatives Considered
1. **End-to-End ML Policy (Direct Action Classification):** Train a multiclass classifier to output `AUTO-CONTEST`, `HUMAN-REVIEW`, or `ACCEPT-LOSS` directly.
2. **LLM Agent with Function Calling:** Feed dispute details, evidence, and customer history into an LLM agent that directly executes dispute representment API calls.
3. **Threshold-Gated ML with Deterministic Safety Policy (Selected):** ML models and LLMs produce advisory signals only (calibrated win probability, feature attributions, evidence summaries); a pure Python deterministic policy layer alone selects the financial action.

### Why This Was Chosen
- **Financial Fiduciary Boundary:** ML models and LLMs are vulnerable to distributional drift, hallucinations, adversarial perturbations, and prompt injections. An LLM must never be given authority to authorize financial actions or move funds.
- **Strict Compliance & Legal Defensibility:** Visa, Mastercard, and acquiring banks mandate explicit reason-code representment rules. Deterministic policy guarantees that mandatory evidence gates (e.g., proof of delivery for Item Not Received), statutory monetary ceilings (₹50,000), and contest count limits are strictly enforced with zero probability of model bypass.
- **Auditability & Explainability:** A deterministic rule engine provides exact, rule-by-rule audit explanations (e.g., *"Evidence completeness 0.33 is below required 0.50"*), satisfying regulatory transparency under FCRA and banking audit requirements.

---

## Decision 2: Isotonic Calibration Over Platt Scaling and Raw Probabilities

### Context
Raw classification scores from Logistic Regression or rules baselines reflect uncalibrated ranking signals rather than true empirical probabilities. Accurate expected value calculations ($\text{EV} = p \times \text{amount} - \text{cost}$) require that when the model predicts 0.70, exactly 70% of those disputes are won in reality.

### Alternatives Considered
1. **Raw Scorer Probabilities:** Use logistic sigmoid outputs directly without calibration.
2. **Platt Scaling (Sigmoid Logistic Calibration):** Fit a secondary univariate logistic regression to map raw logits to calibrated probabilities.
3. **Isotonic Regression / Pool Adjacent Violators Algorithm (PAVA) (Selected):** Fit a non-parametric, monotonic step function using PAVA on held-out development set predictions.

### Why This Was Chosen
- **Non-Parametric Flexibility:** Platt scaling assumes a sigmoidal distortion of probabilities. Chargeback dispute outcomes often exhibit non-sigmoidal empirical win curves due to non-linear card network evidence requirements and dispute thresholds.
- **Preservation of Monotonic Ranking:** PAVA strictly enforces monotonicity ($\hat{y}_{i} \le \hat{y}_{j}$ whenever $x_i \le x_j$), ensuring that higher evidence scores never produce lower win probabilities.
- **Measured Empirical Superiority:** On the held-out test set, isotonic regression calibrated on the live model's development set predictions achieved a lower Brier score (**0.2171** vs **0.2175** raw), eliminating the calibration bug where previous implementations fitted on rules scorers distorted live model probabilities.

---

## Decision 3: Graph Relationship Analysis on Buyer Identifiers Only (Dropping `merchant_id`)

### Context
Graph relationship analysis detects organized dispute abuse, sybil networks, and multi-account fraud rings by clustering disputes that share identifiers (IP address, device ID, card fingerprint, customer ID).

### Alternatives Considered
1. **Full Entity Graph Including `merchant_id`:** Link all disputes sharing any identifier, including the merchant account ID.
2. **Weighted Bipartite Graph:** Weight edges differently based on entity type (e.g., lower weight for `merchant_id`).
3. **Buyer-Side Identifiers Only with Hub Degree Capping (Selected):** Explicitly exclude `merchant_id` from relationship clustering (`ENTITY_FIELDS = ("customer_id", "device_id", "ip_address", "card_fingerprint")`) and cap traversal through high-degree benign hubs (degree $> 20$).

### Why This Was Chosen
- **Elimination of Merchant-Wide Fraud False Positives:** Including `merchant_id` as an entity creates a super-node linking all disputes from the same merchant. In testing, after 5 unrelated disputes from different customers, the graph escalated to `ORGANIZED_ABUSE` and forced every subsequent customer dispute into `HUMAN-REVIEW`. Any busy merchant was effectively disabled.
- **Benign Infrastructure Hub Capping:** Shared public IPs (e.g., university Wi-Fi, mobile carrier NAT gateways) naturally accumulate dozens of disputes. By capping traversal at `max_hub_degree = 20`, benign hubs do not cross-link thousands of innocent buyers into a synthetic "fraud ring".
- **Targeted Fraud Ring Detection:** Restricting entities to buyer-side hardware, network, and financial tokens accurately isolates real sybil attacks: multiple customer IDs sharing the same physical device ID or card fingerprint.

---

## Decision 4: Cryptographically Hash-Chained Audit Ledger Over Simple Append-Only Table

### Context
Dispute operations require durable recordkeeping for dispute replays, acquirer inquiries, and financial audits. Systems must prove that historical records have not been retroactively altered or deleted after decisions were rendered.

### Alternatives Considered
1. **Standard Relational Table (Mutable Records):** Insert rows into SQLite/Postgres with standard timestamps.
2. **Append-Only Table with Database Write Permissions:** An append-only table without cryptographic hashes, relying on database access control.
3. **Cryptographically Hash-Chained Ledger with Canonical Payload Hashing (Selected):** Each decision row contains a canonical SHA-256 digest of the request payload, links to the previous row's digest (`prev_hash`), and computes its own `record_hash = SHA256(payload || prev_hash)`.

### Why This Was Chosen
- **Tamper-Evidence Against Retroactive Edits:** Any retroactive modification to a historical decision (e.g., altering evidence status, amount, or action) breaks the SHA-256 hash chain for all subsequent rows, instantly detectable via `/audit/verify`.
- **True Idempotency with Conflict Detection (HTTP 409):** Storing a canonical hash of the normalized request payload prevents silent split-brain execution. Resubmitting the same `dispute_id` with an identical payload returns the cached decision (`replayed: true`), while resubmitting with a mutated amount or evidence raises `PayloadConflictError` (HTTP 409 Conflict) without overwriting the original audit row.
- **Concurrency Safety:** Writes are serialized using threading locks and `BEGIN IMMEDIATE` transactions, eliminating race conditions and preventing fork creation in the hash chain under concurrent load.

---

## Decision 5: Counterfactuals as Single-Change Actionable Reversals Over Full-Pipeline Reruns

### Context
When a dispute is routed to `HUMAN-REVIEW` or `ACCEPT-LOSS`, merchants need actionable explanations answering: *"What specific evidence would reverse this decision to `AUTO-CONTEST`?"*

### Alternatives Considered
1. **Combinatorial Multi-Feature Search:** Search all `2^N` combinations of missing or failed evidence to find the global minimum distance decision boundary.
2. **Bidirectional Permutation Testing:** Flip evidence in both directions ($True \to False$ and $False \to True$) across all fields.
3. **Isolated Single-Change Merchant-Actionable Reversals (Selected):** Simulate only realistic, merchant-obtainable flips (missing or unconfirmed evidence changed from $None/False \to True$) on an isolated, deep-copied graph instance.

### Why This Was Chosen
- **Actionability Over Abstract Mathematics:** In reality, a merchant cannot "un-deliver" an item or reverse a confirmed tracking number. A counterfactual stating *"Decision changes to AUTO-CONTEST if tracking changes from True to False"* is mathematically possible in unconstrained models but nonsensical to a dispute manager. Flipping only $None/False \to True$ ensures every suggestion is a concrete evidence document the merchant can obtain (e.g., uploading a delivery signature).
- **Zero Graph Mutation / State Isolation:** Candidate counterfactual simulations run against cloned graph views (`RiskGraph.clone()`). This guarantees that candidate test nodes (e.g., `CF_has_signature`) never contaminate the live relationship graph or cross-pollinate subsequent decisions.
- **Latency & Predictability:** Evaluating single-feature additions ($O(K)$ where $K \le 4$ missing fields) executes in $< 1\text{ ms}$, avoiding the combinatorial explosion of full optimization searches while providing clear, single-sentence guidance to dispute operators.
