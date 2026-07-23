from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import re
from difflib import get_close_matches

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
CATALOG_PATH = APP_DIR / "data" / "catalog.csv"
TODAY = date.today()
MAX_RESULT_ROWS = 500

st.set_page_config(page_title="StreamVault", page_icon="🎬", layout="wide")

# The 26 catalog fields available to the assistant.
SCHEMA = {
    "content_id": "Unique content identifier (text)",
    "title": "Title name (text)",
    "content_type": "Movie or TV Show (text)",
    "country": "Primary country (text)",
    "original_language": "Original language (text)",
    "release_year": "Original release year (integer)",
    "rating": "Content/maturity rating (text)",
    "genre": "Primary genre (text)",
    "runtime_min": "Runtime in minutes (integer; often null for TV)",
    "seasons": "Number of seasons (integer; often null for movies)",
    "episodes": "Number of episodes (integer; often null for movies)",
    "studio": "Studio (text)",
    "production_company": "Production company (text)",
    "acquisition_type": "How the content was acquired (text)",
    "license_expiration": "License expiration date (date)",
    "audience_score": "Audience score (number)",
    "critic_score": "Critic score (number)",
    "viewing_hours": "Viewing hours (integer)",
    "completion_rate": "Completion rate stored as a percentage number, e.g. 75 means 75% (number)",
    "cost_usd": "Content cost in U.S. dollars (number)",
    "region_availability": "Regions where content is available (text)",
    "keywords": "Keywords/tags (text)",
    "awards": "Awards information (text)",
    "featured_collection": "Featured collection (text)",
    "date_added": "Date added to catalog (date)",
    "description": "Content description/synopsis (text)",
}

@st.cache_resource
def get_connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    # DuckDB does not allow prepared parameters in CREATE VIEW statements.
    # Escape the local CSV path before embedding it in this static DDL.
    catalog_path_sql = str(CATALOG_PATH).replace("'", "''")
    con.execute(
        f"""
        CREATE OR REPLACE VIEW catalog AS
        SELECT
            "Content ID" AS content_id,
            Title AS title,
            Type AS content_type,
            Country AS country,
            "Original Language" AS original_language,
            CAST("Release Year" AS INTEGER) AS release_year,
            Rating AS rating,
            Genre AS genre,
            CAST("Runtime (min)" AS INTEGER) AS runtime_min,
            CAST(Seasons AS INTEGER) AS seasons,
            CAST(Episodes AS INTEGER) AS episodes,
            Studio AS studio,
            "Production Company" AS production_company,
            "Acquisition Type" AS acquisition_type,
            TRY_CAST("License Expiration" AS DATE) AS license_expiration,
            CAST("Audience Score" AS DOUBLE) AS audience_score,
            CAST("Critic Score" AS DOUBLE) AS critic_score,
            CAST("Viewing Hours" AS BIGINT) AS viewing_hours,
            CAST("Completion Rate" AS DOUBLE) AS completion_rate,
            CAST("Cost (USD)" AS DOUBLE) AS cost_usd,
            "Region Availability" AS region_availability,
            Keywords AS keywords,
            Awards AS awards,
            "Featured Collection" AS featured_collection,
            TRY_CAST("Date Added" AS DATE) AS date_added,
            Description AS description
        FROM read_csv_auto('{catalog_path_sql}', header=true, all_varchar=true)
        """
    )
    return con


def query(sql: str, params: list | None = None) -> pd.DataFrame:
    return get_connection().execute(sql, params or []).df()


def scalar(sql: str, params: list | None = None):
    df = query(sql, params)
    return df.iloc[0, 0] if not df.empty else None


