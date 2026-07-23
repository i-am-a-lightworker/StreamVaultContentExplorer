from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import json
import os
import re
from typing import Any

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

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
    # DuckDB cannot prepare CREATE VIEW statements, so its CSV path must be
    # part of the DDL text. Escape it for SQL while keeping parameters for
    # regular data queries below.
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


def get_secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, os.getenv(name, default)))
    except Exception:
        return os.getenv(name, default)


def schema_text() -> str:
    return "\n".join(f"- {name}: {description}" for name, description in SCHEMA.items())


def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("The AI did not return a valid query plan.")
    return json.loads(cleaned[start:end + 1])


def validate_sql(sql: str) -> str:
    candidate = sql.strip().rstrip(";").strip()
    compact = re.sub(r"\s+", " ", candidate).lower()
    if not (compact.startswith("select ") or compact.startswith("with ")):
        raise ValueError("Only read-only SELECT questions are allowed.")
    if ";" in candidate:
        raise ValueError("Only one SQL statement is allowed.")
    forbidden = r"\b(insert|update|delete|drop|alter|create|replace|copy|attach|detach|install|load|pragma|call|export|import|truncate)\b"
    if re.search(forbidden, compact, flags=re.I):
        raise ValueError("The generated query contained a prohibited operation.")
    if not re.search(r"\bcatalog\b", compact):
        raise ValueError("The query must use the catalog view.")
    # Cap detail outputs while preserving aggregate/grouped queries.
    if not re.search(r"\blimit\s+\d+\b", compact) and not re.search(r"\b(count|sum|avg|min|max|median|quantile|stddev|variance)\s*\(", compact):
        candidate += f" LIMIT {MAX_RESULT_ROWS}"
    return candidate


def build_query_plan(question: str, as_of: date, api_key: str, model: str) -> dict[str, Any]:
    if OpenAI is None:
        raise RuntimeError("The OpenAI package is not installed. Run: pip install -r requirements.txt")
    client = OpenAI(api_key=api_key)
    instructions = f"""
You are the query planner for StreamVault, a streaming catalog analytics application.
Translate the user's question into ONE safe DuckDB SELECT query using only the view named catalog.
The report date is {as_of.isoformat()}. Unless the user explicitly asks about future additions, exclude rows where date_added > DATE '{as_of.isoformat()}'.
Use case-insensitive matching with lower(...) and LIKE for user-supplied text concepts.
For questions about themes, plots, descriptions, or keywords, search description and keywords with LIKE.
Completion rate is stored as 0-100, not 0-1.
Never invent columns. Never modify data. Never use external tables, files, functions that read files, or system metadata.
For title-list questions, include useful identifying and supporting columns and LIMIT 100.
For rankings, sort appropriately and LIMIT 20 unless the user requests another number.
For broad questions, create an aggregate that directly answers the question.

Available columns:
{schema_text()}

Return JSON only in this exact structure:
{{
  "sql": "SELECT ...",
  "interpretation": "one sentence explaining how you interpreted the question",
  "answer_type": "aggregate|comparison|ranking|records|semantic_search",
  "title": "short result heading"
}}
"""
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": question},
        ],
    )
    plan = extract_json(response.output_text)
    plan["sql"] = validate_sql(str(plan.get("sql", "")))
    return plan


def dataframe_for_prompt(df: pd.DataFrame, max_rows: int = 60) -> str:
    safe = df.head(max_rows).copy()
    for col in safe.columns:
        if pd.api.types.is_datetime64_any_dtype(safe[col]):
            safe[col] = safe[col].astype(str)
    return safe.to_json(orient="records", date_format="iso", default_handler=str)


def summarize_answer(question: str, as_of: date, plan: dict[str, Any], result: pd.DataFrame, api_key: str, model: str) -> str:
    client = OpenAI(api_key=api_key)
    result_json = dataframe_for_prompt(result)
    instructions = f"""
You are StreamVault's senior content intelligence analyst. Answer the user's question using ONLY the verified query results supplied below.
Write a comprehensive but readable response with:
1. A direct answer in the first sentence.
2. Key evidence with exact values.
3. Important comparisons, rankings, or patterns when supported.
4. A brief business interpretation or implication.
5. A transparent note when the result is empty, capped, incomplete, or cannot prove causation.
Do not invent facts, totals, percentages, explanations, or titles that are absent from the data.
Format numbers clearly. Format cost as USD and completion rate as a percentage when those fields appear.
Report date: {as_of.isoformat()}.
Interpretation used: {plan.get('interpretation', '')}
Number of returned rows: {len(result)}.
The application caps large detail result sets at {MAX_RESULT_ROWS} rows.
"""
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": f"Question: {question}\nVerified result rows: {result_json}"},
        ],
    )
    return response.output_text.strip()


