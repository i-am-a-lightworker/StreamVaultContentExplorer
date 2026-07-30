#!/usr/bin/env python3
"""
STREAMVAULT Batch Debugger

Purpose:
- Audit every column in a catalog CSV
- Treat blank strings, whitespace, "nothing", "none", "null", "n/a", etc. as missing
- Diagnose inflated country counts caused by incorrect splitting or row counting
- Produce cleaned data and debug reports without requiring OpenAI
"""

from __future__ import annotations

import argparse
import ast
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

COUNTRY_COLUMN_CANDIDATES = (
    "country",
    "countries",
    "production_country",
    "production_countries",
    "origin_country",
    "origin_countries",
)


def normalize_column_name(name: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def normalize_blank(value: Any) -> Any:
    if value is None:
        return pd.NA

    try:
        if pd.isna(value):
            return pd.NA
    except (TypeError, ValueError):
        pass

    if isinstance(value, str):
        cleaned = re.sub(r"\s+", " ", value).strip()
        if cleaned.lower() in BLANK_TOKENS:
            return pd.NA
        return cleaned

    return value


def load_csv(path: Path) -> pd.DataFrame:
    encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    last_error: Exception | None = None

    for encoding in encodings:
        try:
            return pd.read_csv(
                path,
                dtype="string",
                keep_default_na=False,
                na_filter=False,
                encoding=encoding,
                on_bad_lines="warn",
            )
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Could not read {path}: {last_error}")


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()
    cleaned.columns = [normalize_column_name(c) for c in cleaned.columns]

    for column in cleaned.columns:
        cleaned[column] = cleaned[column].map(normalize_blank).astype("string")

    return cleaned


def find_country_column(df: pd.DataFrame, requested: str | None) -> str | None:
    if requested:
        normalized = normalize_column_name(requested)
        return normalized if normalized in df.columns else None

    for candidate in COUNTRY_COLUMN_CANDIDATES:
        if candidate in df.columns:
            return candidate

    for column in df.columns:
        if "country" in column:
            return column

    return None


def parse_country_cell(value: Any) -> list[str]:
    value = normalize_blank(value)
    if pd.isna(value):
        return []

    text = str(value).strip()

    # Handle Python/JSON-style list strings, e.g. ["United States", "Canada"]
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, (list, tuple, set)):
                values = [str(item) for item in parsed]
            else:
                values = [str(parsed)]
        except (ValueError, SyntaxError):
            values = [text]
    else:
        # Split only on common multi-country separators.
        values = re.split(r"\s*(?:,|;|\||/)\s*", text)

    results: list[str] = []
    for item in values:
        item = re.sub(r"\s+", " ", item).strip(" '\"\t\r\n")
        if item and item.lower() not in BLANK_TOKENS:
            results.append(item)

    return results


def country_debug(df: pd.DataFrame, country_column: str | None) -> dict[str, Any]:
    if not country_column:
        return {
            "country_column_found": False,
            "message": "No country column was detected.",
        }

    parsed = df[country_column].map(parse_country_cell)
    exploded = parsed.explode().dropna()
    exploded = exploded[exploded.astype(str).str.strip().ne("")]

    normalized = exploded.astype(str).str.strip()
    normalized_key = normalized.str.casefold()

    unique_display = (
        pd.DataFrame({"display": normalized, "key": normalized_key})
        .drop_duplicates("key")
        .sort_values("display")
    )

    suspicious = sorted(
        {
            item
            for item in normalized.unique().tolist()
            if len(item) <= 1
            or len(item) > 60
            or bool(re.search(r"\d", item))
            or item.lower() in BLANK_TOKENS
        }
    )

    raw_nonblank_rows = int(df[country_column].notna().sum())
    parsed_country_entries = int(len(normalized))
    unique_country_count = int(len(unique_display))

    return {
        "country_column_found": True,
        "country_column": country_column,
        "catalog_rows": int(len(df)),
        "rows_with_country_data": raw_nonblank_rows,
        "parsed_country_entries": parsed_country_entries,
        "unique_country_count": unique_country_count,
        "unique_countries": unique_display["display"].tolist(),
        "suspicious_country_tokens": suspicious,
        "diagnosis": (
            "If the app reported 748 countries, it likely counted rows or exploded "
            "country entries instead of counting normalized unique country names."
        ),
    }


