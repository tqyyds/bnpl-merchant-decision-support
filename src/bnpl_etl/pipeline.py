"""End-to-end BNPL cleaning and feature-table pipeline."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import io
import json
import re
import zipfile

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from src.run_artifacts import claim_run, finish_run, provenance, validate_run_id

from .transforms import (
    annotate_consumer_feature_coverage,
    canonical_identifier,
    clean_consumer_geography,
    deduplicate_fraud,
    parse_merchants,
    stated_household_income_columns,
    transform_transactions,
)


EXPECTED_TRANSACTION_ROWS = 14_195_505
EXPECTED_START_DATE = "2021-02-28"
EXPECTED_END_DATE = "2022-10-26"
EXPECTED_PARTITIONS = 606
DATE_PATTERN = re.compile(r"order_datetime=(\d{4}-\d{2}-\d{2})/.*\.parquet$")
UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


@dataclass(frozen=True)
class PipelinePaths:
    repo_root: Path
    run_id: str = "v1_2"

    def __post_init__(self):
        validate_run_id(self.run_id)

    @property
    def raw_root(self) -> Path:
        return self.repo_root / "tables" / "raw"

    @property
    def staging_root(self) -> Path:
        return self.repo_root / "tables" / "staging" / self.run_id

    @property
    def curated_root(self) -> Path:
        return self.repo_root / "tables" / "curated" / self.run_id

    @property
    def report_path(self) -> Path:
        return self.repo_root / "reports" / "etl" / "runs" / f"{self.run_id}_manifest.json"


def _sha256(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest().upper()


def _read_manifest(repo_root: Path) -> dict:
    path = repo_root / "docs" / "preclean" / "source_manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _read_policy(repo_root: Path) -> dict:
    path = repo_root / "config" / "cleaning_v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def verify_sources(repo_root: Path) -> list[dict]:
    """Fail on any registered raw-source size or hash drift."""
    results = []
    for source in _read_manifest(repo_root)["sources"]:
        path = repo_root / source["local_path"]
        if not path.exists():
            raise FileNotFoundError(f"Missing registered source: {path}")
        size = path.stat().st_size
        digest = _sha256(path)
        if size != source["file_size_bytes"] or digest != source["sha256"].upper():
            raise ValueError(f"Source drift detected: {source['id']}")
        results.append({"id": source["id"], "bytes": size, "sha256": digest})
    return results


def _load_course_masters(raw_root: Path):
    part1 = raw_root / "course" / "project-2-bnpl-tables-part1.zip"
    with zipfile.ZipFile(part1) as archive:
        if archive.testzip() is not None:
            raise ValueError("Course part 1 ZIP CRC failure")
        consumer_fraud = pd.read_csv(archive.open("tables/consumer_fraud_probability.csv"))
        user_map = pd.read_parquet(io.BytesIO(archive.read("tables/consumer_user_details.parquet")))
        merchant_fraud = pd.read_csv(archive.open("tables/merchant_fraud_probability.csv"))
        consumers = pd.read_csv(archive.open("tables/tbl_consumer.csv"), sep="|")
        merchants = pd.read_parquet(io.BytesIO(archive.read("tables/tbl_merchants.parquet")))
    return consumers, user_map, merchants, consumer_fraud, merchant_fraud


def _load_coding_index(raw_root: Path) -> pd.DataFrame:
    path = raw_root / "external" / "sensitivity" / "ASGS2021CodingIndexes.zip"
    member = "2022 Locality to 2021 SA2 Coding Index.csv"
    with zipfile.ZipFile(path) as archive:
        return pd.read_csv(archive.open(member), dtype=str)


def _read_census_member(archive: zipfile.ZipFile, table: str) -> pd.DataFrame:
    member = (
        "2021 Census GCP Postal Areas for AUS/"
        f"2021Census_{table}_AUST_POA.csv"
    )
    return pd.read_csv(archive.open(member), dtype={"POA_CODE_2021": str})


def build_poa_features(raw_root: Path) -> pd.DataFrame:
    """Build the allow-listed POA feature table without touching consumer rows."""
    census_path = raw_root / "external" / "primary" / "2021_GCP_POA_for_AUS_short-header.zip"
    with zipfile.ZipFile(census_path) as archive:
        g01 = _read_census_member(archive, "G01")[["POA_CODE_2021", "Tot_P_P"]]
        g02 = _read_census_member(archive, "G02")[["POA_CODE_2021", "Median_tot_hhd_inc_weekly"]]
        age_fields = [
            "Age_yr_18_P",
            "Age_yr_19_P",
            "Age_yr_20_24_P",
            "Age_yr_25_29_P",
            "Age_yr_30_34_P",
            "Age_yr_35_39_P",
        ]
        g04 = _read_census_member(archive, "G04A")[["POA_CODE_2021", *age_fields]]
        g33 = _read_census_member(archive, "G33")
        income_fields = stated_household_income_columns(g33.columns)
        g33 = g33[
            [
                "POA_CODE_2021",
                *income_fields,
                "Partial_income_stated_Tot",
                "All_incomes_not_stated_Tot",
                "Tot_Tot",
            ]
        ]
        g43_fields = [
            "POA_CODE_2021",
            "P_15_yrs_over_P",
            "lfs_Unmplyed_lookng_for_wrk_P",
            "lfs_Tot_LF_P",
            "Percent_Unem_loyment_P",
            "Percnt_LabForc_prticipation_P",
        ]
        g43 = _read_census_member(archive, "G43")[g43_fields]

    tables = [g01, g02, g04, g33, g43]
    for frame in tables:
        frame["poa_code_2021"] = frame.pop("POA_CODE_2021").str.removeprefix("POA").str.zfill(4)
        if not frame["poa_code_2021"].is_unique:
            raise ValueError("Census POA key is not unique")

    features = tables[0]
    for frame in tables[1:]:
        features = features.merge(frame, on="poa_code_2021", how="outer", validate="one_to_one")

    features = features.rename(
        columns={
            "Tot_P_P": "population_persons",
            "Median_tot_hhd_inc_weekly": "median_household_income_weekly_aud",
            "Percent_Unem_loyment_P": "unemployment_pct",
            "Percnt_LabForc_prticipation_P": "labour_force_participation_pct",
        }
    )
    features["population_18_39"] = features[age_fields].sum(axis=1, min_count=len(age_fields))
    features["population_18_39_share"] = (
        features["population_18_39"] / features["population_persons"].replace(0, np.nan)
    )
    stated_denominator = features[income_fields].sum(axis=1, min_count=len(income_fields))
    for field in income_fields:
        features[f"{field}_share"] = features[field] / stated_denominator.replace(0, np.nan)
    features["household_income_partial_stated_share"] = (
        features["Partial_income_stated_Tot"] / features["Tot_Tot"].replace(0, np.nan)
    )
    features["household_income_not_stated_share"] = (
        features["All_incomes_not_stated_Tot"] / features["Tot_Tot"].replace(0, np.nan)
    )

    seifa_path = raw_root / "external" / "primary" / "SEIFA_2021_POA.xlsx"
    seifa = pd.read_excel(
        seifa_path,
        sheet_name="Table 1",
        header=None,
        skiprows=6,
        usecols="A:E",
        names=["poa_code_2021", "irsd_score", "irsd_decile", "irsad_score", "irsad_decile"],
    )
    seifa = seifa.dropna(subset=["poa_code_2021"]).copy()
    seifa_code = (
        seifa["poa_code_2021"]
        .astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )
    seifa = seifa[seifa_code.str.fullmatch(r"\d+").fillna(False)].copy()
    seifa["poa_code_2021"] = canonical_identifier(seifa["poa_code_2021"], 4)
    for field in ["irsd_score", "irsd_decile", "irsad_score", "irsad_decile"]:
        seifa[field] = pd.to_numeric(seifa[field], errors="coerce")
    if not seifa["poa_code_2021"].is_unique:
        raise ValueError("SEIFA POA key is not unique")
    features = features.merge(seifa, on="poa_code_2021", how="left", validate="one_to_one")
    features["geo_reference_year"] = 2021
    features["feature_contract_version"] = "1.0.0"
    return features.sort_values("poa_code_2021").reset_index(drop=True)


def _transaction_members(raw_root: Path):
    for part in (2, 3, 4):
        package = raw_root / "course" / f"project-2-bnpl-tables-part{part}.zip"
        with zipfile.ZipFile(package) as archive:
            members = sorted(name for name in archive.namelist() if DATE_PATTERN.search(name))
        for member in members:
            yield package, member, DATE_PATTERN.search(member).group(1)


def _read_transaction_member(package: Path, member: str) -> pd.DataFrame:
    with zipfile.ZipFile(package) as archive:
        return pq.read_table(io.BytesIO(archive.read(member))).to_pandas()


def scan_transaction_contract(raw_root: Path) -> dict:
    """First pass: assert the raw fact contract and compute exact amount thresholds."""
    amount_chunks = []
    order_hash_chunks = []
    dates = []
    rows = 0
    for package, member, date in _transaction_members(raw_root):
        frame = _read_transaction_member(package, member)
        if list(frame.columns) != ["user_id", "merchant_abn", "dollar_value", "order_id"]:
            raise ValueError(f"Transaction schema drift in {member}")
        if frame.isna().any().any() or not frame["dollar_value"].gt(0).all():
            raise ValueError(f"Invalid values in {member}")
        if not frame["order_id"].str.fullmatch(UUID_PATTERN).all():
            raise ValueError(f"Invalid order UUID in {member}")
        rows += len(frame)
        dates.append(date)
        amount_chunks.append(frame["dollar_value"].to_numpy(dtype="float64", copy=True))
        order_hash_chunks.append(
            pd.util.hash_pandas_object(frame["order_id"], index=False).to_numpy(dtype="uint64", copy=True)
        )

    amounts = np.concatenate(amount_chunks)
    order_hashes = np.concatenate(order_hash_chunks)
    duplicate_hash_candidates = len(order_hashes) - len(np.unique(order_hashes))
    unique_dates = sorted(set(dates))
    expected_dates = pd.date_range(EXPECTED_START_DATE, EXPECTED_END_DATE, freq="D").strftime("%Y-%m-%d").tolist()
    if rows != EXPECTED_TRANSACTION_ROWS or unique_dates != expected_dates:
        raise ValueError("Transaction row/date baseline drift")
    if duplicate_hash_candidates:
        raise ValueError(f"Possible duplicate order IDs: {duplicate_hash_candidates}")
    return {
        "rows": rows,
        "partitions": len(unique_dates),
        "min_date": unique_dates[0],
        "max_date": unique_dates[-1],
        "amount_p99": float(np.quantile(amounts, 0.99)),
        "amount_p999": float(np.quantile(amounts, 0.999)),
        "amount_min": float(amounts.min()),
        "amount_max": float(amounts.max()),
        "duplicate_order_hash_candidates": duplicate_hash_candidates,
    }


def _fraud_by_date(frame: pd.DataFrame, entity_field: str) -> dict[str, pd.Series]:
    return {
        date.strftime("%Y-%m-%d"): group.set_index(entity_field)["fraud_probability"]
        for date, group in frame.groupby("order_datetime")
    }


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False, compression="snappy")


def _output_inventory(paths: list[Path], repo_root: Path) -> list[dict]:
    inventory = []
    for root in paths:
        for path in sorted(root.rglob("*.parquet")):
            inventory.append(
                {
                    "path": str(path.relative_to(repo_root)).replace("\\", "/"),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    return inventory


def run_pipeline(paths: PipelinePaths) -> dict:
    """Run v1 once. Existing outputs are never overwritten."""
    occupied_output = any(root.exists() for root in (paths.staging_root, paths.curated_root))
    if occupied_output or paths.report_path.exists():
        raise FileExistsError(
            f"Run {paths.run_id!r} already exists; choose a new run ID instead of overwriting"
        )

    policy = _read_policy(paths.repo_root)
    source_checks = verify_sources(paths.repo_root)
    claim_run(paths.staging_root)
    claim_run(paths.curated_root)
    contract = scan_transaction_contract(paths.raw_root)
    consumers, user_map, merchants_raw, consumer_fraud_raw, merchant_fraud_raw = _load_course_masters(paths.raw_root)

    if not (user_map["user_id"].is_unique and user_map["consumer_id"].is_unique):
        raise ValueError("User mapping is not one-to-one")
    clean_merchants, category_crosswalk = parse_merchants(merchants_raw)
    consumer_fraud, consumer_fraud_duplicates = deduplicate_fraud(consumer_fraud_raw, "user_id")
    merchant_fraud, merchant_fraud_duplicates = deduplicate_fraud(merchant_fraud_raw, "merchant_abn")

    coding = _load_coding_index(paths.raw_root)
    clean_consumers = clean_consumer_geography(consumers, coding)
    poa_features = build_poa_features(paths.raw_root)
    clean_consumers = clean_consumers.merge(
        poa_features,
        on=["poa_code_2021", "geo_reference_year"],
        how="left",
        validate="many_to_one",
    )
    clean_consumers = annotate_consumer_feature_coverage(clean_consumers)

    _write_parquet(clean_consumers, paths.staging_root / "consumers.parquet")
    _write_parquet(clean_merchants, paths.staging_root / "merchant_master.parquet")
    _write_parquet(category_crosswalk, paths.staging_root / "merchant_category_crosswalk.parquet")
    _write_parquet(consumer_fraud, paths.staging_root / "fraud" / "consumer_daily.parquet")
    _write_parquet(merchant_fraud, paths.staging_root / "fraud" / "merchant_daily.parquet")
    _write_parquet(poa_features, paths.staging_root / "poa_features.parquet")

    user_to_consumer = user_map.set_index("user_id")["consumer_id"]
    master_numeric = set(pd.Index(merchants_raw.index).astype("int64"))
    consumer_fraud_dates = _fraud_by_date(consumer_fraud, "user_id")
    merchant_fraud_dates = _fraud_by_date(merchant_fraud, "merchant_abn")

    aggregate = defaultdict(
        lambda: {
            "transaction_count": 0,
            "gross_transaction_value": 0.0,
            "active_days": 0,
            "consumer_fraud_signal_orders": 0,
            "merchant_fraud_signal_orders": 0,
            "any_fraud_signal_orders": 0,
            "amount_tail_p99_orders": 0,
            "amount_tail_p999_orders": 0,
            "first_transaction_date": None,
            "last_transaction_date": None,
        }
    )
    merchant_users: dict[str, set[int]] = defaultdict(set)
    output_rows = 0
    for package, member, date in _transaction_members(paths.raw_root):
        raw = _read_transaction_member(package, member)
        transformed = transform_transactions(
            raw,
            date,
            user_to_consumer,
            master_numeric,
            consumer_fraud_dates.get(date, pd.Series(dtype="float64")),
            merchant_fraud_dates.get(date, pd.Series(dtype="float64")),
            contract["amount_p99"],
            contract["amount_p999"],
        )
        output_rows += len(transformed)
        output_path = (
            paths.staging_root
            / "transactions"
            / f"order_datetime={date}"
            / "part-00000.parquet"
        )
        _write_parquet(transformed, output_path)

        grouped = transformed.groupby("merchant_abn", sort=False)
        for merchant_abn, group in grouped:
            item = aggregate[merchant_abn]
            item["transaction_count"] += len(group)
            item["gross_transaction_value"] += float(group["dollar_value"].sum())
            item["active_days"] += 1
            item["consumer_fraud_signal_orders"] += int(group["consumer_fraud_signal_present"].sum())
            item["merchant_fraud_signal_orders"] += int(group["merchant_fraud_signal_present"].sum())
            item["any_fraud_signal_orders"] += int(group["fraud_signal_any"].sum())
            item["amount_tail_p99_orders"] += int(group["amount_tail_p99"].sum())
            item["amount_tail_p999_orders"] += int(group["amount_tail_p999"].sum())
            item["first_transaction_date"] = date if item["first_transaction_date"] is None else min(item["first_transaction_date"], date)
            item["last_transaction_date"] = date if item["last_transaction_date"] is None else max(item["last_transaction_date"], date)
            merchant_users[merchant_abn].update(group["user_id"].astype(int).unique())

    if output_rows != contract["rows"]:
        raise AssertionError("Clean transaction row count differs from raw")

    merchant_aggregate = pd.DataFrame.from_dict(aggregate, orient="index").rename_axis("merchant_abn").reset_index()
    merchant_aggregate["unique_users"] = merchant_aggregate["merchant_abn"].map(
        lambda merchant: len(merchant_users[merchant])
    )
    merchant_features = merchant_aggregate.merge(
        clean_merchants,
        on="merchant_abn",
        how="left",
        validate="one_to_one",
    )
    merchant_features["merchant_master_status"] = merchant_features["merchant_master_status"].fillna("missing")
    merchant_features["candidate_eligible"] = merchant_features["candidate_eligible"].fillna(False).astype(bool)
    merchant_features["estimated_bnpl_revenue"] = (
        merchant_features["gross_transaction_value"] * merchant_features["take_rate_pct"] / 100
    )
    merchant_features["any_fraud_signal_order_share"] = (
        merchant_features["any_fraud_signal_orders"] / merchant_features["transaction_count"]
    )
    merchant_features["amount_tail_p99_order_share"] = (
        merchant_features["amount_tail_p99_orders"] / merchant_features["transaction_count"]
    )
    merchant_features["amount_tail_p999_order_share"] = (
        merchant_features["amount_tail_p999_orders"] / merchant_features["transaction_count"]
    )
    merchant_features = merchant_features.sort_values("merchant_abn").reset_index(drop=True)
    _write_parquet(merchant_features, paths.curated_root / "merchant_features.parquet")

    geo_counts = clean_consumers["geo_match_status"].value_counts().to_dict()
    unknown_merchants = int(merchant_features["merchant_master_status"].eq("missing").sum())
    if unknown_merchants != 396 or len(merchant_features) != 4_422:
        raise AssertionError("Merchant referential baseline changed")
    if geo_counts != {
        "matched_poa": 416_334,
        "postcode_absent_nationally": 83_035,
        "state_postcode_mismatch": 484,
        "poa_feature_unavailable": 146,
    }:
        raise AssertionError(f"Geography baseline changed: {geo_counts}")
    seifa_counts = clean_consumers["seifa_match_status"].value_counts().to_dict()
    if seifa_counts != {
        "matched": 413_641,
        "not_geo_matched": 83_665,
        "poa_score_unavailable": 2_693,
    }:
        raise AssertionError(f"SEIFA coverage baseline changed: {seifa_counts}")

    report = {
        "run_id": paths.run_id,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "policy": policy,
        "provenance": provenance(paths.repo_root, policy),
        "source_checks": source_checks,
        "transaction_contract": contract,
        "outputs": {
            "transaction_rows": output_rows,
            "transaction_partitions": EXPECTED_PARTITIONS,
            "consumer_rows": len(clean_consumers),
            "merchant_rows": len(merchant_features),
            "candidate_eligible_merchants": int(merchant_features["candidate_eligible"].sum()),
            "unknown_merchants": unknown_merchants,
            "consumer_fraud_rows": len(consumer_fraud),
            "consumer_fraud_exact_duplicates_removed": consumer_fraud_duplicates,
            "merchant_fraud_rows": len(merchant_fraud),
            "merchant_fraud_exact_duplicates_removed": merchant_fraud_duplicates,
            "category_raw_variants": int(category_crosswalk["merchant_category_raw"].nunique()),
            "category_normalised_values": int(category_crosswalk["merchant_category"].nunique()),
            "geo_match_status": geo_counts,
            "seifa_match_status": seifa_counts,
        },
    }
    report["output_inventory"] = _output_inventory(
        [paths.staging_root, paths.curated_root], paths.repo_root
    )
    paths.report_path.parent.mkdir(parents=True, exist_ok=True)
    paths.report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    finish_run(paths.staging_root)
    finish_run(paths.curated_root)
    return report