def local_catalog_search(question: str, as_of: date) -> tuple[str, pd.DataFrame]:
    """Useful no-key fallback: searches every text field for meaningful words."""
    stop = {"what", "which", "where", "when", "how", "many", "much", "are", "is", "the", "a", "an", "of", "in", "on", "with", "and", "or", "to", "for", "show", "tell", "me", "find", "content", "titles", "title", "catalog"}
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9'-]+", question) if len(w) > 2 and w.lower() not in stop]
    words = list(dict.fromkeys(words))[:8]
    if not words:
        return "Enter a more specific question or add an OpenAI API key for full natural-language analytics.", pd.DataFrame()
    searchable = "lower(concat_ws(' ', title, content_type, country, original_language, rating, genre, studio, production_company, acquisition_type, region_availability, keywords, awards, featured_collection, description))"
    clauses, params = ["date_added <= ?"], [as_of]
    for word in words:
        clauses.append(f"{searchable} LIKE ?")
        params.append(f"%{word}%")
    df = query(f"""
        SELECT title AS "Title", content_type AS "Type", country AS "Country",
               original_language AS "Language", release_year AS "Release Year",
               rating AS "Rating", genre AS "Genre", studio AS "Studio",
               audience_score AS "Audience Score", critic_score AS "Critic Score",
               viewing_hours AS "Viewing Hours", completion_rate / 100.0 AS "Completion Rate",
               cost_usd AS "Cost (USD)", region_availability AS "Regions",
               date_added AS "Date Added", description AS "Description"
        FROM catalog WHERE {' AND '.join(clauses)}
        ORDER BY viewing_hours DESC NULLS LAST, audience_score DESC NULLS LAST
        LIMIT 100
    """, params)
    return f"Local search found **{len(df):,} matching records** using these terms: **{', '.join(words)}**. Add an OpenAI API key to enable calculations, comparisons, rankings, and detailed narrative answers to unrestricted questions.", df


def ask_streamvault(question: str, as_of: date, api_key: str, model: str):
    if not api_key:
        text, result = local_catalog_search(question, as_of)
        return text, result, None
    plan = build_query_plan(question, as_of, api_key, model)
    result = query(plan["sql"])
    answer = summarize_answer(question, as_of, plan, result, api_key, model)
    return answer, result, plan


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
        is_numeric = not non_null.any() or numeric[non_null].notna().all()
        # Query results can contain text columns whose names happen to include
        # terms such as "score", "cost", or "count". Do not give those
        # values a numeric format code.
        if not is_numeric:
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
    max_date_value = scalar("SELECT MAX(date_added) FROM catalog")
    min_date_value = scalar("SELECT MIN(date_added) FROM catalog")
    # DuckDB returns DATE aggregates through Pandas as Timestamps; convert
    # them to Python dates before comparing them with TODAY or passing them
    # to Streamlit's date-only widget.
    max_date = pd.Timestamp(max_date_value).date() if pd.notna(max_date_value) else None
    min_date = pd.Timestamp(min_date_value).date() if pd.notna(min_date_value) else None
    default_as_of = min(TODAY, max_date) if max_date else TODAY
    as_of = st.date_input(
        "Report as of",
        value=default_as_of,
        min_value=min_date or TODAY,
        max_value=max(TODAY, max_date) if max_date else TODAY,
    )
    st.caption("Records dated after the selected date are excluded unless requested.")
    st.divider()
    st.markdown("**AI question answering**")
    api_key = get_secret("OPENAI_API_KEY")
    model = get_secret("OPENAI_MODEL", "gpt-4.1-mini")
    if api_key:
        st.success("AI analytics is connected")
        st.caption(f"Model: {model}")
    else:
        st.warning("OpenAI API key not configured")
        st.caption("The app can still search records locally, but advanced calculations and detailed AI answers require a key.")
    st.divider()
    st.markdown("**Trusted definitions**")
    st.caption("International: country is not United States")
    st.caption("Recent: trailing 90 calendar days")
    st.caption("All AI-generated SQL is read-only and validated")

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
                    answer, result, plan = ask_streamvault(question, as_of, api_key, model)
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
                    st.caption("Try rewording the question more specifically. Administrators can also inspect the generated SQL and API configuration.")
                    st.session_state.messages.append({"role": "assistant", "content": error_text})

    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.rerun()

with tabs[2]:
    st.subheader("Catalog data dictionary")
    dictionary = pd.DataFrame([{"Field": k, "Meaning": v} for k, v in SCHEMA.items()])
    st.dataframe(dictionary, use_container_width=True, hide_index=True)
    st.caption("All 26 fields are available to the AI question planner and the catalog explorer.")

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
