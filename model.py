"""Personal-loan eligibility waterfall, affordability estimate and scorecard.

Uses lender_rule_matrix.csv in this directory by default. The existing
``evaluate(profile, rules_path, include_estimates)`` interface is retained. This is a
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
from typing import Any

from calculator import monthly_payment as _emi
from calculator import principal_for_payment as _principal_for_emi
from calculator import principal_from_foir
from calculator import principal_from_income_multiple
from calculator import check_loan_amount

DEFAULT_RULES = Path(__file__).with_name("lender_rule_matrix.csv")
# Only rows with these statuses can create a hard rejection by default. Estimates
# and partial/soft statements remain visible in the result and scorecard.
HARD_STATUSES = {"VERIFIED_OFFICIAL"}
OFFICIAL_STATUSES = {"VERIFIED_OFFICIAL", "OFFICIAL_PARTIAL"}
ESTIMATE_STATUSES = {"ESTIMATE_PEER", "ESTIMATE_DERIVED", "THIRD_PARTY_UNVERIFIED", "CONFLICT_RESOLVED"}


def _has_enforceable_rule(rows: list[dict[str, str]], include_estimates: bool) -> bool:
    allowed = HARD_STATUSES | (OFFICIAL_STATUSES | ESTIMATE_STATUSES if include_estimates else set())
    return any(row.get("status") in allowed for row in rows)


def _has_uncertain_rule(rows: list[dict[str, str]]) -> bool:
    return any(row.get("status") in (OFFICIAL_STATUSES | ESTIMATE_STATUSES) - HARD_STATUSES for row in rows)


def _record_failed_check(condition: bool, rows: list[dict[str, str]], message: str,
                         include_estimates: bool, failures: list[str], unknowns: list[str]) -> None:
    if not condition:
        return
    if _has_enforceable_rule(rows, include_estimates):
        failures.append(message)
    elif _has_uncertain_rule(rows):
        unknowns.append(message + " (only partially supported or estimated)")


def _number(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() in {"", "n/a", "na", "none", "not published", "not numerically published"}:
            return None
        return float(str(value).replace(",", "").replace("₹", "").strip())
    except (TypeError, ValueError):
        return None


def load_rules(path: str | Path = DEFAULT_RULES) -> dict[str, list[dict[str, str]]]:
    """Load lender rules from the matrix (or legacy long-format CSV) by lender ID."""
    indexed: dict[str, list[dict[str, str]]] = defaultdict(list)
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        required = {"lender_id", "lender_name", "rule_key", "rule_value", "status"}
        missing = required - headers
        if missing:
            raise ValueError(f"Rules CSV is missing required columns: {sorted(missing)}")
        is_matrix = "record_type" in headers
        if is_matrix and not {"record_type", "source_file"}.issubset(headers):
            raise ValueError("Lender matrix is missing record_type/source_file metadata")
        for row in reader:
            if is_matrix and row.get("record_type") != "lender_rule":
                continue
            if row.get("in_top20", "True").strip().lower() != "false":
                lender_id = (row.get("lender_id") or "").strip()
                if not lender_id:
                    raise ValueError(f"Rule record {row.get('record_id', '')} has no lender_id")
                indexed[lender_id].append(row)
    if not indexed:
        raise ValueError("Rules CSV contains no lender_rule records")
    return dict(indexed)


def load_calculator_evidence(path: str | Path = DEFAULT_RULES) -> dict[str, list[dict[str, str]]]:
    """Load calculator observations/findings as evidence only; never as rule rows."""
    evidence: dict[str, list[dict[str, str]]] = defaultdict(list)
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if "record_type" not in (reader.fieldnames or []):
            return {}
        for row in reader:
            if row.get("record_type") not in {"calculator_observation", "calculator_finding"}:
                continue
            if not row.get("lender_id"):
                continue
            summary = row.get("evidence_summary", "")
            if len(summary) > 240:
                summary = summary[:237] + "..."
            evidence[row["lender_id"]].append({
                "record_id": row.get("record_id", ""),
                "type": row.get("record_type", ""),
                "evidence_status": row.get("evidence_status") or row.get("status", ""),
                "result_type": row.get("calculation_status", ""),
                "rule_or_test": row.get("rule_key") or row.get("source_record_id", ""),
                "value": row.get("rule_value", ""),
                "unit": row.get("rule_unit", ""),
                "source_url": row.get("source_url", ""),
                "accessed_at": row.get("accessed_at", ""),
                "summary": summary,
            })
    return dict(evidence)


def _validate_profile(profile: dict[str, Any]) -> None:
    """Reject malformed supplied values while allowing omitted values to stay unknown."""
    if not isinstance(profile, dict):
        raise ValueError("profile must be a dictionary")
    numeric_fields = {
        "age": 0, "monthly_net_income": 0, "monthly_gross_income": 0,
        "existing_monthly_emi": 0, "credit_score": 0, "current_job_months": 0,
        "total_experience_months": 0, "business_vintage_months": 0,
        "requested_amount": 0, "requested_tenure_months": 1,
    }
    for field, minimum in numeric_fields.items():
        value = profile.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if isinstance(value, bool):
            raise ValueError(f"{field} must be numeric")
        try:
            number = float(str(value).replace(",", "").replace("₹", "").strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be numeric when supplied") from exc
        if not math.isfinite(number) or number < minimum:
            raise ValueError(f"{field} must be finite and at least {minimum}")
        if field.endswith("_months") and not number.is_integer():
            raise ValueError(f"{field} must be a whole number of months")
    if profile.get("employment_type") not in (None, ""):
        emp = str(profile["employment_type"]).strip().casefold().replace("-", "_").replace(" ", "_")
        accepted = {"salaried", "self_employed", "business", "professional"}
        if emp not in accepted:
            raise ValueError("employment_type must be salaried or self_employed")


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
    # Numeric partial/estimated rows may inform a clearly marked scenario
    # estimate. Enforcement is separately controlled by include_estimates.
    usable = [r for r in matches if r.get("status") in OFFICIAL_STATUSES | ESTIMATE_STATUSES]
    values = [(n, r) for r in usable if (n := _number(r.get("rule_value"))) is not None]
    if not values:
        return None, matches
    # Tightest cap/floor is conservative when source segments have ambiguous fit.
    values.sort(key=lambda pair: pair[0], reverse=largest)
    return values[0][0], [r for _, r in values]


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
    nmi_value = _number(profile.get("monthly_net_income"))
    nmi = nmi_value or 0
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
    existing_emi = _number(profile.get("existing_monthly_emi"))
    emi_ratio = (existing_emi / nmi) if nmi > 0 and existing_emi is not None else None
    capacity = (15 if emi_ratio <= .10 else 12 if emi_ratio <= .25 else 8 if emi_ratio <= .40 else 0) if emi_ratio is not None else 0
    score += capacity
    reasons.append(f"existing debt burden: {capacity}/15" if emi_ratio is not None else "existing EMI or income missing: 0/15")
    requested = _number(profile.get("requested_amount"))
    fit = 10 if affordability is not None and requested is not None and affordability >= requested else 0
    score += fit
    reasons.append(f"requested amount fits estimated capacity: {fit}/10")
    return score, reasons


def _rule_evidence(rows: list[dict[str, str]], profile: dict[str, Any]) -> list[dict[str, str]]:
    """Return applicable rule provenance for explaining the lender assessment."""
    result = []
    for row in rows:
        if _segment_match(row.get("segment", "all"), profile) < 0:
            continue
        result.append({key: row.get(key, "") for key in (
            "rule_key", "rule_value", "rule_unit", "segment", "status",
            "source_url", "accessed_at",
        )})
    return result


def evaluate(profile: dict[str, Any], rules_path: str | Path = DEFAULT_RULES,
             include_estimates: bool = False) -> dict[str, Any]:
    """Evaluate a person against matrix rules; estimates are opt-in as constraints."""
    _validate_profile(profile)
    lenders = load_rules(rules_path)
    calculator_evidence = load_calculator_evidence(rules_path)
    employment = _employment(profile)
    age = _number(profile.get("age"))
    nmi = _number(profile.get("monthly_net_income"))
    gross = _number(profile.get("monthly_gross_income"))
    existing_emi = _number(profile.get("existing_monthly_emi"))
    credit = _number(profile.get("credit_score"))
    req_amount = _number(profile.get("requested_amount"))
    req_months = int(_number(profile.get("requested_tenure_months")) or 0)
    outputs = []

    for lender_id, rows in lenders.items():
        name = rows[0].get("lender_name", lender_id)
        failures: list[str] = []
        unknowns: list[str] = []
        if not profile.get("employment_type"):
            unknowns.append("employment_type missing; salaried placeholder used for segment lookup")

        # Waterfall 1: applicant-type gates.
        allowed_rows = _rules_for(rows, "self_employed_allowed", profile)
        allowed_text = " ".join(r.get("rule_value", "").lower() for r in allowed_rows)
        if employment == "self_employed" and not allowed_rows:
            unknowns.append("self_employed_allowed rule unavailable")
        if employment == "self_employed" and any(x in allowed_text for x in ("no", "salaried only", "employees only")):
            _record_failed_check(True, allowed_rows, "self-employed applicants are excluded by the applicable scheme",
                                 include_estimates, failures, unknowns)
        if employment == "self_employed":
            vintage, src = _chosen_number(rows, "min_business_vintage", profile, include_estimates=include_estimates)
            if vintage is not None and _number(profile.get("business_vintage_months")) is not None and _number(profile.get("business_vintage_months")) < vintage:
                if _has_enforceable_rule(src, include_estimates):
                    failures.append(f"business vintage below {vintage:g} months")
            elif vintage is not None and _number(profile.get("business_vintage_months")) is None:
                unknowns.append("business_vintage_months missing")

        # Waterfall 2: age, income, score, and work-history gates.
        minimum, src = _chosen_number(rows, "min_age", profile, include_estimates=include_estimates)
        if minimum is not None and age is not None:
            _record_failed_check(age < minimum, src, f"age below minimum {minimum:g}", include_estimates, failures, unknowns)
        elif minimum is not None and age is None:
            unknowns.append("age missing")
        maximum, src = _chosen_number(rows, "max_age_at_application", profile, include_estimates=include_estimates)
        if maximum is not None and age is not None:
            _record_failed_check(age > maximum, src, f"age above maximum {maximum:g}", include_estimates, failures, unknowns)
        elif maximum is not None and age is None:
            unknowns.append("age missing")
        if age is not None:
            maturity, src = _chosen_number(rows, "max_age_at_maturity", profile, include_estimates=include_estimates)
            if maturity is not None and req_months:
                _record_failed_check(age + req_months / 12 > maturity, src,
                                     f"age at requested maturity exceeds {maturity:g}", include_estimates, failures, unknowns)
            elif maturity is not None and not req_months:
                unknowns.append("requested tenure needed to check age at maturity")
        else:
            maturity, src = _chosen_number(rows, "max_age_at_maturity", profile, include_estimates=include_estimates)
            if maturity is not None:
                unknowns.append("age needed to check maturity limit")

        income_key = "min_net_monthly_income_salaried" if employment == "salaried" else "min_net_monthly_income_self_employed"
        income_floor, src = _chosen_number(rows, income_key, profile, include_estimates=include_estimates)
        if income_floor is not None and nmi is not None:
            _record_failed_check(nmi < income_floor, src, f"net monthly income below {income_floor:g}", include_estimates, failures, unknowns)
        elif income_floor is not None and nmi is None:
            unknowns.append("monthly_net_income missing")

        score_floor, src = _chosen_number(rows, "min_credit_score", profile, include_estimates=include_estimates)
        if score_floor is not None and credit is not None and credit < score_floor:
            _record_failed_check(True, src, f"credit score below recorded minimum {score_floor:g}", include_estimates, failures, unknowns)
        elif score_floor is not None and credit is None:
            unknowns.append("credit_score missing")
        elif credit is None:
            unknowns.append("no credit score supplied; score-linked pricing unavailable")

        for key, field, label in (("min_current_job_tenure", "current_job_months", "current job tenure"),
                                  ("min_total_experience", "total_experience_months", "total work experience")):
            threshold, src = _chosen_number(rows, key, profile, include_estimates=include_estimates)
            val = _number(profile.get(field))
            if threshold is not None and val is not None:
                _record_failed_check(val < threshold, src, f"{label} below {threshold:g} months", include_estimates, failures, unknowns)
            elif threshold is not None and val is None:
                unknowns.append(f"{field} missing")

        # Waterfall 3: derive maximum principal from product, salary-multiple,
        # FOIR and EMI affordability caps. Only sourced rules are hard by default.
        max_loan, src = _chosen_number(rows, "max_loan_amount", profile, largest=False, include_estimates=include_estimates)
        cap = max_loan
        cap_rule_rows = list(src)
        cap_sources = []
        if max_loan is not None:
            cap_sources.append("maximum loan amount")
        multiple, mult_src = _chosen_number(rows, "max_income_multiple", profile, include_estimates=include_estimates)
        multiple_basis = gross if any("gross" in r.get("rule_unit", "").lower() or "gross" in r.get("supporting_passage", "").lower() for r in mult_src) else nmi
        if multiple is not None and multiple_basis is not None:
            multiple_cap = principal_from_income_multiple(multiple_basis, multiple)
            if cap is None or multiple_cap < cap:
                cap = multiple_cap
                cap_rule_rows = list(mult_src)
            elif multiple_cap == cap:
                cap_rule_rows.extend(mult_src)
            cap_sources.append("income multiple")
        elif multiple is not None:
            unknowns.append("income required to apply maximum income multiple")
        foir, foir_src = _chosen_number(rows, "max_foir", profile, include_estimates=include_estimates)
        income_basis = gross if any("gross" in r.get("rule_unit", "").lower() or "gross" in r.get("supporting_passage", "").lower() for r in foir_src) else nmi
        rate_for_cap, rate_cap_src = _chosen_number(rows, "rate_max", profile, largest=True, include_estimates=include_estimates)
        foir_cap = principal_from_foir(income_basis, existing_emi, foir, rate_for_cap, req_months or None)
        if foir_cap is not None:
            if cap is None or foir_cap < cap:
                cap = foir_cap
                cap_rule_rows = list(foir_src) + list(rate_cap_src)
            elif foir_cap == cap:
                cap_rule_rows.extend(foir_src)
                cap_rule_rows.extend(rate_cap_src)
            cap_sources.append("FOIR affordability")
        elif foir is not None:
            missing_foir_inputs = []
            if income_basis is None:
                missing_foir_inputs.append("income")
            if existing_emi is None:
                missing_foir_inputs.append("existing EMI")
            if not req_months:
                missing_foir_inputs.append("requested tenure")
            if rate_for_cap is None:
                missing_foir_inputs.append("usable lender rate")
            unknowns.append("FOIR principal estimate unavailable; missing " + ", ".join(missing_foir_inputs))

        min_amount, min_src = _chosen_number(rows, "min_loan_amount", profile, include_estimates=include_estimates)
        if req_amount is None and (min_amount is not None or max_loan is not None or multiple is not None or foir is not None):
            unknowns.append("requested_amount missing")
        if req_amount is not None:
            amount_check = check_loan_amount(req_amount, min_amount, max_loan)
            if "below_minimum" in amount_check["failures"]:
                _record_failed_check(True, min_src, f"requested amount below product minimum {min_amount:g}", include_estimates, failures, unknowns)
        if cap is not None and req_amount is not None:
            _record_failed_check(req_amount > cap, cap_rule_rows,
                                 f"requested amount exceeds estimated capacity ₹{cap:,.0f}", include_estimates, failures, unknowns)

        min_tenure, min_tsrc = _chosen_number(rows, "min_tenure", profile, include_estimates=include_estimates)
        max_tenure, max_tsrc = _chosen_number(rows, "max_tenure", profile, include_estimates=include_estimates)
        if req_months:
            if min_tenure is not None:
                _record_failed_check(req_months < min_tenure, min_tsrc, f"requested tenure below minimum {min_tenure:g} months", include_estimates, failures, unknowns)
            if max_tenure is not None:
                _record_failed_check(req_months > max_tenure, max_tsrc, f"requested tenure exceeds maximum {max_tenure:g} months", include_estimates, failures, unknowns)
        elif min_tenure is not None or max_tenure is not None:
            unknowns.append("requested_tenure_months missing")

        # Price range and score band. Endpoints may be estimated; return provenance.
        rate_low, low_rows = _chosen_number(rows, "rate_min", profile, include_estimates=True)
        rate_high, high_rows = _chosen_number(rows, "rate_max", profile, include_estimates=True, largest=True)
        if rate_low is not None and rate_high is None:
            rate_high = rate_low
        if rate_high is not None and rate_low is None:
            rate_low = rate_high
        lender_score, score_reasons = _score_lender(profile, rows, cap, include_estimates)
        all_calculator_evidence = calculator_evidence.get(lender_id, [])
        calculator_examples = (
            [item for item in all_calculator_evidence if item["type"] == "calculator_finding"][:1]
            + [item for item in all_calculator_evidence if item["type"] == "calculator_observation"][:2]
        )
        if credit is not None and rate_low is not None and rate_high is not None:
            band, expected_rate = _rate_tier(credit, rate_low, rate_high)
        else:
            band, expected_rate = "unavailable", None
        estimated_emi = _emi(req_amount, expected_rate, req_months) if not failures and expected_rate is not None and req_amount is not None and req_amount > 0 and req_months > 0 else None
        has_calculated_capacity = any(source in cap_sources for source in ("income multiple", "FOIR affordability"))
        capacity_estimate = round(cap) if not failures and has_calculated_capacity and cap is not None else None

        if failures:
            decision = "not_eligible"
        elif unknowns:
            decision = "conditional"
        else:
            decision = "screen_eligible"
        outputs.append({
            "lender_id": lender_id, "lender": name, "decision": decision,
            "reasons": failures, "unknowns": sorted(set(unknowns)),
            "max_loan_amount_estimate": capacity_estimate,
            "published_product_max_loan_amount": round(max_loan) if max_loan is not None else None,
            "capacity_is_estimated": has_calculated_capacity and any(
                row.get("status") != "VERIFIED_OFFICIAL" for row in cap_rule_rows
            ),
            "capacity_limited_by": cap_sources,
            "rate_band": band, "expected_rate_percent_pa": round(expected_rate, 2) if expected_rate is not None else None,
            "rate_is_estimated": expected_rate is not None,
            "rate_source_statuses": sorted({r.get("status", "") for r in low_rows + high_rows}),
            "tenure_months": {"min": int(min_tenure) if min_tenure is not None else None,
                              "max": int(max_tenure) if max_tenure is not None else None},
            "estimated_emi": round(estimated_emi) if estimated_emi is not None else None,
            "scorecard": {"score": lender_score, "out_of": 100, "components": score_reasons},
            "rule_estimates_included_as_constraints": include_estimates,
            "rule_evidence": _rule_evidence(rows, profile),
            "calculator_evidence_count": len(all_calculator_evidence),
            "calculator_evidence_examples": calculator_examples,
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
                "Score bands and rate interpolation are model assumptions; estimated rates are not personalized lender quotes.",
                "Calculator observations are evidence only and never become eligibility thresholds.",
                "A capacity estimate requires an applicable income multiple or a complete FOIR calculation; missing parameters remain unknown."
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
