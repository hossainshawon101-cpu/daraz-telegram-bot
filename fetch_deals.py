import os
import re
import json
import html
import gzip
import random
import urllib.parse
import requests
import gspread
from google.oauth2.service_account import Credentials

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Accept-Language": "en-US,en;q=0.9",
}

AUTHENTIC_DEAL_QUERIES = [
    "DarazMall flash sale",
    "Flagship Store best seller",
    "Official Store discount deal",
    "100% authentic smart watch",
    "DarazMall tws earbuds",
    "Official Store trimmer",
    "authentic perfume best seller",
    "DarazMall power bank",
    "Flagship Store backpack",
    "authentic women bag fancy",
    "DarazMall kitchen gadget",
    "Official Store men watch",
    "authentic skincare face wash",
    "DarazMall bluetooth speaker",
    "best seller aesthetic room lamp",
    "cheapest gadget under 299 best seller",
    "DarazMall sunglasses stylish",
    "Official Store electric kettle",
    "authentic leather wallet men",
    "DarazMall home organizer"
]

BAD_TITLES = {
    "error", "forbidden", "access denied", "blocked", "captcha",
    "403", "404", "not found", "just a moment", "security check",
    "daraz", "daraz.com.bd", "robot check"
}

FAKE_KEYWORDS = {
    "master copy", "1st copy", "first copy", "replica",
    "clone", "fake", "dummy", "aaa copy", "high copy"
}

def is_valid_and_authentic_title(title):
    if not title:
        return False
    clean = title.strip().lower()
    if len(clean) < 6:
        return False
    if any(bad in clean for bad in BAD_TITLES):
        return False
    if any(fake in clean for fake in FAKE_KEYWORDS):
        return False
    return True

def title_from_slug(url):
    m = re.search(r"/products/([a-zA-Z0-9\-]+)-i\d+", url)
    if not m:
        return ""
    words = m.group(1).replace("-", " ").strip()
    return " ".join(w.capitalize() for w in words.split())[:140]

def get_sheets():
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    raw_sheet = os.environ.get("SHEET_ID", "").strip()
    m = re.search(r"/d/([a-zA-Z0-9-_]+)", raw_sheet)
    sheet_id = m.group(1) if m else raw_sheet
    try:
        sheet = client.open_by_key(sheet_id)
    except Exception:
        sheet = client.open("Daraz_Affiliate_Automation")
    return sheet.worksheet("Queue"), sheet.worksheet("Posted_History")

def fetch_via_proxy(target_url):
    try:
        r = requests.get(
            f"https://r.jina.ai/{target_url}",
            headers={"Accept": "text/plain"},
            timeout=25,
        )
        if r.status_code == 200 and len(r.text) > 300:
            return r.text
    except Exception:
        pass

    try:
        encoded = urllib.parse.quote(target_url, safe="")
        r2 = requests.get(f"https://api.allorigins.win/raw?url={encoded}", timeout=25)
        if r2.status_code == 200 and len(r2.text) > 300:
            return r2.text
    except Exception:
        pass

    return ""

def check_authenticity_signals(text_blob):
    if not text_blob:
        return False, 0
    low = text_blob.lower()
    official_markers = [
        "darazmall",
        "flagship store",
        "official store",
        "100% authentic",
        "authenticity guaranteed",
    ]
    is_official = any(marker in low for marker in official_markers)

    review_count = 0
    m_rev = (
        re.search(r'"ratingCount"\s*:\s*"?(\d+)"?', text_blob)
        or re.search(r'"reviewCount"\s*:\s*"?(\d+)"?', text_blob)
        or re.search(r"(\d+)\s*Ratings?", text_blob, re.I)
    )
    if m_rev:
        review_count = int(m_rev.group(1))

    return is_official, review_count

def parse_html_product(page):
    if not page:
        return "", "", 0, 0, 0.0, False, 0

    title = ""
    image_url = ""
    discount_price = 0
    original_price = 0
    rating = 0.0
    is_official, review_count = check_authenticity_signals(page)

    for ld_match in re.findall(r'<script[^>
