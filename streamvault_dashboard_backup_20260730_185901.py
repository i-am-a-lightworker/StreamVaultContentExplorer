from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="STREAMVAULT Content Explorer",
    page_icon="🎬",
    layout="wide",
)

BLANK_TOKENS = {
    "", " ", "none", "null", "nan", "n/a", "na",
    "nothing", "blank", "unknown", "-", "--"
}

DEFAULT_DATASET = "netflix_titles.csv"


def normalize_blank(value):
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
        re.sub(r"[^a-z0-9]+", "_", str(col).strip().lower()).strip("_")
        for col in df.columns
    ]

    for column in df.columns:
        df[column] = df[column].map(normalize_blank).astype("string")

    if "release_year" in df.columns:
        df["release_year_num"] = pd.to_numeric(
            df["release_year"], errors="coerce"
        ).astype("Int64")

    if "date_added" in df.columns:
        df["date_added_parsed"] = pd.to_datetime(
            df["date_added"], errors="coerce"
        )

    if "duration" in df.columns:
        df["duration_value"] = pd.to_numeric(
            df["duration"].str.extract(r"(\d+)", expand=False),
            errors="coerce",
        )
        df["duration_unit"] = (
            df["duration"]
            .str.extract(r"([A-Za-z]+)", expand=False)
            .str.casefold()
        )

    return df


def split_multi_value(series: pd.Series) -> pd.Series:
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


def safe_count(df: pd.DataFrame, column: str) -> int:
    return int(df[column].notna().sum()) if column in df.columns else 0


def top_counts(series: pd.Series, limit: int = 15) -> pd.DataFrame:
    counts = (
        series.dropna()
        .astype(str)
        .str.strip()
        .loc[lambda s: s.ne("")]
        .value_counts()
        .head(limit)
        .rename_axis("Name")
        .reset_index(name="Titles")
    )
    return counts


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df.copy()

    with st.sidebar:
        st.header("Filter catalog")

        if "type" in df.columns:
            values = sorted(df["type"].dropna().unique().tolist())
            selected = st.multiselect("Content type", values, default=values)
            if selected:
                filtered = filtered[filtered["type"].isin(selected)]

        if "release_year_num" in df.columns:
            years = df["release_year_num"].dropna()
            if not years.empty:
                minimum, maximum = int(years.min()), int(years.max())
                selected_years = st.slider(
                    "Release year",
                    minimum,
                    maximum,
                    (minimum, maximum),
                )
                filtered = filtered[
                    filtered["release_year_num"].between(
                        selected_years[0], selected_years[1]
                    )
                ]

        if "rating" in df.columns:
            ratings = sorted(df["rating"].dropna().unique().tolist())
            selected_ratings = st.multiselect("Rating", ratings)
            if selected_ratings:
                filtered = filtered[
                    filtered["rating"].isin(selected_ratings)
                ]

        search_text = st.text_input(
            "Search title or description",
            placeholder="Enter keywords",
        ).strip()

        if search_text:
            searchable = pd.Series(False, index=filtered.index)
            for column in ("title", "description", "listed_in", "cast", "director"):
                if column in filtered.columns:
                    searchable |= filtered[column].fillna("").str.contains(
                        search_text,
                        case=False,
                        regex=False,
                    )
            filtered = filtered[searchable]

    return filtered


def render_overview(df: pd.DataFrame):
    st.subheader("Catalog overview")

    countries = (
        split_multi_value(df["country"])
        if "country" in df.columns else pd.Series(dtype="string")
    )
    genres = (
        split_multi_value(df["listed_in"])
        if "listed_in" in df.columns else pd.Series(dtype="string")
    )

    metrics = st.columns(4)
    metrics[0].metric("Titles", f"{len(df):,}")
    metrics[1].metric(
        "Movies",
        f"{int(df['type'].eq('Movie').sum()):,}" if "type" in df.columns else "—",
    )
    metrics[2].metric(
        "TV Shows",
        f"{int(df['type'].eq('TV Show').sum()):,}" if "type" in df.columns else "—",
    )
    metrics[3].metric(
        "Unique countries",
        f"{countries.str.casefold().nunique():,}" if not countries.empty else "—",
    )

    metrics = st.columns(4)
    metrics[0].metric(
        "Unique genres",
        f"{genres.str.casefold().nunique():,}" if not genres.empty else "—",
    )
    metrics[1].metric("Missing directors", f"{int(df['director'].isna().sum()):,}" if "director" in df.columns else "—")
    metrics[2].metric("Missing cast", f"{int(df['cast'].isna().sum()):,}" if "cast" in df.columns else "—")
    metrics[3].metric("Missing countries", f"{int(df['country'].isna().sum()):,}" if "country" in df.columns else "—")


