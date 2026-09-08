"""CLI wrapper for the package sensitivity analysis."""
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd

from chargeback_risk_engine.paths import DATA_DIR
from chargeback_risk_engine.sensitivity import sweep_auto_contest_threshold, sweep_monetary_ceiling


def main() -> None:
    test = pd.read_csv(DATA_DIR / "test.csv")
    print(sweep_auto_contest_threshold(test, [0.55, 0.60, 0.65, 0.70, 0.75]).to_string(index=False))
    print()
    print(sweep_monetary_ceiling(test, [25_000, 50_000, 75_000]).to_string(index=False))


if __name__ == "__main__":
    main()
