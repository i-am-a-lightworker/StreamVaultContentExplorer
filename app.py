
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import re

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st


APP_DIR = Path(__file__).resolve().parent
CATALOG_PATH = APP_DIR / "data" / "catalog.csv"
TODAY = date.today()

st.set_page_config(
    page_title="StreamVault",
    page_icon="🎬",
    layout="wide",
)

@st.cache_resource
def get_connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    # DuckDB cannot bind parameters in CREATE VIEW statements. Normalize the
    # Windows path and escape apostrophes before inserting it into the SQL.
    csv_path = str(CATALOG_PATH).replace("\\", "/").replace("'", "''")
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
        FROM read_csv_auto('{csv_path}', header=true, all_varchar=true)
        """
    )
    return con

def query(sql: str, params: list | None = None) -> pd.DataFrame:
    con = get_connection()
    return con.execute(sql, params or []).df()

def scalar(sql: str, params: list | None = None):
    df = query(sql, params)
    return df.iloc[0, 0] if not df.empty else None

def period_bounds(as_of: date):
    q_month = ((as_of.month - 1) // 3) * 3 + 1
    q_start = date(as_of.year, q_month, 1)
    if q_month == 10:
        next_q = date(as_of.year + 1, 1, 1)
    else:
        next_q = date(as_of.year, q_month + 3, 1)
    if q_month == 1:
        prev_q = date(as_of.year - 1, 10, 1)
    else:
        prev_q = date(as_of.year, q_month - 3, 1)
    return q_start, next_q, prev_q

def pct(n, d):
    return 0.0 if not d else 100.0 * n / d

def core_metrics(as_of: date) -> dict:
    q_start, q_end, prev_q_start = period_bounds(as_of)
    total = scalar("SELECT COUNT(*) FROM catalog WHERE date_added <= ?", [as_of])
    movies = scalar(
        "SELECT COUNT(*) FROM catalog WHERE date_added <= ? AND content_type='Movie'",
        [as_of],
    )
    shows = scalar(
        "SELECT COUNT(*) FROM catalog WHERE date_added <= ? AND content_type='TV Show'",
        [as_of],
    )
    current = scalar(
        "SELECT COUNT(*) FROM catalog WHERE date_added >= ? AND date_added < ? AND date_added <= ?",
        [q_start, q_end, as_of],
    )
    international = scalar(
        """
        SELECT COUNT(*) FROM catalog
        WHERE date_added >= ? AND date_added < ? AND date_added <= ?
          AND lower(trim(country)) <> 'united states'
        """,
        [q_start, q_end, as_of],
    )
    doc_current = scalar(
        """
        SELECT COUNT(*) FROM catalog
        WHERE date_added >= ? AND date_added < ? AND date_added <= ?
          AND lower(genre) = 'documentary'
        """,
        [q_start, q_end, as_of],
    )
    previous = scalar(
        "SELECT COUNT(*) FROM catalog WHERE date_added >= ? AND date_added < ?",
        [prev_q_start, q_start],
    )
    doc_previous = scalar(
        """
        SELECT COUNT(*) FROM catalog
        WHERE date_added >= ? AND date_added < ?
          AND lower(genre) = 'documentary'
        """,
        [prev_q_start, q_start],
    )
    future = scalar("SELECT COUNT(*) FROM catalog WHERE date_added > ?", [as_of])
    return {
        "total": int(total or 0),
        "movies": int(movies or 0),
        "shows": int(shows or 0),
        "current": int(current or 0),
        "international": int(international or 0),
        "doc_current": int(doc_current or 0),
        "previous": int(previous or 0),
        "doc_previous": int(doc_previous or 0),
        "future": int(future or 0),
        "q_start": q_start,
        "q_end": q_end,
        "prev_q_start": prev_q_start,
    }

def answer_question(question: str, as_of: date) -> tuple[str, pd.DataFrame | None]:
    q = question.lower().strip()
    m = core_metrics(as_of)
    movie_share = pct(m["movies"], m["total"])
    intl_share = pct(m["international"], m["current"])
    doc_now = pct(m["doc_current"], m["current"])
    doc_prev = pct(m["doc_previous"], m["previous"])
    pp_change = doc_now - doc_prev
    rel_change = 0 if doc_prev == 0 else ((doc_now / doc_prev) - 1) * 100

    if any(x in q for x in ["how many titles", "total titles", "catalog size"]):
        detail = query(
            """
            SELECT content_type AS "Type", COUNT(*) AS "Titles"
            FROM catalog WHERE date_added <= ?
            GROUP BY content_type ORDER BY "Titles" DESC
            """,
            [as_of],
        )
        return (
            f"StreamVault contains **{m['total']:,} active catalog records** as of "
            f"**{as_of:%B %d, %Y}**. Future-dated additions are excluded.",
            detail,
        )

    if ("movie" in q and ("show" in q or "tv" in q)) or "mix" in q:
        detail = pd.DataFrame(
            {
                "Type": ["Movies", "TV Shows"],
                "Titles": [m["movies"], m["shows"]],
                "Share": [movie_share / 100, (100 - movie_share) / 100],
            }
        )
        return (
            f"The catalog is almost evenly split: **{m['movies']:,} movies "
            f"({movie_share:.1f}%)** and **{m['shows']:,} TV shows "
            f"({100-movie_share:.1f}%)**.",
            detail,
        )

    if "international" in q or "foreign" in q:
        detail = query(
            """
            SELECT country AS "Country", COUNT(*) AS "Titles Added"
            FROM catalog
            WHERE date_added >= ? AND date_added < ? AND date_added <= ?
              AND lower(trim(country)) <> 'united states'
            GROUP BY country
            ORDER BY "Titles Added" DESC, country
            """,
            [m["q_start"], m["q_end"], as_of],
        )
        return (
            f"**{intl_share:.1f}%** of additions this quarter are international: "
            f"**{m['international']:,} of {m['current']:,} titles**. "
            f"International means the listed country is not the United States.",
            detail,
        )

    if "documentar" in q:
        detail = pd.DataFrame(
            {
                "Period": ["Previous quarter", "Current quarter"],
                "Documentaries": [m["doc_previous"], m["doc_current"]],
                "All additions": [m["previous"], m["current"]],
                "Documentary share": [doc_prev / 100, doc_now / 100],
            }
        )
        direction = "down" if pp_change < 0 else "up"
        return (
            f"Documentaries account for **{doc_now:.1f}%** of this quarter's additions "
            f"({m['doc_current']} of {m['current']}) versus **{doc_prev:.1f}%** last "
            f"quarter ({m['doc_previous']} of {m['previous']}). That is **{abs(pp_change):.1f} "
            f"percentage points {direction}**, a **{abs(rel_change):.1f}% relative "
            f"{'decline' if rel_change < 0 else 'increase'}**.",
            detail,
        )

    if ("country" in q or "region" in q) and any(
        x in q for x in ["no additions", "without", "inactive", "90 days", "recent"]
    ):
        start = as_of - timedelta(days=89)
        detail = query(
            """
            WITH all_countries AS (
                SELECT DISTINCT country FROM catalog WHERE date_added <= ?
            ),
            recent AS (
                SELECT DISTINCT country FROM catalog
                WHERE date_added BETWEEN ? AND ?
            )
            SELECT a.country AS "Country"
            FROM all_countries a
            LEFT JOIN recent r USING (country)
            WHERE r.country IS NULL
            ORDER BY a.country
            """,
            [as_of, start, as_of],
        )
        if detail.empty:
            text = (
                f"**No countries are inactive.** Every country represented in the catalog "
                f"had at least one addition during the 90-day window from "
                f"**{start:%B %d, %Y} through {as_of:%B %d, %Y}**."
            )
        else:
            text = (
                f"**{len(detail)} countries** had no additions during the last 90 days: "
                + ", ".join(detail["Country"].tolist()) + "."
            )
        return text, detail

    return (
        "I can currently answer the five trusted questions shown above. "
        "Try asking about catalog size, movie versus TV mix, international additions, "
        "documentary trends, or countries with no additions in the last 90 days.",
        None,
    )

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.4rem; padding-bottom: 2rem;}
    .sv-title {font-size: 2.35rem; font-weight: 800; letter-spacing: -0.03em;}
    .sv-sub {color: #6b7280; margin-top: -0.5rem; margin-bottom: 1rem;}
    div[data-testid="stMetric"] {
        border: 1px solid rgba(120,120,120,.22);
        border-radius: 14px;
        padding: 14px;
        background: rgba(127,127,127,.04);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="sv-title">🎬 StreamVault</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sv-sub">Content catalog intelligence dashboard</div>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Analysis settings")
    max_date = scalar("SELECT MAX(date_added) FROM catalog")
    min_date = scalar("SELECT MIN(date_added) FROM catalog")
    # `max_date`/`min_date` may be pandas.Timestamp (or NaT). Convert to
    # datetime.date and handle NaT safely before passing to Streamlit.
    if pd.isna(max_date):
        default_as_of = TODAY
        max_value = TODAY
    else:
        max_value = max_date.date() if isinstance(max_date, pd.Timestamp) else max_date
        default_as_of = min(TODAY, max_value)

    min_value = None if pd.isna(min_date) else (min_date.date() if isinstance(min_date, pd.Timestamp) else min_date)

    as_of = st.date_input(
        "Report as of",
        value=default_as_of,
        min_value=min_value,
        max_value=max_value,
    )
    st.caption("Records dated after the selected date are excluded.")
    st.divider()
    st.markdown("**Trusted definitions**")
    st.caption("International: country is not United States")
    st.caption("Documentary: Genre equals Documentary")
    st.caption("Recent: trailing 90 calendar days")

metrics = core_metrics(as_of)
movie_share = pct(metrics["movies"], metrics["total"])
intl_share = pct(metrics["international"], metrics["current"])
doc_current_share = pct(metrics["doc_current"], metrics["current"])
doc_prev_share = pct(metrics["doc_previous"], metrics["previous"])

if metrics["future"]:
    st.warning(
        f"Data quality: {metrics['future']} catalog records are dated after "
        f"{as_of:%B %d, %Y} and are excluded from current metrics."
    )

tabs = st.tabs(["Overview", "Ask StreamVault", "Trends", "Catalog Explorer"])

with tabs[0]:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Catalog Titles", f"{metrics['total']:,}")
    c2.metric("Movies", f"{metrics['movies']:,}", f"{movie_share:.1f}%")
    c3.metric("TV Shows", f"{metrics['shows']:,}", f"{100-movie_share:.1f}%")
    c4.metric("Added This Quarter", f"{metrics['current']:,}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("International This Quarter", f"{intl_share:.1f}%")
    c6.metric(
        "Documentaries This Quarter",
        f"{doc_current_share:.1f}%",
        f"{doc_current_share-doc_prev_share:+.1f} pp vs prior quarter",
    )
    c7.metric(
        "Countries",
        f"{scalar('SELECT COUNT(DISTINCT country) FROM catalog WHERE date_added <= ?', [as_of]):,}",
    )
    c8.metric(
        "Genres",
        f"{scalar('SELECT COUNT(DISTINCT genre) FROM catalog WHERE date_added <= ?', [as_of]):,}",
    )

    left, right = st.columns(2)
    with left:
        type_df = query(
            """
            SELECT content_type AS "Type", COUNT(*) AS "Titles"
            FROM catalog WHERE date_added <= ?
            GROUP BY content_type
            """,
            [as_of],
        )
        fig = px.pie(type_df, names="Type", values="Titles", hole=.58, title="Movie vs TV Mix")
        st.plotly_chart(fig, use_container_width=True)
    with right:
        genre_df = query(
            """
            SELECT genre AS "Genre", COUNT(*) AS "Titles"
            FROM catalog WHERE date_added <= ?
            GROUP BY genre ORDER BY "Titles" DESC LIMIT 10
            """,
            [as_of],
        )
        fig = px.bar(genre_df.sort_values("Titles"), x="Titles", y="Genre",
                     orientation="h", title="Top Genres")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Executive snapshot")
    st.markdown(
        f"""
        As of **{as_of:%B %d, %Y}**, StreamVault contains **{metrics['total']:,} titles**.
        The catalog is nearly evenly divided between movies and television shows.
        This quarter, **{intl_share:.1f}%** of additions are international.
        Documentary share is **{doc_current_share:.1f}%**, compared with
        **{doc_prev_share:.1f}%** in the previous quarter.
        """
    )

with tabs[1]:
    st.subheader("Ask a trusted catalog question")
    suggested = [
        "How many titles are in the catalog?",
        "What is the movie-to-TV-show mix?",
        "What percentage of additions this quarter are international?",
        "How do documentary additions compare with last quarter?",
        "Which countries have had no additions in the last 90 days?",
    ]

    cols = st.columns(2)
    selected = None
    for i, prompt in enumerate(suggested):
        if cols[i % 2].button(prompt, use_container_width=True, key=f"q{i}"):
            selected = prompt

    user_question = st.chat_input("Ask one of the trusted catalog questions")
    question = user_question or selected

    if question:
        with st.chat_message("user"):
            st.write(question)
        answer, detail = answer_question(question, as_of)
        with st.chat_message("assistant"):
            st.markdown(answer)
            if detail is not None and not detail.empty:
                display = detail.copy()
                for col in display.columns:
                    if "Share" in col or "share" in col:
                        st.dataframe(
                            display.style.format({col: "{:.1%}"}),
                            use_container_width=True,
                            hide_index=True,
                        )
                        break
                else:
                    st.dataframe(display, use_container_width=True, hide_index=True)

with tabs[2]:
    monthly = query(
        """
        SELECT date_trunc('month', date_added) AS month,
               COUNT(*) AS titles_added
        FROM catalog
        WHERE date_added <= ?
        GROUP BY month ORDER BY month
        """,
        [as_of],
    )
    fig = px.line(monthly, x="month", y="titles_added", markers=True,
                  title="Titles Added by Month")
    st.plotly_chart(fig, use_container_width=True)

    quarterly = query(
        """
        SELECT
          date_trunc('quarter', date_added) AS quarter,
          COUNT(*) AS total_additions,
          COUNT(*) FILTER (WHERE lower(country) <> 'united states') AS international,
          COUNT(*) FILTER (WHERE lower(genre) = 'documentary') AS documentaries
        FROM catalog
        WHERE date_added <= ?
        GROUP BY quarter ORDER BY quarter
        """,
        [as_of],
    )
    quarterly["International Share"] = quarterly["international"] / quarterly["total_additions"]
    quarterly["Documentary Share"] = quarterly["documentaries"] / quarterly["total_additions"]
    trend = quarterly.melt(
        id_vars=["quarter"],
        value_vars=["International Share", "Documentary Share"],
        var_name="Metric",
        value_name="Share",
    )
    fig = px.line(trend, x="quarter", y="Share", color="Metric", markers=True,
                  title="Quarterly Content Mix")
    fig.update_yaxes(tickformat=".0%")
    st.plotly_chart(fig, use_container_width=True)

with tabs[3]:
    f1, f2, f3, f4 = st.columns(4)
    countries = ["All"] + query(
        "SELECT DISTINCT country FROM catalog ORDER BY country"
    )["country"].tolist()
    genres = ["All"] + query(
        "SELECT DISTINCT genre FROM catalog ORDER BY genre"
    )["genre"].tolist()
    types = ["All", "Movie", "TV Show"]
    country = f1.selectbox("Country", countries)
    genre = f2.selectbox("Genre", genres)
    content_type = f3.selectbox("Type", types)
    search = f4.text_input("Title contains")

    conditions = ["date_added <= ?"]
    params = [as_of]
    if country != "All":
        conditions.append("country = ?")
        params.append(country)
    if genre != "All":
        conditions.append("genre = ?")
        params.append(genre)
    if content_type != "All":
        conditions.append("content_type = ?")
        params.append(content_type)
    if search:
        conditions.append("lower(title) LIKE ?")
        params.append(f"%{search.lower()}%")

    explorer = query(
        f"""
        SELECT
          title AS "Title",
          content_type AS "Type",
          country AS "Country",
          genre AS "Genre",
          release_year AS "Release Year",
          rating AS "Rating",
          date_added AS "Date Added",
          viewing_hours AS "Viewing Hours",
          completion_rate / 100.0 AS "Completion Rate"
        FROM catalog
        WHERE {' AND '.join(conditions)}
        ORDER BY date_added DESC, title
        LIMIT 1000
        """,
        params,
    )
    st.caption(f"Showing {len(explorer):,} records (maximum 1,000).")
    st.dataframe(
        explorer.style.format(
            {"Viewing Hours": "{:,.0f}", "Completion Rate": "{:.0%}"}
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "Download filtered results",
        explorer.to_csv(index=False).encode("utf-8"),
        "streamvault_filtered_catalog.csv",
        "text/csv",
    )
