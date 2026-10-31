"""Command-line interface entrypoint for Chargeback Risk Engine."""

from __future__ import annotations

import argparse
import json
import sys


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "chargeback_risk_engine.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def cmd_verify_audit(args: argparse.Namespace) -> int:
    from chargeback_risk_engine.audit_log import verify_audit_integrity

    db_path = args.db or None
    result = verify_audit_integrity(db_path) if db_path else verify_audit_integrity()
    print(json.dumps(result, indent=2))
    return 0 if result.get("valid") else 1


def cmd_train(args: argparse.Namespace) -> int:
    from chargeback_risk_engine.ml_scorer import save_ml_scorer
    from chargeback_risk_engine.paths import ARTIFACTS_DIR, DATA_DIR

    model_path = args.out or str(ARTIFACTS_DIR / "ml_scorer_model.json")
    train_csv = args.train_csv or str(DATA_DIR / "train.csv")
    print(f"Fitting safe JSON model from '{train_csv}' -> '{model_path}'...")
    save_ml_scorer(model_path, train_csv)
    print("Training successfully completed.")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    from scripts.evaluate_real_data import evaluate_dataset

    csv_file = args.csv
    if not csv_file:
        print("Error: --csv is required for evaluate command", file=sys.stderr)
        return 1
    res = evaluate_dataset(csv_file, loss_penalty_inr=args.penalty)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
        print(f"Report written to {args.out}")
    else:
        print(json.dumps(res, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chargeback-cli",
        description="Unified management and operational CLI for Chargeback Risk Engine",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # serve
    p_serve = subparsers.add_parser("serve", help="Run the FastAPI decision server")
    p_serve.add_argument("--host", default="0.0.0.0", help="Host interface (default 0.0.0.0)")
    p_serve.add_argument("--port", type=int, default=8000, help="Port (default 8000)")
    p_serve.add_argument("--reload", action="store_true", help="Enable reload on changes")
    p_serve.set_defaults(func=cmd_serve)

    # verify-audit
    p_audit = subparsers.add_parser(
        "verify-audit", help="Verify cryptographic audit log hash chain"
    )
    p_audit.add_argument("--db", type=str, default="", help="Path to audit_log.db")
    p_audit.set_defaults(func=cmd_verify_audit)

    # train
    p_train = subparsers.add_parser("train", help="Train and serialize safe JSON model artifact")
    p_train.add_argument("--train-csv", type=str, default="", help="Path to training CSV")
    p_train.add_argument("--out", type=str, default="", help="Output model path")
    p_train.set_defaults(func=cmd_train)

    # evaluate
    p_eval = subparsers.add_parser("evaluate", help="Evaluate a dispute CSV dataset")
    p_eval.add_argument("--csv", type=str, required=True, help="Input CSV dataset")
    p_eval.add_argument("--out", type=str, default="", help="Output report JSON")
    p_eval.add_argument(
        "--penalty", type=float, default=4150.0, help="Assumed penalty per lost dispute"
    )
    p_eval.set_defaults(func=cmd_evaluate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
