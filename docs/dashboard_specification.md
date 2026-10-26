# Dashboard and user actions

## What the final product looks like

The final product is best presented as an internal web dashboard backed by a governed
merchant-level scoring table. It is not just a static chart and it is not a customer-facing app.
Its purpose is to help strategy, partnerships, and risk users assemble and defend a merchant
portfolio.

The included [dashboard mock-up](../dashboard/mockup.html) illustrates the experience with
synthetic data. It is a product-design example, not a production dashboard or a display of model
results.

## Proposed navigation

### 1. Portfolio overview

The landing page answers “what are we recommending under the current scenario?” It shows:

- number of prioritised merchants;
- predicted take-rate revenue proxy;
- average risk and confidence;
- industry mix;
- comparison with simple GMV and customer-count baselines; and
- data/model cut-off and version.

### 2. Merchant explorer

Users can search and filter the candidate universe by merchant, industry, tier, decision status,
risk, confidence, predicted value, or data-quality warning. The ranking table keeps value, risk,
and confidence in separate columns.

### 3. Merchant decision card

Selecting a merchant opens a detailed card containing:

- current portfolio decision and rank;
- predicted value and historical commercial measures;
- top positive reasons;
- risk and missing-data warnings;
- customer engagement, growth, stability, and concentration evidence;
- observation window, model version, and confidence; and
- a field for a human review outcome and rationale in a production version.

### 4. Scenario builder

Authorised users can change business policy without retraining the value model. Proposed controls
include:

- portfolio capacity;
- risk appetite;
- maximum industry concentration;
- minimum evidence confidence;
- maximum average portfolio risk; and
- manual-review capacity.

The dashboard recalculates the proposed shortlist and highlights which merchants entered or left,
how expected value changed, and whether any constraint is binding.

### 5. Data quality and model governance

This page makes limitations visible rather than hiding them. It includes source freshness,
unmatched merchant ABNs, join and fraud coverage, parse exceptions, protected evaluation dates,
feature-selection stability, model-vs-baseline results, and recent monitoring status.

## What a user can do

| User action | Result |
|---|---|
| Search/filter merchants | Narrow the candidate list without changing the underlying score |
| Sort by value, risk, or confidence | Explore different decision perspectives |
| Open a decision card | Understand why a merchant is recommended and see warnings |
| Change a scenario constraint | Produce a new portfolio under explicit business assumptions |
| Compare with baselines | Check whether modelling adds value over simple historical ranking |
| Inspect data quality | See gaps, coverage, cut-off dates, and unresolved records |
| Add a review outcome | Record human judgement and a reason in the production workflow |
| Export the shortlist | Send a merchant-level review file to an authorised downstream process |

## Guardrails

- The dashboard should never expose consumer names, street addresses, or raw transactions.
- Predictions must be labelled estimates and take-rate revenue must not be called profit.
- Missing risk observations must be shown as unknown coverage, not zero risk.
- “Not selected” must not be rendered as “rejected.”
- Scenario settings, model version, data cut-off, exports, and human overrides should be logged.
- Only authorised users should be able to export or write review outcomes.

## Suggested users

| Role | Primary use |
|---|---|
| Head of Merchant Strategy | Approve portfolio assumptions and compare scenarios |
| Partnerships Manager | Investigate priority merchants and plan outreach |
| Risk Analyst | Review risk signals, coverage gaps, and manual-review cases |
| Data/Model Owner | Monitor data freshness, model performance, and feature stability |

## Mock-up behaviour

The browser mock-up lets the viewer change a synthetic portfolio size, risk ceiling, industry cap,
and minimum confidence; search/filter the generated shortlist; and click a row to view a decision
card. All demonstration records use `DEMO-` identifiers and invented values. No supplied project
data is embedded.

