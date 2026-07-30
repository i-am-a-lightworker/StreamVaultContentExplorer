from __future__ import annotations

import io
import re
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="STREAMVAULT Catalog Analyst",
    page_icon="ðŸŽ¬",
    layout="wide",
)

DATA_FILE = "netflix_titles.csv"
DB_TABLE = "catalog"

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


@st.cache_data(show_spinner=False)
def load_catalog(source) -> pd.DataFrame:
    df = pd.read_csv(
        source,
        dtype="string",
        keep_default_na=False,
        na_filter=False,
    )

    df.columns = [
        re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_")
        for c in df.columns
    ]

    for col in df.columns:
        df[col] = df[col].map(normalize_blank).astype("string")

    if "release_year" in df.columns:
        df["release_year_num"] = pd.to_numeric(
            df["release_year"], errors="coerce"
        ).astype("Int64")

    if "date_added" in df.columns:
        parsed = pd.to_datetime(df["date_added"], errors="coerce")
        df["date_added_year"] = parsed.dt.year.astype("Int64")
        df["date_added_month"] = parsed.dt.month.astype("Int64")

    if "duration" in df.columns:
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


def build_sqlite(df: pd.DataFrame) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    sql_df = df.copy()
    for col in sql_df.columns:
        if str(sql_df[col].dtype) == "Int64":
            sql_df[col] = sql_df[col].astype("float")
    sql_df.to_sql(DB_TABLE, conn, index=False, if_exists="replace")
    return conn


def validate_read_only_sql(sql: str) -> tuple[bool, str]:
    cleaned = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE).strip()
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL).strip()

    if not re.match(r"^(SELECT|WITH)\b", cleaned, flags=re.IGNORECASE):
        return False, "Only SELECT or WITH queries are allowed."

    blocked = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|"
        r"ATTACH|DETACH|PRAGMA|VACUUM|REINDEX)\b",
        flags=re.IGNORECASE,
    )
    if blocked.search(cleaned):
        return False, "The query contains a blocked write or schema command."

    statements = [s.strip() for s in cleaned.split(";") if s.strip()]
    if len(statements) != 1:
        return False, "Only one SQL statement may be executed."

    return True, ""


def quoted_term(question: str) -> str | None:
    match = re.search(r'["â€œ](.+?)["â€]', question)
    return match.group(1).strip() if match else None


def extract_year(question: str) -> int | None:
    match = re.search(r"\b(19|20)\d{2}\b", question)
    return int(match.group(0)) if match else None


