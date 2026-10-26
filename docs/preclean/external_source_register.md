# External Source Register

## Accepted primary geography

1. **ABS 2021 Census General Community Profile — Postal Areas.** Official Census DataPacks. Reference year 2021; primary demographic feature source. Use selected, documented variables only and retain POA grain. Licence: Creative Commons Attribution 4.0 as documented inside the archive.
2. **ABS SEIFA 2021 — Postal Area.** Official workbook released 27 April 2023. Use IRSD and IRSAD scores/deciles as area-level measures, never as individual attributes.
3. **ABS ASGS Edition 3 POA boundary, 2021, GDA2020.** Official digital boundary. Use for map geometry and POA-code validation. POAs approximate postcodes and are not exact postal boundaries.

## Accepted validation / sensitivity sources

4. **ASGS 2021 Coding Indexes.** Official data.gov.au distribution. Use the 2022 locality-to-2021-SA2 file because it overlaps the transaction period. The index demonstrates one-to-many postcode/SA2 relationships and is not a deterministic allocation table.
5. **ASGS Edition 3 SA2 boundary, 2021, GDA2020.** Geometry for labelled sensitivity analysis only.
6. **ABS Regional Population 2021–22.** SA2 population workbook for temporal sensitivity checks only; it is not joined to the primary POA feature layer.

## Accepted context-only sources

7. **Reserve Bank of Australia, 2022 Consumer Payments Survey.** Official research publication; narrative and aggregate benchmark only.
8. **ASIC Report 672, Buy now pay later: An industry update.** Official regulatory context. Published in 2020 and therefore not period-matched feature data; context only.

## Reliability criteria applied

Sources are first-party government or central-bank publications, have an identifiable reference period, provide stable downloadable files, and include usable geographic or report metadata. File hashes and structural checks are registered. “Official” does not make grains interchangeable: feature eligibility is constrained by the raw join keys and the source's unit of observation.

## Deferred / rejected

- **ABS Counts of Australian Businesses / ANZSIC:** deferred until a defensible merchant geography and category crosswalk exist.
- **Australian Business Register:** rejected for these synthetic identifiers. Passing an ABN checksum does not establish identity, and only 0.99% pass at all.

Canonical landing/download URLs and local hashes are in `source_manifest.json`.
