import pandas as pd
from scripts.generate_report import _ablation


def test_ablation_modes_are_not_a_copy_of_one_another():
    df = pd.read_csv("data/dev.csv").head(250)
    rows = _ablation(df)
    signatures = {(r["component"], r["auto_contest_count"], round(r["precision"], 6), round(r["recall"], 6)) for r in rows}
    assert len(signatures) >= 3
    # The full report must not silently present identical pipelines as separate ablations.
    assert len({(r["auto_contest_count"], round(r["precision"], 6), round(r["recall"], 6)) for r in rows}) >= 3