def make_plan(question: str) -> dict[str, str]:
    q = question.casefold().strip()
    year = extract_year(question)
    term = quoted_term(question)

    if ("country" in q or "countries" in q) and ("tv" in q or "show" in q):
        sql = """
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
""".strip()
        return {
            "title": "Countries producing the most TV shows",
            "sql": sql,
            "summary": "Countries were split into individual values before counting, so multi-country records do not inflate the result.",
        }

    if "country" in q or "countries" in q:
        sql = """
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
""".strip()
        return {
            "title": "Top countries in the catalog",
            "sql": sql,
            "summary": "The result counts individual countries after splitting multi-country catalog entries.",
        }

    if "director" in q:
        sql = """
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
""".strip()
        return {
            "title": "Directors with the most titles",
            "sql": sql,
            "summary": "Directors were separated from multi-director records before titles were counted.",
        }

    if "actor" in q or "cast" in q:
        sql = """
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
""".strip()
        return {
            "title": "Most frequently listed cast members",
            "sql": sql,
            "summary": "Cast names were separated before counting appearances across titles.",
        }

    if "genre" in q or "category" in q:
        sql = """
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
""".strip()
        return {
            "title": "Top genres and categories",
            "sql": sql,
            "summary": "Each title can contribute to more than one genre because category lists are split before counting.",
        }

    if "rating" in q:
        sql = """
SELECT rating, COUNT(*) AS titles
FROM catalog
WHERE rating IS NOT NULL AND TRIM(rating) <> ''
GROUP BY rating
ORDER BY titles DESC
""".strip()
        return {
            "title": "Ratings distribution",
            "sql": sql,
            "summary": "This result compares the number of catalog titles assigned to each nonblank rating.",
        }

    if "missing" in q or "blank" in q or "complete" in q:
        sql = """
SELECT
    SUM(CASE WHEN director IS NULL OR TRIM(director) = '' THEN 1 ELSE 0 END) AS missing_director,
    SUM(CASE WHEN cast IS NULL OR TRIM(cast) = '' THEN 1 ELSE 0 END) AS missing_cast,
    SUM(CASE WHEN country IS NULL OR TRIM(country) = '' THEN 1 ELSE 0 END) AS missing_country,
    SUM(CASE WHEN date_added IS NULL OR TRIM(date_added) = '' THEN 1 ELSE 0 END) AS missing_date_added,
    SUM(CASE WHEN rating IS NULL OR TRIM(rating) = '' THEN 1 ELSE 0 END) AS missing_rating,
    SUM(CASE WHEN duration IS NULL OR TRIM(duration) = '' THEN 1 ELSE 0 END) AS missing_duration
FROM catalog
""".strip()
        return {
            "title": "Catalog metadata completeness",
            "sql": sql,
            "summary": "Blank-like values were normalized before the catalog was loaded into the read-only query engine.",
        }

    if "longest" in q or "runtime" in q or "duration" in q:
        sql = """
SELECT title, release_year, rating, duration, duration_value
FROM catalog
WHERE type = 'Movie' AND duration_value IS NOT NULL
ORDER BY duration_value DESC
LIMIT 100
""".strip()
        return {
            "title": "Longest movies",
            "sql": sql,
            "summary": "Movie duration was converted to a numeric value so the records could be sorted correctly.",
        }

    if "newest" in q or "latest" in q:
        sql = """
SELECT show_id, type, title, country, release_year, rating, duration, listed_in
FROM catalog
WHERE release_year_num IS NOT NULL
ORDER BY release_year_num DESC, title
LIMIT 100
""".strip()
        return {
            "title": "Newest releases in the catalog",
            "sql": sql,
            "summary": "Titles are ordered by numeric release year, newest first.",
        }

    if year and ("after" in q or "since" in q):
        title_filter = ""
        if "horror" in q:
            title_filter = "AND LOWER(COALESCE(listed_in, '')) LIKE '%horror%'"
        sql = f"""
SELECT show_id, type, title, country, release_year, rating, duration, listed_in
FROM catalog
WHERE release_year_num >= {year}
{title_filter}
ORDER BY release_year_num DESC, title
LIMIT 500
""".strip()
        return {
            "title": f"Catalog titles released since {year}",
            "sql": sql,
            "summary": f"The supporting records include titles with a release year of {year} or later.",
        }

    if term:
        safe_term = term.replace("'", "''")
        sql = f"""
SELECT show_id, type, title, director, cast, country,
       release_year, rating, duration, listed_in, description
FROM catalog
WHERE LOWER(COALESCE(title, '')) LIKE LOWER('%{safe_term}%')
   OR LOWER(COALESCE(description, '')) LIKE LOWER('%{safe_term}%')
   OR LOWER(COALESCE(listed_in, '')) LIKE LOWER('%{safe_term}%')
ORDER BY release_year_num DESC, title
LIMIT 500
""".strip()
        return {
            "title": f'Records matching "{term}"',
            "sql": sql,
            "summary": "The search checks title, description, and catalog category fields.",
        }

    sql = """
SELECT show_id, type, title, director, country,
       release_year, rating, duration, listed_in
FROM catalog
ORDER BY release_year_num DESC, title
LIMIT 250
""".strip()
    return {
        "title": "Catalog records",
        "sql": sql,
        "summary": "The local planner could not confidently map the question to a specialized template, so it returned a safe catalog view.",
    }


def supporting_sql(plan_sql: str, result: pd.DataFrame) -> str | None:
    cols = {c.casefold() for c in result.columns}
    if "country" in cols:
        return """
SELECT show_id, type, title, country, release_year, rating, duration, listed_in
FROM catalog
WHERE country IS NOT NULL AND TRIM(country) <> ''
ORDER BY release_year_num DESC, title
LIMIT 500
""".strip()
    if "director" in cols:
        return """
SELECT show_id, type, title, director, country, release_year, rating
FROM catalog
WHERE director IS NOT NULL AND TRIM(director) <> ''
ORDER BY release_year_num DESC, title
LIMIT 500
""".strip()
    if "genre" in cols:
        return """
SELECT show_id, type, title, listed_in, country, release_year, rating
FROM catalog
WHERE listed_in IS NOT NULL AND TRIM(listed_in) <> ''
ORDER BY release_year_num DESC, title
LIMIT 500
""".strip()
    if "cast_member" in cols:
        return """
SELECT show_id, type, title, cast, country, release_year, rating
FROM catalog
WHERE cast IS NOT NULL AND TRIM(cast) <> ''
ORDER BY release_year_num DESC, title
LIMIT 500
""".strip()
    return None


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Results")
    return output.getvalue()


