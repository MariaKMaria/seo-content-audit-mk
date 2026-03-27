# SEO + GEO Bulk Auditor

A Streamlit web app for bulk SEO and GEO auditing powered by Claude Haiku.

## Features
- Paste URLs and run audits with one click
- Upload GSC export for performance-informed recommendations
- Scores 7 categories: Technical SEO, Content Quality, On-Page SEO, Schema, GEO/AI Readiness, E-E-A-T, Images
- Assigns 6Rs action per page (Retire, Redirect, Refresh, Repurpose, Remain)
- Export results as CSV

## Deploy to Streamlit Community Cloud

1. Fork or upload this repo to GitHub
2. Go to share.streamlit.io
3. Click "New app"
4. Select your GitHub repo
5. Set main file path to: `app.py`
6. Click Deploy

## Local development

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Usage

1. Add your Anthropic API key in the sidebar
2. Upload your GSC export (CSV or XLSX) — optional but recommended
3. Paste URLs (one per line)
4. Click Run Audit
5. Download results as CSV
