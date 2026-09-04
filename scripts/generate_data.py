"""
generate_data.py — builds the synthetic dataset the rest of the project
uses. Calls hidden_truth.generate_one() but DOES NOT store or expose
hidden_seller_legitimate anywhere in the output -- only reason_code,
amount, evidence fields, and would_win are written out, matching what a
real scorer would actually have access to.
"""
from pathlib import Path
import sys

# Allow direct execution from the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))



import argparse
import csv
import random
from datetime import date, timedelta

from chargeback_risk_engine.config import ALL_EVIDENCE_FIELDS, REASON_CODES
from chargeback_risk_engine.hidden_truth import generate_one

CSV_COLUMNS = (
    ["dispute_id", "payment_id", "reason_code", "amount", "respond_by"]
    + ALL_EVIDENCE_FIELDS
    + ["would_win"]
)


def generate_dataset(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        reason_code = rng.choice(REASON_CODES)
        result = generate_one(rng, reason_code)

        amount = round(rng.uniform(300, 8000), 2)
        respond_by = date(2026, 1, 1) + timedelta(days=rng.randint(1, 300))

        row = {
            "dispute_id": f"D{i:06d}",
            "payment_id": f"pay_{rng.randrange(10**8):08d}",
            "reason_code": reason_code,
            "amount": amount,
            "respond_by": respond_by.isoformat(),
            "would_win": result.would_win,
        }
        row.update(result.evidence)
        rows.append(row)
    return rows


def write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=6000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", type=str, default=".")
    args = parser.parse_args()

    all_rows = generate_dataset(args.n, args.seed)

    # Simple 70/15/15 split, done by slicing a pre-shuffled list -- since
    # the whole list was already generated from one seeded rng in a fixed
    # order, we shuffle with a SEPARATE seeded rng for the split so the
    # split itself is reproducible too but independent of generation order.
    split_rng = random.Random(args.seed + 1)
    shuffled = all_rows[:]
    split_rng.shuffle(shuffled)

    n = len(shuffled)
    train_end = int(n * 0.70)
    dev_end = int(n * 0.85)
    train, dev, test = shuffled[:train_end], shuffled[train_end:dev_end], shuffled[dev_end:]

    write_csv(train, f"{args.out_dir}/train.csv")
    write_csv(dev, f"{args.out_dir}/dev.csv")
    write_csv(test, f"{args.out_dir}/test.csv")

    print(f"Generated {n} disputes -> train={len(train)}, dev={len(dev)}, test={len(test)}")


if __name__ == "__main__":
    main()
