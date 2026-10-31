"""Tests for model artifact integrity, safe JSON deserialization, and calibration safety."""
import hashlib
import json
import os
import tempfile
import pytest
import pandas as pd

from chargeback_risk_engine.config import (
    FEATURE_VERSION,
    LIVE_MODEL_VERSION,
    REASON_CODES,
    RELEVANT_EVIDENCE_BY_REASON,
)
from chargeback_risk_engine.ml_scorer import (
    MLScorer,
    load_or_fit_ml_scorer,
    save_ml_scorer,
)
from chargeback_risk_engine.calibration import (
    apply_calibration,
    load_or_fit_calibration_points,
    validate_calibration_points,
    get_calibration_metadata,
)


@pytest.fixture(autouse=True)
def reset_in_process_caches():
    import chargeback_risk_engine.ml_scorer as ml_module
    import chargeback_risk_engine.calibration as cal_module
    ml_module._cached_scorer = None
    cal_module._cached_points = None
    yield
    ml_module._cached_scorer = None
    cal_module._cached_points = None


def test_tampered_model_artifact_is_rejected():
    """Any modification to model JSON must cause SHA-256 sidecar verification to fail."""
    with tempfile.TemporaryDirectory() as tmp:
        model_path = os.path.join(tmp, "model.json")
        train_csv = "data/train.csv"
        save_ml_scorer(path=model_path, train_csv=train_csv)

        # Confirm valid load before tampering
        import chargeback_risk_engine.ml_scorer as ml_module
        ml_module._cached_scorer = None
        loaded = load_or_fit_ml_scorer(path=model_path, train_csv=train_csv)
        assert loaded is not None

        # Tamper with the model file content
        with open(model_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Flip sign on first coefficient
        first_reason = next(iter(data["models"]))
        data["models"][first_reason]["coef"][0] += 1.0
        with open(model_path, "wb") as f:
            f.write(json.dumps(data).encode("utf-8"))

        # Attempt to reload tampered artifact must raise ValueError
        ml_module._cached_scorer = None
        with pytest.raises(ValueError, match="Model integrity failure: SHA-256 mismatch"):
            load_or_fit_ml_scorer(path=model_path, train_csv=train_csv)


def test_wrong_sklearn_or_feature_version_rejected():
    """Model artifacts with mismatched feature_version or sklearn_version must be rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        train_csv = "data/train.csv"
        import chargeback_risk_engine.ml_scorer as ml_module

        # Test incompatible feature version
        path_feat = os.path.join(tmp, "bad_feat.json")
        save_ml_scorer(path=path_feat, train_csv=train_csv)
        with open(path_feat, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["feature_version"] = "v9999_incompatible"
        raw_bytes = json.dumps(data).encode("utf-8")
        with open(path_feat, "wb") as f:
            f.write(raw_bytes)
        with open(path_feat + ".sha256", "w", encoding="utf-8", newline="\n") as f:
            f.write(hashlib.sha256(raw_bytes).hexdigest() + "\n")

        ml_module._cached_scorer = None
        with pytest.raises(RuntimeError, match="Incompatible feature artifact"):
            load_or_fit_ml_scorer(path=path_feat, train_csv=train_csv)

        # Test incompatible sklearn version
        path_sk = os.path.join(tmp, "bad_sklearn.json")
        save_ml_scorer(path=path_sk, train_csv=train_csv)
        with open(path_sk, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["sklearn_version"] = "0.0.1"
        raw_bytes = json.dumps(data).encode("utf-8")
        with open(path_sk, "wb") as f:
            f.write(raw_bytes)
        with open(path_sk + ".sha256", "w", encoding="utf-8", newline="\n") as f:
            f.write(hashlib.sha256(raw_bytes).hexdigest() + "\n")

        ml_module._cached_scorer = None
        with pytest.raises(RuntimeError, match="Live model was trained with scikit-learn"):
            load_or_fit_ml_scorer(path=path_sk, train_csv=train_csv)


def test_malformed_calibration_falls_back_safely():
    """If calibration points are non-monotonic, non-finite, or malformed, fall back to raw probability."""
    with tempfile.TemporaryDirectory() as tmp:
        cal_path = os.path.join(tmp, "bad_cal.json")

        # 1. Non-monotonic y values
        non_monotonic = [
            [0.1, 0.2],
            [0.3, 0.6],
            [0.5, 0.4],  # Decreases from 0.6 -> non-monotonic
            [0.8, 0.9],
        ]
        with open(cal_path, "w", encoding="utf-8") as f:
            json.dump(non_monotonic, f)

        import chargeback_risk_engine.calibration as cal_module
        cal_module._cached_points = None
        points = load_or_fit_calibration_points(path=cal_path)
        assert points == []
        meta = get_calibration_metadata()
        assert meta["valid"] is False
        assert meta["fallback_to_raw"] is True
        assert "monotonic" in meta["error"]

        # Raw probability fallback: apply_calibration returns the exact input probability
        raw_prob = 0.65
        assert apply_calibration(points, raw_prob) == raw_prob

        # 2. Schema corruption (not 2-element pairs)
        corrupted = [[0.1, 0.2, 0.3], [0.4]]
        with open(cal_path, "w", encoding="utf-8") as f:
            json.dump(corrupted, f)
        cal_module._cached_points = None
        points_corrupt = load_or_fit_calibration_points(path=cal_path)
        assert points_corrupt == []
        assert apply_calibration(points_corrupt, 0.42) == 0.42


def test_round_trip_prediction_equality_to_1e_9():
    """In-memory fitted model predictions match re-loaded JSON model predictions to < 1e-9."""
    train_df = pd.read_csv("data/train.csv")
    in_memory = MLScorer().fit(train_df)

    with tempfile.TemporaryDirectory() as tmp:
        json_path = os.path.join(tmp, "model_roundtrip.json")
        save_ml_scorer(path=json_path, train_csv="data/train.csv")

        import chargeback_risk_engine.ml_scorer as ml_module
        ml_module._cached_scorer = None
        reloaded = load_or_fit_ml_scorer(path=json_path, train_csv="data/train.csv")

        # Test across multiple reason codes and feature combinations
        test_cases = [
            {"reason_code": "item_not_received", "has_tracking_number": True, "has_delivery_confirmation": True, "has_signature_confirmation": True},
            {"reason_code": "item_not_received", "has_tracking_number": False, "has_delivery_confirmation": False, "has_signature_confirmation": False},
            {"reason_code": "item_not_received", "has_tracking_number": True, "has_delivery_confirmation": None, "has_signature_confirmation": False},
            {"reason_code": "unauthorized_transaction", "has_avs_match": True, "has_cvv_match": True, "has_device_fingerprint_match": False},
            {"reason_code": "unauthorized_transaction", "has_avs_match": False, "has_cvv_match": True, "has_device_fingerprint_match": True},
            {"reason_code": "item_not_as_described", "has_product_photos": True, "has_item_description_match": True, "has_return_communication": None},
            {"reason_code": "duplicate_charge", "has_duplicate_transaction_proof": True, "has_refund_already_issued": False},
        ]

        for dispute in test_cases:
            p_mem = in_memory.predict_win_probability(dispute)
            p_json = reloaded.predict_win_probability(dispute)
            diff = abs(p_mem - p_json)
            assert diff < 1e-9, f"Dispute {dispute} diff {diff} exceeded 1e-9"


def test_production_mode_refuses_legacy_pkl(monkeypatch):
    """Production mode refuses to deserialize legacy .pkl artifacts."""
    with tempfile.TemporaryDirectory() as tmp:
        pkl_path = os.path.join(tmp, "legacy.pkl")
        with open(pkl_path, "wb") as f:
            f.write(b"not a valid json bundle")
        # Write valid sha256 sidecar
        with open(pkl_path + ".sha256", "w", encoding="utf-8") as f:
            f.write(hashlib.sha256(b"not a valid json bundle").hexdigest() + "\n")

        monkeypatch.setenv("CHARGEBACK_ENV", "production")
        import chargeback_risk_engine.ml_scorer as ml_module
        ml_module._cached_scorer = None
        with pytest.raises(RuntimeError, match="Refusing to load untrusted legacy .pkl model artifact"):
            load_or_fit_ml_scorer(path=pkl_path)
