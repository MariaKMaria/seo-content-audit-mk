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

st.markdown("""
<style>
.block-container { padding-top: 2rem; }
.stProgress > div > div { background-color: #4CAF50; }
</style>
""", unsafe_allow_html=True)

MODEL = "claude-haiku-4-5-20251001"
MAX_HTML_CHARS = 70000
DELAY = 2

ACTION_COLORS = {
    "Reformat":  "#e1bee7",
    "Repurpose": "#bbdefb",
    "Refresh":   "#fff9c4",
    "Redirect":  "#ffe0b2",
    "Retire":    "#ffcdd2",
    "Remain":    "#c8e6c9",
}

ACTION_COLORS_RGB = {
    "Reformat":  {"red": 0.88, "green": 0.75, "blue": 0.91},
    "Repurpose": {"red": 0.68, "green": 0.85, "blue": 1.0},
    "Refresh":   {"red": 1.0,  "green": 0.95, "blue": 0.70},
    "Redirect":  {"red": 1.0,  "green": 0.90, "blue": 0.70},
    "Retire":    {"red": 0.96, "green": 0.80, "blue": 0.80},
    "Remain":    {"red": 0.83, "green": 0.94, "blue": 0.84},
}

OPPORTUNITY_COLORS_RGB = {
    "No traffic":           {"red": 0.96, "green": 0.80, "blue": 0.80},
    "High impr. / Low CTR": {"red": 1.0,  "green": 0.88, "blue": 0.60},
    "Ranking opportunity":  {"red": 0.68, "green": 0.85, "blue": 1.0},
    "Performing well":      {"red": 0.83, "green": 0.94, "blue": 0.84},
    "New page":             {"red": 0.93, "green": 0.93, "blue": 0.93},
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

When classifying opportunity_type, use these definitions:
- high_impression_low_ctr: page has significant impressions but low CTR — title/meta issue
- ranking_opportunity: page ranks position 5-20 with decent impressions — content/on-page can be improved
- no_traffic: page has zero or near-zero clicks and impressions
- performing_well: page is ranking and driving clicks effectively
- new_page: insufficient data to classify

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
    opp     = (result.get("gsc_insights") or {}).get("opportunity_type", "")
    overall = int((result.get("scores") or {}).get("overall", 50) or 50)
    content = int((result.get("scores") or {}).get("content_quality", 50) or 50)
    on_page = int((result.get("scores") or {}).get("on_page_seo", 50) or 50)
    if opp == "no_traffic":
        return "Retire" if overall < 30 else "Redirect"
    if opp == "high_impression_low_ctr":
        return "Refresh"
    if opp == "ranking_opportunity":
        if content < 60:  return "Repurpose"
        if on_page < 60:  return "Reformat"
        return "Remain"
    if opp in ("performing_well", "new_page"):
        if on_page < 60 and content >= 60: return "Reformat"
        return "Remain"
    if on_page < 60 and content >= 60: return "Reformat"
    if content < 60: return "Refresh"
    return "Remain"

def load_gsc(file):
    if file is None:
        return {}
    try:
        if file.name.endswith(".xlsx"):
            df = pd.read_excel(file)
        else:
            df = pd.read_csv(file)
        df.columns = [c.strip().lower() for c in df.columns]
        url_col   = next((c for c in df.columns if any(x in c for x in ["url","page","landing"])), None)
        click_col = next((c for c in df.columns if "click" in c), None)
        imp_col   = next((c for c in df.columns if "impression" in c), None)
        ctr_col   = next((c for c in df.columns if "ctr" in c or "rate" in c), None)
        pos_col   = next((c for c in df.columns if "position" in c or "rank" in c), None)
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

def score_color_rgb(val):
    try:
        v = int(val)
        if v >= 70: return {"red": 0.83, "green": 0.94, "blue": 0.84}
        if v >= 50: return {"red": 1.00, "green": 0.95, "blue": 0.80}
        return {"red": 0.96, "green": 0.80, "blue": 0.80}
    except:
        return {"red": 1.0, "green": 1.0, "blue": 1.0}

def push_to_sheets(df, sheets_token):
    """Push dataframe to a new formatted Google Sheet using OAuth token."""
    headers = {
        "Authorization": f"Bearer {sheets_token}",
        "Content-Type": "application/json"
    }

    # 1. Create spreadsheet
    title = f"SEO GEO Audit {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    resp = requests.post(
        "https://sheets.googleapis.com/v4/spreadsheets",
        headers=headers,
        json={"properties": {"title": title}}
    )
    resp.raise_for_status()
    ss = resp.json()
    ss_id   = ss["spreadsheetId"]
    sheet_id = ss["sheets"][0]["properties"]["sheetId"]
    url_out = f"https://docs.google.com/spreadsheets/d/{ss_id}"

    # 2. Write all data
    values = [df.columns.tolist()] + df.values.tolist()
    requests.put(
        f"https://sheets.googleapis.com/v4/spreadsheets/{ss_id}/values/A1",
        headers=headers,
        params={"valueInputOption": "RAW"},
        json={"values": [[str(c) for c in row] for row in values]}
    )

    # 3. Write URLs as hyperlinks
    url_formulas = [[f'=HYPERLINK("{row}","{row}")'] for row in df["URL"].tolist()]
    requests.put(
        f"https://sheets.googleapis.com/v4/spreadsheets/{ss_id}/values/A2",
        headers=headers,
        params={"valueInputOption": "USER_ENTERED"},
        json={"values": url_formulas}
    )

    num_rows = len(df) + 1
    num_cols = len(df.columns)
    SCORE_COLS = [8, 9, 10, 11, 12, 13, 14, 15]  # Overall → Images (0-indexed)

    batch = []

    # Dark header
    batch.append({"repeatCell": {
        "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                  "startColumnIndex": 0, "endColumnIndex": num_cols},
        "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 0.15, "green": 0.15, "blue": 0.15},
            "textFormat": {"bold": True, "fontSize": 10,
                           "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            "verticalAlignment": "MIDDLE",
            "padding": {"top": 8, "bottom": 8, "left": 8, "right": 8}
        }},
        "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment,padding)"
    }})

    # Freeze header + URL col
    batch.append({"updateSheetProperties": {
        "properties": {"sheetId": sheet_id,
                       "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 1}},
        "fields": "gridProperties(frozenRowCount,frozenColumnCount)"
    }})

    # Row height
    batch.append({"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "ROWS",
                  "startIndex": 0, "endIndex": num_rows},
        "properties": {"pixelSize": 40},
        "fields": "pixelSize"
    }})

    # Alternating rows + score colors + action/opp colors
    for row_idx, (_, row) in enumerate(df.iterrows(), start=1):
        bg = {"red": 1.0, "green": 1.0, "blue": 1.0} if row_idx % 2 == 1 else {"red": 0.97, "green": 0.97, "blue": 0.97}
        batch.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": row_idx,
                      "endRowIndex": row_idx + 1, "startColumnIndex": 0, "endColumnIndex": num_cols},
            "cell": {"userEnteredFormat": {
                "backgroundColor": bg,
                "textFormat": {"fontSize": 10},
                "verticalAlignment": "MIDDLE",
                "padding": {"top": 6, "bottom": 6, "left": 8, "right": 8}
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment,padding)"
        }})

        # Score cells
        row_vals = row.tolist()
        for col_idx in SCORE_COLS:
            if col_idx < len(row_vals):
                batch.append({"repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": row_idx,
                              "endRowIndex": row_idx + 1,
                              "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": score_color_rgb(row_vals[col_idx]),
                        "horizontalAlignment": "CENTER",
                        "textFormat": {"bold": True, "fontSize": 10}
                    }},
                    "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"
                }})

        # Action (6Rs) col = 5
        action = str(row_vals[5]) if len(row_vals) > 5 else ""
        batch.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": row_idx,
                      "endRowIndex": row_idx + 1, "startColumnIndex": 5, "endColumnIndex": 6},
            "cell": {"userEnteredFormat": {
                "backgroundColor": ACTION_COLORS_RGB.get(action, bg),
                "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True, "fontSize": 10}
            }},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"
        }})

        # Opportunity Type col = 6
        opp = str(row_vals[6]) if len(row_vals) > 6 else ""
        batch.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": row_idx,
                      "endRowIndex": row_idx + 1, "startColumnIndex": 6, "endColumnIndex": 7},
            "cell": {"userEnteredFormat": {
                "backgroundColor": OPPORTUNITY_COLORS_RGB.get(opp, bg),
                "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True, "fontSize": 10}
            }},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"
        }})

    # Column widths
    col_widths = {0:280,1:70,2:110,3:65,4:75,5:120,6:170,7:300,
                  8:75,9:100,10:100,11:95,12:75,13:110,14:70,15:75,
                  16:300,17:300,18:300}
    for col_idx, width in col_widths.items():
        if col_idx < num_cols:
            batch.append({"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                          "startIndex": col_idx, "endIndex": col_idx + 1},
                "properties": {"pixelSize": width},
                "fields": "pixelSize"
            }})

    # Wrap text columns
    for col_idx in [7, 16, 17, 18]:
        if col_idx < num_cols:
            batch.append({"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1,
                          "endRowIndex": num_rows, "startColumnIndex": col_idx,
                          "endColumnIndex": col_idx + 1},
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                "fields": "userEnteredFormat.wrapStrategy"
            }})

    # Apply all formatting
    requests.post(
        f"https://sheets.googleapis.com/v4/spreadsheets/{ss_id}:batchUpdate",
        headers=headers,
        json={"requests": batch}
    )

    return url_out

