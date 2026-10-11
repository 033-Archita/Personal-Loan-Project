"""Focused Streamlit view of profile screening results. Launch: streamlit run app.py"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from outputs.data import INPUT_CSV, OUTPUT_CSV, create_files


st.set_page_config(page_title="Personal Loan Match", page_icon="₹", layout="wide")

if not INPUT_CSV.exists() or not OUTPUT_CSV.exists():
    create_files()

profiles = pd.read_csv(INPUT_CSV, keep_default_na=False)
outputs = pd.read_csv(OUTPUT_CSV, keep_default_na=False)

st.title("Personal loan match")
st.caption("A quick screening against the lender rules in this project. Results are estimates, not approvals.")

with st.sidebar:
    st.header("Applicant")
    chosen = st.selectbox(
        "Choose a profile",
        profiles.to_dict("records"),
        format_func=lambda row: f"{row['profile_id']} · {row['edge_case']}",
        label_visibility="collapsed",
    )

profile = chosen
result_row = outputs.loc[outputs.profile_id == profile["profile_id"]].iloc[0]
lender_rows = json.loads(result_row["lender_results_json"])
eligible = [row for row in lender_rows if row["decision"] == "screen_eligible"]
conditional = [row for row in lender_rows if row["decision"] == "conditional"]
eligible.sort(key=lambda row: (row["expected_rate_percent_pa"] or 999, -row["scorecard"]["score"]))
conditional.sort(key=lambda row: (row["expected_rate_percent_pa"] or 999, -row["scorecard"]["score"]))

if eligible:
    best = eligible[0]
    st.success(f"{len(eligible)} lenders pass the available screening rules")
elif conditional:
    best = conditional[0]
    st.warning("No firm match from the available rules. Some lenders need more information.")
else:
    best = None
    st.error("No lender passed the available screening rules for this profile.")

if best:
    st.subheader("Best current match")
    st.markdown(f"### {best['lender']}")
    a, b, c, d = st.columns(4)
    a.metric("Estimated rate", f"{best['expected_rate_percent_pa']:.2f}% p.a." if best["expected_rate_percent_pa"] is not None else "Unavailable")
    amount = best["max_loan_amount_estimate"]
    b.metric("Estimated maximum", f"₹{amount:,.0f}" if amount is not None else "Unavailable")
    tenure_max = best["tenure_months"]["max"]
    c.metric("Maximum tenure", f"{tenure_max} months" if tenure_max is not None else "Unavailable")
    d.metric("Model score", f"{best['scorecard']['score']} / 100")

st.subheader("Other matching lenders")
if eligible:
    offer_rows = []
    for row in eligible[:5]:
        offer_rows.append({
            "Lender": row["lender"],
            "Estimated rate": f"{row['expected_rate_percent_pa']:.2f}%" if row["expected_rate_percent_pa"] is not None else "—",
            "Max loan estimate": f"₹{row['max_loan_amount_estimate']:,.0f}" if row["max_loan_amount_estimate"] is not None else "—",
            "Max tenure": f"{row['tenure_months']['max']} mo" if row["tenure_months"]["max"] is not None else "—",
        })
    st.dataframe(pd.DataFrame(offer_rows), width="stretch", hide_index=True)
    if len(eligible) > 5:
        st.caption(f"Showing 5 of {len(eligible)} matching lenders. See all results below.")
elif conditional:
    st.caption("These lenders could not be confirmed because one or more applicant details or lender rules are unknown.")
    st.write(", ".join(row["lender"] for row in conditional[:5]))
else:
    st.caption("Review the reasons below to see which rules filtered out the lenders.")

with st.expander("Applicant summary"):
    summary = [
        ("Age", f"{profile['age']} years"),
        ("Employment", str(profile["employment_type"]).replace("_", " ").title()),
        ("Monthly take-home", f"₹{int(float(profile['monthly_net_income'])):,}"),
        ("Existing EMI", f"₹{int(float(profile['existing_monthly_emi'])):,}"),
        ("Credit score", str(profile["credit_score"]) if profile["credit_score"] else "Not available"),
        ("Requested loan", f"₹{int(float(profile['requested_amount'])):,}"),
        ("Requested tenure", f"{profile['requested_tenure_months']} months"),
    ]
    st.write(" · ".join(f"**{key}:** {value}" for key, value in summary))

with st.expander(f"All lender results ({len(lender_rows)})"):
    result_table = []
    for row in lender_rows:
        reasons = row["reasons"] + row["unknowns"]
        result_table.append({
            "Lender": row["lender"],
            "Screening": row["decision"].replace("_", " ").title(),
            "Rate estimate": f"{row['expected_rate_percent_pa']:.2f}%" if row["expected_rate_percent_pa"] is not None else "—",
            "Max loan estimate": f"₹{row['max_loan_amount_estimate']:,.0f}" if row["max_loan_amount_estimate"] is not None else "—",
            "Reason / missing detail": "; ".join(reasons) if reasons else "Passed available rules",
        })
    st.dataframe(pd.DataFrame(result_table), width="stretch", hide_index=True)

st.caption("Rates, loan amounts and screening outcomes are model estimates based on the available public-rule dataset. A lender makes the final decision.")
