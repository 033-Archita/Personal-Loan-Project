"""Reusable, lender-agnostic loan calculations with strict input validation.

Lender-specific rates, FOIR limits, and loan limits belong in the lender-rule
data. Missing lender parameters remain unknown; this module supplies no defaults.
All rates are annual percentages and all payments/principals are INR.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any


def _finite_number(value: Any, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number, not a boolean")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return number


def _months(value: Any) -> int:
    number = _finite_number(value, "months", minimum=1)
    if not number.is_integer():
        raise ValueError("months must be a whole number")
    return int(number)


def monthly_payment(principal: float, annual_rate_percent: float, months: int) -> float:
    """Return the fixed monthly EMI for a standard monthly reducing-balance loan."""
    amount = _finite_number(principal, "principal", minimum=0)
    rate = _finite_number(annual_rate_percent, "annual_rate_percent", minimum=0)
    term = _months(months)
    if amount == 0:
        return 0.0
    monthly_rate = rate / 1200.0
    if monthly_rate == 0:
        return amount / term
    growth = (1.0 + monthly_rate) ** term
    return amount * monthly_rate * growth / (growth - 1.0)


def principal_for_payment(monthly_payment_amount: float, annual_rate_percent: float, months: int) -> float:
    """Return the principal supported by a monthly payment, rate, and term."""
    payment = _finite_number(monthly_payment_amount, "monthly_payment_amount", minimum=0)
    rate = _finite_number(annual_rate_percent, "annual_rate_percent", minimum=0)
    term = _months(months)
    monthly_rate = rate / 1200.0
    if monthly_rate == 0:
        return payment * term
    return payment * (1.0 - (1.0 + monthly_rate) ** -term) / monthly_rate


def emi_capacity(income: float, existing_emi: float, foir_percent: float) -> float:
    """Return remaining monthly EMI capacity under a supplied FOIR percentage."""
    monthly_income = _finite_number(income, "income", minimum=0)
    current_emi = _finite_number(existing_emi, "existing_emi", minimum=0)
    foir = _finite_number(foir_percent, "foir_percent", minimum=0)
    if foir > 100:
        raise ValueError("foir_percent cannot exceed 100")
    return max(0.0, monthly_income * foir / 100.0 - current_emi)


def principal_from_foir(
    income: float | None,
    existing_emi: float | None,
    foir_percent: float | None,
    annual_rate_percent: float | None,
    months: int | None,
) -> float | None:
    """Return FOIR-supported principal, or ``None`` if any lender parameter is unknown."""
    if any(value is None for value in (income, existing_emi, foir_percent, annual_rate_percent, months)):
        return None
    room = emi_capacity(income, existing_emi, foir_percent)
    return principal_for_payment(room, annual_rate_percent, months)


def principal_from_income_multiple(monthly_income: float | None, multiple: float | None) -> float | None:
    """Return a salary-multiple cap when both lender parameters are available."""
    if monthly_income is None or multiple is None:
        return None
    income = _finite_number(monthly_income, "monthly_income", minimum=0)
    factor = _finite_number(multiple, "multiple", minimum=0)
    return income * factor


def check_loan_amount(
    amount: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> dict[str, Any]:
    """Check requested principal against available lender limits without guessing missing limits."""
    requested = _finite_number(amount, "amount", minimum=0)
    lower = _finite_number(minimum, "minimum", minimum=0) if minimum is not None else None
    upper = _finite_number(maximum, "maximum", minimum=0) if maximum is not None else None
    if lower is not None and upper is not None and lower > upper:
        raise ValueError("minimum cannot exceed maximum")
    failures = []
    if lower is not None and requested < lower:
        failures.append("below_minimum")
    if upper is not None and requested > upper:
        failures.append("above_maximum")
    return {
        "status": "outside_limits" if failures else "within_known_limits" if lower is not None or upper is not None else "unknown",
        "failures": failures,
        "minimum": lower,
        "maximum": upper,
    }


def calculate_scenarios(
    principal: float,
    annual_rates_percent: Iterable[float],
    tenures_months: Iterable[int],
) -> list[dict[str, float | int]]:
    """Calculate EMI scenarios for explicit rates and terms supplied by the caller."""
    amount = _finite_number(principal, "principal", minimum=0)
    scenarios = []
    rates = list(annual_rates_percent)
    terms = list(tenures_months)
    for rate in rates:
        for term in terms:
            scenarios.append({
                "principal": amount,
                "annual_rate_percent": _finite_number(rate, "annual_rate_percent", minimum=0),
                "months": _months(term),
                "monthly_payment": monthly_payment(amount, rate, term),
            })
    return scenarios