def render_overview(df: pd.DataFrame):
    countries = split_values(df["country"]) if "country" in df else pd.Series(dtype="string")
    genres = split_values(df["listed_in"]) if "listed_in" in df else pd.Series(dtype="string")

    st.subheader("Catalog overview")
    cols = st.columns(4)
    cols[0].metric("Titles", f"{len(df):,}")
    cols[1].metric("Movies", f"{int(df['type'].eq('Movie').sum()):,}")
    cols[2].metric("TV Shows", f"{int(df['type'].eq('TV Show').sum()):,}")
    cols[3].metric("Countries", f"{countries.str.casefold().nunique():,}")

    cols = st.columns(4)
    cols[0].metric("Genres", f"{genres.str.casefold().nunique():,}")
    cols[1].metric("Missing directors", f"{int(df['director'].isna().sum()):,}")
    cols[2].metric("Missing cast", f"{int(df['cast'].isna().sum()):,}")
    cols[3].metric("Missing countries", f"{int(df['country'].isna().sum()):,}")


def main():
    st.title("STREAMVAULT")
    st.caption("Ask a business question. Review the answer, records, SQL, and download.")

    uploaded = st.file_uploader("Upload a catalog CSV", type=["csv"])

    if uploaded is not None:
        source = uploaded
    elif Path(DATA_FILE).exists():
        source = DATA_FILE
    elif Path("netflix_titles(1).csv").exists():
        source = "netflix_titles(1).csv"
    else:
        st.warning("Upload a CSV or place netflix_titles.csv in this folder.")
        st.stop()

    df = load_catalog(source)
    render_overview(df)

    st.divider()
    st.subheader("Ask the catalog")

    suggestions = [
        "Which countries produce the most TV shows?",
        "Which directors have the most titles?",
        "Which genres are most common?",
        "Which ratings are most common?",
        "Which records have missing metadata?",
        "Show the longest movies.",
    ]

    suggestion = st.selectbox(
        "Start with a template question",
        ["Choose a question"] + suggestions,
    )

    default_question = "" if suggestion == "Choose a question" else suggestion
    question = st.text_area(
        "Business question",
        value=default_question,
        placeholder="Example: Which countries produce the most TV shows?",
        height=100,
    )

    run = st.button("Analyze catalog", type="primary", use_container_width=True)

    if not run:
        st.info("Choose a template or type a question, then select Analyze catalog.")
        return

    if not question.strip():
        st.warning("Enter a business question.")
        return

    plan = make_plan(question)
    conn = build_sqlite(df)

    valid, reason = validate_read_only_sql(plan["sql"])
    if not valid:
        st.error(reason)
        return

    try:
        result = pd.read_sql_query(plan["sql"], conn)
    except Exception as exc:
        st.error(f"The read-only query could not run: {exc}")
        return

    st.divider()
    st.subheader(plan["title"])

    if result.empty:
        st.warning("No records matched this question.")
    else:
        st.success(f"{len(result):,} result rows returned.")
        st.write(plan["summary"])
        st.dataframe(result, hide_index=True, use_container_width=True)

    support_query = supporting_sql(plan["sql"], result)
    support_df = pd.DataFrame()
    if support_query:
        with st.expander("Supporting catalog records", expanded=True):
            support_df = pd.read_sql_query(support_query, conn)
            st.caption("These records let you inspect the catalog rows behind the answer.")
            st.dataframe(support_df, hide_index=True, use_container_width=True)

    with st.expander("Verify read-only SQL", expanded=False):
        st.code(plan["sql"], language="sql")
        st.success("Verified: one read-only SELECT/WITH statement. Write operations are blocked.")

    st.subheader("Download results")
    d1, d2, d3 = st.columns(3)

    d1.download_button(
        "Download CSV",
        result.to_csv(index=False).encode("utf-8"),
        file_name="streamvault_query_results.csv",
        mime="text/csv",
        use_container_width=True,
    )

    d2.download_button(
        "Download Excel",
        to_excel_bytes(result),
        file_name="streamvault_query_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    d3.download_button(
        "Download SQL",
        plan["sql"].encode("utf-8"),
        file_name="streamvault_read_only_query.sql",
        mime="text/plain",
        use_container_width=True,
    )


if __name__ == "__main__":
    main()

