import pandas as pd

df = pd.read_csv("content_catalog.csv")

def catalog_overview(df):
    return {
        "total_titles": df["show_id"].nunique(),
        "movies_vs_shows": df["type"].value_counts().to_dict(),
        "top_countries": df["country"].value_counts().head(5).to_dict(),
        "top_genres": df["listed_in"].value_counts().head(5).to_dict(),
    }

def content_trends(df):
    return df.groupby("release_year")["show_id"].count().to_dict()

def runtime_insights(df):
    movies = df[df["type"] == "Movie"].copy()
    shows = df[df["type"] == "TV Show"].copy()
    movies["runtime_min"] = movies["duration"].str.extract(r"(\d+)").astype(float)
    shows["num_seasons"] = shows["duration"].str.extract(r"(\d+)").astype(float)
    return {
        "avg_movie_runtime": movies["runtime_min"].mean(),
        "avg_seasons_per_show": shows["num_seasons"].mean(),
    }

def rating_distribution(df):
    return df["rating"].value_counts().to_dict()

print(catalog_overview(df))
print(content_trends(df))
print(runtime_insights(df))
print(rating_distribution(df))
