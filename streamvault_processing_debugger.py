#!/usr/bin/env python3
"""
STREAMVAULT Processing Trace Debugger

Run from the STREAMVAULT project folder:
    python streamvault_processing_debugger.py --csv netflix_titles.csv

This debugger:
1. Audits raw and normalized blank values.
2. Traces country counts at each processing stage.
3. Scans all Python files for country-count logic.
4. Identifies likely incorrect raw nunique() calculations.
5. Writes machine-readable and human-readable reports.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd


BLANK_TOKENS = {
    "",
    " ",
    "none",
    "null",
    "nan",
    "n/a",
    "na",
    "nothing",
    "blank",
    "unknown",
    "-",
    "--",
}


def normalize_blank(value: Any) -> Any:
    if value is None:
        return pd.NA

    try:
        if pd.isna(value):
            return pd.NA
    except (TypeError, ValueError):
        pass

    text = re.sub(r"\s+", " ", str(value)).strip()

    if text.casefold() in BLANK_TOKENS:
        return pd.NA

    return text


def load_catalog(path: Path) -> pd.DataFrame:
    encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    last_error: Exception | None = None

    for encoding in encodings:
        try:
            df = pd.read_csv(
                path,
                dtype="string",
                keep_default_na=False,
                na_filter=False,
                encoding=encoding,
                on_bad_lines="warn",
            )
            break
        except Exception as exc:
            last_error = exc
    else:
        raise RuntimeError(f"Unable to read CSV: {last_error}")

    df.columns = [
        re.sub(r"[^a-z0-9]+", "_", str(column).strip().lower()).strip("_")
        for column in df.columns
    ]

    return df


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()

    for column in cleaned.columns:
        cleaned[column] = cleaned[column].map(normalize_blank).astype("string")

    return cleaned


def split_countries(series: pd.Series) -> pd.Series:
    values = (
        series.dropna()
        .astype(str)
        .str.split(r"\s*(?:,|;|\|)\s*", regex=True)
        .explode()
        .astype("string")
        .str.strip()
        .replace("", pd.NA)
        .dropna()
    )

    return values[
        ~values.str.casefold().isin(BLANK_TOKENS)
    ]


def country_trace(raw: pd.DataFrame, cleaned: pd.DataFrame) -> dict[str, Any]:
    if "country" not in raw.columns:
        return {
            "country_column_found": False,
            "error": "No country column was found.",
        }

    raw_series = raw["country"].astype("string")
    cleaned_series = cleaned["country"]
    countries = split_countries(cleaned_series)

    raw_nonempty = raw_series.fillna("").str.strip().ne("")
    raw_combinations = raw_series[raw_nonempty]

    normalized_table = pd.DataFrame(
        {
            "display": countries,
            "key": countries.str.casefold(),
        }
    ).drop_duplicates("key")

    suspicious = normalized_table[
        normalized_table["display"].str.contains(r"\d", regex=True, na=False)
        | normalized_table["display"].str.len().gt(60)
        | normalized_table["display"].str.len().le(1)
    ]["display"].tolist()

    return {
        "country_column_found": True,
        "total_catalog_rows": int(len(raw)),
        "raw_blank_country_cells": int((~raw_nonempty).sum()),
        "raw_nonblank_country_cells": int(raw_nonempty.sum()),
        "raw_unique_country_strings_including_combinations": int(
            raw_combinations.nunique()
        ),
        "cleaned_blank_country_cells": int(cleaned_series.isna().sum()),
        "cleaned_unique_country_strings_including_combinations": int(
            cleaned_series.dropna().str.casefold().nunique()
        ),
        "exploded_country_occurrences": int(len(countries)),
        "normalized_unique_individual_countries": int(len(normalized_table)),
        "top_25_individual_countries": {
            str(key): int(value)
            for key, value in countries.value_counts().head(25).items()
        },
        "suspicious_country_tokens": suspicious,
        "correct_dashboard_formula": (
            "split country strings first, explode them, strip whitespace, "
            "case-normalize, then call nunique()"
        ),
        "incorrect_dashboard_formula": (
            "df['country'].dropna().nunique() counts combinations such as "
            "'United States, Canada' as separate country values"
        ),
    }


def blank_trace(raw: pd.DataFrame, cleaned: pd.DataFrame) -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []

    for column in cleaned.columns:
        raw_text = raw[column].astype("string").fillna("").str.strip()
        explicit_blank_tokens = raw_text.str.casefold().isin(BLANK_TOKENS)

        report.append(
            {
                "column": column,
                "rows": int(len(cleaned)),
                "raw_empty_strings": int(raw_text.eq("").sum()),
                "raw_blank_token_values": int(explicit_blank_tokens.sum()),
                "cleaned_missing_values": int(cleaned[column].isna().sum()),
                "cleaned_nonmissing_values": int(cleaned[column].notna().sum()),
            }
        )

    return report


def scan_python_files(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    patterns = {
        "raw_country_nunique": re.compile(
            r"""(?:df|data|catalog|filtered)\s*\[\s*["']country["']\s*\].*?nunique\s*\(""",
            re.IGNORECASE,
        ),
        "country_value_counts": re.compile(
            r"""(?:df|data|catalog|filtered)\s*\[\s*["']country["']\s*\].*?value_counts\s*\(""",
            re.IGNORECASE,
        ),
        "streamlit_metric_country": re.compile(
            r"""(?:st\.)?metric\s*\([^)]*(?:country|countries)""",
            re.IGNORECASE,
        ),
        "country_split": re.compile(
            r"""(?:country|countries).*?(?:split|explode)""",
            re.IGNORECASE,
        ),
    }

    ignored_parts = {".venv", "venv", "__pycache__", ".git", "site-packages"}

    for file in root.rglob("*.py"):
        if any(part in ignored_parts for part in file.parts):
            continue

        try:
            lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        for line_number, line in enumerate(lines, start=1):
            for finding_type, pattern in patterns.items():
                if pattern.search(line):
                    severity = "INFO"

                    if finding_type == "raw_country_nunique":
                        severity = "WARNING"

                    findings.append(
                        {
                            "file": str(file.resolve()),
                            "line": line_number,
                            "type": finding_type,
                            "severity": severity,
                            "code": line.strip(),
                        }
                    )

    return findings


