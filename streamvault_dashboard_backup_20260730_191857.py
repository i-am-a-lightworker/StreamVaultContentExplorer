from __future__ import annotations

import io
import re
import sqlite3
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


st.set_page_config(
    page_title="STREAMVAULT Catalog Analyst",
    page_icon="ðŸŽ¬",
    layout="wide",
)

DEFAULT_CSV_CANDIDATES = ("netflix_titles.csv", "netflix_titles(1).csv")

REQUIRED_COLUMNS = [
    "show_id", "type", "title", "director", "cast", "country",
    "date_added", "release_year", "rating", "duration",
    "listed_in", "description",
]

BLANK_TOKENS = {
    "", " ", "none", "null", "nan", "n/a", "na",
    "nothing", "blank", "unknown", "-", "--",
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
        return pd.read_csv(uploaded, dtype="string", keep_default_na=False, na_filter=False)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(uploaded, dtype="string")
    raise ValueError("Supported formats are CSV, XLSX, and XLS.")


@st.cache_data(show_spinner=False)
def load_default_catalog(path: str) -> pd.DataFrame:
    return pd.read_csv(path, dtype="string", keep_default_na=False, na_filter=False)


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

    parsed = pd.to_datetime(df["date_added"], errors="coerce")
    df["date_added_year"] = parsed.dt.year.astype("Int64")
    df["date_added_month"] = parsed.dt.month.astype("Int64")
    df["date_added_date"] = parsed.dt.strftime("%Y-%m-%d").astype("string")

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


REPORTS = {
    "Catalog Executive Summary": {
        "group": "Catalog Health",
        "purpose": "Review catalog size, format mix, market breadth, and release range.",
        "summary": "This report provides a one-page snapshot of the active catalog.",
        "sql": """
SELECT
    COUNT(*) AS total_titles,
    SUM(CASE WHEN type = 'Movie' THEN 1 ELSE 0 END) AS movies,
    SUM(CASE WHEN type = 'TV Show' THEN 1 ELSE 0 END) AS tv_shows,
    MIN(release_year_num) AS oldest_release_year,
    MAX(release_year_num) AS newest_release_year,
    SUM(CASE WHEN director IS NULL OR TRIM(director) = '' THEN 1 ELSE 0 END) AS missing_director,
    SUM(CASE WHEN cast IS NULL OR TRIM(cast) = '' THEN 1 ELSE 0 END) AS missing_cast,
    SUM(CASE WHEN country IS NULL OR TRIM(country) = '' THEN 1 ELSE 0 END) AS missing_country
FROM catalog
""".strip(),
    },
    "Missing Metadata Audit": {
        "group": "Catalog Health",
        "purpose": "Measure field completeness and identify metadata gaps.",
        "summary": "This report counts missing values in the most important catalog fields.",
        "sql": """
SELECT 'director' AS field,
       SUM(CASE WHEN director IS NULL OR TRIM(director) = '' THEN 1 ELSE 0 END) AS missing_records,
       ROUND(100.0 * SUM(CASE WHEN director IS NULL OR TRIM(director) = '' THEN 1 ELSE 0 END) / COUNT(*), 2) AS missing_percent
FROM catalog
UNION ALL
SELECT 'cast',
       SUM(CASE WHEN cast IS NULL OR TRIM(cast) = '' THEN 1 ELSE 0 END),
       ROUND(100.0 * SUM(CASE WHEN cast IS NULL OR TRIM(cast) = '' THEN 1 ELSE 0 END) / COUNT(*), 2)
FROM catalog
UNION ALL
SELECT 'country',
       SUM(CASE WHEN country IS NULL OR TRIM(country) = '' THEN 1 ELSE 0 END),
       ROUND(100.0 * SUM(CASE WHEN country IS NULL OR TRIM(country) = '' THEN 1 ELSE 0 END) / COUNT(*), 2)
FROM catalog
UNION ALL
SELECT 'date_added',
       SUM(CASE WHEN date_added IS NULL OR TRIM(date_added) = '' THEN 1 ELSE 0 END),
       ROUND(100.0 * SUM(CASE WHEN date_added IS NULL OR TRIM(date_added) = '' THEN 1 ELSE 0 END) / COUNT(*), 2)
FROM catalog
UNION ALL
SELECT 'rating',
       SUM(CASE WHEN rating IS NULL OR TRIM(rating) = '' THEN 1 ELSE 0 END),
       ROUND(100.0 * SUM(CASE WHEN rating IS NULL OR TRIM(rating) = '' THEN 1 ELSE 0 END) / COUNT(*), 2)
FROM catalog
UNION ALL
SELECT 'duration',
       SUM(CASE WHEN duration IS NULL OR TRIM(duration) = '' THEN 1 ELSE 0 END),
       ROUND(100.0 * SUM(CASE WHEN duration IS NULL OR TRIM(duration) = '' THEN 1 ELSE 0 END) / COUNT(*), 2)
FROM catalog
UNION ALL
SELECT 'description',
       SUM(CASE WHEN description IS NULL OR TRIM(description) = '' THEN 1 ELSE 0 END),
       ROUND(100.0 * SUM(CASE WHEN description IS NULL OR TRIM(description) = '' THEN 1 ELSE 0 END) / COUNT(*), 2)
FROM catalog
ORDER BY missing_records DESC
""".strip(),
    },
    "Duplicate Title Audit": {
        "group": "Catalog Health",
        "purpose": "Find repeated IDs, repeated rows, and repeated title-year combinations.",
        "summary": "This report flags possible duplicates that may inflate catalog counts.",
        "sql": """
SELECT
    title,
    release_year,
    type,
    COUNT(*) AS duplicate_count
FROM catalog
WHERE title IS NOT NULL AND TRIM(title) <> ''
GROUP BY title, release_year, type
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC, title
""".strip(),
    },
    "Movies vs TV Shows": {
        "group": "Content Mix",
        "purpose": "Compare the catalog share of movies and television shows.",
        "summary": "This report compares title counts and catalog share by format.",
        "sql": """
SELECT
    type,
    COUNT(*) AS titles,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM catalog), 2) AS catalog_share_percent
FROM catalog
WHERE type IS NOT NULL AND TRIM(type) <> ''
GROUP BY type
ORDER BY titles DESC
""".strip(),
    },
    "Genre Portfolio": {
        "group": "Content Mix",
        "purpose": "Review the most represented genres and categories.",
        "summary": "Multi-genre records are split before titles are counted.",
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
LIMIT 50
""".strip(),
    },
    "Ratings Distribution": {
        "group": "Content Mix",
        "purpose": "Compare how titles are distributed across content ratings.",
        "summary": "This report counts nonblank ratings across the active catalog.",
        "sql": """
SELECT
    rating,
    COUNT(*) AS titles,
    ROUND(100.0 * COUNT(*) / (
        SELECT COUNT(*) FROM catalog
        WHERE rating IS NOT NULL AND TRIM(rating) <> ''
    ), 2) AS share_percent
FROM catalog
WHERE rating IS NOT NULL AND TRIM(rating) <> ''
GROUP BY rating
ORDER BY titles DESC
""".strip(),
    },
    "Runtime and Season Profile": {
        "group": "Content Mix",
        "purpose": "Review movie runtimes and TV-show season counts.",
        "summary": "Duration values are converted to numbers before the profile is calculated.",
        "sql": """
SELECT
    type,
    COUNT(*) AS titles_with_duration,
    ROUND(AVG(duration_value), 1) AS average_duration_value,
    MIN(duration_value) AS minimum_duration_value,
    MAX(duration_value) AS maximum_duration_value
FROM catalog
WHERE duration_value IS NOT NULL
GROUP BY type
ORDER BY type
""".strip(),
    },
    "Titles Added by Year": {
        "group": "Catalog Timing",
        "purpose": "Track how many titles entered the catalog each year.",
        "summary": "This report uses date_added rather than release_year.",
        "sql": """
SELECT
    date_added_year AS year_added,
    COUNT(*) AS titles_added,
    SUM(CASE WHEN type = 'Movie' THEN 1 ELSE 0 END) AS movies_added,
    SUM(CASE WHEN type = 'TV Show' THEN 1 ELSE 0 END) AS tv_shows_added
FROM catalog
WHERE date_added_year IS NOT NULL
GROUP BY date_added_year
ORDER BY date_added_year
""".strip(),
    },
    "Release Age": {
        "group": "Catalog Timing",
        "purpose": "Separate recent releases from older library content.",
        "summary": "Release age is calculated against the newest release year in the active catalog.",
        "sql": """
WITH max_year AS (
    SELECT MAX(release_year_num) AS newest_year FROM catalog
)
SELECT
    CASE
        WHEN release_year_num >= newest_year - 2 THEN 'Released within 2 years'
        WHEN release_year_num >= newest_year - 5 THEN 'Released 3-5 years ago'
        WHEN release_year_num >= newest_year - 10 THEN 'Released 6-10 years ago'
        ELSE 'Released more than 10 years ago'
    END AS release_age_group,
    COUNT(*) AS titles
FROM catalog, max_year
WHERE release_year_num IS NOT NULL
GROUP BY release_age_group
ORDER BY
    CASE release_age_group
        WHEN 'Released within 2 years' THEN 1
        WHEN 'Released 3-5 years ago' THEN 2
        WHEN 'Released 6-10 years ago' THEN 3
        ELSE 4
    END
""".strip(),
    },
    "New vs Library Titles": {
        "group": "Catalog Timing",
        "purpose": "Measure the delay between release and catalog addition.",
        "summary": "This report compares release year with the year a title was added.",
        "sql": """
SELECT
    CASE
        WHEN date_added_year IS NULL OR release_year_num IS NULL THEN 'Unknown'
        WHEN date_added_year - release_year_num <= 1 THEN 'Added within 1 year of release'
        WHEN date_added_year - release_year_num <= 5 THEN 'Added 2-5 years after release'
        WHEN date_added_year - release_year_num <= 10 THEN 'Added 6-10 years after release'
        ELSE 'Added more than 10 years after release'
    END AS addition_delay_group,
    COUNT(*) AS titles
FROM catalog
GROUP BY addition_delay_group
ORDER BY titles DESC
""".strip(),
    },
    "Recent Catalog Additions": {
        "group": "Catalog Timing",
        "purpose": "Review the newest records added to the catalog.",
        "summary": "The newest parsed date_added records appear first.",
        "sql": """
SELECT
    show_id, type, title, country, release_year,
    rating, duration, listed_in, date_added
FROM catalog
WHERE date_added_date IS NOT NULL
ORDER BY date_added_date DESC, title
LIMIT 250
""".strip(),
    },
    "Country Portfolio": {
        "group": "Markets & Talent",
        "purpose": "Review title counts by individual country.",
        "summary": "Multi-country records are split before counting.",
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
LIMIT 75
""".strip(),
    },
    "International Content Mix": {
        "group": "Markets & Talent",
        "purpose": "Compare U.S.-only, international, multinational, and unknown records.",
        "summary": "This report classifies records by the country field as stored in the catalog.",
        "sql": """
SELECT
    CASE
        WHEN country IS NULL OR TRIM(country) = '' THEN 'Missing country'
        WHEN country = 'United States' THEN 'United States only'
        WHEN INSTR(country, ',') > 0 THEN 'Multinational production'
        ELSE 'Non-United States'
    END AS market_group,
    COUNT(*) AS titles
FROM catalog
GROUP BY market_group
ORDER BY titles DESC
""".strip(),
    },
    "Top Directors": {
        "group": "Markets & Talent",
        "purpose": "Identify directors with the most catalog appearances.",
        "summary": "Multi-director records are split before counting.",
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
LIMIT 50
""".strip(),
    },
    "Top Cast Members": {
        "group": "Markets & Talent",
        "purpose": "Identify cast members appearing most often in the catalog.",
        "summary": "This measures catalog appearances, not popularity or audience performance.",
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
LIMIT 50
""".strip(),
    },
}


def create_template_workbook() -> bytes:
    example = pd.DataFrame(
        [{
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
        }],
        columns=REQUIRED_COLUMNS,
    )
    notes = pd.DataFrame({
        "Field": REQUIRED_COLUMNS,
        "Expected format": [
            "Unique text ID", "Movie or TV Show", "Title text",
            "Comma-separated names; blank allowed",
            "Comma-separated names; blank allowed",
            "Comma-separated countries; blank allowed",
            "Month D, YYYY; blank allowed", "Four-digit year",
            "Rating text; blank allowed", "Examples: 95 min or 2 Seasons",
            "Comma-separated categories", "Description text; blank allowed",
        ],
    })
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


def dataframe_to_pdf(title: str, summary: str, df: pd.DataFrame) -> bytes:
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
        Paragraph(summary, styles["BodyText"]),
        Spacer(1, 12),
    ]

    export_df = df.head(250).fillna("").astype(str)
    if export_df.empty:
        story.append(Paragraph("No records were returned.", styles["BodyText"]))
    else:
        export_df = export_df.iloc[:, : min(len(export_df.columns), 9)]
        data = [export_df.columns.tolist()]
        for row in export_df.itertuples(index=False, name=None):
            data.append([
                "\n".join(textwrap.wrap(str(value), width=28))[:500]
                for value in row
            ])

        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9EAF7")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F6F6F6")]),
        ]))
        story.append(table)

    document.build(story)
    return output.getvalue()


