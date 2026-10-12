"""Validate and losslessly normalize research CSVs into lender_rule_matrix.csv.

The matrix keeps one row per input record. Calculator observations and findings
remain evidence records; they are never converted into lender eligibility rules.
Original input CSVs are read only and are never overwritten.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
MATRIX_FIELDS = [
    "record_id", "record_type", "source_file", "source_row", "source_record_id",
    "lender_id", "lender_name", "lender_class", "in_top20",
    "rule_key", "segment", "rule_value", "rule_unit", "rule_type", "model_role",
    "status", "evidence_status", "confidence", "estimate_method", "conflict_resolution",
    "needs_official_verification", "source_id", "source_url", "source_publisher",
    "source_type", "publication_date", "accessed_at", "supporting_passage",
    "calculation_category", "calculation_status", "calculation_confidence",
    "calculation_inputs", "calculation_outputs", "evidence_summary", "evidence_references",
    "raw_record_json",
]
NUMERIC_RULES = {
    "min_age", "max_age_at_application", "max_age_at_maturity", "max_foir",
    "max_income_multiple", "max_loan_amount", "max_tenure", "min_age",
    "min_business_vintage", "min_credit_score", "min_current_job_tenure",
    "min_loan_amount", "min_net_monthly_income_salaried",
    "min_net_monthly_income_self_employed", "min_tenure", "min_total_experience",
    "processing_fee_max", "rate_min", "rate_max",
}
NON_NUMERIC_STATUSES = {"NOT_APPLICABLE", "NOT_PUBLISHED"}


def _normal_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_csv(path: Path, required: set[str]) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Required source CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        duplicate_headers = sorted({name for name in headers if headers.count(name) > 1})
        if duplicate_headers:
            raise ValueError(f"{path.name} has duplicate columns: {duplicate_headers}")
        missing = required - set(headers)
        if missing:
            raise ValueError(f"{path.name} is missing required columns: {sorted(missing)}")
        return list(reader), headers


def _valid_date(value: str) -> bool:
    if not value or value.strip().casefold() in {"unknown", "n/a", "na", "not known", "not published"}:
        return True
    try:
        date.fromisoformat(value.strip())
        return True
    except ValueError:
        return False


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_matrix(
    source_dir: Path = HERE,
    output_dir: Path = HERE,
    *,
    lender_filename: str = "lender_rules.csv",
    observations_filename: str = "calculator_observations.csv",
    findings_filename: str = "calculator_rule_findings.csv",
) -> tuple[Path, Path, dict[str, Any]]:
    """Build matrix and JSON report from the three named input files."""
    file_map = {
        "lender_rule": lender_filename,
        "calculator_observation": observations_filename,
        "calculator_finding": findings_filename,
    }
    schemas = {
        "lender_rule": {"rule_id", "lender_id", "lender_name", "lender_class", "rule_key", "rule_value", "rule_unit", "status", "source_url", "accessed_at"},
        "calculator_observation": {"lender_name", "calculator_url", "access_date", "test_id", "result_type", "evidence_type", "observation"},
        "calculator_finding": {"lender_name", "rule_name", "rule_category", "candidate_threshold_or_value", "unit", "evidence_status", "source_url", "access_date", "recommended_model_handling"},
    }
    read_rows: dict[str, list[dict[str, str]]] = {}
    source_info: dict[str, Any] = {}
    for kind, filename in file_map.items():
        path = source_dir / filename
        rows, headers = _read_csv(path, schemas[kind])
        read_rows[kind] = rows
        source_info[filename] = {
            "path": filename, "rows": len(rows), "columns": headers,
            "sha256_before": _sha256(path),
        }

    lender_map: dict[str, tuple[str, str]] = {}
    for row in read_rows["lender_rule"]:
        key = _normal_name(row.get("lender_name", ""))
        if key and key not in lender_map:
            lender_map[key] = (row.get("lender_id", ""), row.get("lender_class", ""))

    matrix_rows: list[dict[str, str]] = []
    invalid_dates: list[str] = []
    invalid_numeric: list[str] = []
    missing_required: list[str] = []
    duplicate_rule_ids: list[str] = []
    rule_ids: Counter[str] = Counter()
    conflict_groups: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    units_by_rule: dict[str, set[str]] = defaultdict(set)
    invalid_booleans: list[str] = []
    rules_by_lender_segment: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    invalid_rule_ranges: list[str] = []
    unmatched_lenders: list[str] = []
    evidence_by_lender: Counter[str] = Counter()

    for kind, filename in file_map.items():
        for row_number, raw in enumerate(read_rows[kind], start=2):
            record_id = f"{kind}:{row_number - 1:04d}"
            name = raw.get("lender_name", "")
            lender_id, lender_class = lender_map.get(_normal_name(name), ("", ""))
            if kind != "lender_rule" and not lender_id:
                unmatched_lenders.append(f"{filename}:{row_number}:{name}")
            source_url = raw.get("source_url", "") or raw.get("calculator_url", "")
            accessed_at = raw.get("accessed_at", "") or raw.get("access_date", "")
            if accessed_at and not _valid_date(accessed_at):
                invalid_dates.append(f"{filename}:{row_number}:{accessed_at}")
            publication_date = raw.get("publication_date", "")
            if publication_date and not _valid_date(publication_date):
                invalid_dates.append(f"{filename}:{row_number}:publication_date={publication_date}")

            record = {field: "" for field in MATRIX_FIELDS}
            record.update({
                "record_id": record_id,
                "record_type": kind,
                "source_file": filename,
                "source_row": str(row_number),
                "source_record_id": raw.get("rule_id", "") or raw.get("test_id", "") or raw.get("rule_name", ""),
                "lender_id": lender_id or raw.get("lender_id", ""),
                "lender_name": name,
                "lender_class": lender_class or raw.get("lender_class", ""),
                "in_top20": raw.get("in_top20", ""),
                "rule_key": raw.get("rule_key", "") or raw.get("rule_name", ""),
                "segment": raw.get("segment", ""),
                "rule_value": raw.get("rule_value", "") or raw.get("candidate_threshold_or_value", ""),
                "rule_unit": raw.get("rule_unit", "") or raw.get("unit", ""),
                "rule_type": raw.get("rule_type", ""),
                "model_role": raw.get("model_role", ""),
                "status": raw.get("status", "") or raw.get("evidence_status", "") or raw.get("evidence_type", ""),
                "evidence_status": raw.get("evidence_status", "") or raw.get("evidence_type", "") or raw.get("status", ""),
                "confidence": raw.get("confidence", "") or raw.get("calculation_confidence", ""),
                "estimate_method": raw.get("estimate_method", ""),
                "conflict_resolution": raw.get("conflict_resolution", ""),
                "needs_official_verification": raw.get("needs_official_verification", ""),
                "source_id": raw.get("source_id", ""),
                "source_url": source_url,
                "source_publisher": raw.get("source_publisher", ""),
                "source_type": raw.get("source_type", ""),
                "publication_date": raw.get("publication_date", ""),
                "accessed_at": accessed_at,
                "supporting_passage": raw.get("supporting_passage", ""),
                "calculation_category": raw.get("rule_category", ""),
                "calculation_status": raw.get("result_type", "") or raw.get("evidence_status", ""),
                "calculation_confidence": raw.get("confidence", ""),
                "calculation_inputs": _json({k: v for k, v in raw.items() if k.startswith("input_")} if kind == "calculator_observation" else {"additional_inputs": raw.get("additional_inputs", "")}),
                "calculation_outputs": _json({k: v for k, v in raw.items() if k.startswith("displayed_")} if kind == "calculator_observation" else {}),
                "evidence_summary": _json({k: raw[k] for k in ("observation", "observed_relationship", "limitations", "recommended_model_handling") if raw.get(k)}) if kind != "lender_rule" else raw.get("supporting_passage", ""),
                "evidence_references": raw.get("screenshot_or_evidence_reference", "") or raw.get("supporting_test_ids", ""),
                "raw_record_json": _json(raw),
            })
            matrix_rows.append(record)

            if kind == "lender_rule":
                rule_id = raw.get("rule_id", "")
                rule_ids[rule_id] += 1
                key = (raw.get("lender_id", ""), raw.get("rule_key", ""), raw.get("segment", ""))
                conflict_groups[key].add(raw.get("rule_value", ""))
                for field in ("rule_id", "lender_id", "lender_name", "rule_key", "rule_value", "status"):
                    if not raw.get(field, "").strip():
                        missing_required.append(f"{filename}:{row_number}:{field}")
                for field in ("in_top20", "needs_official_verification"):
                    value = raw.get(field, "").strip().casefold()
                    if value and value not in {"true", "false", "1", "0"}:
                        invalid_booleans.append(f"{filename}:{row_number}:{field}={value}")
                if raw.get("rule_unit", "").strip():
                    units_by_rule[raw.get("rule_key", "")].add(raw["rule_unit"].strip())
                if raw.get("rule_key") in NUMERIC_RULES and raw.get("status") not in NON_NUMERIC_STATUSES:
                    value = raw.get("rule_value", "").strip()
                    if value:
                        try:
                            number = float(value.replace(",", "").replace("₹", "").strip())
                            if not math.isfinite(number):
                                raise ValueError
                            if number < 0 or (raw.get("rule_key") in {"min_age", "min_tenure", "min_loan_amount", "min_credit_score"} and number == 0):
                                invalid_rule_ranges.append(f"{filename}:{row_number}:{raw.get('rule_key')}={value}")
                            if raw.get("rule_key") == "max_foir" and number > 100:
                                invalid_rule_ranges.append(f"{filename}:{row_number}:max_foir={value} exceeds 100")
                            rules_by_lender_segment[(raw.get("lender_id", ""), raw.get("segment", ""))][raw.get("rule_key", "")] = number
                        except ValueError:
                            # Score-band descriptions such as the PNB rate table are
                            # deliberately retained as text, never coerced or dropped.
                            if raw.get("rule_key") != "rate_by_cibil_band":
                                invalid_numeric.append(f"{filename}:{row_number}:{raw.get('rule_key')}={value}")
                if raw.get("source_url") and not _valid_date(raw.get("accessed_at", "")):
                    invalid_dates.append(f"{filename}:{row_number}:accessed_at={raw.get('accessed_at')}")
            else:
                evidence_by_lender[lender_id or f"UNMATCHED:{name}"] += 1

    for rule_id, count in rule_ids.items():
        if count > 1:
            duplicate_rule_ids.append(f"{rule_id} ({count} rows)")
    conflicts = [
        {"lender_id": lender_id, "rule_key": rule_key, "segment": segment, "distinct_values": sorted(values)}
        for (lender_id, rule_key, segment), values in sorted(conflict_groups.items()) if len(values) > 1
    ]
    invalid_pairs = []
    for (lender_id, segment), values in sorted(rules_by_lender_segment.items()):
        for lower_key, upper_key in (("min_age", "max_age_at_application"), ("min_loan_amount", "max_loan_amount"), ("min_tenure", "max_tenure"), ("rate_min", "rate_max")):
            if lower_key in values and upper_key in values and values[lower_key] > values[upper_key]:
                invalid_pairs.append({"lender_id": lender_id, "segment": segment, "minimum_rule": lower_key,
                                      "minimum_value": values[lower_key], "maximum_rule": upper_key,
                                      "maximum_value": values[upper_key]})

    output_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = output_dir / "lender_rule_matrix.csv"
    report_path = output_dir / "csv_validation_report.json"
    with matrix_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_FIELDS, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows(matrix_rows)

    for filename, info in source_info.items():
        info["sha256_after"] = _sha256(Path(info["path"]))
        info["unchanged_during_run"] = info["sha256_before"] == info["sha256_after"]
    report = {
        "pipeline": "csv_clean_and_format.py",
        "sources": source_info,
        "output": {"matrix_path": str(matrix_path), "record_count": len(matrix_rows), "columns": MATRIX_FIELDS,
                   "record_type_counts": dict(Counter(row["record_type"] for row in matrix_rows))},
        "reconciliation": {
            "lender_count": len(lender_map),
            "evidence_rows_by_lender_id": dict(evidence_by_lender),
            "unmatched_calculator_rows": unmatched_lenders,
            "conflicting_rule_groups_preserved": conflicts,
        },
        "validation": {
            "missing_required_rule_fields": missing_required,
            "duplicate_rule_ids": duplicate_rule_ids,
            "invalid_numeric_rule_values": invalid_numeric,
            "invalid_boolean_values": invalid_booleans,
            "invalid_rule_ranges": invalid_rule_ranges,
            "inconsistent_minimum_maximum_pairs": invalid_pairs,
            "invalid_dates": sorted(set(invalid_dates)),
            "rule_keys_with_multiple_units": {key: sorted(values) for key, values in sorted(units_by_rule.items()) if len(values) > 1},
            "all_source_files_unchanged": all(v["unchanged_during_run"] for v in source_info.values()),
            "all_rows_preserved": len(matrix_rows) == sum(len(v) for v in read_rows.values()),
        },
        "notes": [
            "Original source columns and values are retained in raw_record_json; empty cells remain empty, not zero.",
            "Multiple and conflicting lender rules remain separate records, with conflict groups reported above.",
            "Calculator observations/findings are evidence-only record types. The model must not treat them as hard eligibility rules.",
            "Calculator displayed values are not normalized into rates, FOIR, or eligibility rules because their input scenarios and validity vary.",
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return matrix_path, report_path, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=HERE, help="Directory containing the three source CSVs")
    parser.add_argument("--output-dir", type=Path, default=HERE, help="Directory for generated matrix and report")
    parser.add_argument("--lender-rules", default="lender_rules.csv")
    parser.add_argument("--observations", default="calculator_observations.csv")
    parser.add_argument("--findings", default="calculator_rule_findings.csv")
    args = parser.parse_args()
    matrix, report_path, report = build_matrix(
        args.source_dir, args.output_dir,
        lender_filename=args.lender_rules,
        observations_filename=args.observations,
        findings_filename=args.findings,
    )
    print(f"Wrote {report['output']['record_count']} records to {matrix}")
    print(f"Wrote validation report to {report_path}")
    print(f"Sources unchanged: {report['validation']['all_source_files_unchanged']}")


if __name__ == "__main__":
    main()

