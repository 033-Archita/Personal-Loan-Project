"""Create ten illustrative applicant profiles and run them through model.py.

Running ``python data.py`` writes ``input.csv`` and ``test_outputs.csv`` beside
this script. These are synthetic scenarios, not real applicant data.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from model import evaluate


HERE = Path(__file__).resolve().parent
INPUT_CSV = HERE / "input.csv"
OUTPUT_CSV = HERE / "test_outputs.csv"

PROFILES = [
    {"profile_id": "P01", "edge_case": "Baseline salaried", "age": 32, "employment_type": "salaried", "monthly_net_income": 80000, "monthly_gross_income": 95000, "existing_monthly_emi": 10000, "credit_score": 760, "current_job_months": 36, "total_experience_months": 72, "business_vintage_months": 0, "requested_amount": 800000, "requested_tenure_months": 48, "employer_category": "private", "salary_account_lender": "", "city_type": "metro"},
    {"profile_id": "P02", "edge_case": "Recently salaried / new job", "age": 25, "employment_type": "salaried", "monthly_net_income": 45000, "monthly_gross_income": 52000, "existing_monthly_emi": 5000, "credit_score": 720, "current_job_months": 2, "total_experience_months": 18, "business_vintage_months": 0, "requested_amount": 300000, "requested_tenure_months": 36, "employer_category": "private", "salary_account_lender": "", "city_type": "urban"},
    {"profile_id": "P03", "edge_case": "No CIBIL score", "age": 29, "employment_type": "salaried", "monthly_net_income": 65000, "monthly_gross_income": 76000, "existing_monthly_emi": 8000, "credit_score": "", "current_job_months": 24, "total_experience_months": 48, "business_vintage_months": 0, "requested_amount": 500000, "requested_tenure_months": 48, "employer_category": "mnc", "salary_account_lender": "", "city_type": "metro"},
    {"profile_id": "P04", "edge_case": "Young applicant with high EMI burden", "age": 21, "employment_type": "salaried", "monthly_net_income": 35000, "monthly_gross_income": 42000, "existing_monthly_emi": 22000, "credit_score": 710, "current_job_months": 12, "total_experience_months": 18, "business_vintage_months": 0, "requested_amount": 250000, "requested_tenure_months": 36, "employer_category": "private", "salary_account_lender": "", "city_type": "urban"},
    {"profile_id": "P05", "edge_case": "Low income with high existing EMI", "age": 34, "employment_type": "salaried", "monthly_net_income": 22000, "monthly_gross_income": 27000, "existing_monthly_emi": 12000, "credit_score": 680, "current_job_months": 30, "total_experience_months": 96, "business_vintage_months": 0, "requested_amount": 150000, "requested_tenure_months": 24, "employer_category": "private", "salary_account_lender": "", "city_type": "semi_urban"},
    {"profile_id": "P06", "edge_case": "Self-employed with short business vintage", "age": 38, "employment_type": "self_employed", "monthly_net_income": 90000, "monthly_gross_income": 110000, "existing_monthly_emi": 15000, "credit_score": 780, "current_job_months": 0, "total_experience_months": 120, "business_vintage_months": 10, "requested_amount": 1000000, "requested_tenure_months": 60, "employer_category": "professional", "salary_account_lender": "", "city_type": "metro"},
    {"profile_id": "P07", "edge_case": "Near upper age limit", "age": 59, "employment_type": "salaried", "monthly_net_income": 100000, "monthly_gross_income": 125000, "existing_monthly_emi": 10000, "credit_score": 790, "current_job_months": 120, "total_experience_months": 360, "business_vintage_months": 0, "requested_amount": 1200000, "requested_tenure_months": 60, "employer_category": "government/PSU", "salary_account_lender": "", "city_type": "urban"},
    {"profile_id": "P08", "edge_case": "Low credit score", "age": 31, "employment_type": "salaried", "monthly_net_income": 70000, "monthly_gross_income": 82000, "existing_monthly_emi": 8000, "credit_score": 620, "current_job_months": 48, "total_experience_months": 96, "business_vintage_months": 0, "requested_amount": 400000, "requested_tenure_months": 36, "employer_category": "private", "salary_account_lender": "", "city_type": "metro"},
    {"profile_id": "P09", "edge_case": "High income / large loan request", "age": 40, "employment_type": "salaried", "monthly_net_income": 180000, "monthly_gross_income": 220000, "existing_monthly_emi": 25000, "credit_score": 820, "current_job_months": 72, "total_experience_months": 180, "business_vintage_months": 0, "requested_amount": 5000000, "requested_tenure_months": 84, "employer_category": "mnc", "salary_account_lender": "", "city_type": "metro"},
    {"profile_id": "P10", "edge_case": "Very high EMI leaves little repayment room", "age": 42, "employment_type": "salaried", "monthly_net_income": 60000, "monthly_gross_income": 74000, "existing_monthly_emi": 40000, "credit_score": 740, "current_job_months": 60, "total_experience_months": 180, "business_vintage_months": 0, "requested_amount": 500000, "requested_tenure_months": 48, "employer_category": "private", "salary_account_lender": "", "city_type": "urban"},
    {"profile_id": "P11", "edge_case": "Normal accepted: stable salaried, low EMI", "age": 30, "employment_type": "salaried", "monthly_net_income": 90000, "monthly_gross_income": 108000, "existing_monthly_emi": 5000, "credit_score": 790, "current_job_months": 48, "total_experience_months": 84, "business_vintage_months": 0, "requested_amount": 500000, "requested_tenure_months": 48, "employer_category": "mnc", "salary_account_lender": "", "city_type": "metro"},
    {"profile_id": "P12", "edge_case": "Normal accepted: experienced professional", "age": 35, "employment_type": "salaried", "monthly_net_income": 120000, "monthly_gross_income": 145000, "existing_monthly_emi": 10000, "credit_score": 810, "current_job_months": 60, "total_experience_months": 120, "business_vintage_months": 0, "requested_amount": 800000, "requested_tenure_months": 60, "employer_category": "private", "salary_account_lender": "", "city_type": "metro"},
    {"profile_id": "P13", "edge_case": "Normal accepted: government employee", "age": 40, "employment_type": "salaried", "monthly_net_income": 85000, "monthly_gross_income": 103000, "existing_monthly_emi": 8000, "credit_score": 780, "current_job_months": 72, "total_experience_months": 180, "business_vintage_months": 0, "requested_amount": 400000, "requested_tenure_months": 36, "employer_category": "government/PSU", "salary_account_lender": "", "city_type": "urban"},
    {"profile_id": "P14", "edge_case": "Normal accepted: long tenure and low loan request", "age": 28, "employment_type": "salaried", "monthly_net_income": 70000, "monthly_gross_income": 84000, "existing_monthly_emi": 3000, "credit_score": 770, "current_job_months": 30, "total_experience_months": 54, "business_vintage_months": 0, "requested_amount": 250000, "requested_tenure_months": 48, "employer_category": "private", "salary_account_lender": "", "city_type": "urban"},
    {"profile_id": "P15", "edge_case": "Normal accepted: strong income and credit", "age": 33, "employment_type": "salaried", "monthly_net_income": 150000, "monthly_gross_income": 180000, "existing_monthly_emi": 12000, "credit_score": 830, "current_job_months": 48, "total_experience_months": 96, "business_vintage_months": 0, "requested_amount": 1000000, "requested_tenure_months": 60, "employer_category": "mnc", "salary_account_lender": "", "city_type": "metro"},
]


def create_files() -> tuple[Path, Path]:
    fields = list(PROFILES[0])
    with INPUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(PROFILES)

    output_fields = ["profile_id", "edge_case", "overall_decision", "best_lender", "best_rate_percent_pa", "best_max_loan_estimate", "lender_results_json"]
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields)
        writer.writeheader()
        for profile in PROFILES:
            result = evaluate(profile)
            best = result.get("best_option") or {}
            writer.writerow({
                "profile_id": profile["profile_id"],
                "edge_case": profile["edge_case"],
                "overall_decision": result["overall_decision"],
                "best_lender": best.get("lender", ""),
                "best_rate_percent_pa": best.get("expected_rate_percent_pa", ""),
                "best_max_loan_estimate": best.get("max_loan_amount_estimate", ""),
                "lender_results_json": json.dumps(result["lenders"], ensure_ascii=False, separators=(",", ":")),
            })
    return INPUT_CSV, OUTPUT_CSV


if __name__ == "__main__":
    input_path, output_path = create_files()
    print(f"Wrote {len(PROFILES)} profiles to {input_path}")
    print(f"Wrote model results to {output_path}")
