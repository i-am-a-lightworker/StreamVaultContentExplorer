# StreamVault Dashboard

A ready-to-run Streamlit dashboard for the uploaded 10,000-record streaming content catalog.

## Verified business answers (as of July 23, 2026)

1. **Catalog size:** 9,992 records are active as of the report date. Eight records dated July 24, 2026 are excluded.
2. **Movie vs TV mix:** 5,013 movies (50.2%) and 4,979 TV shows (49.8%).
3. **International additions this quarter:** 103 of 161 additions, or 64.0%.
4. **Documentary comparison:** 9 of 161 additions this quarter (5.6%) versus 60 of 717 last quarter (8.4%). This is down 2.8 percentage points, or 33.2% relatively.
5. **Countries with no additions in the last 90 days:** None. All 14 represented countries had at least one addition from April 25 through July 23, 2026.

## Run locally

```powershell
cd path\to\streamvault_dashboard
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Trusted definitions

- **International:** Country is not `United States`.
- **Documentary:** Genre equals `Documentary`.
- **This quarter:** Calendar quarter through the selected report date.
- **Recent:** Trailing 90 calendar days.
- **Future records:** Excluded from metrics and shown as a data-quality warning.

## Dashboard sections

- Overview and executive snapshot
- Ask StreamVault with five trusted natural-language questions
- Monthly and quarterly trends
- Filterable catalog explorer with CSV download

The first version uses trusted SQL calculations rather than a generative AI model, which makes the core figures auditable. An OpenAI-powered question router can be added after these metrics are validated.