def column_audit(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for column in df.columns:
        series = df[column]
        nonblank = series.dropna()
        normalized = nonblank.astype(str).str.strip()

        rows.append(
            {
                "column": column,
                "row_count": len(series),
                "blank_count": int(series.isna().sum()),
                "nonblank_count": int(series.notna().sum()),
                "unique_nonblank_count": int(normalized.str.casefold().nunique()),
                "duplicate_nonblank_count": int(normalized.str.casefold().duplicated().sum()),
                "sample_values": " | ".join(normalized.head(5).tolist()),
            }
        )

    return pd.DataFrame(rows)


def duplicate_audit(df: pd.DataFrame) -> dict[str, Any]:
    exact_duplicates = int(df.duplicated().sum())

    id_candidates = [
        c for c in ("show_id", "id", "title_id", "content_id") if c in df.columns
    ]

    title_candidates = [
        c for c in ("title", "name", "content_title") if c in df.columns
    ]

    result: dict[str, Any] = {
        "exact_duplicate_rows": exact_duplicates,
    }

    if id_candidates:
        col = id_candidates[0]
        result["id_column"] = col
        result["duplicate_ids"] = int(df[col].dropna().str.casefold().duplicated().sum())

    if title_candidates:
        col = title_candidates[0]
        result["title_column"] = col
        result["duplicate_titles"] = int(df[col].dropna().str.casefold().duplicated().sum())

    return result


def print_summary(
    source: Path,
    cleaned: pd.DataFrame,
    audit: pd.DataFrame,
    countries: dict[str, Any],
    duplicates: dict[str, Any],
) -> None:
    print("\nSTREAMVAULT BATCH DEBUG REPORT")
    print("=" * 34)
    print(f"File: {source}")
    print(f"Rows: {len(cleaned):,}")
    print(f"Columns: {len(cleaned.columns)}")
    print(f"Total blank cells: {int(cleaned.isna().sum().sum()):,}")
    print(f"Exact duplicate rows: {duplicates['exact_duplicate_rows']:,}")

    if len(cleaned.columns) != 26:
        print(f"WARNING: Expected 26 fields but found {len(cleaned.columns)}.")

    print("\nCOUNTRY CHECK")
    print("-" * 20)

    if countries.get("country_column_found"):
        print(f"Country field: {countries['country_column']}")
        print(f"Rows with country data: {countries['rows_with_country_data']:,}")
        print(f"Parsed country entries: {countries['parsed_country_entries']:,}")
        print(f"Unique normalized countries: {countries['unique_country_count']:,}")
        print(countries["diagnosis"])

        if countries["suspicious_country_tokens"]:
            print("Suspicious country values:")
            for value in countries["suspicious_country_tokens"][:20]:
                print(f"  - {value}")
    else:
        print(countries["message"])

    print("\nFIELDS WITH THE MOST BLANKS")
    print("-" * 28)
    top_blanks = audit.sort_values("blank_count", ascending=False).head(10)
    for _, row in top_blanks.iterrows():
        print(
            f"{row['column']}: {int(row['blank_count']):,} blank "
            f"of {int(row['row_count']):,}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and clean a STREAMVAULT CSV.")
    parser.add_argument("csv_file", help="Path to the catalog CSV file")
    parser.add_argument(
        "--country-column",
        help="Optional exact country column name",
    )
    parser.add_argument(
        "--output-dir",
        default="streamvault_debug_output",
        help="Directory for generated reports",
    )
    args = parser.parse_args()

    source = Path(args.csv_file).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

    if not source.exists():
        print(f"ERROR: File not found: {source}", file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    raw = load_csv(source)
    cleaned = clean_dataframe(raw)

    audit = column_audit(cleaned)
    countries = country_debug(
        cleaned,
        find_country_column(cleaned, args.country_column),
    )
    duplicates = duplicate_audit(cleaned)

    cleaned_path = output_dir / "streamvault_cleaned.csv"
    audit_path = output_dir / "streamvault_column_audit.csv"
    country_path = output_dir / "streamvault_country_debug.json"
    summary_path = output_dir / "streamvault_debug_summary.json"

    cleaned.to_csv(cleaned_path, index=False)
    audit.to_csv(audit_path, index=False)

    country_path.write_text(
        json.dumps(countries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    summary_path.write_text(
        json.dumps(
            {
                "source_file": str(source),
                "row_count": len(cleaned),
                "column_count": len(cleaned.columns),
                "total_blank_cells": int(cleaned.isna().sum().sum()),
                "duplicates": duplicates,
                "country_debug": countries,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print_summary(source, cleaned, audit, countries, duplicates)

    print("\nFILES CREATED")
    print("-" * 20)
    print(cleaned_path)
    print(audit_path)
    print(country_path)
    print(summary_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
