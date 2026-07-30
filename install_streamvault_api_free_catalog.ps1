# STREAMVAULT API-free catalog experience installer
# Run from the STREAMVAULT project folder.

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Updating STREAMVAULT..." -ForegroundColor Cyan

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

if (-not (Test-Path ".\.venv")) {
    Write-Host "Creating virtual environment..."
    py -m venv .venv
}

& ".\.venv\Scripts\Activate.ps1"

Write-Host "Installing local dependencies..."
python -m pip install --upgrade pip
python -m pip install streamlit pandas openpyxl xlrd reportlab

if (Test-Path ".\streamvault_dashboard.py") {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    Copy-Item `
        ".\streamvault_dashboard.py" `
        ".\streamvault_dashboard_backup_$stamp.py" `
        -Force
    Write-Host "Existing dashboard backed up." -ForegroundColor Yellow
}

$appCode = @'
from __future__ import annotations

import io
import re
import sqlite3
import textwrap
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


st.set_page_config(
    page_title="STREAMVAULT Catalog Analyst",
    page_icon="🎬",
    layout="wide",
)

DEFAULT_CSV_CANDIDATES = (
    "netflix_titles.csv",
    "netflix_titles(1).csv",
)

REQUIRED_COLUMNS = [
    "show_id",
    "type",
    "title",
    "director",
    "cast",
    "country",
    "date_added",
    "release_year",
    "rating",
    "duration",
    "listed_in",
    "description",
]

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


def normalize_blank(value: Any):
    if value is None:
        return pd.NA

    try:
        if pd.isna(value):
            return pd.NA
    except (TypeError, ValueError):
        pass

    text = re.sub(r"\s+", " ", str(value)).strip()
    return pd.NA if text.casefold() in BLANK_TOKENS else text


def normalize_columns(columns) -> list[str]:
    return [
        re.sub(r"[^a-z0-9]+", "_", str(col).strip().lower()).strip("_")
        for col in columns
    ]


def read_uploaded_file(uploaded) -> pd.DataFrame:
    suffix = Path(uploaded.name).suffix.casefold()

    if suffix == ".csv":
        return pd.read_csv(
            uploaded,
            dtype="string",
            keep_default_na=False,
            na_filter=False,
        )

    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(uploaded, dtype="string")

    raise ValueError("Supported formats are CSV, XLSX, and XLS.")


@st.cache_data(show_spinner=False)
def load_default_catalog(path: str) -> pd.DataFrame:
    return pd.read_csv(
        path,
        dtype="string",
        keep_default_na=False,
        na_filter=False,
    )


def prepare_catalog(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df.columns = normalize_columns(df.columns)

    for required in REQUIRED_COLUMNS:
        if required not in df.columns:
            df[required] = pd.NA

    for column in df.columns:
        df[column] = df[column].map(normalize_blank).astype("string")

    df["release_year_num"] = pd.to_numeric(
        df["release_year"], errors="coerce"
    ).astype("Int64")

    date_added = pd.to_datetime(df["date_added"], errors="coerce")
    df["date_added_year"] = date_added.dt.year.astype("Int64")
    df["date_added_month"] = date_added.dt.month.astype("Int64")

    df["duration_value"] = pd.to_numeric(
        df["duration"].str.extract(r"(\d+)", expand=False),
        errors="coerce",
    )

    return df


def split_values(series: pd.Series) -> pd.Series:
    return (
        series.dropna()
        .astype(str)
        .str.split(r"\s*,\s*", regex=True)
        .explode()
        .astype("string")
        .str.strip()
        .replace("", pd.NA)
        .dropna()
    )


def build_database(df: pd.DataFrame) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")

    sql_df = df.copy()
    for col in sql_df.columns:
        if str(sql_df[col].dtype) == "Int64":
            sql_df[col] = sql_df[col].astype("float")

    sql_df.to_sql("catalog", conn, index=False, if_exists="replace")
    return conn


def validate_read_only_sql(sql: str) -> tuple[bool, str]:
    cleaned = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL).strip()

    if not re.match(r"^(SELECT|WITH)\b", cleaned, flags=re.IGNORECASE):
        return False, "Only SELECT and WITH queries are allowed."

    blocked = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|"
        r"ATTACH|DETACH|PRAGMA|VACUUM|REINDEX)\b",
        flags=re.IGNORECASE,
    )

    if blocked.search(cleaned):
        return False, "A blocked write or schema command was detected."

    statements = [part.strip() for part in cleaned.split(";") if part.strip()]
    if len(statements) != 1:
        return False, "Only one SQL statement may be executed."

    return True, ""


def extract_year(question: str) -> int | None:
    match = re.search(r"\b(?:19|20)\d{2}\b", question)
    return int(match.group(0)) if match else None


def plan_query(question: str) -> dict[str, str]:
    q = question.casefold().strip()
    year = extract_year(question)

    if ("country" in q or "countries" in q) and ("tv" in q or "show" in q):
        return {
            "title": "Countries producing the most TV shows",
            "summary": (
                "The catalog was filtered to TV shows, multi-country values were "
                "split into individual countries, and titles were counted once per country."
            ),
            "sql": """
WITH RECURSIVE split(show_id, country, rest) AS (
    SELECT
        show_id,
        TRIM(SUBSTR(COALESCE(country, '') || ',', 1,
             INSTR(COALESCE(country, '') || ',', ',') - 1)),
        SUBSTR(COALESCE(country, '') || ',',
             INSTR(COALESCE(country, '') || ',', ',') + 1)
    FROM catalog
    WHERE type = 'TV Show'
    UNION ALL
    SELECT
        show_id,
        TRIM(SUBSTR(rest, 1, INSTR(rest, ',') - 1)),
        SUBSTR(rest, INSTR(rest, ',') + 1)
    FROM split
    WHERE rest <> ''
)
SELECT country, COUNT(DISTINCT show_id) AS tv_shows
FROM split
WHERE country <> ''
GROUP BY country
ORDER BY tv_shows DESC
LIMIT 25
""".strip(),
        }

    if "country" in q or "countries" in q:
        return {
            "title": "Top countries represented in the catalog",
            "summary": (
                "Multi-country records were split first, preventing combinations "
                "such as 'United States, Canada' from being counted as a country."
            ),
            "sql": """
WITH RECURSIVE split(show_id, country, rest) AS (
    SELECT
        show_id,
        TRIM(SUBSTR(COALESCE(country, '') || ',', 1,
             INSTR(COALESCE(country, '') || ',', ',') - 1)),
        SUBSTR(COALESCE(country, '') || ',',
             INSTR(COALESCE(country, '') || ',', ',') + 1)
    FROM catalog
    UNION ALL
    SELECT
        show_id,
        TRIM(SUBSTR(rest, 1, INSTR(rest, ',') - 1)),
        SUBSTR(rest, INSTR(rest, ',') + 1)
    FROM split
    WHERE rest <> ''
)
SELECT country, COUNT(DISTINCT show_id) AS titles
FROM split
WHERE country <> ''
GROUP BY country
ORDER BY titles DESC
LIMIT 25
""".strip(),
        }

    if "director" in q:
        return {
            "title": "Directors with the most catalog titles",
            "summary": "Multi-director records were split before counting titles.",
            "sql": """
WITH RECURSIVE split(show_id, director, rest) AS (
    SELECT
        show_id,
        TRIM(SUBSTR(COALESCE(director, '') || ',', 1,
             INSTR(COALESCE(director, '') || ',', ',') - 1)),
        SUBSTR(COALESCE(director, '') || ',',
             INSTR(COALESCE(director, '') || ',', ',') + 1)
    FROM catalog
    UNION ALL
    SELECT
        show_id,
        TRIM(SUBSTR(rest, 1, INSTR(rest, ',') - 1)),
        SUBSTR(rest, INSTR(rest, ',') + 1)
    FROM split
    WHERE rest <> ''
)
SELECT director, COUNT(DISTINCT show_id) AS titles
FROM split
WHERE director <> ''
GROUP BY director
ORDER BY titles DESC
LIMIT 25
""".strip(),
        }

    if "actor" in q or "cast" in q:
        return {
            "title": "Most frequently listed cast members",
            "summary": "Cast lists were split into individual names before counting.",
            "sql": """
WITH RECURSIVE split(show_id, cast_member, rest) AS (
    SELECT
        show_id,
        TRIM(SUBSTR(COALESCE(cast, '') || ',', 1,
             INSTR(COALESCE(cast, '') || ',', ',') - 1)),
        SUBSTR(COALESCE(cast, '') || ',',
             INSTR(COALESCE(cast, '') || ',', ',') + 1)
    FROM catalog
    UNION ALL
    SELECT
        show_id,
        TRIM(SUBSTR(rest, 1, INSTR(rest, ',') - 1)),
        SUBSTR(rest, INSTR(rest, ',') + 1)
    FROM split
    WHERE rest <> ''
)
SELECT cast_member, COUNT(DISTINCT show_id) AS titles
FROM split
WHERE cast_member <> ''
GROUP BY cast_member
ORDER BY titles DESC
LIMIT 25
""".strip(),
        }

    if "genre" in q or "category" in q:
        return {
            "title": "Most common genres and categories",
            "summary": "Catalog categories were split before titles were counted.",
            "sql": """
WITH RECURSIVE split(show_id, genre, rest) AS (
    SELECT
        show_id,
        TRIM(SUBSTR(COALESCE(listed_in, '') || ',', 1,
             INSTR(COALESCE(listed_in, '') || ',', ',') - 1)),
        SUBSTR(COALESCE(listed_in, '') || ',',
             INSTR(COALESCE(listed_in, '') || ',', ',') + 1)
    FROM catalog
    UNION ALL
    SELECT
        show_id,
        TRIM(SUBSTR(rest, 1, INSTR(rest, ',') - 1)),
        SUBSTR(rest, INSTR(rest, ',') + 1)
    FROM split
    WHERE rest <> ''
)
SELECT genre, COUNT(DISTINCT show_id) AS titles
FROM split
WHERE genre <> ''
GROUP BY genre
ORDER BY titles DESC
LIMIT 25
""".strip(),
        }

    if "rating" in q:
        return {
            "title": "Catalog ratings distribution",
            "summary": "The result counts nonblank ratings across the catalog.",
            "sql": """
SELECT rating, COUNT(*) AS titles
FROM catalog
WHERE rating IS NOT NULL AND TRIM(rating) <> ''
GROUP BY rating
ORDER BY titles DESC
""".strip(),
        }

    if "missing" in q or "blank" in q or "complete" in q:
        return {
            "title": "Catalog metadata completeness",
            "summary": "Blank-like values were normalized before missing fields were counted.",
            "sql": """
SELECT
    SUM(CASE WHEN director IS NULL OR TRIM(director) = '' THEN 1 ELSE 0 END) AS missing_director,
    SUM(CASE WHEN cast IS NULL OR TRIM(cast) = '' THEN 1 ELSE 0 END) AS missing_cast,
    SUM(CASE WHEN country IS NULL OR TRIM(country) = '' THEN 1 ELSE 0 END) AS missing_country,
    SUM(CASE WHEN date_added IS NULL OR TRIM(date_added) = '' THEN 1 ELSE 0 END) AS missing_date_added,
    SUM(CASE WHEN rating IS NULL OR TRIM(rating) = '' THEN 1 ELSE 0 END) AS missing_rating,
    SUM(CASE WHEN duration IS NULL OR TRIM(duration) = '' THEN 1 ELSE 0 END) AS missing_duration
FROM catalog
""".strip(),
        }

    if "longest" in q or "runtime" in q or "duration" in q:
        return {
            "title": "Longest movies in the catalog",
            "summary": "Movie duration was converted to a number before sorting.",
            "sql": """
SELECT title, country, release_year, rating, duration, listed_in
FROM catalog
WHERE type = 'Movie' AND duration_value IS NOT NULL
ORDER BY duration_value DESC
LIMIT 100
""".strip(),
        }

    if "newest" in q or "latest" in q:
        return {
            "title": "Newest releases in the catalog",
            "summary": "Titles are sorted by numeric release year, newest first.",
            "sql": """
SELECT show_id, type, title, country, release_year, rating, duration, listed_in
FROM catalog
WHERE release_year_num IS NOT NULL
ORDER BY release_year_num DESC, title
LIMIT 250
""".strip(),
        }

    if year and ("after" in q or "since" in q):
        genre_filter = ""
        if "horror" in q:
            genre_filter = (
                "AND LOWER(COALESCE(listed_in, '')) LIKE '%horror%'"
            )

        return {
            "title": f"Catalog titles released since {year}",
            "summary": f"The result includes titles released in {year} or later.",
            "sql": f"""
SELECT show_id, type, title, country, release_year, rating, duration, listed_in
FROM catalog
WHERE release_year_num >= {year}
{genre_filter}
ORDER BY release_year_num DESC, title
LIMIT 500
""".strip(),
        }

    return {
        "title": "Catalog overview records",
        "summary": (
            "This API-free planner did not confidently match the question to a "
            "specialized template, so it returned a safe, read-only catalog view."
        ),
        "sql": """
SELECT show_id, type, title, director, country,
       release_year, rating, duration, listed_in
FROM catalog
ORDER BY release_year_num DESC, title
LIMIT 250
""".strip(),
    }


def create_template_workbook() -> bytes:
    example = pd.DataFrame(
        [
            {
                "show_id": "example_001",
                "type": "Movie",
                "title": "Example Title",
                "director": "",
                "cast": "",
                "country": "United States",
                "date_added": "September 1, 2021",
                "release_year": "2021",
                "rating": "TV-14",
                "duration": "95 min",
                "listed_in": "Dramas, Independent Movies",
                "description": "Example catalog description.",
            }
        ],
        columns=REQUIRED_COLUMNS,
    )

    notes = pd.DataFrame(
        {
            "Field": REQUIRED_COLUMNS,
            "Expected format": [
                "Unique text ID",
                "Movie or TV Show",
                "Title text",
                "Comma-separated names; blank allowed",
                "Comma-separated names; blank allowed",
                "Comma-separated countries; blank allowed",
                "Month D, YYYY; blank allowed",
                "Four-digit year",
                "Rating text; blank allowed",
                "Examples: 95 min or 2 Seasons",
                "Comma-separated categories",
                "Description text; blank allowed",
            ],
        }
    )

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        example.to_excel(writer, index=False, sheet_name="Catalog Template")
        notes.to_excel(writer, index=False, sheet_name="Field Guide")

    return output.getvalue()


def dataframe_to_excel(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Results")
    return output.getvalue()


def dataframe_to_pdf(
    title: str,
    question: str,
    summary: str,
    df: pd.DataFrame,
) -> bytes:
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=landscape(letter),
        rightMargin=0.35 * inch,
        leftMargin=0.35 * inch,
        topMargin=0.35 * inch,
        bottomMargin=0.35 * inch,
    )

    styles = getSampleStyleSheet()
    story = [
        Paragraph(title, styles["Title"]),
        Spacer(1, 8),
        Paragraph(f"<b>Question:</b> {question}", styles["BodyText"]),
        Spacer(1, 6),
        Paragraph(summary, styles["BodyText"]),
        Spacer(1, 12),
    ]

    export_df = df.head(250).fillna("").astype(str)
    if export_df.empty:
        story.append(Paragraph("No records were returned.", styles["BodyText"]))
    else:
        max_columns = min(len(export_df.columns), 9)
        export_df = export_df.iloc[:, :max_columns]

        data = [export_df.columns.tolist()]
        for row in export_df.itertuples(index=False, name=None):
            wrapped = [
                "\n".join(textwrap.wrap(str(value), width=28))[:500]
                for value in row
            ]
            data.append(wrapped)

        table = Table(data, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9EAF7")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F6F6")]),
                ]
            )
        )
        story.append(table)

    document.build(story)
    return output.getvalue()


def render_catalog_overview(df: pd.DataFrame) -> None:
    countries = split_values(df["country"])
    genres = split_values(df["listed_in"])

    st.subheader("Netflix titles catalog overview")

    first_row = st.columns(4)
    first_row[0].metric("Titles", f"{len(df):,}")
    first_row[1].metric("Movies", f"{int(df['type'].eq('Movie').sum()):,}")
    first_row[2].metric("TV shows", f"{int(df['type'].eq('TV Show').sum()):,}")
    first_row[3].metric("Countries", f"{countries.str.casefold().nunique():,}")

    second_row = st.columns(4)
    second_row[0].metric("Genres", f"{genres.str.casefold().nunique():,}")
    second_row[1].metric("Missing directors", f"{int(df['director'].isna().sum()):,}")
    second_row[2].metric("Missing cast", f"{int(df['cast'].isna().sum()):,}")
    second_row[3].metric("Missing countries", f"{int(df['country'].isna().sum()):,}")


def choose_catalog() -> tuple[pd.DataFrame | None, str | None]:
    st.subheader("Choose a catalog")

    choice = st.radio(
        "Would you like to use the existing Netflix titles catalog or upload a new catalog?",
        [
            "Use the existing Netflix titles catalog",
            "Upload a new CSV or Excel catalog",
        ],
        horizontal=True,
    )

    template_bytes = create_template_workbook()
    st.download_button(
        "Download catalog upload template",
        template_bytes,
        file_name="streamvault_catalog_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    with st.expander("Required upload format"):
        st.write(
            "The template includes the expected columns and a field guide. "
            "Blank cells are accepted and treated as empty."
        )
        st.code(", ".join(REQUIRED_COLUMNS), language="text")

    if choice == "Use the existing Netflix titles catalog":
        for candidate in DEFAULT_CSV_CANDIDATES:
            if Path(candidate).exists():
                return prepare_catalog(load_default_catalog(candidate)), candidate

        st.error(
            "The default Netflix catalog was not found. Place netflix_titles.csv "
            "in the project folder."
        )
        return None, None

    uploaded = st.file_uploader(
        "Upload your catalog",
        type=["csv", "xlsx", "xls"],
        help="Supported file types: .csv, .xlsx, and .xls",
    )

    if uploaded is None:
        return None, None

    try:
        raw = read_uploaded_file(uploaded)
        return prepare_catalog(raw), uploaded.name
    except Exception as exc:
        st.error(f"The uploaded catalog could not be read: {exc}")
        return None, None


@st.dialog("Ask the catalog", width="large")
def query_dialog(df: pd.DataFrame, catalog_name: str) -> None:
    st.caption(f"Active catalog: {catalog_name}")

    examples = [
        "Which countries produce the most TV shows?",
        "Which directors have the most titles?",
        "Which genres are most common?",
        "Which ratings are most common?",
        "Which records have missing metadata?",
        "Show the longest movies.",
    ]

    template = st.selectbox(
        "Choose a sample question",
        ["Write my own question"] + examples,
    )

    initial = "" if template == "Write my own question" else template
    question = st.text_area(
        "Ask a business question in everyday language",
        value=initial,
        placeholder="Example: Which countries produce the most TV shows?",
        height=120,
    )

    if not st.button("Process question", type="primary", use_container_width=True):
        return

    if not question.strip():
        st.warning("Enter a business question.")
        return

    with st.status("Processing your question...", expanded=True) as status:
        st.write("Reading the active catalog...")
        conn = build_database(df)

        st.write("Matching the question to a local report template...")
        plan = plan_query(question)

        st.write("Validating read-only SQL...")
        valid, reason = validate_read_only_sql(plan["sql"])
        if not valid:
            status.update(label="Query blocked", state="error")
            st.error(reason)
            return

        st.write("Running the query...")
        try:
            result = pd.read_sql_query(plan["sql"], conn)
        except Exception as exc:
            status.update(label="Query failed", state="error")
            st.error(f"The query could not run: {exc}")
            return

        status.update(label="Analysis complete", state="complete")

    st.subheader(plan["title"])
    st.write(plan["summary"])

    if result.empty:
        st.warning("No matching records were found.")
    else:
        st.dataframe(result, hide_index=True, use_container_width=True)

    with st.expander("Verify read-only SQL"):
        st.code(plan["sql"], language="sql")
        st.success(
            "Verified: the local engine permits one SELECT or WITH statement only."
        )

    pdf_bytes = dataframe_to_pdf(
        plan["title"],
        question,
        plan["summary"],
        result,
    )
    csv_bytes = result.to_csv(index=False).encode("utf-8")
    excel_bytes = dataframe_to_excel(result)

    st.subheader("Download results")
    download_columns = st.columns(3)

    download_columns[0].download_button(
        "Download PDF",
        pdf_bytes,
        file_name="streamvault_results.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

    download_columns[1].download_button(
        "Download CSV",
        csv_bytes,
        file_name="streamvault_results.csv",
        mime="text/csv",
        use_container_width=True,
    )

    download_columns[2].download_button(
        "Download Excel",
        excel_bytes,
        file_name="streamvault_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


def main() -> None:
    st.title("STREAMVAULT")
    st.caption(
        "API-free catalog analysis using local rules and read-only SQL."
    )

    df, catalog_name = choose_catalog()

    if df is None or catalog_name is None:
        st.info("Select the existing catalog or upload a new catalog to continue.")
        return

    render_catalog_overview(df)

    st.divider()
    st.success(f"Active catalog: {catalog_name}")

    if st.button(
        "Ask a business question",
        type="primary",
        use_container_width=True,
    ):
        query_dialog(df, catalog_name)


if __name__ == "__main__":
    main()

'@

Set-Content `
    -Path ".\streamvault_dashboard.py" `
    -Value $appCode `
    -Encoding UTF8

if ((Test-Path ".\netflix_titles(1).csv") -and (-not (Test-Path ".\netflix_titles.csv"))) {
    Copy-Item ".\netflix_titles(1).csv" ".\netflix_titles.csv" -Force
}

Write-Host "Checking for the default Netflix catalog..."
if (-not (Test-Path ".\netflix_titles.csv")) {
    Write-Host "WARNING: netflix_titles.csv is not in this folder." -ForegroundColor Yellow
}

Write-Host "Clearing Streamlit cache..."
python -m streamlit cache clear

Write-Host ""
Write-Host "Launching STREAMVAULT..." -ForegroundColor Green
python -m streamlit run .\streamvault_dashboard.py
