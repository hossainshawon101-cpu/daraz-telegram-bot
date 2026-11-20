import os
import re
import json
import html
import random
import urllib.parse
import requests
import gspread
from google.oauth2.service_account import Credentials

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Accept-Language": "en-US,en;q=0.9",
}

A_TO_Z_DARAZ_OFFER_QUERIES = [
    # 1. Buy 1 Get 1, Mystery Box & Free Delivery Offers
    "buy 1 get 1 free offer daraz",
    "buy 1 get 1 combo deal daraz",
    "mystery box surprise offer daraz",
    "free delivery choice offer daraz",
    "free gift with purchase daraz",
    # 2. Daraz Choice & Super Lowest Kop Deals
    "daraz choice 11 tk 35 tk deal",
    "daraz choice 49 tk 99 tk offer",
    "daraz choice under 149 tk best seller",
    "flash sale under 199 tk daraz",
    "mega discount deal under 299 tk daraz",
    # 3. Useful Everyday Gadgets & Mobile Accessories
    "mini portable rechargeable fan daraz",
    "usb night light mini led lamp daraz",
    "silicone smart watch band under 199 daraz",
    "in ear wired earphone best seller daraz",
    "tws wireless earbuds under 499 daraz",
    "type c fast charging cable best seller daraz",
    "mobile phone stand holder desk daraz",
    "mini rechargeable led torch light daraz",
    "otg adapter usb c best seller daraz",
    "selfie stick tripod mini daraz",
    # 4. Useful Home & Kitchen Gadgets
    "kitchen cleaning scrubber pad combo daraz",
    "mini heat sealer machine plastic bag daraz",
    "lint remover fabric shaver daraz",
    "microfiber cleaning towel cloth combo daraz",
    "insulated water bottle flask under 399 daraz",
    "airtight food storage box combo daraz",
    "digital kitchen weighing scale daraz",
    "rechargeable emergency led bulb daraz",
    "wall mounted organizer rack holder daraz",
    # 5. Personal Care, Grooming & Fashion Essentials
    "shoe heel protector insole pad daraz",
    "men wallet card holder under 299 daraz",
    "face wash cleanser buy 1 get 1 daraz",
    "sunscreen lotion offer under 399 daraz",
    "body spray perfume combo under 399 daraz",
    "hair trimmer beard shaver under 499 daraz",
    "men cotton t shirt combo under 399 daraz",
    "women daily handbag pouch under 399 daraz",
    "portable folding umbrella daraz",
    # 6. Study, Office & Health Utility
    "digital thermometer best seller daraz",
    "notebook diary pen combo offer daraz",
    "laptop cooling pad stand under 499 daraz",
    "cable organizer clip holder daraz",
]

BAD_TITLES = {
    "error", "forbidden", "access denied", "blocked", "captcha",
    "403", "404", "not found", "just a moment", "security check",
    "daraz", "daraz.com.bd", "robot check",
}

FAKE_OR_JUNK_KEYWORDS = {
    "master copy", "1st copy", "first copy", "replica",
    "clone", "fake", "dummy", "aaa copy", "high copy",
    "empty jar", "empty bottle", "empty box", "old jar", "second hand", "used",
}


def is_valid_and_authentic_title(title):
    if not title:
        return False
    clean = title.strip().lower()
    if len(clean) < 6:
        return False
    if any(bad in clean for bad in BAD_TITLES):
        return False
    if any(junk in clean for junk in FAKE_OR_JUNK_KEYWORDS):
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
            timeout=14,
        )
        if r.status_code == 200 and len(r.text) > 300:
            return r.text
    except Exception:
        pass

    try:
        encoded = urllib.parse.quote(target_url, safe="")
        r2 = requests.get(f"https://api.allorigins.win/raw?url={encoded}", timeout=14)
        if r2.status_code == 200 and len(r2.text) > 300:
            return r2.text
    except Exception:
        pass

    return ""


def check_authenticity_signals(text_blob):
    if not text_blob:
        return False, 0, []
    low = text_blob.lower()
    official_markers = [
        "darazmall",
        "flagship store",
        "official store",
        "choice",
        "100% authentic",
    ]
    is_official = any(marker in low for marker in official_markers)

    tags = []
    if "buy 1 get 1" in low or "bogo" in low or "buy one get one" in low:
        tags.append("Buy 1 Get 1")
    if "mystery box" in low:
        tags.append("Mystery Box")
    if "free delivery" in low or "free shipping" in low or "choice" in low:
        tags.append("Free Delivery")

    review_count = 0
    matches = (
        re.findall(r'"ratingCount"\s*:\s*"?(\d+)"?', text_blob)
        + re.findall(r'"reviewCount"\s*:\s*"?(\d+)"?', text_blob)
        + re.findall(r"(\d+)\s*Ratings?", text_blob, re.I)
        + re.findall(r"\((\d+)\)\s*Ratings?", text_blob, re.I)
    )
    if matches:
        review_count = max(int(x) for x in matches)

    return is_official, review_count, tags


