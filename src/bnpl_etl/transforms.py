"""Pure, testable transformations used by the BNPL cleaning pipeline."""

from __future__ import annotations

import re
from collections.abc import Iterable

import numpy as np
import pandas as pd


TAG_PATTERN = re.compile(
    r"^[\(\[]+[\(\[](?P<merchant_category_raw>.+)[\)\]]\s*,\s*"
    r"[\(\[](?P<revenue_level>[A-Za-z])[\)\]]\s*,\s*"
    r"[\(\[]take rate:\s*(?P<take_rate_pct>[0-9.]+)[\)\]][\)\]]+$"
)


def canonical_identifier(values: pd.Series, width: int) -> pd.Series:
    """Return zero-padded numeric identifiers without accepting non-digits."""
    result = values.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    if result.isna().any() or (~result.str.fullmatch(r"\d+")).any():
        raise ValueError("Identifier contains null or non-numeric values")
    result = result.str.zfill(width)
    if result.str.len().ne(width).any():
        raise ValueError(f"Identifier must contain at most {width} digits")
    return result


def normalise_category(value: str) -> str:
    """Apply the approved v1 category normalisation."""
    return re.sub(r"\s+", " ", value.casefold()).strip()


def parse_merchants(merchants: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse tags and return one clean row per master merchant plus its crosswalk."""
    if not merchants.index.is_unique:
        raise ValueError("merchant_abn must be unique in the merchant master")
    if not {"name", "tags"}.issubset(merchants.columns):
        raise ValueError("Merchant master is missing name or tags")

    parsed = merchants["tags"].str.extract(TAG_PATTERN)
    if parsed.isna().any().any():
        bad = int(parsed.isna().any(axis=1).sum())
        raise ValueError(f"Unable to parse {bad} merchant tag rows")

    clean = merchants.reset_index().copy()
    identifier_column = clean.columns[0]
    clean = clean.rename(columns={identifier_column: "merchant_abn", "name": "merchant_name"})
    clean["merchant_abn"] = canonical_identifier(clean["merchant_abn"], 11)
    clean["merchant_category_raw"] = parsed["merchant_category_raw"].to_numpy()
    clean["merchant_category"] = clean["merchant_category_raw"].map(normalise_category)
    clean["revenue_level"] = parsed["revenue_level"].str.upper().to_numpy()
    clean["take_rate_pct"] = parsed["take_rate_pct"].astype(float).to_numpy()
    clean["merchant_master_status"] = "matched"
    clean["candidate_eligible"] = True

    crosswalk = (
        clean[["merchant_category_raw", "merchant_category"]]
        .drop_duplicates()
        .sort_values(["merchant_category", "merchant_category_raw"])
        .reset_index(drop=True)
    )
    crosswalk["category_map_version"] = "1.0.0"

    columns = [
        "merchant_abn",
        "merchant_name",
        "merchant_category_raw",
        "merchant_category",
        "revenue_level",
        "take_rate_pct",
        "merchant_master_status",
        "candidate_eligible",
    ]
    return clean[columns], crosswalk


def deduplicate_fraud(
    frame: pd.DataFrame,
    entity_field: str,
) -> tuple[pd.DataFrame, int]:
    """Drop exact duplicates and fail if a native key has conflicting probabilities."""
    required = {entity_field, "order_datetime", "fraud_probability"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Fraud table missing fields: {sorted(required - set(frame.columns))}")

    clean = frame.copy()
    clean["order_datetime"] = pd.to_datetime(clean["order_datetime"], errors="raise").dt.normalize()
    if clean["fraud_probability"].isna().any() or not clean["fraud_probability"].between(0, 100).all():
        raise ValueError("fraud_probability must be non-null and within 0-100")

    duplicate_count = len(clean) - len(clean.drop_duplicates())
    clean = clean.drop_duplicates().copy()
    conflicts = (
        clean.groupby([entity_field, "order_datetime"], dropna=False)["fraud_probability"]
        .nunique(dropna=False)
        .gt(1)
    )
    if conflicts.any():
        raise ValueError(f"Conflicting probabilities for {int(conflicts.sum())} native fraud keys")
    if clean.duplicated([entity_field, "order_datetime"]).any():
        raise ValueError("Fraud native key is not unique after exact deduplication")
    return clean.sort_values(["order_datetime", entity_field]).reset_index(drop=True), duplicate_count


def clean_consumer_geography(
    consumers: pd.DataFrame,
    valid_state_postcodes: pd.DataFrame,
) -> pd.DataFrame:
    """Validate state/postcode without imputing or forcing an SA2 assignment."""
    required = {"consumer_id", "state", "postcode"}
    if not required.issubset(consumers.columns):
        raise ValueError(f"Consumer table missing fields: {sorted(required - set(consumers.columns))}")
    if not consumers["consumer_id"].is_unique:
        raise ValueError("consumer_id must be unique")

    clean = consumers[["consumer_id", "state", "postcode"]].copy()
    clean["state"] = clean["state"].astype("string").str.strip().str.upper()
    clean["postcode4"] = canonical_identifier(clean["postcode"], 4)

    official = valid_state_postcodes[["STATE", "POSTCODE"]].drop_duplicates().copy()
    official = official.dropna(subset=["STATE", "POSTCODE"])
    official["STATE"] = official["STATE"].astype("string").str.strip().str.upper()
    official["POSTCODE"] = official["POSTCODE"].astype("string").str.strip()
    official = official[official["POSTCODE"].str.fullmatch(r"\d+").fillna(False)].copy()
    official["POSTCODE"] = canonical_identifier(official["POSTCODE"], 4)
    official["pair_is_valid"] = True
    clean = clean.merge(
        official,
        how="left",
        left_on=["state", "postcode4"],
        right_on=["STATE", "POSTCODE"],
        validate="many_to_one",
    )

    national_postcodes = set(official["POSTCODE"])
    clean["geo_match_status"] = np.select(
        [
            clean["pair_is_valid"].eq(True).to_numpy(dtype=bool),
            clean["postcode4"].isin(national_postcodes).to_numpy(dtype=bool),
        ],
        ["matched_poa", "state_postcode_mismatch"],
        default="postcode_absent_nationally",
    )
    clean["poa_code_2021"] = clean["postcode4"].where(clean["geo_match_status"].eq("matched_poa"))
    clean["geo_reference_year"] = 2021
    return clean.drop(columns=["STATE", "POSTCODE", "pair_is_valid"])


def annotate_consumer_feature_coverage(consumers: pd.DataFrame) -> pd.DataFrame:
    """Make missing POA/SEIFA feature coverage explicit after enrichment."""
    required = {"geo_match_status", "population_persons", "irsd_score", "irsad_score"}
    if not required.issubset(consumers.columns):
        raise ValueError(f"Enriched consumers missing fields: {sorted(required - set(consumers.columns))}")
    clean = consumers.copy()
    poa_unavailable = clean["geo_match_status"].eq("matched_poa") & clean["population_persons"].isna()
    clean.loc[poa_unavailable, "geo_match_status"] = "poa_feature_unavailable"
    clean["seifa_match_status"] = np.select(
        [
            clean["geo_match_status"].ne("matched_poa").to_numpy(dtype=bool),
            (clean["irsd_score"].notna() & clean["irsad_score"].notna()).to_numpy(dtype=bool),
        ],
        ["not_geo_matched", "matched"],
        default="poa_score_unavailable",
    )
    return clean


def transform_transactions(
    frame: pd.DataFrame,
    order_date: str,
    user_to_consumer: pd.Series,
    master_merchant_ids: set[int],
    consumer_fraud_day: pd.Series,
    merchant_fraud_day: pd.Series,
    amount_p99: float,
    amount_p999: float,
) -> pd.DataFrame:
    """Apply all order-level v1 policies while preserving row count and raw amount."""
    required = {"user_id", "merchant_abn", "dollar_value", "order_id"}
    if set(frame.columns) != required:
        raise ValueError(f"Unexpected transaction schema: {list(frame.columns)}")
    if frame.isna().any().any() or not frame["dollar_value"].gt(0).all():
        raise ValueError("Transactions contain nulls or non-positive amounts")

    clean = frame.copy()
    raw_amount = clean["dollar_value"].to_numpy(copy=True)
    clean["consumer_id"] = clean["user_id"].map(user_to_consumer)
    if clean["consumer_id"].isna().any():
        raise ValueError("Transaction user is absent from the user mapping")
    clean["consumer_id"] = clean["consumer_id"].astype("int64")

    merchant_numeric = clean["merchant_abn"].astype("int64")
    clean["merchant_master_status"] = np.where(
        merchant_numeric.isin(master_merchant_ids), "matched", "missing"
    )
    clean["merchant_abn"] = canonical_identifier(merchant_numeric, 11)
    clean["order_datetime"] = pd.Timestamp(order_date).normalize()
    clean["dollar_value_log1p"] = np.log1p(clean["dollar_value"])
    clean["amount_tail_p99"] = clean["dollar_value"].gt(amount_p99)
    clean["amount_tail_p999"] = clean["dollar_value"].gt(amount_p999)
    clean["consumer_fraud_probability"] = clean["user_id"].map(consumer_fraud_day)
    clean["merchant_fraud_probability"] = merchant_numeric.map(merchant_fraud_day)
    clean["consumer_fraud_signal_present"] = clean["consumer_fraud_probability"].notna()
    clean["merchant_fraud_signal_present"] = clean["merchant_fraud_probability"].notna()
    clean["fraud_signal_any"] = (
        clean["consumer_fraud_signal_present"] | clean["merchant_fraud_signal_present"]
    )

    if len(clean) != len(frame) or not np.array_equal(clean["dollar_value"].to_numpy(), raw_amount):
        raise AssertionError("Transaction transform changed row count or raw dollar values")
    return clean[
        [
            "order_id",
            "order_datetime",
            "user_id",
            "consumer_id",
            "merchant_abn",
            "merchant_master_status",
            "dollar_value",
            "dollar_value_log1p",
            "amount_tail_p99",
            "amount_tail_p999",
            "consumer_fraud_probability",
            "merchant_fraud_probability",
            "consumer_fraud_signal_present",
            "merchant_fraud_signal_present",
            "fraud_signal_any",
        ]
    ]


def stated_household_income_columns(columns: Iterable[str]) -> list[str]:
    """Return the approved G33 total stated-income bands in source order."""
    result = [
        column
        for column in columns
        if column == "Negative_Nil_income_Tot"
        or (column.startswith("HI_") and column.endswith("_Tot"))
    ]
    if not result:
        raise ValueError("No approved household income bands found")
    return result
