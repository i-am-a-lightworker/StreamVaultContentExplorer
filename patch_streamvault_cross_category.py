from pathlib import Path
import re
import shutil
from datetime import datetime

TARGET = Path("streamvault_dashboard.py")

if not TARGET.exists():
    raise SystemExit("streamvault_dashboard.py was not found in this folder.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(f"streamvault_dashboard_backup_{stamp}.py")
shutil.copy2(TARGET, backup)

text = TARGET.read_text(encoding="utf-8")

old_featured = '''    featured = [
        "Catalog Executive Summary",
        "Titles Added by Year",
        "Genre Portfolio",
        "Country Portfolio",
        "Missing Metadata Audit",
    ]'''

new_featured = '''    featured = [
        "Catalog Executive Summary",
        "Titles Added by Year",
        "Genre Portfolio",
        "Country Portfolio",
    ]'''

text = text.replace(old_featured, new_featured)

marker = "\ndef create_template_workbook() -> bytes:\n"

planner_code = r'''
def plan_cross_category_query(question: str) -> dict[str, str]:
    q = question.casefold().strip()

    months_match = re.search(r"\blast\s+(\d+)\s+months?\b", q)
    months = int(months_match.group(1)) if months_match else None

    years_match = re.search(r"\blast\s+(\d+)\s+years?\b", q)
    years = int(years_match.group(1)) if years_match else None

    country_map = {
        "united states": "United States",
        "usa": "United States",
        "u.s.": "United States",
        "us": "United States",
        "united kingdom": "United Kingdom",
        "uk": "United Kingdom",
        "canada": "Canada",
        "india": "India",
        "japan": "Japan",
        "south korea": "South Korea",
        "france": "France",
        "germany": "Germany",
        "spain": "Spain",
        "mexico": "Mexico",
        "brazil": "Brazil",
        "australia": "Australia",
    }

    selected_country = None
    for phrase, country in sorted(
        country_map.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if re.search(rf"\b{re.escape(phrase)}\b", q):
            selected_country = country
            break

    genre_terms = []
    genre_map = {
        "romantic comedies": ["romantic", "comed"],
        "romantic comedy": ["romantic", "comed"],
        "science fiction": ["sci-fi"],
        "documentaries": ["documentar"],
        "documentary": ["documentar"],
        "comedies": ["comed"],
        "comedy": ["comed"],
        "romance": ["romantic"],
        "horror": ["horror"],
        "dramas": ["drama"],
        "drama": ["drama"],
        "action": ["action"],
        "thrillers": ["thriller"],
        "thriller": ["thriller"],
        "children": ["children"],
        "family": ["family"],
        "anime": ["anime"],
        "sci-fi": ["sci-fi"],
    }

    for phrase, terms in sorted(
        genre_map.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if phrase in q:
            genre_terms = terms
            break

    type_filter = None
    if any(word in q for word in ["movie", "movies", "film", "films"]):
        type_filter = "Movie"
    elif any(word in q for word in ["tv show", "tv shows", "series"]):
        type_filter = "TV Show"

    wants_count = any(
        phrase in q for phrase in ["how many", "count", "number of", "total"]
    )

    conditions = ["date_added_date IS NOT NULL"]
    explanation_parts = []

    if selected_country:
        safe_country = selected_country.replace("'", "''")
        conditions.append(
            f"LOWER(COALESCE(country, '')) LIKE LOWER('%{safe_country}%')"
        )
        explanation_parts.append(f"country contains {selected_country}")

    for genre_term in genre_terms:
        safe_term = genre_term.replace("'", "''")
        conditions.append(
            f"LOWER(COALESCE(listed_in, '')) LIKE LOWER('%{safe_term}%')"
        )

    if genre_terms:
        explanation_parts.append("genre matches the requested category")

    if type_filter:
        conditions.append(f"type = '{type_filter}'")
        explanation_parts.append(f"type is {type_filter}")

    if months:
        conditions.append(
            "date(date_added_date) >= date("
            "(SELECT MAX(date(date_added_date)) FROM catalog "
            "WHERE date_added_date IS NOT NULL), "
            f"'-{months} months')"
        )
        explanation_parts.append(
            f"added within {months} months of the latest catalog-addition date"
        )
    elif years:
        conditions.append(
            "date(date_added_date) >= date("
            "(SELECT MAX(date(date_added_date)) FROM catalog "
            "WHERE date_added_date IS NOT NULL), "
            f"'-{years} years')"
        )
        explanation_parts.append(
            f"added within {years} years of the latest catalog-addition date"
        )

    where_clause = "\n  AND ".join(conditions)

    if not selected_country and not genre_terms and not type_filter and not months and not years:
        return {
            "title": "Cross-category catalog results",
            "summary": (
                "The local planner could not identify enough structured filters. "
                "Try including a country, genre, content type, or time period."
            ),
            "sql": """
SELECT show_id, type, title, country, date_added,
       release_year, rating, duration, listed_in
FROM catalog
ORDER BY date_added_date DESC, title
LIMIT 250
""".strip(),
        }

    if wants_count:
        sql = f"""
SELECT
    COUNT(*) AS matching_titles,
    MIN(date_added_date) AS earliest_matching_addition,
    MAX(date_added_date) AS latest_matching_addition
FROM catalog
WHERE {where_clause}
""".strip()
    else:
        sql = f"""
SELECT
    show_id,
    type,
    title,
    country,
    date_added,
    release_year,
    rating,
    duration,
    listed_in
FROM catalog
WHERE {where_clause}
ORDER BY date_added_date DESC, title
LIMIT 500
""".strip()

    explanation = ", ".join(explanation_parts)
    return {
        "title": "Cross-category catalog analysis",
        "summary": (
            f"The API-free local query combined these filters: {explanation}. "
            "Relative time periods use the latest date_added value in the active catalog."
        ),
        "sql": sql,
    }


def run_custom_query(df: pd.DataFrame, question: str) -> None:
    with st.status("Processing your question...", expanded=True) as status:
        st.write("Reading the active catalog...")
        conn = build_database(df)

        st.write("Extracting country, genre, format, and time filters...")
        plan = plan_cross_category_query(question)

        st.write("Validating read-only SQL...")
        valid, reason = validate_read_only_sql(plan["sql"])
        if not valid:
            status.update(label="Query blocked", state="error")
            st.error(reason)
            return

        st.write("Running the local query...")
        try:
            result = pd.read_sql_query(plan["sql"], conn)
        except Exception as exc:
            status.update(label="Query failed", state="error")
            st.error(str(exc))
            return

        status.update(label="Analysis complete", state="complete")

    st.session_state["custom_query_title"] = plan["title"]
    st.session_state["custom_query_summary"] = plan["summary"]
    st.session_state["custom_query_sql"] = plan["sql"]
    st.session_state["custom_query_result"] = result
    st.session_state["custom_query_question"] = question


def render_custom_query_result() -> None:
    if "custom_query_result" not in st.session_state:
        return

    title = st.session_state["custom_query_title"]
    summary = st.session_state["custom_query_summary"]
    sql = st.session_state["custom_query_sql"]
    result = st.session_state["custom_query_result"]
    question = st.session_state["custom_query_question"]

    st.divider()
    st.subheader(title)
    st.markdown(f"**Question:** {question}")
    st.write(summary)
    st.dataframe(result, hide_index=True, use_container_width=True)

    with st.expander("Verify read-only SQL"):
        st.code(sql, language="sql")
        st.success("Verified: one local SELECT or WITH statement only.")

    downloads = st.columns(3)
    downloads[0].download_button(
        "Download PDF",
        dataframe_to_pdf(title, summary, result),
        file_name="streamvault_custom_query.pdf",
        mime="application/pdf",
        use_container_width=True,
    )
    downloads[1].download_button(
        "Download CSV",
        result.to_csv(index=False).encode("utf-8"),
        file_name="streamvault_custom_query.csv",
        mime="text/csv",
        use_container_width=True,
    )
    downloads[2].download_button(
        "Download Excel",
        dataframe_to_excel(result),
        file_name="streamvault_custom_query.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


def render_ask_catalog(df: pd.DataFrame) -> None:
    st.subheader("Ask across catalog categories")
    st.caption(
        "Combine country, genre, format, and date-added filters without an API."
    )

    examples = [
        "How many US romantic comedies were placed onto the catalog in the last 6 months?",
        "Show Canadian documentaries added in the last 2 years.",
        "How many Japanese anime TV shows were added in the last 12 months?",
        "Show US horror movies added in the last 3 years.",
    ]

    selected = st.selectbox(
        "Sample sophisticated questions",
        ["Write my own question"] + examples,
    )

    initial = "" if selected == "Write my own question" else selected
    question = st.text_area(
        "Business question",
        value=initial,
        placeholder=(
            "Example: How many US romantic comedies were placed onto "
            "the catalog in the last 6 months?"
        ),
        height=110,
    )

    if st.button("Process question", type="primary", use_container_width=True):
        if not question.strip():
            st.warning("Enter a business question.")
        else:
            run_custom_query(df, question)

    render_custom_query_result()
'''

if marker not in text:
    raise SystemExit(
        "Could not find the insertion point. Confirm this is the Standard Reports version."
    )

text = text.replace(marker, "\n" + planner_code + marker, 1)

old_tabs = '''    tab_reports, tab_data = st.tabs(["Standard Reports", "Catalog Records"])

    with tab_reports:
        render_standard_reports(df)
        render_report_result()

    with tab_data:
        st.dataframe(
            df[REQUIRED_COLUMNS],
            hide_index=True,
            use_container_width=True,
        )'''

new_tabs = '''    tab_reports, tab_ask, tab_data = st.tabs(
        ["Standard Reports", "Ask the Catalog", "Catalog Records"]
    )

    with tab_reports:
        render_standard_reports(df)
        render_report_result()

    with tab_ask:
        render_ask_catalog(df)

    with tab_data:
        st.dataframe(
            df[REQUIRED_COLUMNS],
            hide_index=True,
            use_container_width=True,
        )'''

if old_tabs not in text:
    raise SystemExit(
        "Could not find the dashboard tab block. Confirm the current app is the Standard Reports version."
    )

text = text.replace(old_tabs, new_tabs, 1)

TARGET.write_text(text, encoding="utf-8")

print(f"Updated: {TARGET}")
print(f"Backup:  {backup}")
print("Duplicate featured Missing Metadata card removed.")
print("Ask the Catalog cross-category query tab added.")