def find_candidate_app_files(root: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    ignored_parts = {".venv", "venv", "__pycache__", ".git", "site-packages"}

    for file in root.rglob("*.py"):
        if any(part in ignored_parts for part in file.parts):
            continue

        try:
            content = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        score = 0
        signals: list[str] = []

        if "import streamlit" in content:
            score += 3
            signals.append("imports Streamlit")

        if "st.set_page_config" in content:
            score += 2
            signals.append("sets page configuration")

        if "st.title" in content:
            score += 1
            signals.append("renders a page title")

        if "country" in content.casefold():
            score += 1
            signals.append("contains country logic")

        if score:
            candidates.append(
                {
                    "file": str(file.resolve()),
                    "score": score,
                    "signals": signals,
                    "modified_timestamp": file.stat().st_mtime,
                }
            )

    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def write_text_report(
    path: Path,
    csv_path: Path,
    country: dict[str, Any],
    blanks: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    app_candidates: list[dict[str, Any]],
) -> None:
    lines: list[str] = []

    lines.extend(
        [
            "STREAMVAULT PROCESSING TRACE",
            "=" * 31,
            f"Dataset: {csv_path.resolve()}",
            "",
            "COUNTRY PIPELINE",
            "-" * 20,
        ]
    )

    if country.get("country_column_found"):
        lines.extend(
            [
                f"Catalog rows: {country['total_catalog_rows']:,}",
                f"Raw blank country cells: {country['raw_blank_country_cells']:,}",
                f"Raw nonblank country cells: {country['raw_nonblank_country_cells']:,}",
                (
                    "Raw unique country strings/combinations: "
                    f"{country['raw_unique_country_strings_including_combinations']:,}"
                ),
                (
                    "Cleaned unique country strings/combinations: "
                    f"{country['cleaned_unique_country_strings_including_combinations']:,}"
                ),
                (
                    "Exploded country occurrences: "
                    f"{country['exploded_country_occurrences']:,}"
                ),
                (
                    "CORRECT unique individual countries: "
                    f"{country['normalized_unique_individual_countries']:,}"
                ),
                "",
                "Diagnosis:",
                country["incorrect_dashboard_formula"],
            ]
        )
    else:
        lines.append(country["error"])

    lines.extend(
        [
            "",
            "POSSIBLE STREAMLIT APP FILES",
            "-" * 29,
        ]
    )

    if app_candidates:
        for item in app_candidates:
            lines.append(
                f"[score {item['score']}] {item['file']} "
                f"({', '.join(item['signals'])})"
            )
    else:
        lines.append("No Streamlit application files were detected.")

    lines.extend(
        [
            "",
            "COUNTRY CODE SCAN",
            "-" * 17,
        ]
    )

    if findings:
        for finding in findings:
            lines.append(
                f"{finding['severity']}: {finding['file']}:{finding['line']} "
                f"[{finding['type']}] {finding['code']}"
            )
    else:
        lines.append("No country-processing code patterns were found.")

    lines.extend(
        [
            "",
            "BLANK FIELD AUDIT",
            "-" * 17,
        ]
    )

    for row in sorted(
        blanks,
        key=lambda item: item["cleaned_missing_values"],
        reverse=True,
    ):
        lines.append(
            f"{row['column']}: "
            f"{row['cleaned_missing_values']:,} empty; "
            f"{row['cleaned_nonmissing_values']:,} populated"
        )

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Trace STREAMVAULT CSV and country-count processing."
    )
    parser.add_argument(
        "--csv",
        default="netflix_titles.csv",
        help="Catalog CSV path",
    )
    parser.add_argument(
        "--project",
        default=".",
        help="STREAMVAULT project folder",
    )
    parser.add_argument(
        "--output",
        default="streamvault_processing_debug",
        help="Output report folder",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv).expanduser().resolve()
    project_root = Path(args.project).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()

    if not csv_path.exists():
        print(f"ERROR: CSV not found: {csv_path}", file=sys.stderr)
        return 1

    if not project_root.exists():
        print(f"ERROR: Project folder not found: {project_root}", file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    raw = load_catalog(csv_path)
    cleaned = normalize_dataframe(raw)

    country = country_trace(raw, cleaned)
    blanks = blank_trace(raw, cleaned)
    findings = scan_python_files(project_root)
    app_candidates = find_candidate_app_files(project_root)

    payload = {
        "dataset": str(csv_path),
        "project_root": str(project_root),
        "row_count": int(len(cleaned)),
        "column_count": int(len(cleaned.columns)),
        "columns": cleaned.columns.tolist(),
        "country_trace": country,
        "blank_trace": blanks,
        "python_code_findings": findings,
        "candidate_streamlit_apps": app_candidates,
    }

    json_path = output_dir / "processing_trace.json"
    text_path = output_dir / "processing_trace.txt"
    blank_path = output_dir / "blank_field_audit.csv"
    cleaned_path = output_dir / "catalog_normalized_for_debug.csv"

    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    write_text_report(
        text_path,
        csv_path,
        country,
        blanks,
        findings,
        app_candidates,
    )

    pd.DataFrame(blanks).to_csv(blank_path, index=False)
    cleaned.to_csv(cleaned_path, index=False)

    print("\nSTREAMVAULT PROCESSING TRACE")
    print("=" * 31)
    print(f"CSV: {csv_path}")
    print(f"Project: {project_root}")
    print(f"Rows: {len(cleaned):,}")
    print(f"Columns: {len(cleaned.columns):,}")

    if country.get("country_column_found"):
        print(
            "Raw country strings/combinations: "
            f"{country['raw_unique_country_strings_including_combinations']:,}"
        )
        print(
            "Correct normalized individual countries: "
            f"{country['normalized_unique_individual_countries']:,}"
        )

    warnings = [
        finding for finding in findings
        if finding["severity"] == "WARNING"
    ]

    print(f"Potential incorrect country formulas found: {len(warnings)}")

    for warning in warnings:
        print(
            f"WARNING: {warning['file']}:{warning['line']} "
            f"{warning['code']}"
        )

    print("\nCandidate Streamlit app files:")
    for candidate in app_candidates[:10]:
        print(f"  {candidate['file']} [score {candidate['score']}]")

    print("\nReports created:")
    print(f"  {text_path}")
    print(f"  {json_path}")
    print(f"  {blank_path}")
    print(f"  {cleaned_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
