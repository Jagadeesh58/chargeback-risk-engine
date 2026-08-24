"""
verify_no_leakage.py — one-off empirical check (Checkpoint 1 requirement,
principle #3). Not part of the pipeline; run manually after generating
data.
"""

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from config import ALL_EVIDENCE_FIELDS

train = pd.read_csv("train.csv")
dev = pd.read_csv("dev.csv")

print(f"Overall would_win rate (train): {train['would_win'].mean():.1%}")
print()
print("would_win rate by reason_code (train):")
print(train.groupby("reason_code")["would_win"].mean().round(3))
print()

# Encode: True->1, False->0, missing (NaN after pandas read) -> 0.5 (neutral)
def encode(df):
    X = df[ALL_EVIDENCE_FIELDS].copy()
    for col in ALL_EVIDENCE_FIELDS:
        X[col] = X[col].map({True: 1.0, False: 0.0}).fillna(0.5)
    y = df["would_win"].astype(int)
    return X, y

X_train, y_train = encode(train)
X_dev, y_dev = encode(dev)

# --- Full model: all evidence fields together ---
model = LogisticRegression(max_iter=1000)
model.fit(X_train, y_train)
dev_probs = model.predict_proba(X_dev)[:, 1]
full_auc = roc_auc_score(y_dev, dev_probs)
print(f"Full model (all 11 evidence fields) AUC on dev: {full_auc:.3f}")
print()

# --- Single-field check: does ANY one field alone predict too well? ---
print("Single-field AUCs (each field alone, no reason-code awareness):")
worst_single, best_single = 1.0, 0.0
for field_name in ALL_EVIDENCE_FIELDS:
    single_model = LogisticRegression(max_iter=1000)
    single_model.fit(X_train[[field_name]], y_train)
    probs = single_model.predict_proba(X_dev[[field_name]])[:, 1]
    auc = roc_auc_score(y_dev, probs)
    best_single = max(best_single, auc)
    worst_single = min(worst_single, auc)
    print(f"  {field_name:35s} AUC={auc:.3f}")

print()
print(f"Best single field AUC: {best_single:.3f} (want this well below full model AUC)")

# --- Reason-code-AWARE model: does knowing the reason code help? ---
train_aware = pd.get_dummies(train, columns=["reason_code"], prefix="reason")
dev_aware = pd.get_dummies(dev, columns=["reason_code"], prefix="reason")
reason_cols = [c for c in train_aware.columns if c.startswith("reason_")]

X_train_aware = pd.concat([X_train, train_aware[reason_cols]], axis=1)
X_dev_aware = pd.concat([X_dev, dev_aware[reason_cols]], axis=1)

aware_model = LogisticRegression(max_iter=1000)
aware_model.fit(X_train_aware, y_train)
aware_probs = aware_model.predict_proba(X_dev_aware)[:, 1]
aware_auc = roc_auc_score(y_dev, aware_probs)

print()
print(f"Reason-code-BLIND model AUC: {full_auc:.3f}")
print(f"Reason-code-AWARE (extra column) model AUC: {aware_auc:.3f}  <- flawed, see notes")

# --- CORRECTED reason-code-aware: separate model per reason code, only
# trained/scored on that reason's own relevant evidence fields ---
from config import RELEVANT_EVIDENCE_BY_REASON

all_dev_probs = pd.Series(index=dev.index, dtype=float)
for reason, fields in RELEVANT_EVIDENCE_BY_REASON.items():
    tr_mask = train["reason_code"] == reason
    dv_mask = dev["reason_code"] == reason

    sub_model = LogisticRegression(max_iter=1000)
    sub_model.fit(X_train.loc[tr_mask, fields], y_train.loc[tr_mask])
    probs = sub_model.predict_proba(X_dev.loc[dv_mask, fields])[:, 1]
    all_dev_probs.loc[dv_mask] = probs

per_reason_auc = roc_auc_score(y_dev, all_dev_probs)
print(f"Reason-code-AWARE (per-reason submodel) AUC: {per_reason_auc:.3f}")
print(f"Gap vs blind: {per_reason_auc - full_auc:+.3f}")
