"""Command-line interface for the BNPL cleaning pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import PipelinePaths, run_pipeline, verify_sources


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the versioned BNPL cleaning ETL")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", default="v1_2")
    parser.add_argument(
        "--validate-sources-only",
        action="store_true",
        help="Verify registered raw files without creating cleaned outputs",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    if args.validate_sources_only:
        checks = verify_sources(repo_root)
        print(f"PASS: {len(checks)} registered raw sources match size and SHA-256")
        return
    report = run_pipeline(PipelinePaths(repo_root=repo_root, run_id=args.run_id))
    print(
        "PASS: run={run} transactions={rows:,} merchants={merchants:,} candidates={candidates:,}".format(
            run=args.run_id,
            rows=report["outputs"]["transaction_rows"],
            merchants=report["outputs"]["merchant_rows"],
            candidates=report["outputs"]["candidate_eligible_merchants"],
        )
    )


if __name__ == "__main__":
    main()
