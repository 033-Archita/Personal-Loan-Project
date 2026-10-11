"""Personal-loan eligibility waterfall, affordability estimate and scorecard.

Uses lender_rules.csv in this directory by default. This is a
transparent screening model, not a lender approval or a credit decision.

Example profile (call ``evaluate(profile)`` from Python):
    {
      "age": 32, "employment_type": "salaried", "monthly_net_income": 80000,
      "monthly_gross_income": 95000, "existing_monthly_emi": 10000,
      "credit_score": 760, "current_job_months": 36,
      "total_experience_months": 72, "requested_amount": 800000,
      "requested_tenure_months": 48, "employer_category": "private",
      "salary_account_lender": "L01", "city_type": "metro"
    }

Run directly: python model.py profile.json [--rules path/to/rules.csv]
The JSON profile is read as input; the script writes a JSON result to stdout.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


DEFAULT_RULES = Path(__file__).with_name("lender_rules.csv")
# Only rows with these statuses can create a hard rejection by default. Estimates
# and partial/soft statements remain visible in the result and scorecard.
HARD_STATUSES = {"VERIFIED_OFFICIAL"}
OFFICIAL_STATUSES = {"VERIFIED_OFFICIAL", "OFFICIAL_PARTIAL"}


def _number(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() in {"", "n/a", "na", "none", "not published", "not numerically published"}:
            return None
        return float(str(value).replace(",", "").replace("₹", "").strip())
    except (TypeError, ValueError):
        return None


def load_rules(path: str | Path = DEFAULT_RULES) -> dict[str, list[dict[str, str]]]:
    """Load the flat lender rule CSV and index its rows by lender id."""
    indexed: dict[str, list[dict[str, str]]] = defaultdict(list)
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("in_top20", "True").strip().lower() != "false":
                indexed[row["lender_id"]].append(row)
    return dict(indexed)


def _employment(profile: dict[str, Any]) -> str:
    value = str(profile.get("employment_type", "salaried")).lower().replace("-", "_")
    if value in {"self_employed", "self employed", "business", "professional"}:
        return "self_employed"
    return "salaried"


def _segment_match(segment: str, profile: dict[str, Any]) -> int:
    """Return a specificity score; -1 means the segment does not apply."""
    s = (segment or "all").strip().lower()
    if s in {"", "all", "n/a", "not applicable"}:
        return 0
    emp = _employment(profile)
    employer = str(profile.get("employer_category", "")).lower()
    job_months = _number(profile.get("current_job_months"))
    salary_lender = str(profile.get("salary_account_lender", "")).lower()
    checks: list[tuple[tuple[str, ...], bool]] = [
        (("self-employed", "self employed", "non-salaried", "professionals/self-employed"), emp == "self_employed"),
        (("salaried", "employees", "permanent employees", "corporate", "government/defence", "govt/defence"), emp == "salaried"),
        (("govt", "government", "psu", "public sector", "defence"), any(x in employer for x in ("gov", "psu", "public", "defence"))),
        (("private", "corporate", "mnc", "rated corporate"), any(x in employer for x in ("private", "corporate", "mnc", "rated"))),
        (("boB salary account", "bob salary account"), "l02" in salary_lender or "baroda" in salary_lender),
        (("other-bank salary account", "other bank salary account"), bool(salary_lender) and "l02" not in salary_lender and "baroda" not in salary_lender),
        (("low income",), (_number(profile.get("monthly_net_income")) or 0) < 50000),
        (("high income",), (_number(profile.get("monthly_net_income")) or 0) >= 50000),
        (("metro",), str(profile.get("city_type", "")).lower() == "metro"),
        (("rural", "semi-urban", "semi urban"), str(profile.get("city_type", "")).lower() in {"rural", "semi_urban", "semi-urban"}),
    ]
    matched_specific = False
    for tokens, condition in checks:
        if any(token.lower() in s for token in tokens):
            if not condition:
                return -1
            matched_specific = True
    if any(x in s for x in ("salaried only", "employees only")) and emp != "salaried":
        return -1
    if any(x in s for x in ("self-employed only", "self employed only")) and emp != "self_employed":
        return -1
    # Unknown segment descriptors are not assumed to apply to this applicant.
    known = any(word in s for word in ("salaried", "employee", "corporate", "government", "govt", "psu", "defence", "self", "non-salaried", "professional", "income", "account", "metro", "rural", "urban", "all", "n/a"))
    if not known:
        return -1
    return 2 if matched_specific else 0


def _rules_for(rows: list[dict[str, str]], key: str, profile: dict[str, Any]) -> list[dict[str, str]]:
    candidates = []
    for row in rows:
        if row.get("rule_key") != key:
            continue
        score = _segment_match(row.get("segment", "all"), profile)
        if score >= 0:
            candidates.append((score, row))
    if not candidates:
        return []
    best = max(score for score, _ in candidates)
    # Preserve multiple equally specific bands where the CSV intentionally has
    # multiple values; numerical constraints choose the conservative bound below.
    return [row for score, row in candidates if score == best]


def _chosen_number(rows: list[dict[str, str]], key: str, profile: dict[str, Any], *, largest: bool = False,
                   include_estimates: bool = False) -> tuple[float | None, list[dict[str, str]]]:
    matches = _rules_for(rows, key, profile)
    usable = [r for r in matches if r.get("status") in OFFICIAL_STATUSES or include_estimates]
    values = [(n, r) for r in usable if (n := _number(r.get("rule_value"))) is not None]
    if not values:
        return None, matches
    # Tightest cap/floor is conservative when source segments have ambiguous fit.
    values.sort(key=lambda pair: pair[0], reverse=largest)
    return values[0][0], [r for _, r in values]


def _emi(principal: float, annual_rate: float, months: int) -> float:
    monthly = annual_rate / 1200.0
    if months <= 0:
        return math.inf
    if monthly == 0:
        return principal / months
    factor = (1 + monthly) ** months
    return principal * monthly * factor / (factor - 1)


def _principal_for_emi(emi: float, annual_rate: float, months: int) -> float:
    if emi <= 0 or months <= 0:
        return 0.0
    monthly = annual_rate / 1200.0
    if monthly == 0:
        return emi * months
    return emi * (1 - (1 + monthly) ** -months) / monthly


def _rate_tier(score: float, low: float, high: float) -> tuple[str, float]:
    """Transparent score bands mapped across the CSV published/estimated range."""
    if score >= 800:
        band, fraction = "A (800+)", 0.10
    elif score >= 750:
        band, fraction = "B (750-799)", 0.25
    elif score >= 700:
        band, fraction = "C (700-749)", 0.55
    elif score >= 650:
        band, fraction = "D (650-699)", 0.85
    else:
        band, fraction = "E (<650)", 1.0
    return band, low + (high - low) * fraction


def _score_lender(profile: dict[str, Any], lender_rows: list[dict[str, str]],
                  affordability: float | None, include_estimates: bool) -> tuple[int, list[str]]:
    """100-point prioritization score; this never overrides a failed rule."""
    score = 0
    reasons: list[str] = []
    credit = _number(profile.get("credit_score"))
    if credit is not None:
        points = 30 if credit >= 800 else 26 if credit >= 750 else 19 if credit >= 700 else 10 if credit >= 650 else 0
        score += points
        reasons.append(f"credit score: {points}/30")
    else:
        reasons.append("credit score missing: 0/30")
    nmi = _number(profile.get("monthly_net_income")) or 0
    income_floor, _ = _chosen_number(lender_rows, "min_net_monthly_income_salaried" if _employment(profile) == "salaried" else "min_net_monthly_income_self_employed", profile, include_estimates=include_estimates)
    floor = income_floor or 25000
    income_points = 25 if nmi >= 2 * floor else 20 if nmi >= 1.5 * floor else 14 if nmi >= floor else 0
    score += income_points
    reasons.append(f"income headroom: {income_points}/25")
    job_months = _number(profile.get("current_job_months"))
    experience = _number(profile.get("total_experience_months"))
    stability = 20 if (job_months or 0) >= 36 and (experience or 0) >= 60 else 16 if (job_months or 0) >= 12 and (experience or 0) >= 24 else 10 if (job_months or 0) >= 6 else 0
    score += stability
    reasons.append(f"employment stability: {stability}/20")
    emi_ratio = ((_number(profile.get("existing_monthly_emi")) or 0) / nmi) if nmi > 0 else 1.0
    capacity = 15 if emi_ratio <= .10 else 12 if emi_ratio <= .25 else 8 if emi_ratio <= .40 else 0
    score += capacity
    reasons.append(f"existing debt burden: {capacity}/15")
    fit = 10 if affordability is None or affordability >= (_number(profile.get("requested_amount")) or 0) else 0
    score += fit
    reasons.append(f"requested amount fits estimated capacity: {fit}/10")
    return score, reasons


def evaluate(profile: dict[str, Any], rules_path: str | Path = DEFAULT_RULES,
             include_estimates: bool = False) -> dict[str, Any]:
    """Evaluate a person across lender rows. Estimated rows are opt-in."""
    lenders = load_rules(rules_path)
    employment = _employment(profile)
    age = _number(profile.get("age"))
    nmi = _number(profile.get("monthly_net_income"))
    gross = _number(profile.get("monthly_gross_income"))
    existing_emi = _number(profile.get("existing_monthly_emi")) or 0.0
    credit = _number(profile.get("credit_score"))
    req_amount = _number(profile.get("requested_amount")) or 0.0
    req_months = int(_number(profile.get("requested_tenure_months")) or 0)
    outputs = []

    for lender_id, rows in lenders.items():
        name = rows[0].get("lender_name", lender_id)
        failures: list[str] = []
        unknowns: list[str] = []
        evidence: list[str] = []

        # Waterfall 1: applicant-type gates.
        allowed_rows = _rules_for(rows, "self_employed_allowed", profile)
        allowed_text = " ".join(r.get("rule_value", "").lower() for r in allowed_rows)
        if employment == "self_employed" and any(x in allowed_text for x in ("no", "salaried only", "employees only")):
            if any(r.get("status") in HARD_STATUSES for r in allowed_rows):
                failures.append("self-employed applicants are excluded by the published scheme")
        if employment == "self_employed":
            vintage, src = _chosen_number(rows, "min_business_vintage", profile, include_estimates=include_estimates)
            if vintage is not None and _number(profile.get("business_vintage_months")) is not None and _number(profile.get("business_vintage_months")) < vintage:
                if any(r.get("status") in HARD_STATUSES for r in src):
                    failures.append(f"business vintage below {vintage:g} months")
            elif vintage is not None and _number(profile.get("business_vintage_months")) is None:
                unknowns.append("business_vintage_months missing")

        # Waterfall 2: age, income, score, and work-history gates.
        minimum, src = _chosen_number(rows, "min_age", profile, include_estimates=include_estimates)
        if minimum is not None and age is not None and age < minimum and any(r.get("status") in HARD_STATUSES for r in src):
            failures.append(f"age below minimum {minimum:g}")
        elif minimum is not None and age is None:
            unknowns.append("age missing")
        maximum, src = _chosen_number(rows, "max_age_at_application", profile, include_estimates=include_estimates)
        if maximum is not None and age is not None and age > maximum and any(r.get("status") in HARD_STATUSES for r in src):
            failures.append(f"age above maximum {maximum:g}")
        if age is not None:
            maturity, src = _chosen_number(rows, "max_age_at_maturity", profile, include_estimates=include_estimates)
            if maturity is not None and req_months and age + req_months / 12 > maturity and any(r.get("status") in HARD_STATUSES for r in src):
                failures.append(f"age at requested maturity exceeds {maturity:g}")

        income_key = "min_net_monthly_income_salaried" if employment == "salaried" else "min_net_monthly_income_self_employed"
        income_floor, src = _chosen_number(rows, income_key, profile, include_estimates=include_estimates)
        if income_floor is not None and nmi is not None and nmi < income_floor and any(r.get("status") in HARD_STATUSES for r in src):
            failures.append(f"net monthly income below {income_floor:g}")
        elif income_floor is not None and nmi is None:
            unknowns.append("monthly_net_income missing")

        score_floor, src = _chosen_number(rows, "min_credit_score", profile, include_estimates=include_estimates)
        hard_score_floor = score_floor if any(r.get("status") in HARD_STATUSES for r in src) else None
        if hard_score_floor is not None and credit is not None and credit < hard_score_floor:
            failures.append(f"credit score below published minimum {hard_score_floor:g}")
        elif hard_score_floor is not None and credit is None:
            unknowns.append("credit_score missing")
        elif credit is None:
            unknowns.append("no credit score supplied; score-linked pricing unavailable")

        for key, field, label in (("min_current_job_tenure", "current_job_months", "current job tenure"),
                                  ("min_total_experience", "total_experience_months", "total work experience")):
            threshold, src = _chosen_number(rows, key, profile, include_estimates=include_estimates)
            val = _number(profile.get(field))
            if threshold is not None and val is not None and val < threshold and any(r.get("status") in HARD_STATUSES for r in src):
                failures.append(f"{label} below {threshold:g} months")
            elif threshold is not None and val is None:
                unknowns.append(f"{field} missing")

        # Waterfall 3: derive maximum principal from product, salary-multiple,
        # FOIR and EMI affordability caps. Only sourced rules are hard by default.
        max_loan, src = _chosen_number(rows, "max_loan_amount", profile, largest=False, include_estimates=include_estimates)
        cap = max_loan
        cap_sources = []
        if max_loan is not None:
            cap_sources.append("maximum loan amount")
        multiple, mult_src = _chosen_number(rows, "max_income_multiple", profile, include_estimates=include_estimates)
        if multiple is not None and nmi is not None:
            multiple_cap = multiple * nmi
            cap = min(cap, multiple_cap) if cap is not None else multiple_cap
            cap_sources.append("income multiple")
        foir, foir_src = _chosen_number(rows, "max_foir", profile, include_estimates=include_estimates)
        income_basis = gross if any("gross" in r.get("rule_unit", "").lower() or "gross" in r.get("supporting_passage", "").lower() for r in foir_src) else nmi
        if foir is not None and income_basis is not None and req_months > 0:
            emi_room = max(0.0, income_basis * foir / 100.0 - existing_emi)
            rate_for_cap, _ = _chosen_number(rows, "rate_max", profile, largest=True, include_estimates=include_estimates)
            rate_for_cap = rate_for_cap or 30.0
            foir_cap = _principal_for_emi(emi_room, rate_for_cap, req_months)
            cap = min(cap, foir_cap) if cap is not None else foir_cap
            cap_sources.append("FOIR affordability")
        elif foir is not None:
            unknowns.append("income/tenure needed to apply FOIR")

        min_amount, min_src = _chosen_number(rows, "min_loan_amount", profile, include_estimates=include_estimates)
        if req_amount and min_amount is not None and req_amount < min_amount and any(r.get("status") in HARD_STATUSES for r in min_src):
            failures.append(f"requested amount below product minimum {min_amount:g}")
        if cap is not None and req_amount > cap and any(r.get("status") in HARD_STATUSES for r in (src + mult_src + foir_src)):
            failures.append(f"requested amount exceeds estimated capacity ₹{cap:,.0f}")

        min_tenure, min_tsrc = _chosen_number(rows, "min_tenure", profile, include_estimates=include_estimates)
        max_tenure, max_tsrc = _chosen_number(rows, "max_tenure", profile, include_estimates=include_estimates)
        if req_months:
            if min_tenure is not None and req_months < min_tenure and any(r.get("status") in HARD_STATUSES for r in min_tsrc):
                failures.append(f"requested tenure below minimum {min_tenure:g} months")
            if max_tenure is not None and req_months > max_tenure and any(r.get("status") in HARD_STATUSES for r in max_tsrc):
                failures.append(f"requested tenure exceeds maximum {max_tenure:g} months")

        # Price range and score band. Endpoints may be estimated; return provenance.
        rate_low, low_rows = _chosen_number(rows, "rate_min", profile, include_estimates=True)
        rate_high, high_rows = _chosen_number(rows, "rate_max", profile, include_estimates=True, largest=True)
        if rate_low is not None and rate_high is None:
            rate_high = rate_low
        if rate_high is not None and rate_low is None:
            rate_low = rate_high
        lender_score, score_reasons = _score_lender(profile, rows, cap, include_estimates)
        if credit is not None and rate_low is not None and rate_high is not None:
            band, expected_rate = _rate_tier(credit, rate_low, rate_high)
        else:
            band, expected_rate = "unavailable", None
        estimated_emi = _emi(req_amount, expected_rate, req_months) if expected_rate is not None and req_amount > 0 and req_months > 0 else None

        if failures:
            decision = "not_eligible"
        elif unknowns:
            decision = "conditional"
        else:
            decision = "screen_eligible"
        outputs.append({
            "lender_id": lender_id, "lender": name, "decision": decision,
            "reasons": failures, "unknowns": sorted(set(unknowns)),
            "max_loan_amount_estimate": round(cap) if cap is not None else None,
            "capacity_limited_by": cap_sources,
            "rate_band": band, "expected_rate_percent_pa": round(expected_rate, 2) if expected_rate is not None else None,
            "rate_is_estimated": any(r.get("status") not in OFFICIAL_STATUSES for r in low_rows + high_rows),
            "tenure_months": {"min": int(min_tenure) if min_tenure is not None else None,
                              "max": int(max_tenure) if max_tenure is not None else None},
            "estimated_emi": round(estimated_emi) if estimated_emi is not None else None,
            "scorecard": {"score": lender_score, "out_of": 100, "components": score_reasons},
            "rule_estimates_included_as_constraints": include_estimates,
        })

    outputs.sort(key=lambda x: (x["decision"] == "not_eligible", x["decision"] == "conditional",
                                -(x["scorecard"]["score"]), x["expected_rate_percent_pa"] or 9999))
    viable = [x for x in outputs if x["decision"] != "not_eligible"]
    best = viable[0] if viable else None
    if nmi is not None and nmi > 0 and credit is not None:
        overall = "eligible_for_at_least_one_lender" if any(x["decision"] == "screen_eligible" for x in viable) else "conditional_or_no_match"
    else:
        overall = "insufficient_profile_data"
    return {"overall_decision": overall, "profile": {"employment_type": employment},
            "best_option": best, "lenders": outputs,
            "model_notes": [
                "Screening results are estimates, not lender approvals.",
                "Only VERIFIED_OFFICIAL numeric rules create hard rejections by default; partial/estimated facts are shown as uncertainty.",
                "Set include_estimates=True to apply inferred CSV thresholds as constraints.",
                "Score bands are model assumptions: >=800, 750-799, 700-749, 650-699, <650; rates interpolate within each lender's CSV range.",
                "A maximum loan estimate is capped by available product, income-multiple, and FOIR rules; unknown rules cannot safely be treated as passes."
            ]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", help="Path to applicant profile JSON")
    parser.add_argument("--rules", default=str(DEFAULT_RULES), help="Lender rules CSV path")
    parser.add_argument("--include-estimates", action="store_true", help="Apply inferred rules as constraints")
    args = parser.parse_args()
    with Path(args.profile).open("r", encoding="utf-8") as handle:
        profile = json.load(handle)
    print(json.dumps(evaluate(profile, args.rules, args.include_estimates), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