def to_python_date(value: object) -> date | None:
    """Normalize database and pandas date scalars for Streamlit widgets."""
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def period_bounds(as_of: date):
    q_month = ((as_of.month - 1) // 3) * 3 + 1
    q_start = date(as_of.year, q_month, 1)
    q_end = date(as_of.year + 1, 1, 1) if q_month == 10 else date(as_of.year, q_month + 3, 1)
    prev_q = date(as_of.year - 1, 10, 1) if q_month == 1 else date(as_of.year, q_month - 3, 1)
    return q_start, q_end, prev_q


def pct(n, d):
    return 0.0 if not d else 100.0 * n / d


def core_metrics(as_of: date) -> dict:
    q_start, q_end, prev_q_start = period_bounds(as_of)
    total = scalar("SELECT COUNT(*) FROM catalog WHERE date_added <= ?", [as_of])
    movies = scalar("SELECT COUNT(*) FROM catalog WHERE date_added <= ? AND content_type='Movie'", [as_of])
    shows = scalar("SELECT COUNT(*) FROM catalog WHERE date_added <= ? AND content_type='TV Show'", [as_of])
    current = scalar("SELECT COUNT(*) FROM catalog WHERE date_added >= ? AND date_added < ? AND date_added <= ?", [q_start, q_end, as_of])
    international = scalar("SELECT COUNT(*) FROM catalog WHERE date_added >= ? AND date_added < ? AND date_added <= ? AND lower(trim(country)) <> 'united states'", [q_start, q_end, as_of])
    doc_current = scalar("SELECT COUNT(*) FROM catalog WHERE date_added >= ? AND date_added < ? AND date_added <= ? AND lower(genre) = 'documentary'", [q_start, q_end, as_of])
    previous = scalar("SELECT COUNT(*) FROM catalog WHERE date_added >= ? AND date_added < ?", [prev_q_start, q_start])
    doc_previous = scalar("SELECT COUNT(*) FROM catalog WHERE date_added >= ? AND date_added < ? AND lower(genre) = 'documentary'", [prev_q_start, q_start])
    future = scalar("SELECT COUNT(*) FROM catalog WHERE date_added > ?", [as_of])
    return {"total": int(total or 0), "movies": int(movies or 0), "shows": int(shows or 0), "current": int(current or 0), "international": int(international or 0), "doc_current": int(doc_current or 0), "previous": int(previous or 0), "doc_previous": int(doc_previous or 0), "future": int(future or 0), "q_start": q_start, "q_end": q_end, "prev_q_start": prev_q_start}


def clean_words(text: str) -> list[str]:
    stop = {
        "what", "which", "where", "when", "how", "many", "much", "are", "is", "was", "were",
        "the", "a", "an", "of", "in", "on", "with", "and", "or", "to", "for", "show", "tell",
        "me", "find", "content", "titles", "title", "catalog", "please", "give", "list", "that",
        "have", "has", "from", "by", "based", "using", "all", "any", "our", "their", "its"
    }
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9'-]+", text)]
    return list(dict.fromkeys(w for w in words if len(w) > 2 and w not in stop))


def detect_limit(question: str, default: int = 20) -> int:
    q = question.lower()
    match = re.search(r"\b(?:top|first|highest|lowest|best|worst)\s+(\d{1,3})\b", q)
    if not match:
        match = re.search(r"\b(\d{1,3})\s+(?:titles|records|movies|shows|items)\b", q)
    return max(1, min(int(match.group(1)), 100)) if match else default


METRIC_MAP = {
    "viewing_hours": ["viewing hours", "watch hours", "watched", "viewership", "views"],
    "cost_usd": ["cost", "costs", "spend", "spent", "budget", "dollar"],
    "audience_score": ["audience score", "audience rating", "user score"],
    "critic_score": ["critic score", "critic rating", "critics"],
    "completion_rate": ["completion rate", "completion", "finished"],
    "runtime_min": ["runtime", "length", "minutes", "duration"],
    "seasons": ["seasons", "season"],
    "episodes": ["episodes", "episode"],
    "release_year": ["release year", "year released"],
}

DIMENSION_MAP = {
    "content_type": ["movie versus tv", "movies versus tv", "movie vs tv", "movies vs tv", "content type", "type"],
    "genre": ["genre", "genres"],
    "country": ["country", "countries"],
    "original_language": ["language", "languages"],
    "studio": ["studio", "studios"],
    "production_company": ["production company", "production companies", "producer"],
    "rating": ["rating", "ratings", "maturity"],
    "acquisition_type": ["acquisition type", "acquisition"],
    "region_availability": ["region", "regions", "availability"],
    "featured_collection": ["collection", "collections"],
    "release_year": ["release year", "year"],
}

LABELS = {
    "content_type": "Type", "genre": "Genre", "country": "Country", "original_language": "Language",
    "studio": "Studio", "production_company": "Production Company", "rating": "Rating",
    "acquisition_type": "Acquisition Type", "region_availability": "Region Availability",
    "featured_collection": "Featured Collection", "release_year": "Release Year",
    "viewing_hours": "Viewing Hours", "cost_usd": "Cost (USD)", "audience_score": "Audience Score",
    "critic_score": "Critic Score", "completion_rate": "Completion Rate", "runtime_min": "Runtime (min)",
    "seasons": "Seasons", "episodes": "Episodes"
}


def detect_metrics(question: str) -> list[str]:
    q = question.lower()
    found = [column for column, phrases in METRIC_MAP.items() if any(phrase in q for phrase in phrases)]
    if "score" in q and not any(x in found for x in ("audience_score", "critic_score")):
        found.extend(["audience_score", "critic_score"])
    return list(dict.fromkeys(found))


def detect_dimension(question: str) -> str | None:
    q = question.lower()
    for column, phrases in DIMENSION_MAP.items():
        if any(phrase in q for phrase in phrases):
            return column
    return None


def known_values(column: str, as_of: date) -> list[str]:
    df = query(f"SELECT DISTINCT {column} AS value FROM catalog WHERE date_added <= ? AND {column} IS NOT NULL ORDER BY value", [as_of])
    return [str(v) for v in df["value"].tolist() if str(v).strip()]


def selected_genres(question: str, as_of: date) -> list[str]:
    """Return every catalog genre explicitly named in the question."""
    q = question.lower()
    return [
        value for value in known_values("genre", as_of)
        if len(value) >= 3 and re.search(rf"\b{re.escape(value.lower())}\b", q)
    ]


def value_filter(question: str, as_of: date) -> tuple[list[str], list[Any], list[str]]:
    q = question.lower()
    conditions = ["date_added <= ?"]
    params: list[Any] = [as_of]
    notes: list[str] = []

    if "movie" in q and "tv" not in q and "show" not in q:
        conditions.append("content_type = 'Movie'")
        notes.append("movies")
    elif ("tv show" in q or "tv shows" in q or "series" in q) and "movie" not in q:
        conditions.append("content_type = 'TV Show'")
        notes.append("TV shows")

    # A question may name several genres, such as "Action, Comedy and Drama".
    # Use one IN filter so all requested genre categories are included.
    genre_values = known_values("genre", as_of)
    genre_matches = [v for v in genre_values if len(v) >= 3 and re.search(rf"\b{re.escape(v.lower())}\b", q)]
    if genre_matches:
        placeholders = ", ".join("?" for _ in genre_matches)
        conditions.append(f"lower(genre) IN ({placeholders})")
        params.extend(v.lower() for v in genre_matches)
        if len(genre_matches) == 1:
            notes.append(f"Genre = {genre_matches[0]}")
        else:
            notes.append(f"Genres = {', '.join(genre_matches)}")

    for column in ["country", "original_language", "rating", "studio", "acquisition_type", "featured_collection"]:
        values = known_values(column, as_of)
        matches = [v for v in values if len(v) >= 3 and v.lower() in q]
        if matches:
            conditions.append(f"lower({column}) = ?")
            params.append(matches[0].lower())
            notes.append(f"{LABELS[column]} = {matches[0]}")

    year_match = re.search(r"\b(19|20)\d{2}\b", q)
    if year_match:
        year = int(year_match.group(0))
        if any(x in q for x in ["released", "release", "from", "in "]):
            conditions.append("release_year = ?")
            params.append(year)
            notes.append(f"release year {year}")

    score_match = re.search(r"(?:audience|critic)?\s*score\s*(?:above|over|greater than|at least)\s*(\d+(?:\.\d+)?)", q)
    if score_match:
        metric = "critic_score" if "critic" in q else "audience_score"
        conditions.append(f"{metric} >= ?")
        params.append(float(score_match.group(1)))
        notes.append(f"{LABELS[metric]} at least {score_match.group(1)}")

    if "next 90 days" in q or "within 90 days" in q:
        conditions.append("license_expiration BETWEEN ? AND ?")
        params.extend([as_of, as_of + timedelta(days=90)])
        notes.append("license expiration within 90 days")
    elif "next 30 days" in q or "within 30 days" in q:
        conditions.append("license_expiration BETWEEN ? AND ?")
        params.extend([as_of, as_of + timedelta(days=30)])
        notes.append("license expiration within 30 days")
    elif "expired" in q:
        conditions.append("license_expiration < ?")
        params.append(as_of)
        notes.append("expired licenses")

    return conditions, params, notes


def make_answer(title: str, result: pd.DataFrame, notes: list[str], metric: str | None = None) -> str:
    filter_text = f" Filters applied: {', '.join(notes)}." if notes else ""
    if result.empty:
        return f"**{title}:** No matching catalog records were found.{filter_text}"

    if len(result) == 1 and result.shape[1] <= 5:
        pieces = []
        for col, value in result.iloc[0].items():
            if pd.isna(value):
                continue
            if "cost" in col.lower():
                pieces.append(f"**{col}:** ${float(value):,.2f}")
            elif "completion" in col.lower():
                pieces.append(f"**{col}:** {float(value):.1f}%")
            elif isinstance(value, (int, float)):
                pieces.append(f"**{col}:** {value:,.1f}" if isinstance(value, float) else f"**{col}:** {value:,}")
            else:
                pieces.append(f"**{col}:** {value}")
        return f"**{title}.** " + " · ".join(pieces) + filter_text

    lead = f"**{title}.** StreamVault found **{len(result):,} result rows**"
    if metric and metric in result.columns:
        top = result.iloc[0]
        value = top[metric]
        if "Cost" in metric:
            shown = f"${float(value):,.2f}"
        elif "Completion" in metric:
            shown = f"{float(value):.1f}%"
        else:
            shown = f"{float(value):,.1f}"
        lead += f". The leading result is **{top.iloc[0]}** with **{shown}**"
    patterns = []
    for col in ["Type", "Genre", "Country", "Language", "Studio", "Rating"]:
        if col in result.columns and result[col].notna().any():
            counts = result[col].astype(str).value_counts()
            if not counts.empty and counts.iloc[0] >= max(2, len(result) * 0.3):
                patterns.append(f"{counts.index[0]} is the most common {col.lower()} ({counts.iloc[0]} of {len(result)})")
    pattern_text = f" A notable pattern is that {'; '.join(patterns[:3])}." if patterns else ""
    return lead + "." + filter_text + pattern_text + " The supporting table contains the exact records and values used."


def semantic_search(question: str, as_of: date, conditions: list[str], params: list[Any], limit: int) -> tuple[str, pd.DataFrame, dict]:
    words = clean_words(question)[:10]
    if not words:
        return "Please enter a more specific catalog question.", pd.DataFrame(), {"interpretation": "No searchable terms detected", "sql": ""}
    searchable = "lower(concat_ws(' ', title, content_type, country, original_language, rating, genre, studio, production_company, acquisition_type, region_availability, keywords, awards, featured_collection, description))"
    score_parts = []
    local_params = list(params)
    for word in words:
        score_parts.append(f"CASE WHEN {searchable} LIKE ? THEN 1 ELSE 0 END")
        local_params.append(f"%{word}%")
    score_expr = " + ".join(score_parts)
    sql = f"""
        SELECT title AS "Title", content_type AS "Type", country AS "Country", original_language AS "Language",
               release_year AS "Release Year", rating AS "Rating", genre AS "Genre", studio AS "Studio",
               audience_score AS "Audience Score", critic_score AS "Critic Score", viewing_hours AS "Viewing Hours",
               completion_rate AS "Completion Rate", cost_usd AS "Cost (USD)", region_availability AS "Regions",
               keywords AS "Keywords", description AS "Description", ({score_expr}) AS "Match Score"
        FROM catalog
        WHERE {' AND '.join(conditions)} AND ({score_expr}) > 0
        ORDER BY "Match Score" DESC, viewing_hours DESC NULLS LAST, audience_score DESC NULLS LAST
        LIMIT {limit}
    """
    # Score expression appears twice, so repeat word params for the WHERE expression.
    exec_params = local_params + [f"%{word}%" for word in words]
    result = query(sql, exec_params)
    answer = f"**Local semantic search found {len(result):,} matching titles** using the concepts: **{', '.join(words)}**. Results are ranked by how many concepts appear across titles, descriptions, keywords, genres, studios, awards, regions, and other text fields."
    return answer, result, {"interpretation": "Local keyword-based semantic search across catalog text fields", "sql": sql}


def local_question_engine(question: str, as_of: date) -> tuple[str, pd.DataFrame, dict]:
    q = question.lower().strip()
    limit = detect_limit(question)
    conditions, params, notes = value_filter(question, as_of)
    where = " AND ".join(conditions)
    metrics = detect_metrics(question)
    dimension = detect_dimension(question)
    genres_in_question = selected_genres(question, as_of)
    # Naming two or more genres implies a genre comparison/grouping even when
    # the user does not explicitly type the word "genre".
    if len(genres_in_question) >= 2 and dimension is None:
        dimension = "genre"

    # License expiration questions.
    if "license" in q and any(x in q for x in ["expire", "expiration", "renew", "expired"]):
        sql = f"""
            SELECT title AS "Title", content_type AS "Type", genre AS "Genre", studio AS "Studio",
                   license_expiration AS "License Expiration", viewing_hours AS "Viewing Hours",
                   audience_score AS "Audience Score", cost_usd AS "Cost (USD)"
            FROM catalog WHERE {where}
            ORDER BY license_expiration ASC NULLS LAST, viewing_hours DESC NULLS LAST LIMIT {limit}
        """
        result = query(sql, params)
        answer = make_answer("License review", result, notes)
        return answer, result, {"interpretation": "License-expiration review using the selected report date", "sql": sql}

    # Counts.
    if any(phrase in q for phrase in ["how many", "number of", "count of", "total titles"]):
        if dimension:
            sql = f"SELECT {dimension} AS \"{LABELS[dimension]}\", COUNT(*) AS \"Title Count\" FROM catalog WHERE {where} GROUP BY {dimension} ORDER BY \"Title Count\" DESC LIMIT {limit}"
            result = query(sql, params)
            title = f"Title count by {LABELS[dimension].lower()}"
        else:
            sql = f"SELECT COUNT(*) AS \"Title Count\" FROM catalog WHERE {where}"
            result = query(sql, params)
            title = "Catalog count"
        return make_answer(title, result, notes), result, {"interpretation": title, "sql": sql}

    # Value/efficiency analysis such as score or viewing per dollar.
    if dimension and any(x in q for x in ["per dollar", "relative to cost", "value for money", "efficiency", "roi"]):
        numerator = "viewing_hours" if any(x in q for x in ["viewing", "watch", "hours"]) else "audience_score"
        sql = f"""
            SELECT {dimension} AS "{LABELS[dimension]}", COUNT(*) AS "Title Count",
                   AVG({numerator}) AS "Average {LABELS[numerator]}",
                   AVG(cost_usd) AS "Average Cost (USD)",
                   SUM({numerator}) / NULLIF(SUM(cost_usd), 0) AS "{LABELS[numerator]} per Dollar"
            FROM catalog WHERE {where} AND cost_usd > 0 AND {numerator} IS NOT NULL
            GROUP BY {dimension}
            ORDER BY "{LABELS[numerator]} per Dollar" DESC NULLS LAST LIMIT {limit}
        """
        result = query(sql, params)
        title = f"{LABELS[numerator]} per dollar by {LABELS[dimension].lower()}"
        return make_answer(title, result, notes), result, {"interpretation": title, "sql": sql}

    # Comparisons and averages by a dimension.
    wants_average = any(x in q for x in ["average", "avg", "mean"])
    wants_compare = any(x in q for x in ["compare", "versus", " vs ", "difference", "by "])
    if dimension and (wants_compare or wants_average or len(metrics) > 1):
        use_metrics = metrics or ["audience_score", "critic_score", "viewing_hours", "completion_rate", "cost_usd"]
        agg = [f"COUNT(*) AS \"Title Count\""]
        for m in use_metrics:
            agg.append(f"AVG({m}) AS \"Average {LABELS[m]}\"")
        sql = f"SELECT {dimension} AS \"{LABELS[dimension]}\", {', '.join(agg)} FROM catalog WHERE {where} GROUP BY {dimension} ORDER BY \"Title Count\" DESC LIMIT {limit}"
        result = query(sql, params)
        title = f"Comparison by {LABELS[dimension].lower()}"
        return make_answer(title, result, notes), result, {"interpretation": title, "sql": sql}

    # Ranking by a metric.
    ranking_words = ["highest", "lowest", "top", "best", "worst", "rank", "most", "least"]
    if metrics and any(x in q for x in ranking_words):
        metric = metrics[0]
        ascending = any(x in q for x in ["lowest", "least", "worst", "cheapest"])
        direction = "ASC" if ascending else "DESC"
        sql = f"""
            SELECT title AS "Title", content_type AS "Type", genre AS "Genre", country AS "Country",
                   original_language AS "Language", release_year AS "Release Year", studio AS "Studio",
                   {metric} AS "{LABELS[metric]}", audience_score AS "Audience Score",
                   critic_score AS "Critic Score", viewing_hours AS "Viewing Hours",
                   completion_rate AS "Completion Rate", cost_usd AS "Cost (USD)"
            FROM catalog WHERE {where} AND {metric} IS NOT NULL
            ORDER BY {metric} {direction} NULLS LAST LIMIT {limit}
        """
        result = query(sql, params)
        title = f"{'Lowest' if ascending else 'Highest'} {LABELS[metric].lower()}"
        return make_answer(title, result, notes, LABELS[metric]), result, {"interpretation": title, "sql": sql}

    # Single-metric summary.
    if metrics and any(x in q for x in ["average", "avg", "mean", "total", "sum", "median", "minimum", "maximum"]):
        metric = metrics[0]
        if "median" in q:
            func, label = "MEDIAN", "Median"
        elif any(x in q for x in ["minimum", "lowest"]):
            func, label = "MIN", "Minimum"
        elif any(x in q for x in ["maximum", "highest"]):
            func, label = "MAX", "Maximum"
        elif any(x in q for x in ["total", "sum"]):
            func, label = "SUM", "Total"
        else:
            func, label = "AVG", "Average"
        sql = f"SELECT {func}({metric}) AS \"{label} {LABELS[metric]}\", COUNT(*) AS \"Records Used\" FROM catalog WHERE {where} AND {metric} IS NOT NULL"
        result = query(sql, params)
        title = f"{label} {LABELS[metric].lower()}"
        return make_answer(title, result, notes), result, {"interpretation": title, "sql": sql}

    # Explicit multi-genre title request. The source catalog stores one primary
    # genre per title, so this returns titles across all requested genre groups.
    multi_genre_language = any(phrase in q for phrase in [
        "multiple genres", "multi genre", "multi-genre", "across genres",
        "span across", "spanning", "cross genre", "cross-genre"
    ])
    if len(genres_in_question) >= 2 or (multi_genre_language and dimension == "genre"):
        sql = f"""
            SELECT title AS "Title", content_type AS "Type", genre AS "Primary Genre",
                   country AS "Country", original_language AS "Language",
                   release_year AS "Release Year", rating AS "Rating", studio AS "Studio",
                   audience_score AS "Audience Score", critic_score AS "Critic Score",
                   viewing_hours AS "Viewing Hours", completion_rate AS "Completion Rate",
                   cost_usd AS "Cost (USD)", keywords AS "Keywords", description AS "Description"
            FROM catalog WHERE {where}
            ORDER BY genre, viewing_hours DESC NULLS LAST, audience_score DESC NULLS LAST
            LIMIT {limit}
        """
        result = query(sql, params)
        if genres_in_question:
            scope = ", ".join(genres_in_question)
            title = f"Titles across {scope}"
            answer = make_answer(title, result, notes)
            answer += " Each catalog title has one primary genre; this result combines the requested genre groups into one report."
        else:
            answer = make_answer("Titles across multiple genre groups", result, notes)
            answer += " The catalog currently stores one primary genre per title rather than multiple genre tags for an individual title."
        return answer, result, {"interpretation": "Multi-genre title search using all named genre categories", "sql": sql}

    # Descriptive/theme search or broad fallback.
    return semantic_search(question, as_of, conditions, params, limit)


def ask_streamvault(question: str, as_of: date):
    return local_question_engine(question, as_of)

def format_result(df: pd.DataFrame):
    display = df.copy()
    formats = {}
    for col in display.columns:
        name = str(col).lower()
        needs_number_format = (
            "completion" in name
            or name.endswith("share")
            or "percentage" in name
            or name == "percent"
            or "cost" in name
            or "revenue" in name
            or "hours" in name
            or "count" in name
            or "titles" in name
            or "episodes" in name
            or "score" in name
            or "average" in name
            or "avg" in name
        )
        if not needs_number_format:
            continue
        numeric = pd.to_numeric(display[col], errors="coerce")
        non_null = display[col].notna()
        # A name like "Score" or "Cost" does not prove that a query result
        # is numeric. Only format columns whose actual non-null values convert.
        if non_null.any() and not numeric[non_null].notna().all():
            continue
        display[col] = numeric
        if "completion" in name or name.endswith("share") or "percentage" in name or name == "percent":
            # Query results may be 0-1 ratios or 0-100 percentages. Normalize only when appropriate.
            if numeric.notna().any() and numeric.abs().max() <= 1.0:
                formats[col] = "{:.1%}"
            else:
                formats[col] = "{:.1f}%"
        elif "cost" in name or "revenue" in name:
            formats[col] = "${:,.2f}"
        elif "hours" in name or "count" in name or "titles" in name or "episodes" in name:
            formats[col] = "{:,.0f}"
        elif "score" in name or "average" in name or "avg" in name:
            formats[col] = "{:,.1f}"
    return display.style.format(formats, na_rep="—") if formats else display


# ---------- Interface ----------
st.markdown("""
<style>
.block-container {padding-top: 1.4rem; padding-bottom: 2rem;}
.sv-title {font-size: 2.35rem; font-weight: 800; letter-spacing: -0.03em;}
.sv-sub {color: #6b7280; margin-top: -0.5rem; margin-bottom: 1rem;}
div[data-testid="stMetric"] {border: 1px solid rgba(120,120,120,.22); border-radius: 14px; padding: 14px; background: rgba(127,127,127,.04);}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="sv-title">🎬 StreamVault</div>', unsafe_allow_html=True)
st.markdown('<div class="sv-sub">Interactive intelligence across all 26 content catalog fields</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Analysis settings")
    max_date = to_python_date(scalar("SELECT MAX(date_added) FROM catalog"))
    min_date = to_python_date(scalar("SELECT MIN(date_added) FROM catalog"))
    default_as_of = min(TODAY, max_date) if max_date else TODAY
    as_of = st.date_input(
        "Report as of",
        value=default_as_of,
        min_value=min_date or TODAY,
        max_value=max(TODAY, max_date) if max_date else TODAY,
    )
    st.caption("Records dated after the selected date are excluded unless requested.")
    st.divider()
    st.markdown("**Local question engine**")
    st.success("No API key required")
    st.caption("Questions are interpreted locally and calculated with DuckDB. There are no model-credit charges.")
    st.divider()
    st.markdown("**Trusted definitions**")
    st.caption("International: country is not United States")
    st.caption("Recent: trailing 90 calendar days")
    st.caption("All generated SQL is read-only and runs locally")

metrics = core_metrics(as_of)
movie_share = pct(metrics["movies"], metrics["total"])
intl_share = pct(metrics["international"], metrics["current"])
doc_current_share = pct(metrics["doc_current"], metrics["current"])
doc_prev_share = pct(metrics["doc_previous"], metrics["previous"])

if metrics["future"]:
    st.warning(f"Data quality: {metrics['future']} catalog records are dated after {as_of:%B %d, %Y} and are excluded from current metrics.")

tabs = st.tabs(["Overview", "Ask StreamVault", "Data Dictionary", "Trends", "Catalog Explorer"])

with tabs[0]:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Catalog Titles", f"{metrics['total']:,}")
    c2.metric("Movies", f"{metrics['movies']:,}", f"{movie_share:.1f}%")
    c3.metric("TV Shows", f"{metrics['shows']:,}", f"{100-movie_share:.1f}%")
    c4.metric("Added This Quarter", f"{metrics['current']:,}")
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("International This Quarter", f"{intl_share:.1f}%")
    c6.metric("Documentaries This Quarter", f"{doc_current_share:.1f}%", f"{doc_current_share-doc_prev_share:+.1f} pp vs prior quarter")
    c7.metric("Countries", f"{scalar('SELECT COUNT(DISTINCT country) FROM catalog WHERE date_added <= ?', [as_of]):,}")
    c8.metric("Genres", f"{scalar('SELECT COUNT(DISTINCT genre) FROM catalog WHERE date_added <= ?', [as_of]):,}")
    left, right = st.columns(2)
    with left:
        type_df = query('SELECT content_type AS "Type", COUNT(*) AS "Titles" FROM catalog WHERE date_added <= ? GROUP BY content_type', [as_of])
        st.plotly_chart(px.pie(type_df, names="Type", values="Titles", hole=.58, title="Movie vs TV Mix"), use_container_width=True)
    with right:
        genre_df = query('SELECT genre AS "Genre", COUNT(*) AS "Titles" FROM catalog WHERE date_added <= ? GROUP BY genre ORDER BY "Titles" DESC LIMIT 10', [as_of])
        st.plotly_chart(px.bar(genre_df.sort_values("Titles"), x="Titles", y="Genre", orientation="h", title="Top Genres"), use_container_width=True)

with tabs[1]:
    st.subheader("Ask any question about the catalog")
    st.write("Ask about titles, countries, languages, ratings, genres, runtime, seasons, studios, licenses, scores, viewing, costs, regions, keywords, awards, dates, descriptions—or combinations of them.")

    examples = [
        "Which 10 titles have the highest viewing hours and what do they have in common?",
        "Compare average cost, audience score, and completion rate for movies versus TV shows.",
        "Find highly rated Spanish-language dramas available in North America.",
        "Which licenses expire in the next 90 days, ranked by viewing hours?",
        "What genres give us the strongest audience score per dollar spent?",
        "Show the top 20 titles across Action, Comedy, and Drama.",
        "Compare audience scores for Horror, Thriller, and Sci-Fi titles.",
        "Show content about friendship or coming of age based on descriptions and keywords.",
    ]
    selected = None
    ex_cols = st.columns(2)
    for i, prompt in enumerate(examples):
        if ex_cols[i % 2].button(prompt, use_container_width=True, key=f"example_{i}"):
            selected = prompt

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("data") is not None:
                st.dataframe(format_result(message["data"]), use_container_width=True, hide_index=True)

    entered = st.chat_input("Type a specific catalog question")
    question = entered or selected
    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            with st.spinner("Analyzing all relevant catalog fields..."):
                try:
                    answer, result, plan = ask_streamvault(question, as_of)
                    st.markdown(answer)
                    if plan:
                        with st.expander("How StreamVault analyzed this question"):
                            st.write(plan.get("interpretation", ""))
                            st.code(plan.get("sql", ""), language="sql")
                    if result is not None and not result.empty:
                        st.markdown("#### Supporting data")
                        st.dataframe(format_result(result), use_container_width=True, hide_index=True)
                        st.download_button("Download these results", result.to_csv(index=False).encode("utf-8"), "streamvault_question_results.csv", "text/csv", key=f"download_{len(st.session_state.messages)}")
                    elif result is not None:
                        st.info("No catalog records matched the interpreted question.")
                    st.session_state.messages.append({"role": "assistant", "content": answer, "data": result})
                except Exception as exc:
                    error_text = f"I could not complete that analysis: **{exc}**"
                    st.error(error_text)
                    st.caption("Try rewording the question with a metric, category, filter, ranking, comparison, or theme.")
                    st.session_state.messages.append({"role": "assistant", "content": error_text})

    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.rerun()

with tabs[2]:
    st.subheader("Catalog data dictionary")
    dictionary = pd.DataFrame([{"Field": k, "Meaning": v} for k, v in SCHEMA.items()])
    st.dataframe(dictionary, use_container_width=True, hide_index=True)
    st.caption("All 26 fields are available to the local question engine and the catalog explorer.")

with tabs[3]:
    monthly = query("SELECT date_trunc('month', date_added) AS month, COUNT(*) AS titles_added FROM catalog WHERE date_added <= ? GROUP BY month ORDER BY month", [as_of])
    st.plotly_chart(px.line(monthly, x="month", y="titles_added", markers=True, title="Titles Added by Month"), use_container_width=True)
    quarterly = query("""
        SELECT date_trunc('quarter', date_added) AS quarter, COUNT(*) AS total_additions,
        COUNT(*) FILTER (WHERE lower(country) <> 'united states') AS international,
        COUNT(*) FILTER (WHERE lower(genre) = 'documentary') AS documentaries
        FROM catalog WHERE date_added <= ? GROUP BY quarter ORDER BY quarter
    """, [as_of])
    quarterly["International Share"] = quarterly["international"] / quarterly["total_additions"]
    quarterly["Documentary Share"] = quarterly["documentaries"] / quarterly["total_additions"]
    trend = quarterly.melt(id_vars=["quarter"], value_vars=["International Share", "Documentary Share"], var_name="Metric", value_name="Share")
    fig = px.line(trend, x="quarter", y="Share", color="Metric", markers=True, title="Quarterly Content Mix")
    fig.update_yaxes(tickformat=".0%")
    st.plotly_chart(fig, use_container_width=True)

with tabs[4]:
    f1, f2, f3, f4 = st.columns(4)
    countries = ["All"] + query("SELECT DISTINCT country FROM catalog ORDER BY country")["country"].tolist()
    genres = ["All"] + query("SELECT DISTINCT genre FROM catalog ORDER BY genre")["genre"].tolist()
    country = f1.selectbox("Country", countries)
    genre = f2.selectbox("Genre", genres)
    content_type = f3.selectbox("Type", ["All", "Movie", "TV Show"])
    search = f4.text_input("Search title, keywords, or description")
    conditions, params = ["date_added <= ?"], [as_of]
    if country != "All": conditions.append("country = ?"); params.append(country)
    if genre != "All": conditions.append("genre = ?"); params.append(genre)
    if content_type != "All": conditions.append("content_type = ?"); params.append(content_type)
    if search:
        conditions.append("lower(concat_ws(' ', title, keywords, description)) LIKE ?")
        params.append(f"%{search.lower()}%")
    explorer = query(f"""
        SELECT content_id AS "Content ID", title AS "Title", content_type AS "Type", country AS "Country",
        original_language AS "Language", release_year AS "Release Year", rating AS "Rating", genre AS "Genre",
        runtime_min AS "Runtime (min)", seasons AS "Seasons", episodes AS "Episodes", studio AS "Studio",
        production_company AS "Production Company", acquisition_type AS "Acquisition Type",
        license_expiration AS "License Expiration", audience_score AS "Audience Score", critic_score AS "Critic Score",
        viewing_hours AS "Viewing Hours", completion_rate AS "Completion Rate", cost_usd AS "Cost (USD)",
        region_availability AS "Region Availability", keywords AS "Keywords", awards AS "Awards",
        featured_collection AS "Featured Collection", date_added AS "Date Added", description AS "Description"
        FROM catalog WHERE {' AND '.join(conditions)} ORDER BY date_added DESC, title LIMIT 1000
    """, params)
    st.caption(f"Showing {len(explorer):,} records (maximum 1,000).")
    st.dataframe(format_result(explorer), use_container_width=True, hide_index=True)
    st.download_button("Download filtered results", explorer.to_csv(index=False).encode("utf-8"), "streamvault_filtered_catalog.csv", "text/csv")
