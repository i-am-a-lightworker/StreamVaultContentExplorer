# STREAMVAULT deployment

## Local launch

```powershell
python -m pip install -r requirements.txt
python -m streamlit run streamvault_dashboard.py
```

## Streamlit Community Cloud

1. Commit these files to the GitHub repository:
   - `streamvault_dashboard.py`
   - `netflix_titles.csv`
   - `requirements.txt`
   - `.streamlit/config.toml`
2. Push the repository.
3. In Streamlit Community Cloud, create an app from the repository.
4. Select `streamvault_dashboard.py` as the entrypoint.
5. Use Python 3.12 unless your existing deployment requires another supported version.
6. Deploy.
7. Copy the final `streamlit.app` URL into the Launch button in `index.html`.

## GitHub Pages landing page

GitHub Pages hosts the static `index.html` landing page. It does not run the Python Streamlit application.

1. Replace `https://YOUR-STREAMLIT-SUBDOMAIN.streamlit.app` in `index.html`.
2. Commit and push `index.html`.
3. In GitHub: **Settings → Pages**.
4. Deploy from the repository branch containing `index.html`.
