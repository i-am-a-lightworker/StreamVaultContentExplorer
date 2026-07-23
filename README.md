# StreamVault — Local Interactive Catalog Intelligence

StreamVault is a browser-based dashboard for exploring a 26-field streaming-content catalog. When published on Streamlit Community Cloud, visitors only open the app's web link—there is nothing to download, install, or configure. The question engine runs on the hosted server with DuckDB and deterministic natural-language rules. It requires **no OpenAI API key, no API credits, and no paid model calls**.

## What users can ask

The local engine supports:

- Counts: “How many Spanish-language dramas are in the catalog?”
- Rankings: “Which 10 titles have the highest viewing hours?”
- Comparisons: “Compare movies and TV shows by average cost and audience score.”
- Grouped analysis: “Show average completion rate by genre.”
- License reviews: “Which licenses expire in the next 90 days?”
- Value analysis: “Which genres have the highest audience score per dollar?”
- Theme and description searches: “Find titles about friendship or coming of age.”
- Filters using catalog values such as country, language, genre, rating, studio, type, year, and score threshold.

Every answer is calculated against the catalog CSV included with the app. The app displays the supporting records and the read-only SQL used for the result.

## Use the published app

Once the publisher deploys StreamVault, share its `streamlit.app` URL. Visitors can open that link in any modern browser and start using the dashboard immediately. They do not need Python, Git, the repository, or any local files.

## Publish to the browser with Streamlit Community Cloud

The repository is ready to deploy as-is: `app.py` is the entrypoint, `requirements.txt` declares the server dependencies, and `data/catalog.csv` is bundled with the app.

1. Push this repository to GitHub.
2. Sign in at [Streamlit Community Cloud](https://share.streamlit.io/) with the GitHub account that owns the repository.
3. Select **Create app**, choose the repository and the `main` branch, then set the entrypoint file to `app.py`.
4. Optionally choose a memorable `streamlit.app` subdomain, then deploy.
5. Share the resulting browser URL with users.

Future pushes to the selected branch update the hosted app automatically. See Streamlit's [deployment guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy) for publisher account and visibility options.

## Local development (optional)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run locally

```powershell
streamlit run app.py
```

Open `http://localhost:8501` if the browser does not open automatically.

## No API configuration is needed

Do not create a `.streamlit/secrets.toml` file for this version. The `openai` package is not included in `requirements.txt`, and the application does not send catalog data or questions to an external AI service.

## How the local question engine works

1. Detects the requested operation: count, ranking, comparison, average, total, license review, efficiency analysis, or descriptive search.
2. Detects metrics such as viewing hours, cost, audience score, critic score, completion rate, runtime, seasons, and episodes.
3. Detects grouping fields and filters from the 26 catalog columns.
4. Builds a read-only DuckDB query.
5. Executes the query locally.
6. Produces a concise explanation, identifies common patterns when supported, and displays the exact result table.

## Important limitation

A deterministic local engine is highly reliable for supported analytical phrasing, but it does not have the unlimited language flexibility of a large language model. When a question is too broad, StreamVault automatically falls back to ranked keyword search across the catalog’s text fields. Rewording with a metric, category, filter, comparison, or ranking usually produces the strongest result.

## Multi-genre questions

The local question engine recognizes every catalog genre named in a question instead of applying only the first genre. It can combine, count, rank, or compare selected genre groups without an API key.

Examples:

- `Show the top 20 titles across Action, Comedy, and Drama.`
- `Compare average audience scores for Horror, Thriller, and Sci-Fi.`
- `How many titles are in Romance, Family, and Fantasy?`
- `Which Action, Crime, or Thriller titles have the highest viewing hours?`

The current catalog contains one **primary genre** per title. Multi-genre questions therefore combine titles from several requested genre categories into one analysis; they do not claim that an individual title has several stored genre labels.