def choose_catalog() -> tuple[pd.DataFrame | None, str | None]:
    choice = st.radio(
        "Which catalog would you like to use?",
        [
            "Use the existing Netflix titles catalog",
            "Upload a new CSV or Excel catalog",
        ],
        horizontal=True,
    )

    st.download_button(
        "Download upload template",
        create_template_workbook(),
        file_name="streamvault_catalog_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    if choice == "Use the existing Netflix titles catalog":
        for candidate in DEFAULT_CSV_CANDIDATES:
            if Path(candidate).exists():
                return prepare_catalog(load_default_catalog(candidate)), candidate
        st.error("Place netflix_titles.csv in this project folder.")
        return None, None

    uploaded = st.file_uploader(
        "Upload catalog",
        type=["csv", "xlsx", "xls"],
    )
    if uploaded is None:
        return None, None

    try:
        return prepare_catalog(read_uploaded_file(uploaded)), uploaded.name
    except Exception as exc:
        st.error(f"Could not read the uploaded catalog: {exc}")
        return None, None


def render_overview(df: pd.DataFrame) -> None:
    countries = split_values(df["country"])
    genres = split_values(df["listed_in"])

    st.subheader("Catalog overview")
    row1 = st.columns(4)
    row1[0].metric("Titles", f"{len(df):,}")
    row1[1].metric("Movies", f"{int(df['type'].eq('Movie').sum()):,}")
    row1[2].metric("TV shows", f"{int(df['type'].eq('TV Show').sum()):,}")
    row1[3].metric("Countries", f"{countries.str.casefold().nunique():,}")

    row2 = st.columns(4)
    row2[0].metric("Genres", f"{genres.str.casefold().nunique():,}")
    row2[1].metric("Missing directors", f"{int(df['director'].isna().sum()):,}")
    row2[2].metric("Missing cast", f"{int(df['cast'].isna().sum()):,}")
    row2[3].metric("Missing countries", f"{int(df['country'].isna().sum()):,}")


def run_report(df: pd.DataFrame, report_name: str) -> None:
    report = REPORTS[report_name]

    with st.status(f"Running {report_name}...", expanded=True) as status:
        st.write("Loading the active catalog...")
        conn = build_database(df)

        st.write("Validating the saved read-only SQL...")
        valid, reason = validate_read_only_sql(report["sql"])
        if not valid:
            status.update(label="Report blocked", state="error")
            st.error(reason)
            return

        st.write("Executing the local report...")
        try:
            result = pd.read_sql_query(report["sql"], conn)
        except Exception as exc:
            status.update(label="Report failed", state="error")
            st.error(str(exc))
            return

        status.update(label="Report complete", state="complete")

    st.session_state["last_report_name"] = report_name
    st.session_state["last_report_time"] = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    st.session_state["last_report_result"] = result
    st.session_state["last_report_sql"] = report["sql"]
    st.session_state["last_report_summary"] = report["summary"]


def render_report_result() -> None:
    if "last_report_result" not in st.session_state:
        return

    name = st.session_state["last_report_name"]
    result = st.session_state["last_report_result"]
    summary = st.session_state["last_report_summary"]
    sql = st.session_state["last_report_sql"]

    st.divider()
    st.subheader(name)
    st.write(summary)
    st.caption(f"Last run: {st.session_state['last_report_time']}")
    st.dataframe(result, hide_index=True, use_container_width=True)

    with st.expander("Verify read-only SQL"):
        st.code(sql, language="sql")
        st.success("Verified: one local SELECT or WITH statement only.")

    downloads = st.columns(3)
    downloads[0].download_button(
        "Download PDF",
        dataframe_to_pdf(name, summary, result),
        file_name=f"{name.lower().replace(' ', '_')}.pdf",
        mime="application/pdf",
        use_container_width=True,
    )
    downloads[1].download_button(
        "Download CSV",
        result.to_csv(index=False).encode("utf-8"),
        file_name=f"{name.lower().replace(' ', '_')}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[2].download_button(
        "Download Excel",
        dataframe_to_excel(result),
        file_name=f"{name.lower().replace(' ', '_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


def render_standard_reports(df: pd.DataFrame) -> None:
    st.subheader("Standard reports")
    st.caption("Run recurring catalog reports without writing a question.")

    featured = [
        "Catalog Executive Summary",
        "Titles Added by Year",
        "Genre Portfolio",
        "Country Portfolio",
        "Missing Metadata Audit",
    ]

    st.markdown("### Featured reports")
    featured_cols = st.columns(len(featured))
    for index, report_name in enumerate(featured):
        report = REPORTS[report_name]
        with featured_cols[index]:
            st.markdown(f"**{report_name}**")
            st.caption(report["purpose"])
            if st.button(
                "Run report",
                key=f"featured_{report_name}",
                use_container_width=True,
            ):
                run_report(df, report_name)
                st.rerun()

    for group in ["Catalog Health", "Content Mix", "Catalog Timing", "Markets & Talent"]:
        st.markdown(f"### {group}")
        names = [name for name, data in REPORTS.items() if data["group"] == group]

        for start in range(0, len(names), 3):
            cols = st.columns(3)
            for offset, report_name in enumerate(names[start:start + 3]):
                report = REPORTS[report_name]
                with cols[offset]:
                    with st.container(border=True):
                        st.markdown(f"**{report_name}**")
                        st.write(report["purpose"])
                        if st.button(
                            "Run report",
                            key=f"report_{report_name}",
                            use_container_width=True,
                        ):
                            run_report(df, report_name)
                            st.rerun()


def main() -> None:
    st.title("STREAMVAULT")
    st.caption("API-free catalog intelligence using local templates and read-only SQL.")

    df, catalog_name = choose_catalog()
    if df is None or catalog_name is None:
        st.info("Select the existing catalog or upload a catalog to continue.")
        return

    st.success(f"Active catalog: {catalog_name}")
    render_overview(df)

    tab_reports, tab_data = st.tabs(["Standard Reports", "Catalog Records"])

    with tab_reports:
        render_standard_reports(df)
        render_report_result()

    with tab_data:
        st.dataframe(
            df[REQUIRED_COLUMNS],
            hide_index=True,
            use_container_width=True,
        )


if __name__ == "__main__":
    main()