# ── UI ─────────────────────────────────────────────────────────

st.title("🔍 SEO + GEO Bulk Auditor")
st.caption("Powered by Claude Haiku · GSC performance data · 6Rs action framework")

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
        st.info("No GSC file — HTML analysis only")
    st.divider()
    st.header("📊 Google Sheets")
    sheets_token = st.text_input(
        "Google OAuth token",
        type="password",
        placeholder="ya29.a...",
        help="Get this from developers.google.com/oauthplayground — authorize the Sheets + Drive APIs"
    )
    if sheets_token:
        st.success("✓ Token ready")
    else:
        with st.expander("How to get a token"):
            st.markdown("""
1. Go to [OAuth Playground](https://developers.google.com/oauthplayground)
2. In Step 1, select:
   - `Google Sheets API v4` → `https://www.googleapis.com/auth/spreadsheets`
   - `Drive API v3` → `https://www.googleapis.com/auth/drive.file`
3. Click **Authorize APIs**
4. Click **Exchange authorization code for tokens**
5. Copy the **Access token** and paste it above

⚠️ Tokens expire after 1 hour — get a fresh one each session.
            """)
    st.divider()
    st.caption("💡 GSC: Performance → Pages → Export")

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

if run and api_key and urls:
    client = anthropic.Anthropic(api_key=api_key)
    results = []
    errors  = []

    st.divider()
    st.subheader(f"Auditing {len(urls)} URL{'s' if len(urls) > 1 else ''}...")
    progress  = st.progress(0)
    status    = st.empty()
    results_container = st.container()

    for i, url in enumerate(urls):
        status.markdown(f"**[{i+1}/{len(urls)}]** Auditing `{url}`...")
        gsc = get_gsc_metrics(gsc_data, url)

        try:
            html   = fetch_html(url)
            result = audit_page(client, url, html, gsc)
            result["url"] = url
            results.append((result, gsc))

            s      = result.get("scores", {})
            action = get_action(result)
            opp    = OPPORTUNITY_LABELS.get((result.get("gsc_insights") or {}).get("opportunity_type", ""), "")

            with results_container:
                with st.expander(f"✓ {url} — Overall: {s.get('overall', '?')}/100", expanded=False):
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
                    if result.get("quick_wins"):
                        st.success("⚡ Quick wins: " + " · ".join(result["quick_wins"]))

        except Exception as e:
            errors.append((url, str(e)))
            with results_container:
                st.error(f"✗ {url}: {e}")

        progress.progress((i + 1) / len(urls))
        if i < len(urls) - 1:
            time.sleep(DELAY)

    status.markdown(f"✅ **Done!** {len(results)} audited, {len(errors)} failed.")

    if results:
        st.divider()
        st.subheader("📊 Export results")

        df = results_to_df(results)

        col_a, col_b = st.columns(2)

        # CSV download
        with col_a:
            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)
            st.download_button(
                label="⬇ Download CSV",
                data=csv_buffer.getvalue(),
                file_name=f"seo_audit_{datetime.now().strftime('%Y-%m-%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )

        # Google Sheets push
        with col_b:
            if sheets_token:
                if st.button("📊 Push to Google Sheets", type="primary", use_container_width=True):
                    with st.spinner("Creating formatted Google Sheet..."):
                        try:
                            sheet_url = push_to_sheets(df, sheets_token)
                            st.success("✓ Sheet created!")
                            st.markdown(f"**[Open in Google Sheets]({sheet_url})**")
                        except Exception as e:
                            st.error(f"Failed to create sheet: {e}")
                            st.caption("Your OAuth token may have expired — get a fresh one from the sidebar.")
            else:
                st.info("Add a Google OAuth token in the sidebar to push directly to Sheets.")

        st.divider()
        st.subheader("📋 Full results table")
        st.dataframe(df, use_container_width=True, height=400)
