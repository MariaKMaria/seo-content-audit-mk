import streamlit as st
import anthropic
import requests
import pandas as pd
import json
import re
import time
import io
from bs4 import BeautifulSoup
from datetime import datetime

st.set_page_config(
    page_title="SEO + GEO Auditor",
    page_icon="🔍",
    layout="wide"
)

# ── Styles ─────────────────────────────────────────────────────
st.markdown("""
<style>
.block-container { padding-top: 2rem; }
.stProgress > div > div { background-color: #4CAF50; }
.metric-card {
    background: #f8f9fa;
    border-radius: 8px;
    padding: 1rem;
    text-align: center;
    border: 1px solid #e0e0e0;
}
.score-high { color: #2e7d32; font-weight: bold; }
.score-mid  { color: #f57c00; font-weight: bold; }
.score-low  { color: #c62828; font-weight: bold; }
.action-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

# ── Constants ──────────────────────────────────────────────────
MODEL = "claude-haiku-4-5-20251001"
MAX_HTML_CHARS = 70000
DELAY = 2

ACTION_COLORS = {
    "Retire":    "#ffcdd2",
    "Redirect":  "#ffe0b2",
    "Refresh":   "#fff9c4",
    "Repurpose": "#bbdefb",
    "Remain":    "#c8e6c9",
}

OPPORTUNITY_LABELS = {
    "no_traffic":              "No traffic",
    "high_impression_low_ctr": "High impr. / Low CTR",
    "ranking_opportunity":     "Ranking opportunity",
    "performing_well":         "Performing well",
    "new_page":                "New page",
}

AUDIT_PROMPT = """You are an expert SEO and GEO (Generative Engine Optimization) auditor.

Note: HTML was fetched statically. Schema markup injected by JavaScript may not appear — do not penalise heavily for missing schema if the site appears JS-rendered.

GSC PERFORMANCE DATA:
- Clicks (last 12 months): {clicks}
- Impressions (last 12 months): {impressions}
- CTR: {ctr}
- Average position: {position}

Analyze the HTML and return a JSON object with this exact structure:

{{
  "url": "<the page URL>",
  "scores": {{
    "technical_seo": <0-100>,
    "content_quality": <0-100>,
    "on_page_seo": <0-100>,
    "schema": <0-100>,
    "geo_ai_readiness": <0-100>,
    "eeat": <0-100>,
    "images": <0-100>,
    "overall": <0-100>
  }},
  "gsc_insights": {{
    "opportunity_type": "<one of: high_impression_low_ctr | ranking_opportunity | no_traffic | performing_well | new_page>",
    "opportunity_summary": "<1-2 sentence plain English summary>"
  }},
  "priorities": {{
    "critical": ["<issue 1>", "<issue 2>"],
    "high": ["<issue 1>", "<issue 2>"],
    "medium": ["<issue 1>", "<issue 2>"]
  }},
  "findings": {{
    "technical_seo": "<2-3 sentence summary>",
    "on_page_seo": "<2-3 sentence summary>",
    "schema": "<2-3 sentence summary>",
    "geo_ai_readiness": "<2-3 sentence summary>",
    "eeat": "<2-3 sentence summary>",
    "images": "<1-2 sentence summary>"
  }},
  "quick_wins": ["<fix 1>", "<fix 2>", "<fix 3>"]
}}

Scoring weights: technical 22%, content 23%, on-page 20%, schema 10%, geo 10%, eeat 10%, images 5%

Return ONLY the JSON — no markdown fences, no explanation.

URL: {url}

HTML:
{html}
"""

# ── Helpers ────────────────────────────────────────────────────

def fetch_html(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup.find_all("script"):
        if tag.get("type") != "application/ld+json":
            tag.decompose()
    for tag in soup(["style", "noscript", "svg"]):
        tag.decompose()
    html = str(soup)
    return html[:MAX_HTML_CHARS] + "\n<!-- [truncated] -->" if len(html) > MAX_HTML_CHARS else html

def audit_page(client, url, html, gsc):
    prompt = AUDIT_PROMPT.format(
        url=url, html=html,
        clicks=gsc.get("clicks", "N/A"),
        impressions=gsc.get("impressions", "N/A"),
        ctr=gsc.get("ctr", "N/A"),
        position=gsc.get("position", "N/A"),
    )
    msg = client.messages.create(
        model=MODEL, max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = msg.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        raw = match.group(0)
    return json.loads(raw)

def get_action(result):
    opp = (result.get("gsc_insights") or {}).get("opportunity_type", "")
    overall = int((result.get("scores") or {}).get("overall", 50) or 50)
    content = int((result.get("scores") or {}).get("content_quality", 50) or 50)
    if opp == "no_traffic":              return "Retire" if overall < 30 else "Redirect"
    if opp == "high_impression_low_ctr": return "Refresh"
    if opp == "ranking_opportunity":     return "Repurpose" if content < 60 else "Remain"
    if opp == "performing_well":         return "Remain"
    return "Remain"

def score_badge(val):
    try:
        v = int(val)
        cls = "score-high" if v >= 70 else "score-mid" if v >= 50 else "score-low"
        return f'<span class="{cls}">{v}</span>'
    except:
        return str(val)

def load_gsc(file) -> dict:
    if file is None:
        return {}
    try:
        if file.name.endswith(".xlsx"):
            df = pd.read_excel(file)
        else:
            df = pd.read_csv(file)
        df.columns = [c.strip().lower() for c in df.columns]
        url_col = next((c for c in df.columns if any(x in c for x in ["url","page","landing"])), None)
        click_col = next((c for c in df.columns if "click" in c), None)
        imp_col = next((c for c in df.columns if "impression" in c), None)
        ctr_col = next((c for c in df.columns if "ctr" in c or "rate" in c), None)
        pos_col = next((c for c in df.columns if "position" in c or "rank" in c), None)
        gsc = {}
        for _, row in df.iterrows():
            url = str(row[url_col]).strip().rstrip("/") if url_col else ""
            if not url.startswith("http"):
                continue
            gsc[url] = {
                "clicks":      str(row[click_col]) if click_col else "N/A",
                "impressions": str(row[imp_col])   if imp_col   else "N/A",
                "ctr":         str(row[ctr_col])   if ctr_col   else "N/A",
                "position":    str(row[pos_col])   if pos_col   else "N/A",
            }
        return gsc
    except Exception as e:
        st.warning(f"Could not parse GSC file: {e}")
        return {}

def get_gsc_metrics(gsc, url):
    clean = url.rstrip("/")
    return gsc.get(clean) or gsc.get(clean + "/") or {
        "clicks": "N/A", "impressions": "N/A", "ctr": "N/A", "position": "N/A"
    }

def results_to_df(results):
    rows = []
    for r, gsc in results:
        s = r.get("scores", {})
        p = r.get("priorities", {})
        g = r.get("gsc_insights", {})
        rows.append({
            "URL": r.get("url", ""),
            "Clicks": gsc.get("clicks", "N/A"),
            "Impressions": gsc.get("impressions", "N/A"),
            "CTR": gsc.get("ctr", "N/A"),
            "Position": gsc.get("position", "N/A"),
            "Action (6Rs)": get_action(r),
            "Opportunity Type": OPPORTUNITY_LABELS.get(g.get("opportunity_type", ""), g.get("opportunity_type", "")),
            "Opportunity Summary": g.get("opportunity_summary", ""),
            "Overall": s.get("overall", ""),
            "Technical SEO": s.get("technical_seo", ""),
            "Content Quality": s.get("content_quality", ""),
            "On-Page SEO": s.get("on_page_seo", ""),
            "Schema": s.get("schema", ""),
            "GEO / AI Readiness": s.get("geo_ai_readiness", ""),
            "E-E-A-T": s.get("eeat", ""),
            "Images": s.get("images", ""),
            "Critical Issues": " | ".join(p.get("critical", [])),
            "High Issues": " | ".join(p.get("high", [])),
            "Quick Wins": " | ".join(r.get("quick_wins", [])),
        })
    return pd.DataFrame(rows)

# ── UI ─────────────────────────────────────────────────────────

st.title("🔍 SEO + GEO Bulk Auditor")
st.caption("Powered by Claude Haiku · Includes GSC performance data · 6Rs action framework")

# Sidebar config
with st.sidebar:
    st.header("⚙️ Settings")
    api_key = st.text_input("Anthropic API key", type="password", placeholder="sk-ant-...")
    st.divider()
    st.header("📂 GSC Data")
    gsc_file = st.file_uploader("Upload GSC export (CSV or XLSX)", type=["csv", "xlsx"])
    if gsc_file:
        gsc_data = load_gsc(gsc_file)
        st.success(f"✓ {len(gsc_data)} URLs loaded from GSC")
    else:
        gsc_data = {}
        st.info("No GSC file — scores will be based on HTML only")
    st.divider()
    st.caption("💡 Tip: export from GSC → Performance → Pages → Export")

# Main area
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("URLs to audit")
    url_input = st.text_area(
        "One URL per line",
        height=200,
        placeholder="https://example.com/page-1\nhttps://example.com/page-2"
    )

with col2:
    st.subheader("About this tool")
    st.markdown("""
- Fetches & analyzes each page
- Combines GSC performance data
- Scores 7 SEO/GEO categories
- Assigns 6Rs action per page
- Export to CSV or Google Sheets
    """)

urls = [u.strip() for u in url_input.strip().splitlines() if u.strip().startswith("http")]

if urls:
    st.info(f"**{len(urls)} URL{'s' if len(urls) > 1 else ''}** ready to audit")

run = st.button("▶ Run Audit", type="primary", disabled=not (api_key and urls))

if not api_key:
    st.warning("Add your Anthropic API key in the sidebar to get started.")

# ── Run audit ──────────────────────────────────────────────────
if run and api_key and urls:
    client = anthropic.Anthropic(api_key=api_key)
    results = []
    errors = []

    st.divider()
    st.subheader(f"Auditing {len(urls)} URL{'s' if len(urls) > 1 else ''}...")
    progress = st.progress(0)
    status = st.empty()
    results_container = st.container()

    for i, url in enumerate(urls):
        status.markdown(f"**[{i+1}/{len(urls)}]** Auditing `{url}`...")
        gsc = get_gsc_metrics(gsc_data, url)

        try:
            html = fetch_html(url)
            result = audit_page(client, url, html, gsc)
            result["url"] = url
            results.append((result, gsc))

            # Show live result card
            s = result.get("scores", {})
            action = get_action(result)
            opp = OPPORTUNITY_LABELS.get(
                (result.get("gsc_insights") or {}).get("opportunity_type", ""), ""
            )
            with results_container:
                with st.expander(f"{'✓'} {url} — Overall: {s.get('overall', '?')}/100", expanded=False):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Overall", s.get("overall", "?"))
                    c2.metric("Action", action)
                    c3.metric("Opportunity", opp)
                    c4.metric("Clicks", gsc.get("clicks", "N/A"))

                    cc1, cc2, cc3, cc4 = st.columns(4)
                    cc1.metric("Technical SEO", s.get("technical_seo", "?"))
                    cc2.metric("Content", s.get("content_quality", "?"))
                    cc3.metric("On-Page", s.get("on_page_seo", "?"))
                    cc4.metric("Schema", s.get("schema", "?"))

                    ccc1, ccc2, ccc3, ccc4 = st.columns(4)
                    ccc1.metric("GEO / AI", s.get("geo_ai_readiness", "?"))
                    ccc2.metric("E-E-A-T", s.get("eeat", "?"))
                    ccc3.metric("Images", s.get("images", "?"))
                    ccc4.metric("Impressions", gsc.get("impressions", "N/A"))

                    priorities = result.get("priorities", {})
                    if priorities.get("critical"):
                        st.error("🚨 Critical: " + " · ".join(priorities["critical"]))
                    if priorities.get("high"):
                        st.warning("⚠️ High: " + " · ".join(priorities["high"]))

                    quick_wins = result.get("quick_wins", [])
                    if quick_wins:
                        st.success("⚡ Quick wins: " + " · ".join(quick_wins))

        except Exception as e:
            errors.append((url, str(e)))
            with results_container:
                st.error(f"✗ {url}: {e}")

        progress.progress((i + 1) / len(urls))
        if i < len(urls) - 1:
            time.sleep(DELAY)

    status.markdown(f"✅ **Done!** {len(results)} audited, {len(errors)} failed.")

    # ── Export ─────────────────────────────────────────────────
    if results:
        st.divider()
        st.subheader("📊 Export results")

        df = results_to_df(results)

        # CSV download
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        st.download_button(
            label="⬇ Download CSV",
            data=csv_buffer.getvalue(),
            file_name=f"seo_audit_{datetime.now().strftime('%Y-%m-%d')}.csv",
            mime="text/csv"
        )

        st.caption("💡 To get it into Google Sheets: download the CSV → open Sheets → File → Import")

        # Full results table
        st.divider()
        st.subheader("📋 Full results table")
        st.dataframe(df, use_container_width=True, height=400)
