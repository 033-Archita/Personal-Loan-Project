# Personal Loan Eligibility Model — India

A transparent, rule-based screening prototype that compares an applicant profile with publicly documented personal-loan criteria from 20 lenders in India. It reports lender-level screening outcomes, missing information, estimated borrowing capacity, indicative rate and tenure, and a ranked match.

> **Important:** `screen_eligible` means only that the supplied profile did not fail an applicable hard rule available in this dataset. It is not a lender decision, offer, or approval guarantee.

## Contents

- [Problem and scope](#problem-and-scope)
- [Lender selection](#lender-selection)
- [Repository structure](#repository-structure)
- [Research and evidence](#research-and-evidence)
- [Applicant input variables](#applicant-input-variables)
- [Lender-rule dataset](#lender-rule-dataset)
- [Model methodology](#model-methodology)
- [Setup and usage](#setup-and-usage)
- [Sample scenarios and recorded outputs](#sample-scenarios-and-recorded-outputs)
- [What the sample results show](#what-the-sample-results-show)


## Problem and scope

Applicants comparing Indian personal loans often need to consider more than a headline interest rate. Lender criteria can include age, income, employment type, work history, bureau score, existing EMIs, employer or salary-account category, FOIR, loan size, and tenure. Some criteria are published clearly; others are scheme-specific, calculator-derived, incomplete, or not public.

This project brings recorded public rules into one auditable CSV and applies a deterministic screening waterfall. Its objectives are to:

1. represent published lender criteria with source and evidence status;
2. identify possible hard-rule failures and unresolved inputs for a profile;
3. estimate repayment capacity and indicative pricing where the dataset supports an estimate; and
4. present lender comparisons in a small Streamlit interface.

The scope is **unsecured personal loans in India**. The model does not cover other loan products, access lender systems, use customer data, or train an approval model. Results depend on the rule data included in this repository.

## Lender selection

The dataset contains 20 lender IDs spanning public-sector banks, private banks, small finance banks, and NBFCs:

| Type | Lenders |
| --- | --- |
| Public-sector banks (7) | State Bank of India, Bank of Baroda, Union Bank of India, Central Bank of India, Bank of Maharashtra, Punjab National Bank, Canara Bank |
| Private banks (5) | HDFC Bank, ICICI Bank, Axis Bank, Kotak Mahindra Bank, IDFC FIRST Bank |
| Small finance banks (3) | AU Small Finance Bank, Equitas Small Finance Bank, ESAF Small Finance Bank |
| NBFCs (5) | Bajaj Finance, Tata Capital, Poonawalla Fincorp, SMFG India Credit, L&T Finance |

This is a practical comparison set chosen to include major bank and non-bank providers and lenders with different public product information. The repository does not document a ranking by current market share or a formal “top 20” market-size calculation. Fintech platforms are not listed as a separate lender category; lenders are represented by the bank or NBFC recorded in the dataset.

## Repository structure

The runnable project is in this directory (`outputs/` in the surrounding workspace):

```text
.
├── README.md                 # Project documentation
├── app.py                    # Streamlit results browser
├── data.py                   # 15 synthetic profiles and output generation
├── input.csv                 # Generated applicant profiles
├── lender_rules.csv          # Long-format, sourced lender-rule dataset
├── model.py                  # Screening, affordability, scorecard, and ranking
└── test_outputs.csv          # Saved results for input.csv
```

`input.csv` and `test_outputs.csv` are generated snapshots. Regenerate them after changing the rules or model. No formal automated unit-test suite, `requirements.txt`, `pyproject.toml`, or package lockfile is present in this project directory. The surrounding workspace contains research and data-preparation artifacts; they are not needed to launch this app.

## Research and evidence

The rule collection uses public sources. The documented research workflow reviewed lender product and eligibility pages, FAQs, scheme/product terms, published rate tables, and public calculators. Discovery and extraction used Claude with Firecrawl, Perplexity web search, and Gemini web search. For gaps that depended on public calculators, an open-source AI browser-agent MCP server was used to inspect calculator behavior. Calculator results are treated as estimates and are not converted into lender-published rules unless separately supported by a source.

The CSV stores source URLs, publisher/type, access date, supporting passage, segment, confidence, status, and estimation/conflict notes where available. The recorded access dates range from **2026-10-11 to 2026-10-12**. There are 486 rule rows and 40 distinct non-empty source URLs in the current file; a row may have no URL when it is an estimate or no source was located. These are the dates recorded in the dataset, not a guarantee that a page or rule remains current. Recheck the lender source before relying on any value.

Examples of direct sources represented in the CSV:

- [SBI personal loan](https://sbi.bank.in/web/personal-banking/loans/personal-loans/sbi-personal-loan) — several recorded rules accessed 2026-10-11.
- [Bank of Baroda personal loan](https://bankofbaroda.bank.in/loans/personal-loan/baroda-personal-loan) — recorded rules accessed 2026-10-11 and 2026-10-12.
- [PNB personal loan for public](https://pnb.bank.in/personalloanforpublic.html) and [PNB interest rates](https://www.pnb.bank.in/interst-rate-on-advances-linked-to-mclr.html) — recorded rules accessed 2026-10-11 and 2026-10-12.
- [ICICI personal-loan eligibility](https://www.icici.bank.in/personal-banking/loans/personal-loan/eligibility) — recorded rules accessed 2026-10-11.
- [Axis Bank personal loan](https://www.axis.bank.in/loans/personal-loan) — recorded rules accessed 2026-10-11.

These examples do not represent every source or imply that every row for a lender is official. The row-level `source_url`, `accessed_at`, `supporting_passage`, `segment`, and `status` in [`lender_rules.csv`](lender_rules.csv) are the evidence trail. No separate RBI rule table is represented in the current lender-rule CSV; do not assume RBI material was used as a lender-specific underwriting threshold.

### Evidence labels in `lender_rules.csv`

| Status | Meaning in this project |
| --- | --- |
| `VERIFIED_OFFICIAL` | Recorded as directly supported by a lender source. The model can use numeric rows with this status for hard-rule rejection. |
| `OFFICIAL_PARTIAL` | An official source supports only part of the rule or provides incomplete information. Not treated as a hard rejection by default. |
| `ESTIMATE_PEER`, `ESTIMATE_DERIVED` | Inferred from peer information or derived; not a lender-published fact. |
| `THIRD_PARTY_UNVERIFIED` | Found in a public third-party source but not verified against a lender source. |
| `CONFLICT_RESOLVED` | Conflicting source information was recorded with a resolution note; this status is not in the model's hard-rule allowlist. |
| `NOT_PUBLISHED` | No explicit or numeric public value was located for the rule. |
| `NOT_APPLICABLE` | The rule does not apply to the stated product/scheme segment. |

The current CSV status counts are 210 `VERIFIED_OFFICIAL`, 34 `OFFICIAL_PARTIAL`, 217 `ESTIMATE_PEER`, 7 `ESTIMATE_DERIVED`, 6 `THIRD_PARTY_UNVERIFIED`, 1 `CONFLICT_RESOLVED`, 3 `NOT_PUBLISHED`, and 8 `NOT_APPLICABLE`. These totals describe rows, not lender coverage or independent verification quality. `lender_rules.csv` is a **long-format** dataset: each row represents one rule/segment observation, and a lender can have several different values for the same rule under different schemes or segments.

### What varies across lenders

The dataset records rule keys for age at application and maturity, salaried and self-employed income floors, minimum credit score, total and current-job experience, business vintage, employment eligibility, employer category, salary-account requirement, FOIR, income multiple, minimum/maximum amount and tenure, rate range, CIBIL rate bands, and processing fees. Coverage is uneven. Some values are official and numeric; some are segment-specific; and some remain estimates, unpublished, or absent.

A few illustrations from the recorded rows:

- **SBI:** the CSV records a 65% of net monthly income FOIR cap, a 30-times monthly income multiple, a ₹50 lakh maximum amount, and up to 84 months for the cited salaried segment. The same record set marks SBI's public numeric CIBIL floor as `NOT_PUBLISHED`.
- **Bank of Baroda:** a recorded official row lists a 701 minimum score; published FOIR and tenure rows vary by income, employer, and salary-account segment. The CSV has rate rows for named categories, including a 10.65%–15.50% p.a. Gold-category range accessed 2026-10-12. These are segment-level values, not universal offers.
- **PNB:** the public personal-loan page row does not establish a universal salaried minimum CIBIL score; the dataset separately records scheme-specific PNB Sahyog category B rate bands by score, with floating/fixed rates preserved in `rate_by_cibil_band`. The current model does not directly apply those granular bands when it estimates rates.
- **ICICI:** the dataset has official rows for 12-month minimum and up-to-72-month maximum tenure accessed 2026-10-12. The model uses the row's status and segment when evaluating the requested tenure.

For exact values and scope, consult the source row rather than interpreting these examples as a complete lender offer. The requested values can change and may be superseded by current lender terms.

## Applicant input variables

The model consumes a Python dictionary (or JSON object through its command-line interface). These values are provided by the applicant in the synthetic examples and would normally require documentary or bureau verification in a real application.

| Variable | Type | Unit / allowed values | Description | Origin / verification source |
| --- | --- | --- | --- | --- |
| `age` | Number | Years | Applicant's current age. | Applicant; verify with KYC document. |
| `employment_type` | Category | `salaried`, `self_employed` | Employment class; other input strings are treated as salaried by the current model. | Applicant; verify with employment/business records. |
| `monthly_net_income` | Number | INR/month | Take-home/net monthly income. | Applicant; payslips, bank statement, or income records. |
| `monthly_gross_income` | Number | INR/month | Gross monthly income; used for FOIR where source evidence indicates a gross basis. | Applicant; payslip or income documents. |
| `existing_monthly_emi` | Number | INR/month | Existing monthly debt instalments. | Applicant; bureau report and statements. |
| `credit_score` | Number or blank | Bureau points | Credit score used for hard floor checks and pricing bands. Blank means unavailable/no score; it does not mean zero. | Bureau report with applicant authorization. |
| `current_job_months` | Number | Months | Tenure in the current job. | Applicant; employer records/payslips. |
| `total_experience_months` | Number | Months | Total employment experience. | Applicant; employment history/documents. |
| `business_vintage_months` | Number | Months | Time in business for a self-employed applicant. | Applicant; business and tax records. |
| `requested_amount` | Number | INR | Loan principal requested. | Applicant. |
| `requested_tenure_months` | Number | Months | Requested repayment period. | Applicant. |
| `employer_category` | Category | Text (for example, `government/PSU`, `private`, `mnc`) | Used to match lender rule segments. | Applicant; employer documentation. |
| `salary_account_lender` | Text | Lender name or ID | Salary-credit bank, used for some lender segments. | Applicant; bank statement. |
| `city_type` | Category | Text (for example, `metro`, `urban`, `semi_urban`, `rural`) | Used for some geographic segments, when present in the source rows. | Applicant; address/KYC documentation. |

`profile_id` and `edge_case` in `input.csv` are scenario identifiers/labels for the demo, not underwriting inputs. Missing fields may produce a `conditional` result or an unknown in the lender-level output. The model does not validate uploaded documents or bureau data.

## Model methodology

`model.py` implements a deterministic **waterfall + scorecard + rate-tier** approach. It loads the long-format CSV from the same directory by default and groups rule records by `lender_id`.

### 1. Applicant and scheme matching

The model attempts to match rule `segment` descriptions to employment type, employer category, salary-account lender, income, and location. It selects the most specific matching segment it recognizes. Unrecognized segment text is not assumed to apply. Scheme-level wording and complex employer lists may not be captured perfectly by this text-matching logic.

### 2. Eligibility waterfall

For each lender, it checks available records for:

1. self-employment inclusion/exclusion and business vintage;
2. minimum/maximum age and, when requested, age at loan maturity;
3. employment-specific monthly income floor;
4. published minimum credit score;
5. current-job tenure and total work experience;
6. product minimum/maximum amount and requested tenure; and
7. repayment capacity using an income multiple and/or FOIR where applicable values and inputs exist.

Only rows with status exactly `VERIFIED_OFFICIAL` create hard rejection conditions by default. `OFFICIAL_PARTIAL`, estimates, third-party values, unpublished values, and unknown rules are not treated as verified cutoffs. Calling `evaluate(profile, include_estimates=True)` opts estimates into numeric rule checks; it does not transform those estimates into official facts. Some segment-specific rules or duplicate rule rows can still be difficult to interpret and should be reviewed in the output/evidence CSV.

For a published FOIR percentage, the model calculates the remaining EMI room as:

```text
max(0, income_basis × FOIR% − existing_monthly_emi)
```

It then converts that EMI room to a principal estimate using a standard amortization formula, the requested tenure, and the available upper rate estimate (or a fallback rate when one is absent). Income basis is gross only when the matching FOIR evidence indicates gross; otherwise it uses net income. An income multiple, when present, is currently applied as `multiple × monthly_net_income`, even if a source row describes a gross-income multiple. This is a known implementation limitation. Product maximum, multiple, and FOIR-derived caps are combined by taking the lowest available cap. Unknown rules are not automatically converted to zero or treated as proof of eligibility.

### 3. Rate and tenure estimate

The model reads `rate_min` and `rate_max` rows to establish a range, then interpolates an indicative point within that range by credit-score band:

| Model band | Score | Interpolation within lender range |
| --- | ---: | ---: |
| A | 800+ | 10% from the low endpoint |
| B | 750–799 | 25% |
| C | 700–749 | 55% |
| D | 650–699 | 85% |
| E | Below 650 | At the high endpoint |

This is a model assumption, not a lender's actual score-tier pricing unless a specific lender formula says so. Even where the CSV contains `rate_by_cibil_band` rows, the current model does not consume that field directly. The reported tenure is the available minimum/maximum range; EMI is calculated for the requested amount and requested term when rate and term are available.

### 4. Decision labels, scorecard, and recommendation

Each lender receives one of these labels:

- `not_eligible`: at least one applicable hard rule failed;
- `conditional`: no hard failure was found, but required profile information or lender rules are missing; or
- `screen_eligible`: no hard failure or unresolved required item was found from the rules the model applied.

The 100-point scorecard prioritizes matches. Its implemented point rules are:

| Component | Points in the code |
| --- | --- |
| Credit score (30) | 30 at 800+, 26 at 750–799, 19 at 700–749, 10 at 650–699, otherwise 0; missing score gives 0. |
| Income headroom (25) | 25 at 2× the income floor, 20 at 1.5×, 14 at the floor, otherwise 0. If no floor is found, the scorecard uses a ₹25,000/month fallback. |
| Employment stability (20) | 20 for at least 36 current-job months and 60 total-experience months; 16 for at least 12 and 24 months respectively; 10 for at least 6 current-job months; otherwise 0. |
| Existing debt burden (15) | 15 when existing EMI is at most 10% of net income, 12 at most 25%, 8 at most 40%, otherwise 0. |
| Requested-amount fit (10) | 10 when the estimated capacity is unknown or at least the requested amount; otherwise 0. |

The scorecard does not override a failed rule. Its fallback values and treatment of unknown capacity are ranking assumptions, not lender criteria. The model's `best_option` sorts screen-eligible lenders before conditional lenders, then by score and estimated rate. The Streamlit app separately sorts screen-eligible lenders by estimated rate for its displayed “Best current match.” Therefore, the model's `best_option` and the app's top displayed option can differ.

`overall_decision` is also a coarse summary: with both positive net income and a supplied credit score, it reports `eligible_for_at_least_one_lender` if any lender is `screen_eligible`; otherwise it reports `conditional_or_no_match`. If either is missing, it reports `insufficient_profile_data`, even if individual lender rows are conditional or screen-eligible. Review per-lender decisions, reasons, unknowns, rate estimate, and scorecard rather than relying on the summary alone.

## Setup and usage

Run these commands from the directory containing `app.py` and `model.py` (the project files shown above). Python 3.10 or newer is recommended. Install the packages imported by the app:

```bash
python -m pip install streamlit pandas
```

Generate the 15 synthetic applicant profiles and lender results:

```bash
python data.py
```

Launch the Streamlit app:

```bash
python -m streamlit run app.py
```

The app is a browser for the pre-generated profiles; it does not currently provide a form for entering an arbitrary new applicant. Regenerate the CSVs before launch if you have edited model or rule data, because the app reads the saved input/output files when they exist.

### Run a custom profile through the Python API

```python
from model import evaluate

profile = {
    "age": 32,
    "employment_type": "salaried",
    "monthly_net_income": 80000,
    "monthly_gross_income": 95000,
    "existing_monthly_emi": 10000,
    "credit_score": 760,
    "current_job_months": 36,
    "total_experience_months": 72,
    "business_vintage_months": 0,
    "requested_amount": 800000,
    "requested_tenure_months": 48,
    "employer_category": "private",
    "salary_account_lender": "",
    "city_type": "metro",
}

result = evaluate(profile)
print(result["overall_decision"])
for lender in result["lenders"]:
    if lender["decision"] != "not_eligible":
        print(lender["lender"], lender["decision"], lender["expected_rate_percent_pa"])
```

The equivalent CLI requires a JSON profile file:

```bash
python model.py profile.json
```

The JSON should use the same field names and values as the Python dictionary above. To apply estimated rule rows as constraints, use `evaluate(profile, include_estimates=True)` or the CLI flag `--include-estimates`.

## Sample scenarios and recorded outputs

`data.py` defines 15 synthetic scenarios. `input.csv` contains their input fields; `test_outputs.csv` contains the saved overall label, model-ranked lender/rate/maximum estimate, and lender-level results as JSON. The following table reflects those saved files; it is not a newly run test suite.

| ID | Scenario | Recorded overall label | `model.py` best option | Rate estimate (% p.a.) |
| --- | --- | --- | --- | ---: |
| P01 | Baseline salaried | `eligible_for_at_least_one_lender` | Equitas Small Finance Bank | 11.62 |
| P02 | Recently salaried / new job | `eligible_for_at_least_one_lender` | Axis Bank | 14.03 |
| P03 | No CIBIL score | `insufficient_profile_data` | State Bank of India (conditional; no rate) | — |
| P04 | Young applicant with high EMI burden | `eligible_for_at_least_one_lender` | Axis Bank | 14.03 |
| P05 | Low income with high existing EMI | `eligible_for_at_least_one_lender` | Tata Capital | 23.74 |
| P06 | Self-employed with short business vintage | `eligible_for_at_least_one_lender` | Equitas Small Finance Bank | 11.62 |
| P07 | Near upper age limit | `eligible_for_at_least_one_lender` | Equitas Small Finance Bank | 11.62 |
| P08 | Low credit score | `eligible_for_at_least_one_lender` | ICICI Bank | 17.34 |
| P09 | High income / large loan request | `eligible_for_at_least_one_lender` | Axis Bank | 10.72 |
| P10 | Very high EMI leaves little repayment room | `eligible_for_at_least_one_lender` | HDFC Bank | 14.03 |
| P11 | Normal case: stable salaried, low EMI | `eligible_for_at_least_one_lender` | Equitas Small Finance Bank | 11.62 |
| P12 | Normal case: experienced professional | `eligible_for_at_least_one_lender` | HDFC Bank | 10.72 |
| P13 | Normal case: government employee | `eligible_for_at_least_one_lender` | Equitas Small Finance Bank | 11.62 |
| P14 | Normal case: long tenure and low request | `eligible_for_at_least_one_lender` | HDFC Bank | 11.83 |
| P15 | Normal case: strong income and credit | `eligible_for_at_least_one_lender` | HDFC Bank | 10.72 |

These are outputs of the project's current rule data, not independently confirmed lender offers. The fact that a synthetic scenario has one or more screen-eligible lenders only shows the implemented rules did not reject it; it does not establish that the lender would approve it.

## What the sample results show

- Edge cases exercise missing credit history, short job/business tenure, high EMI relative to income, low score, age near a limit, self-employment, and a high requested amount.
- The five designated normal profiles (P11–P15) have model-level matches in the saved output. The sample set is constructed, not randomly sampled from applicants.
- The no-score case is summarized as `insufficient_profile_data`; its lender rows remain conditional or rejected. This illustrates why the overall summary and lender-level results must be read together.
- The generated output includes 300 lender-profile evaluations (15 profiles × 20 lenders): 200 `screen_eligible`, 82 `not_eligible`, and 18 `conditional` labels in the saved snapshot. These are counts of model outputs on synthetic profiles, not approval rates or evidence of predictive accuracy.
- A model scorecard may prefer a lender with a higher estimated rate, while the app's eligible-lender list is sorted by estimated rate. The two views answer different ranking questions and should not be treated as a single optimized financial recommendation.

## Conclusion

This project demonstrates how public lender rules can be collected into an evidence-labeled dataset and applied transparently to synthetic applicant profiles. It can explain why an applicant's profile passes, fails, or remains conditional against the rules it knows, and it can compare rough lender-level amount, rate, and tenure estimates. Its practical value is an auditable first-pass comparison—not a substitute for lender underwriting or a confirmed loan offer.
