# StreamVault Dashboard

StreamVault is an interactive Streamlit content-intelligence application for a 26-field streaming catalog. It combines DuckDB calculations with an optional OpenAI question planner and analyst so users can ask detailed natural-language questions and receive grounded answers with supporting records.

## New interactive question-answering capability

The **Ask StreamVault** tab now supports questions across all 26 catalog fields, including:

- Titles, content type, country, language, release year, rating, and genre
- Runtime, seasons, episodes, studio, and production company
- Acquisition type and license expiration
- Audience score, critic score, viewing hours, completion rate, and cost
- Region availability, keywords, awards, featured collections, date added, and description

The workflow is:

1. The AI interprets the question.
2. It creates one read-only DuckDB `SELECT` query.
3. StreamVault validates the query and blocks write/admin operations.
4. DuckDB calculates the answer from the catalog.
5. The AI explains only the verified results.
6. The user can inspect the SQL and download the supporting data.

Without an API key, the app still provides a local search across all text fields. Full calculations, comparisons, rankings, and narrative responses require an OpenAI API key.

## Run locally

```powershell
cd C:\Users\sha\Desktop\Github-Projects\streamvault_dashboard
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Configure the OpenAI API key locally

Create this folder and file inside the project:

```text
.streamlit\secrets.toml
```

Add:

```toml
OPENAI_API_KEY = "your-api-key-here"
OPENAI_MODEL = "gpt-4.1-mini"
```

Never commit `secrets.toml`. The included `.gitignore` excludes it.

## Configure Streamlit Community Cloud

In the deployed app, open **App settings → Secrets** and add:

```toml
OPENAI_API_KEY = "your-api-key-here"
OPENAI_MODEL = "gpt-4.1-mini"
```

Then save and reboot the app.

## Safety and accuracy controls

- Only one read-only `SELECT`/`WITH` statement is allowed.
- Data-changing and administrative SQL commands are blocked.
- Questions default to records on or before the selected report date.
- Detail outputs are capped to protect performance.
- Answers are generated from query results, not from model memory.
- Users can expand **How StreamVault analyzed this question** to inspect the interpretation and SQL.

## Verified baseline metrics as of July 23, 2026

- Active catalog records: 9,992
- Movies: 5,013 (50.2%)
- TV shows: 4,979 (49.8%)
- International additions this quarter: 103 of 161 (64.0%)
- Documentary share this quarter: 9 of 161 (5.6%)
- Documentary share previous quarter: 60 of 717 (8.4%)
- Countries with no additions in the previous 90 days: none
