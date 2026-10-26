"""Build the reproducible read-only raw-data audit notebook."""

from pathlib import Path

import nbformat as nbf


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "notebooks" / "01_raw_data_audit.ipynb"


def md(text: str):
    return nbf.v4.new_markdown_cell(text.strip())


def code(text: str):
    return nbf.v4.new_code_cell(text.strip())


nb = nbf.v4.new_notebook()
nb.metadata.update(
    {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python", "version": "3"},
    }
)

nb.cells = [
    md(
        """
# BNPL Raw-Data Audit

## TL;DR

This notebook verifies the immutable course and external inputs before any cleaning. The registered baseline is 14,195,505 orders in 606 continuous daily partitions from 2021-02-28 through 2022-10-26. Order keys and transaction completeness are strong. The main blockers to direct modelling are 396 merchant foreign-key gaps (4.09% of transactions), daily rather than order-level fraud signals, 99 duplicate consumer-fraud records, 16.70% consumer geography non-coverage, and one-to-many postcode-to-SA2 mappings.

The notebook performs no cleaning and writes nothing into `tables/raw`.
"""
    ),
    md(
        """
## Context & Methods

The downstream business question is which merchants should be prioritised for onboarding. Before feature engineering or ranking, this audit establishes source integrity, grains, candidate keys, domains, temporal coverage, join cardinality and external geography coverage.

Key assumptions:

- transaction dates come from the ZIP member partition paths;
- course identifiers are synthetic;
- `merchant_abn` is an identifier label, not evidence of a real ABN;
- POA is the primary demographic geography and SA2 is sensitivity-only;
- hash/schema drift is a hard failure rather than silently accepted.
"""
    ),
    code(
        r"""
from collections import Counter, defaultdict
from pathlib import Path
import hashlib
import io
import json
import re
import uuid
import zipfile

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from IPython.display import display

pd.set_option("display.max_columns", 30)
pd.set_option("display.max_rows", 30)
pd.set_option("display.width", 140)

cwd = Path.cwd().resolve()
repo_root = next(
    candidate
    for candidate in (cwd, *cwd.parents)
    if (candidate / "docs" / "preclean" / "source_manifest.json").exists()
)
raw_root = repo_root / "tables" / "raw"
manifest_path = repo_root / "docs" / "preclean" / "source_manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

def raw_snapshot():
    return {
        str(path.relative_to(raw_root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in raw_root.rglob("*")
        if path.is_file()
    }

raw_before = raw_snapshot()
print(f"Repository: {repo_root}")
print(f"Registered sources: {len(manifest['sources'])}; raw files present: {len(raw_before)}")
"""
    ),
    md(
        """
## Data

The course layer contains one mixed master/fraud ZIP plus three transaction ZIPs. The external layer contains POA primary features, SA2 sensitivity inputs, and two context-only publications. The manifest is the byte-level source of truth.
"""
    ),
    code(
        r"""
def sha256_file(path: Path, block_size=8 * 1024 * 1024):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest().upper()

integrity_rows = []
for source in manifest["sources"]:
    path = repo_root / source["local_path"]
    exists = path.exists()
    actual_size = path.stat().st_size if exists else None
    actual_hash = sha256_file(path) if exists else None
    integrity_rows.append(
        {
            "id": source["id"],
            "exists": exists,
            "size_match": actual_size == source["file_size_bytes"],
            "sha256_match": actual_hash == source["sha256"].upper(),
            "bytes": actual_size,
        }
    )

integrity = pd.DataFrame(integrity_rows)
display(integrity)
assert integrity[["exists", "size_match", "sha256_match"]].all().all(), "Manifest integrity failure"
"""
    ),
    code(
        r"""
external_rows = []
for source in manifest["sources"]:
    if source["tier"] == "course":
        continue
    path = repo_root / source["local_path"]
    suffix = path.suffix.lower()
    check = ""
    if suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()
            names = archive.namelist()
            check = f"CRC={'pass' if bad_member is None else bad_member}; members={len(names)}"
            if "boundary" in source["id"]:
                extensions = {Path(name).suffix.lower() for name in names}
                assert {".shp", ".dbf", ".shx", ".prj"}.issubset(extensions)
    elif suffix == ".xlsx":
        sheets = pd.ExcelFile(path).sheet_names
        check = f"workbook opens; sheets={len(sheets)}"
    elif suffix == ".pdf":
        from pypdf import PdfReader
        check = f"PDF opens; pages={len(PdfReader(path).pages)}"
    external_rows.append({"id": source["id"], "tier": source["tier"], "structural_check": check})

external_checks = pd.DataFrame(external_rows)
display(external_checks)

# Contract-level schema checks for the selected primary geography sources.
census_path = raw_root / "external" / "primary" / "2021_GCP_POA_for_AUS_short-header.zip"
census_prefix = "2021 Census GCP Postal Areas for AUS/"
census_required = {
    "2021Census_G01_AUST_POA.csv": {"POA_CODE_2021", "Tot_P_P"},
    "2021Census_G02_AUST_POA.csv": {"POA_CODE_2021", "Median_tot_hhd_inc_weekly"},
    "2021Census_G04A_AUST_POA.csv": {"POA_CODE_2021", "Age_yr_18_P", "Age_yr_19_P", "Age_yr_20_24_P", "Age_yr_25_29_P", "Age_yr_30_34_P", "Age_yr_35_39_P"},
    "2021Census_G33_AUST_POA.csv": {"POA_CODE_2021", "Negative_Nil_income_Tot", "HI_1_149_Tot", "HI_4000_more_Tot", "Partial_income_stated_Tot", "All_incomes_not_stated_Tot", "Tot_Tot"},
    "2021Census_G43_AUST_POA.csv": {"POA_CODE_2021", "P_15_yrs_over_P", "lfs_Unmplyed_lookng_for_wrk_P", "lfs_Tot_LF_P", "Percent_Unem_loyment_P", "Percnt_LabForc_prticipation_P"},
}
with zipfile.ZipFile(census_path) as archive:
    for member, required_columns in census_required.items():
        header = set(pd.read_csv(archive.open(census_prefix + member), nrows=0).columns)
        assert required_columns <= header, f"Census schema drift: {member}"

seifa_path = raw_root / "external" / "primary" / "SEIFA_2021_POA.xlsx"
seifa_header = pd.read_excel(seifa_path, sheet_name="Table 1", header=None, skiprows=5, nrows=1).iloc[0, :5].tolist()
assert seifa_header == ["2021 Postal Area (POA) Code", "Score", "Decile", "Score", "Decile"]
print("PASS: required Census G01/G02/G04A/G33/G43 columns and SEIFA Table 1 A:E are present.")
"""
    ),
    md("## Results\n\n### Master tables, native grains and fields"),
    code(
        r"""
part1_path = raw_root / "course" / "project-2-bnpl-tables-part1.zip"
with zipfile.ZipFile(part1_path) as archive:
    assert archive.testzip() is None
    consumer_fraud = pd.read_csv(archive.open("tables/consumer_fraud_probability.csv"))
    user_map = pd.read_parquet(io.BytesIO(archive.read("tables/consumer_user_details.parquet")))
    merchant_fraud = pd.read_csv(archive.open("tables/merchant_fraud_probability.csv"))
    consumers = pd.read_csv(archive.open("tables/tbl_consumer.csv"), sep="|")
    merchants = pd.read_parquet(io.BytesIO(archive.read("tables/tbl_merchants.parquet")))

table_summary = pd.DataFrame(
    [
        ("consumers", len(consumers), len(consumers.columns), int(consumers.isna().sum().sum()), consumers["consumer_id"].nunique()),
        ("user mapping", len(user_map), len(user_map.columns), int(user_map.isna().sum().sum()), user_map["user_id"].nunique()),
        ("merchants", len(merchants), len(merchants.columns) + 1, int(merchants.isna().sum().sum()), merchants.index.nunique()),
        ("consumer fraud", len(consumer_fraud), len(consumer_fraud.columns), int(consumer_fraud.isna().sum().sum()), len(consumer_fraud.drop_duplicates(["user_id", "order_datetime"]))),
        ("merchant fraud", len(merchant_fraud), len(merchant_fraud.columns), int(merchant_fraud.isna().sum().sum()), len(merchant_fraud.drop_duplicates(["merchant_abn", "order_datetime"]))),
    ],
    columns=["table", "rows", "fields_including_index", "null_cells", "candidate_key_count"],
)
display(table_summary)

assert consumers["consumer_id"].is_unique
assert user_map["user_id"].is_unique and user_map["consumer_id"].is_unique
assert merchants.index.is_unique
consumer_fraud_exact_duplicates = len(consumer_fraud) - len(consumer_fraud.drop_duplicates())
assert consumer_fraud_exact_duplicates == 99
assert not merchant_fraud.duplicated(["merchant_abn", "order_datetime"]).any()
"""
    ),
    md("### Merchant-tag syntax and synthetic ABN evidence"),
    code(
        r"""
tag_pattern = re.compile(
    r"^[\(\[]+[\(\[](?P<category>.+)[\)\]]\s*,\s*[\(\[](?P<segment>[A-Za-z])[\)\]]\s*,\s*[\(\[]take rate:\s*(?P<rate>[0-9.]+)[\)\]][\)\]]+$"
)
parsed_tags = merchants["tags"].str.extract(tag_pattern)
assert not parsed_tags.isna().any().any()
parsed_tags["category_normalised"] = parsed_tags["category"].map(
    lambda value: re.sub(r"\s+", " ", value.casefold()).strip()
)
parsed_tags["segment"] = parsed_tags["segment"].str.upper()
parsed_tags["rate"] = parsed_tags["rate"].astype(float)

tag_summary = pd.DataFrame(
    {
        "metric": ["raw category strings", "normalised categories", "tag parse failures"],
        "value": [parsed_tags["category"].nunique(), parsed_tags["category_normalised"].nunique(), int(parsed_tags.isna().any(axis=1).sum())],
    }
)
display(tag_summary)
display(merchants["tags"].str[:2].value_counts().rename_axis("opening_brackets").to_frame("merchants"))
display(parsed_tags.groupby("segment")["rate"].agg(["count", "min", "median", "max"]))

def valid_abn(value):
    digits = [int(char) for char in str(int(value)).zfill(11)]
    digits[0] -= 1
    return sum(digit * weight for digit, weight in zip(digits, [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19])) % 89 == 0

valid_master_abns = sum(valid_abn(value) for value in merchants.index)
print(f"Valid ABN checksums in merchant master: {valid_master_abns:,}/{len(merchants):,} ({valid_master_abns/len(merchants):.2%})")
assert valid_master_abns == 40
"""
    ),
    md(
        """
### Full transaction scan

The next cell reads every Parquet member directly from its ZIP. It does not extract or export any data. It retains only bounded audit arrays/sets and aggregate counts in memory.
"""
    ),
    code(
        r"""
transaction_paths = [raw_root / "course" / f"project-2-bnpl-tables-part{part}.zip" for part in (2, 3, 4)]
date_pattern = re.compile(r"order_datetime=(\d{4}-\d{2}-\d{2})/.*\.parquet$")
uuid_pattern = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")

consumer_fraud_work = consumer_fraud.copy()
merchant_fraud_work = merchant_fraud.copy()
consumer_fraud_work["date"] = consumer_fraud_work["order_datetime"].astype(str).str[:10]
merchant_fraud_work["date"] = merchant_fraud_work["order_datetime"].astype(str).str[:10]
consumer_signal_by_date = {date: set(group["user_id"].astype("int64")) for date, group in consumer_fraud_work.drop_duplicates(["user_id", "date"]).groupby("date")}
merchant_signal_by_date = {date: set(group["merchant_abn"].astype("int64")) for date, group in merchant_fraud_work.drop_duplicates(["merchant_abn", "date"]).groupby("date")}

master_merchant_ids = set(pd.Index(merchants.index).astype("int64"))
mapped_user_ids = set(user_map["user_id"].astype("int64"))
all_user_ids, all_merchant_ids = set(), set()
matched_consumer_keys, matched_merchant_keys = set(), set()
amount_chunks, order_hash_chunks = [], []
daily_rows, package_rows = [], []
null_counts = Counter()
schema_strings = set()
total_rows = invalid_uuid_rows = unknown_merchant_rows = 0
consumer_signal_order_matches = merchant_signal_order_matches = both_signal_order_matches = 0
max_consumer_orders_per_signal = max_merchant_orders_per_signal = 0

for package_path in transaction_paths:
    package_total = 0
    package_dates = []
    with zipfile.ZipFile(package_path) as archive:
        assert archive.testzip() is None
        parquet_members = [name for name in archive.namelist() if date_pattern.search(name)]
        for member in parquet_members:
            date = date_pattern.search(member).group(1)
            member_bytes = archive.read(member)
            frame = pq.read_table(io.BytesIO(member_bytes)).to_pandas()
            assert list(frame.columns) == ["user_id", "merchant_abn", "dollar_value", "order_id"]
            schema_strings.add(str(pq.read_schema(io.BytesIO(member_bytes))))
            n_rows = len(frame)
            package_total += n_rows
            total_rows += n_rows
            package_dates.append(date)
            daily_rows.append((date, n_rows))
            null_counts.update(frame.isna().sum().astype(int).to_dict())
            invalid_uuid_rows += int((~frame["order_id"].str.fullmatch(uuid_pattern)).sum())
            amount_chunks.append(frame["dollar_value"].to_numpy(dtype="float64", copy=True))
            order_hash_chunks.append(pd.util.hash_pandas_object(frame["order_id"], index=False).to_numpy(dtype="uint64", copy=True))

            users = frame["user_id"].astype("int64")
            merchant_ids = frame["merchant_abn"].astype("int64")
            all_user_ids.update(users.unique())
            all_merchant_ids.update(merchant_ids.unique())
            unknown_merchant_rows += int((~merchant_ids.isin(master_merchant_ids)).sum())

            consumer_ids_today = consumer_signal_by_date.get(date, set())
            merchant_ids_today = merchant_signal_by_date.get(date, set())
            consumer_mask = users.isin(consumer_ids_today)
            merchant_mask = merchant_ids.isin(merchant_ids_today)
            consumer_signal_order_matches += int(consumer_mask.sum())
            merchant_signal_order_matches += int(merchant_mask.sum())
            both_signal_order_matches += int((consumer_mask & merchant_mask).sum())
            if consumer_mask.any():
                counts = users[consumer_mask].value_counts()
                max_consumer_orders_per_signal = max(max_consumer_orders_per_signal, int(counts.max()))
                matched_consumer_keys.update((int(user), date) for user in counts.index)
            if merchant_mask.any():
                counts = merchant_ids[merchant_mask].value_counts()
                max_merchant_orders_per_signal = max(max_merchant_orders_per_signal, int(counts.max()))
                matched_merchant_keys.update((int(merchant), date) for merchant in counts.index)
    package_rows.append((package_path.name, len(package_dates), package_total, min(package_dates), max(package_dates)))

amounts = np.concatenate(amount_chunks)
order_hashes = np.concatenate(order_hash_chunks)
duplicate_hash_candidates = len(order_hashes) - len(np.unique(order_hashes))
daily = pd.DataFrame(daily_rows, columns=["date", "rows"]).sort_values("date")
packages = pd.DataFrame(package_rows, columns=["package", "partitions", "rows", "min_date", "max_date"])

display(packages)
print(f"Total rows: {total_rows:,}; distinct dates: {daily['date'].nunique():,}; schemas observed: {len(schema_strings)}")
print(f"Null cells: {dict(null_counts)}; invalid UUIDs: {invalid_uuid_rows:,}; duplicate hash candidates: {duplicate_hash_candidates:,}")

assert total_rows == 14_195_505
assert daily["date"].nunique() == 606
assert daily["date"].min() == "2021-02-28" and daily["date"].max() == "2022-10-26"
assert list(pd.to_datetime(daily["date"])) == list(pd.date_range("2021-02-28", "2022-10-26", freq="D"))
assert sum(null_counts.values()) == 0 and invalid_uuid_rows == 0 and duplicate_hash_candidates == 0
assert len(schema_strings) == 1
"""
    ),
    md("### Transaction domains, temporal profile and foreign keys"),
    code(
        r"""
quantile_points = [0, 0.001, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 0.999, 0.9999, 1]
amount_summary = pd.DataFrame(
    {"quantile": quantile_points, "dollar_value": np.quantile(amounts, quantile_points)}
)
display(amount_summary)
print(f"mean=${amounts.mean():,.2f}; std=${amounts.std():,.2f}; total=${amounts.sum():,.2f}; <=0={int((amounts <= 0).sum()):,}; under $1={int((amounts < 1).sum()):,}")

active_user_count = len(all_user_ids)
unknown_merchants = all_merchant_ids - master_merchant_ids
fk_summary = pd.DataFrame(
    [
        ("transaction users", active_user_count, len(all_user_ids - mapped_user_ids), None),
        ("transaction merchants", len(all_merchant_ids), len(unknown_merchants), unknown_merchant_rows),
    ],
    columns=["entity", "distinct_in_transactions", "missing_from_master", "affected_transaction_rows"],
)
display(fk_summary)
display(daily.nlargest(10, "rows"))

assert amounts.min() > 0
assert active_user_count == 24_081 and not (all_user_ids - mapped_user_ids)
assert len(all_merchant_ids) == 4_422
assert len(unknown_merchants) == 396 and unknown_merchant_rows == 580_830
assert daily.nlargest(1, "rows").iloc[0].to_dict() == {"date": "2021-11-26", "rows": 61_237}
"""
    ),
    md("### Fraud join cardinality"),
    code(
        r"""
consumer_unique_keys = set(
    zip(consumer_fraud_work["user_id"].astype("int64"), consumer_fraud_work["date"])
)
merchant_unique_keys = set(
    zip(merchant_fraud_work["merchant_abn"].astype("int64"), merchant_fraud_work["date"])
)
fraud_summary = pd.DataFrame(
    [
        ("consumer", len(consumer_fraud), len(consumer_unique_keys), consumer_fraud_exact_duplicates, consumer_signal_order_matches, max_consumer_orders_per_signal, len(consumer_unique_keys - matched_consumer_keys)),
        ("merchant", len(merchant_fraud), len(merchant_unique_keys), 0, merchant_signal_order_matches, max_merchant_orders_per_signal, len(merchant_unique_keys - matched_merchant_keys)),
    ],
    columns=["signal", "source_rows", "unique_native_keys", "exact_duplicates", "matched_order_rows", "max_orders_per_native_key", "native_keys_without_order"],
)
display(fraud_summary)
print(f"Orders matching both consumer and merchant signals: {both_signal_order_matches:,}")

assert consumer_signal_order_matches == 80_348
assert merchant_signal_order_matches == 4_059
assert both_signal_order_matches == 405
assert max_consumer_orders_per_signal == 11 and max_merchant_orders_per_signal == 535
assert consumer_unique_keys == matched_consumer_keys and merchant_unique_keys == matched_merchant_keys
"""
    ),
    md("### Postcode coverage and SA2 ambiguity"),
    code(
        r"""
coding_path = raw_root / "external" / "sensitivity" / "ASGS2021CodingIndexes.zip"
coding_member = "2022 Locality to 2021 SA2 Coding Index.csv"
with zipfile.ZipFile(coding_path) as archive:
    coding = pd.read_csv(archive.open(coding_member), dtype=str)

coding["STATE"] = coding["STATE"].str.strip()
coding["POSTCODE"] = coding["POSTCODE"].str.strip().str.zfill(4)
coding["SA2_MAINCODE_2021"] = coding["SA2_MAINCODE_2021"].str.strip()
official_counts = (
    coding.groupby(["STATE", "POSTCODE"], as_index=False)["SA2_MAINCODE_2021"]
    .nunique()
    .rename(columns={"SA2_MAINCODE_2021": "sa2_count"})
)

consumer_geo = consumers[["state", "postcode"]].copy()
consumer_geo["state"] = consumer_geo["state"].astype(str).str.strip()
consumer_geo["postcode4"] = consumer_geo["postcode"].astype(str).str.strip().str.zfill(4)
consumer_geo = consumer_geo.merge(
    official_counts,
    how="left",
    left_on=["state", "postcode4"],
    right_on=["STATE", "POSTCODE"],
)
unmatched = consumer_geo["sa2_count"].isna()
official_postcodes = set(coding["POSTCODE"])
global_postcode_invalid = unmatched & ~consumer_geo["postcode4"].isin(official_postcodes)
state_mismatch = unmatched & consumer_geo["postcode4"].isin(official_postcodes)

geo_summary = pd.DataFrame(
    {
        "status": ["unique SA2", "multiple SA2", "unmatched", "unmatched: postcode absent nationally", "unmatched: state mismatch"],
        "consumers": [
            int((consumer_geo["sa2_count"] == 1).sum()),
            int((consumer_geo["sa2_count"] > 1).sum()),
            int(unmatched.sum()),
            int(global_postcode_invalid.sum()),
            int(state_mismatch.sum()),
        ],
    }
)
geo_summary["share_of_consumers"] = geo_summary["consumers"] / len(consumers)
display(geo_summary)

assert int(unmatched.sum()) == 83_519
assert int((consumer_geo["sa2_count"] == 1).sum()) == 237_729
assert int((consumer_geo["sa2_count"] > 1).sum()) == 178_751
assert int(global_postcode_invalid.sum()) == 83_035 and int(state_mismatch.sum()) == 484
"""
    ),
    md("### Raw immutability check"),
    code(
        r"""
raw_after = raw_snapshot()
assert raw_after == raw_before, "A raw file was added, removed, resized, or modified during the audit"
print(f"PASS: all {len(raw_after)} raw files retain their original size and modification timestamp.")
"""
    ),
    md(
        """
## Takeaways

1. **Proceed to controlled cleaning, not modelling.** File integrity, transaction coverage and order keys are sound, but five policy decisions remain open.
2. **Prevent silent row loss or multiplication.** Unknown merchants must be explicit, and daily fraud sources must be made unique at native grain before any order join.
3. **Use POA as the primary geography.** Keep unmatched status and version metadata. Do not force ambiguous postcodes into a single SA2.
4. **Treat extremes as evidence.** Preserve the amount tail and Black Friday spike; compare robust transformations downstream.
5. **Never ABR-enrich these IDs.** Their checksum behaviour supports the course description that they are synthetic.

The controlling hand-off documents are `cleaning_specification.md`, `decision_log.md`, and `cleaning_readiness_checklist.md`.
"""
    ),
]

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
nbf.write(nb, OUTPUT)
print(f"Wrote {OUTPUT}")
