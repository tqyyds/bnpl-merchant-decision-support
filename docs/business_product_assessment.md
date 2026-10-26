# Business product assessment

## Verdict

The proposed product is worthwhile, but it should be framed as a **merchant portfolio and
onboarding prioritisation tool**, not a fully automated approval engine. It answers a useful
operating question: given limited partnership capacity, which merchants should the BNPL team
investigate first, and why?

The strongest version of the product does not collapse everything into one opaque score. It shows
commercial value, risk, and evidence confidence separately, then lets an authorised user apply
portfolio constraints. This makes the recommendation explainable and gives the business control
over its risk appetite.

## What makes the idea strong

- It turns a broad analytical exercise into a repeated business decision: produce and review a
  merchant shortlist.
- The transaction history supports features for scale, growth, stability, customer engagement,
  and concentration.
- Merchant take rate makes a revenue-oriented outcome possible; ranking by GMV alone would miss
  this commercial difference.
- The later transaction period allows honest retrospective testing of whether an earlier ranking
  identified merchants that subsequently produced value.
- A dashboard is appropriate because users need to compare merchants, test portfolio assumptions,
  understand warnings, and export a review list.

## Important changes to the original framing

### Call the value measure take-rate revenue, not profit

The supplied data can estimate `GMV × take rate`. It does not contain funding cost, credit losses,
merchant acquisition cost, servicing cost, refunds, chargebacks, or contract-specific economics.
The model therefore estimates a revenue proxy, not net profit or lifetime value.

### Keep value, risk, and confidence separate

A single score can hide why a merchant ranks highly. A merchant could have high expected value but
weak fraud coverage, or low measured risk only because no risk record was observed. The dashboard
should always expose the component measures and warnings.

### Treat the output as prioritisation, not rejection

“Not selected” should mean outside the current capacity-constrained portfolio, not a bad or
ineligible merchant. The final contractual decision still needs due diligence and a human owner.

### Use geographic data carefully

Consumer postcode can describe a merchant's observed customer catchment. It cannot establish the
merchant's physical location, and area-level socioeconomic indicators must not be presented as
attributes of individual customers.

## Should Boruta be used?

### Recommendation: yes as a comparison, no as the foundation

Boruta is an all-relevant feature-selection method based on random forests and shadow features. It
can be useful for testing whether engineered merchant variables contain stable predictive signal.
It should not decide what a “good merchant” means, and it should not be the only feature-selection
method.

The key issue is sample size. Although the source contains more than 14 million transactions, the
modelled unit is the merchant, so there are only about 4,026 candidate observations. The proposed
features—GMV, transaction count, customer count, average order value, growth, and related
concentration measures—are also likely to be correlated. Boruta may retain several redundant
features, and its output may change across random seeds.

### Recommended feature-selection approach

1. Remove leakage, identifiers, personally identifying information, and variables unavailable at
   decision time.
2. Define a compact set of business-supported feature families before modelling.
3. Establish simple baselines using historical take-rate revenue and an all-feature model.
4. Run Boruta only on the training portion of the data.
5. Repeat Boruta across several seeds or resamples and record selection frequency.
6. Compare validation error, rank correlation, top-portfolio value, and stability—not just the
   number of selected variables.
7. Keep business-required risk and confidence controls in the decision layer even if Boruta does
   not select them for the value model.

### Decision rule

Adopt the Boruta feature set only if it produces similar or better out-of-time ranking performance,
is stable across repeated runs, and makes the model materially easier to explain or maintain.
Otherwise, use the simpler business-defined set or the all-feature benchmark.

## What this product cannot claim from the supplied data

- true merchant profitability or customer lifetime value;
- causal impact of onboarding a merchant;
- future fraud loss or credit default without loss labels;
- merchant geographic location;
- fairness at individual-customer level from aggregated postcode context; or
- production readiness without monitoring, access control, and current operational data.

## Overall recommendation

Proceed with the product as a transparent, human-in-the-loop portfolio tool. Demonstrate that it
beats simple historical rankings in the later period, show uncertainty and missing-data coverage,
and make Boruta a documented sensitivity analysis. That positioning is both commercially useful
and defensible for the data available.