def render_template_reports(df: pd.DataFrame):
    tabs = st.tabs([
        "Content Mix",
        "Release Trends",
        "Countries",
        "Genres",
        "Ratings",
        "People",
        "Duration",
        "Data Quality",
    ])

    with tabs[0]:
        st.subheader("Content type distribution")
        if "type" in df.columns:
            type_counts = df["type"].value_counts().rename("Titles")
            st.bar_chart(type_counts)
            st.dataframe(
                type_counts.rename_axis("Content Type").reset_index(),
                hide_index=True,
                use_container_width=True,
            )

    with tabs[1]:
        st.subheader("Titles by release year")
        if "release_year_num" in df.columns:
            yearly = (
                df.dropna(subset=["release_year_num"])
                .groupby("release_year_num")
                .size()
                .rename("Titles")
                .sort_index()
            )
            st.line_chart(yearly)

        if "date_added_parsed" in df.columns:
            st.subheader("Titles added to catalog by year")
            added = (
                df.dropna(subset=["date_added_parsed"])
                .assign(added_year=lambda x: x["date_added_parsed"].dt.year)
                .groupby("added_year")
                .size()
                .rename("Titles Added")
                .sort_index()
            )
            st.line_chart(added)

    with tabs[2]:
        st.subheader("Top production countries")
        if "country" in df.columns:
            countries = split_multi_value(df["country"])
            country_report = top_counts(countries, 20)
            st.bar_chart(country_report.set_index("Name")["Titles"])
            st.dataframe(country_report, hide_index=True, use_container_width=True)

            raw_combinations = int(df["country"].dropna().nunique())
            normalized_countries = int(countries.str.casefold().nunique())
            st.caption(
                f"Raw country combinations: {raw_combinations:,} · "
                f"Normalized individual countries: {normalized_countries:,}"
            )

    with tabs[3]:
        st.subheader("Top genres and categories")
        if "listed_in" in df.columns:
            genres = split_multi_value(df["listed_in"])
            genre_report = top_counts(genres, 20)
            st.bar_chart(genre_report.set_index("Name")["Titles"])
            st.dataframe(genre_report, hide_index=True, use_container_width=True)

    with tabs[4]:
        st.subheader("Ratings distribution")
        if "rating" in df.columns:
            rating_report = top_counts(df["rating"], 25)
            st.bar_chart(rating_report.set_index("Name")["Titles"])
            st.dataframe(rating_report, hide_index=True, use_container_width=True)

    with tabs[5]:
        director_col, cast_col = st.columns(2)

        with director_col:
            st.subheader("Top directors")
            if "director" in df.columns:
                directors = split_multi_value(df["director"])
                st.dataframe(
                    top_counts(directors, 15),
                    hide_index=True,
                    use_container_width=True,
                )

        with cast_col:
            st.subheader("Most-listed cast members")
            if "cast" in df.columns:
                cast = split_multi_value(df["cast"])
                st.dataframe(
                    top_counts(cast, 15),
                    hide_index=True,
                    use_container_width=True,
                )

    with tabs[6]:
        movie_col, tv_col = st.columns(2)

        with movie_col:
            st.subheader("Movie duration")
            if {"type", "duration_value"}.issubset(df.columns):
                movies = df[
                    df["type"].eq("Movie") & df["duration_value"].notna()
                ]
                if not movies.empty:
                    st.metric(
                        "Median runtime",
                        f"{movies['duration_value'].median():.0f} minutes",
                    )
                    bins = pd.cut(
                        movies["duration_value"],
                        bins=[0, 60, 90, 120, 180, float("inf")],
                        labels=["≤60", "61–90", "91–120", "121–180", "180+"],
                    )
                    st.bar_chart(bins.value_counts().sort_index())

        with tv_col:
            st.subheader("TV show seasons")
            if {"type", "duration_value"}.issubset(df.columns):
                shows = df[
                    df["type"].eq("TV Show") & df["duration_value"].notna()
                ]
                if not shows.empty:
                    st.metric(
                        "Median seasons",
                        f"{shows['duration_value'].median():.0f}",
                    )
                    seasons = (
                        shows["duration_value"]
                        .value_counts()
                        .sort_index()
                        .head(15)
                    )
                    st.bar_chart(seasons)

    with tabs[7]:
        st.subheader("Missing-field audit")
        audit = pd.DataFrame({
            "Field": df.columns,
            "Blank cells": [int(df[c].isna().sum()) for c in df.columns],
            "Complete cells": [int(df[c].notna().sum()) for c in df.columns],
            "Completion rate": [
                f"{df[c].notna().mean() * 100:.1f}%"
                for c in df.columns
            ],
            "Unique nonblank values": [
                int(df[c].dropna().nunique())
                for c in df.columns
            ],
        }).sort_values("Blank cells", ascending=False)

        st.dataframe(audit, hide_index=True, use_container_width=True)
        st.metric("Exact duplicate rows", f"{int(df.duplicated().sum()):,}")


def render_catalog_table(df: pd.DataFrame):
    st.subheader("Filtered catalog")

    preferred = [
        "show_id", "type", "title", "director", "country",
        "release_year", "rating", "duration", "listed_in"
    ]
    visible = [column for column in preferred if column in df.columns]

    display_df = df[visible].fillna("")
    st.dataframe(display_df, hide_index=True, use_container_width=True)

    st.download_button(
        "Download filtered catalog",
        data=display_df.to_csv(index=False).encode("utf-8"),
        file_name="streamvault_filtered_catalog.csv",
        mime="text/csv",
    )


def main():
    st.title("STREAMVAULT Content Explorer")
    st.caption(
        "Dynamic catalog reporting with blank values treated as empty."
    )

    uploaded = st.file_uploader("Upload a catalog CSV", type=["csv"])

    if uploaded is not None:
        source = uploaded
    elif Path(DEFAULT_DATASET).exists():
        source = DEFAULT_DATASET
        st.info(f"Loaded default dataset: {DEFAULT_DATASET}")
    else:
        st.warning(
            f"Upload a CSV or place {DEFAULT_DATASET} in the app folder."
        )
        st.stop()

    try:
        catalog = load_catalog(source)
    except Exception as exc:
        st.error(f"Could not load the catalog: {exc}")
        st.stop()

    filtered = apply_filters(catalog)

    if filtered.empty:
        st.warning("No records match the selected filters.")
        st.stop()

    render_overview(filtered)
    render_template_reports(filtered)
    render_catalog_table(filtered)


if __name__ == "__main__":
    main()