def parse_html_product(page):
    if not page:
        return "", "", 0, 0, 0.0, False, 0, []

    title = ""
    image_url = ""
    discount_price = 0
    original_price = 0
    rating = 0.0
    is_official, review_count, tags = check_authenticity_signals(page)

    ld_pattern = r'type=["\']application/ld\+json["\'][^>]*>(.*?)' + chr(60) + r"/script>"
    for ld_match in re.findall(ld_pattern, page, re.S):
        try:
            data = json.loads(ld_match.strip())
            if isinstance(data, list):
                data = data[0]
            if data.get("@type") == "Product":
                cand_title = html.unescape(str(data.get("name", ""))).strip()
                if is_valid_and_authentic_title(cand_title):
                    title = cand_title
                img = data.get("image", "")
                image_url = img[0] if isinstance(img, list) and img else str(img)
                offers = data.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0]
                discount_price = float(offers.get("price", 0) or 0)
                original_price = float(offers.get("highPrice", 0) or 0)
                agg = data.get("aggregateRating", {})
                if agg.get("ratingValue"):
                    rating = round(float(agg["ratingValue"]), 1)
                if agg.get("ratingCount") or agg.get("reviewCount"):
                    review_count = max(
                        review_count,
                        int(agg.get("ratingCount") or agg.get("reviewCount") or 0),
                    )
                break
        except Exception:
            continue

    if not is_valid_and_authentic_title(title):
        m_title = re.search(r'property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', page)
        if m_title:
            cand = html.unescape(m_title.group(1)).replace("| Daraz.com.bd", "").strip()
            if is_valid_and_authentic_title(cand):
                title = cand

    if not image_url:
        m_img = re.search(r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', page)
        if m_img:
            image_url = m_img.group(1).strip()

    if image_url.startswith("//"):
        image_url = "https:" + image_url

    if discount_price <= 0:
        m_price = (
            re.search(r'"salePrice"\s*:\s*\{[^}]*"value"\s*:\s*([\d.]+)', page)
            or re.search(r'"price"\s*:\s*([\d.]+)', page)
        )
        if m_price:
            discount_price = float(m_price.group(1))

    if original_price <= discount_price:
        m_orig = (
            re.search(r'"originalPrice"\s*:\s*\{[^}]*"value"\s*:\s*([\d.]+)', page)
            or re.search(r'"originalPrice"\s*:\s*([\d.]+)', page)
        )
        if m_orig:
            original_price = float(m_orig.group(1))

    return title, image_url, discount_price, original_price, rating, is_official, review_count, tags


def scrape_product_page(url, is_manual=False):
    try:
        is_short = "s.daraz.com.bd" in url
        fetch_target = url.strip() if is_short else url.split("?")[0]
        if fetch_target.startswith("//"):
            fetch_target = "https:" + fetch_target

        pid_match = re.search(r"-i(\d+)", fetch_target)
        pid = pid_match.group(1) if pid_match else str(abs(hash(fetch_target)))[:10]

        title = ""
        image_url = ""
        discount_price = 0
        original_price = 0
        badge_discount = 0
        rating = 0.0
        is_official = False
        review_count = 0
        all_tags = []

        try:
            res = requests.get(fetch_target, headers=HEADERS, allow_redirects=True, timeout=12)
            if res.status_code == 200:
                if is_short and "-i" in res.url:
                    m_p = re.search(r"-i(\d+)", res.url)
                    if m_p:
                        pid = m_p.group(1)
                title, image_url, discount_price, original_price, rating, off1, rev1, tgs1 = parse_html_product(res.text)
                is_official = is_official or off1
                review_count = max(review_count, rev1)
                all_tags.extend(tgs1)
        except Exception:
            pass

        if not is_valid_and_authentic_title(title) or discount_price <= 0 or review_count < 100:
            try:
                p_url = f"https://api.allorigins.win/raw?url={urllib.parse.quote(fetch_target, safe='')}"
                p_res = requests.get(p_url, timeout=14)
                if p_res.status_code == 200:
                    t2, img2, dp2, op2, r2, off2, rev2, tgs2 = parse_html_product(p_res.text)
                    if is_valid_and_authentic_title(t2):
                        title = t2
                    if img2 and not image_url:
                        image_url = img2
                    if dp2 > 0:
                        discount_price = dp2
                    if op2 > discount_price:
                        original_price = op2
                    if r2 > 0:
                        rating = r2
                    is_official = is_official or off2
                    review_count = max(review_count, rev2)
                    all_tags.extend(tgs2)
            except Exception:
                pass

        if not is_valid_and_authentic_title(title) or discount_price <= 0 or review_count < 100:
            j_text = fetch_via_proxy(fetch_target)
            if j_text and "error 403" not in j_text.lower() and "target url returned error" not in j_text.lower():
                off3, rev3, tgs3 = check_authenticity_signals(j_text)
                is_official = is_official or off3
                review_count = max(review_count, rev3)
                all_tags.extend(tgs3)

                top_section = j_text[:4000]
                if not is_valid_and_authentic_title(title):
                    m_t = re.search(r"^Title:\s*(.+)$", top_section, re.M) or re.search(r"^#\s+(.+)$", top_section, re.M)
                    if m_t:
                        cand = html.unescape(m_t.group(1)).replace("| Daraz.com.bd", "").strip()
                        if is_valid_and_authentic_title(cand):
                            title = cand

                raw_prices = re.findall(r"৳\s*([\d,]+)", top_section)
                valid_prices = [int(p.replace(",", "")) for p in raw_prices if 11 <= int(p.replace(",",
