import numpy as np
import pandas as pd
import pytest

from src.bnpl_etl.transforms import (
    annotate_consumer_feature_coverage,
    clean_consumer_geography,
    deduplicate_fraud,
    normalise_category,
    parse_merchants,
    transform_transactions,
)


def test_category_normalisation_and_tag_parser():
    merchants = pd.DataFrame(
        {
            "name": ["One", "Two"],
            "tags": [
                "((Art  dealers and galleries), (a), (take rate: 6.20))",
                "[[ART dealers  and galleries], [b], [take rate: 4.10]]",
            ],
        },
        index=pd.Index([10023283211, 10142254217], name="merchant_abn"),
    )
    clean, crosswalk = parse_merchants(merchants)
    assert clean["merchant_category"].tolist() == [
        "art dealers and galleries",
        "art dealers and galleries",
    ]
    assert clean["revenue_level"].tolist() == ["A", "B"]
    assert clean["take_rate_pct"].tolist() == [6.2, 4.1]
    assert len(crosswalk) == 2
    assert normalise_category("  A  b ") == "a b"


def test_fraud_exact_duplicates_are_removed_but_conflicts_fail():
    source = pd.DataFrame(
        {
            "user_id": [1, 1],
            "order_datetime": ["2022-01-01", "2022-01-01"],
            "fraud_probability": [20.0, 20.0],
        }
    )
    clean, removed = deduplicate_fraud(source, "user_id")
    assert len(clean) == 1 and removed == 1

    conflicting = pd.concat(
        [source.iloc[:1], source.iloc[:1].assign(fraud_probability=30.0)],
        ignore_index=True,
    )
    with pytest.raises(ValueError, match="Conflicting probabilities"):
        deduplicate_fraud(conflicting, "user_id")


def test_geography_retains_unmatched_rows_with_explicit_status():
    consumers = pd.DataFrame(
        {
            "consumer_id": [1, 2, 3],
            "state": ["VIC", "NSW", "VIC"],
            "postcode": [800, 800, 9999],
        }
    )
    official = pd.DataFrame(
        {"STATE": ["VIC", "VIC", None], "POSTCODE": ["0800", None, "not-a-postcode"]}
    )
    clean = clean_consumer_geography(consumers, official)
    assert clean["postcode4"].tolist() == ["0800", "0800", "9999"]
    assert clean["geo_match_status"].tolist() == [
        "matched_poa",
        "state_postcode_mismatch",
        "postcode_absent_nationally",
    ]
    assert clean["poa_code_2021"].isna().tolist() == [False, True, True]


def test_transaction_rules_preserve_rows_and_amounts():
    raw = pd.DataFrame(
        {
            "user_id": [1, 2],
            "merchant_abn": [10023283211, 99999999999],
            "dollar_value": [10.0, 200.0],
            "order_id": ["a", "b"],
        }
    )
    clean = transform_transactions(
        raw,
        "2022-01-01",
        pd.Series({1: 101, 2: 102}),
        {10023283211},
        pd.Series({1: 80.0}),
        pd.Series({99999999999: 90.0}),
        amount_p99=100.0,
        amount_p999=150.0,
    )
    assert len(clean) == len(raw)
    assert np.array_equal(clean["dollar_value"], raw["dollar_value"])
    assert clean["merchant_master_status"].tolist() == ["matched", "missing"]
    assert clean["consumer_fraud_signal_present"].tolist() == [True, False]
    assert clean["merchant_fraud_signal_present"].tolist() == [False, True]
    assert clean["amount_tail_p99"].tolist() == [False, True]
    assert clean["amount_tail_p999"].tolist() == [False, True]


def test_feature_coverage_statuses_are_explicit():
    enriched = pd.DataFrame(
        {
            "geo_match_status": ["matched_poa", "matched_poa", "postcode_absent_nationally"],
            "population_persons": [100.0, np.nan, np.nan],
            "irsd_score": [900.0, np.nan, np.nan],
            "irsad_score": [950.0, np.nan, np.nan],
        }
    )
    clean = annotate_consumer_feature_coverage(enriched)
    assert clean["geo_match_status"].tolist() == [
        "matched_poa",
        "poa_feature_unavailable",
        "postcode_absent_nationally",
    ]
    assert clean["seifa_match_status"].tolist() == [
        "matched",
        "not_geo_matched",
        "not_geo_matched",
    ]
