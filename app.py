"""Simple Streamlit viewer for the saved personal-loan screening results."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from data import INPUT_CSV, OUTPUT_CSV, create_files


st.set_page_config(page_title="Personal Loan Match", page_icon="₹", layout="centered")

if not INPUT_CSV.exists() or not OUTPUT_CSV.exists():
    create_files()

profiles = pd.read_csv(INPUT_CSV, keep_default_na=False)
outputs = pd.read_csv(OUTPUT_CSV, keep_default_na=False)

st.title("Personal loan match")
st.caption("A first-pass comparison using the project's public lender-rule dataset.")

profile = st.selectbox(
    "Sample applicant",
    profiles.to_dict("records"),
    format_func=lambda row: f"{row['profile_id']} · {row['edge_case']}",
)
saved = outputs.loc[outputs["profile_id"] == profile["profile_id"]]
if saved.empty:
    st.info("Run `python data.py` to refresh the sample results.")
    st.stop()

result = saved.iloc[0]
lenders = json.loads(result["lender_results_json"])
screened = [row for row in lenders if row["decision"] == "screen_eligible"]
conditional = [row for row in lenders if row["decision"] == "conditional"]

def rate_value(row: dict) -> float:
    rate = row.get("expected_rate_percent_pa")
    return float(rate) if rate is not None else float("inf")

def capacity_label(value: object) -> str:
    """Render absent or non-positive capacity as a dash."""
    if value in (None, "") or float(value) <= 0:
        return "—"
    return f"₹{float(value):,.0f}"

screened.sort(key=rate_value)
conditional.sort(key=rate_value)

if screened:
    best = screened[0]
    st.success(f"{len(screened)} lender(s) match the available screening rules")
    st.subheader(best["lender"])
    col1, col2, col3 = st.columns(3)
    rate = best.get("expected_rate_percent_pa")
    amount = best.get("max_loan_amount_estimate")
    tenure = best.get("tenure_months") or {}
    col1.metric("Expected rate", f"{rate:.2f}% p.a." if rate is not None else "—")
    col2.metric("Estimated capacity", capacity_label(amount))
    col3.metric("Tenure", f"{tenure['min']}–{tenure['max']} months" if tenure.get("min") is not None and tenure.get("max") is not None else "—")
elif conditional:
    best = conditional[0]
    st.info(f"{best['lender']} is a potential match; some profile or lender details need review.")
else:
    st.info("This profile is outside the recorded lender criteria. Review the profile or dataset rules for more options.")

st.subheader("Lender options")
ordered = screened + conditional
rows = []
for lender in ordered:
    amount = lender.get("max_loan_amount_estimate")
    rate = lender.get("expected_rate_percent_pa")
    term = lender.get("tenure_months") or {}
    rows.append({
        "Lender": lender["lender"],
        "Screen": "Matches" if lender["decision"] == "screen_eligible" else "Review",
        "Expected rate": f"{rate:.2f}%" if rate is not None else "—",
        "Estimated capacity": capacity_label(amount),
        "Tenure": f"{term['min']}–{term['max']} mo" if term.get("min") is not None and term.get("max") is not None else "—",
    })
if rows:
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
else:
    st.write("No lender matches are available for this sample profile.")

with st.expander("Applicant summary"):
    score = profile.get("credit_score") or "Not supplied"
    st.write(
        f"**Age:** {profile['age']} · **Employment:** {profile['employment_type'].replace('_', ' ')} · "
        f"**Monthly net income:** ₹{int(float(profile['monthly_net_income'])):,} · "
        f"**Existing EMIs:** ₹{int(float(profile['existing_monthly_emi'])):,} · "
        f"**Credit score:** {score} · **Requested amount:** ₹{int(float(profile['requested_amount'])):,}"
    )

st.caption("Rates and capacities are model estimates. Final terms are determined by each lender's assessment.")
