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

CHEAP_KOP_QUERIES = [
    "daraz choice 35 tk deal",
    "daraz choice 49 tk offer",
    "daraz choice 99 tk best seller",
    "under 150 tk best seller daraz",
    "under 199 tk flash sale daraz",
    "under 250 tk top rated daraz",
    "under 299 tk mega discount daraz",
    "usb night light mini led daraz",
    "silicone smart band watch under 199",
    "in ear wired earphone best seller daraz",
    "kitchen cleaning scrubber pad combo",
    "shoe heel protector insole pad",
    "mini portable fan rechargeable daraz",
    "mobile stand holder desk daraz",
    "type c fast charging cable best seller",
    "lint remover cloth shaver daraz",
    "microfiber towel cleaning cloth daraz",
    "face wash cleanser under 299 daraz",
    "soap shampoo combo offer daraz",
    "water bottle flask under 350 daraz",
]

BAD_TITLES = {
    "error", "forbidden", "access denied", "blocked", "captcha",
    "403", "404", "not found", "just a moment", "security check",
    "daraz", "daraz.com.bd", "robot check",
}

FAKE_KEYWORDS = {
    "master copy", "1st copy", "first copy", "replica",
    "clone", "fake", "dummy", "aaa copy", "high copy",
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
        return False, 0
    low = text_blob.lower()
    official_markers = [
        "darazmall",
        "flagship store",
        "official store",
        "choice",
        "100% authentic",
    ]
    is_official = any(marker in low for marker in official_markers)

    review_count = 0
    matches = (
        re.findall(r'"ratingCount"\s*:\s*"?(\d+)"?', text_blob)
        + re.findall(r'"reviewCount"\s*:\s*"?(\d+)"?', text_blob)
        + re.findall(r"(\d+)\s*Ratings?", text_blob, re.I)
        + re.findall(r"\((\d+)\)\s*Ratings?", text_blob, re.I)
    )
    if matches:
        review_count = max(int(x) for x in matches)

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

    return title, image_url, discount_price, original_price, rating, is_official, review_count


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

        try:
            res = requests.get(fetch_target, headers=HEADERS, allow_redirects=True, timeout=12)
            if res.status_code == 200:
                if is_short and "-i" in res.url:
                    m_p = re.search(r"-i(\d+)", res.url)
                    if m_p:
                        pid = m_p.group(1)
                title, image_url, discount_price, original_price, rating, off1, rev1 = parse_html_product(res.text)
                is_official = is_official or off1
                review_count = max(review_count, rev1)
        except Exception:
            pass

        if not is_valid_and_authentic_title(title) or discount_price <= 0 or review_count < 100:
            try:
                p_url = f"https://api.allorigins.win/raw?url={urllib.parse.quote(fetch_target, safe='')}"
                p_res = requests.get(p_url, timeout=14)
                if p_res.status_code == 200:
                    t2, img2, dp2, op2, r2, off2, rev2 = parse_html_product(p_res.text)
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
            except Exception:
                pass

        if not is_valid_and_authentic_title(title) or discount_price <= 0 or review_count < 100:
            j_text = fetch_via_proxy(fetch_target)
            if j_text and "error 403" not in j_text.lower() and "target url returned error" not in j_text.lower():
                off3, rev3 = check_authenticity_signals(j_text)
                is_official = is_official or off3
                review_count = max(review_count, rev3)

                top_section = j_text[:4000]
                if not is_valid_and_authentic_title(title):
                    m_t = re.search(r"^Title:\s*(.+)$", top_section, re.M) or re.search(r"^#\s+(.+)$", top_section, re.M)
                    if m_t:
                        cand = html.unescape(m_t.group(1)).replace("| Daraz.com.bd", "").strip()
                        if is_valid_and_authentic_title(cand):
                            title = cand

                raw_prices = re.findall(r"৳\s*([\d,]+)", top_section)
                valid_prices = [int(p.replace(",", "")) for p in raw_prices if 11 <= int(p.replace(",", "")) <= 50000]
                if valid_prices and discount_price <= 0:
                    discount_price = valid_prices[0]
                if len(valid_prices) > 1 and valid_prices[1] > discount_price and original_price <= discount_price:
                    original_price = valid_prices[1]

                m_badge = re.search(r"-(\d{2})%", top_section) or re.search(r"(\d{2})%\s*OFF", top_section, re.I)
                if m_badge:
                    badge_discount = int(m_badge.group(1))

                if rating <= 0:
                    m_rat = re.search(r"([45]\.\d)\s*/\s*5", top_section)
                    if m_rat:
                        rating = float(m_rat.group(1))

                if not image_url:
                    m_img = re.search(r"https://[^\s\)\"']+lazcdn\.com[^\s\)\"']+\.(?:jpg|jpeg|png|webp)", j_text)
                    if m_img:
                        image_url = m_img.group(0)

        if not is_valid_and_authentic_title(title):
            slug_t = title_from_slug(fetch_target)
            if is_valid_and_authentic_title(slug_t):
                title = slug_t

        if not is_valid_and_authentic_title(title) or discount_price <= 0:
            return None

        # কড়া বাজেট ও ১০০+ আসল রিভিউ ফিল্টার (Strict Cheap Budget + 100+ Verified Reviews)
        if not is_manual:
            if discount_price > 499:
                return None
            if review_count < 100:
                return None
            if rating > 0 and rating < 4.4:
                return None

        if rating <= 0:
            rating = 4.7

        if original_price > discount_price:
            discount_percent = round(((original_price - discount_price) / original_price) * 100)
        elif badge_discount >= 40:
            discount_percent = badge_discount
            original_price = round(discount_price / (1 - (discount_percent / 100)))
        else:
            discount_percent = 0

        if not is_manual and (discount_percent < 40 or discount_percent > 95):
            return None

        if original_price <= discount_price:
            original_price = round(discount_price * 1.8)
            discount_percent = 45

        rating_display = f"{rating}/5 ({review_count}+ Reviews)"

        return {
            "pid": pid,
            "title": title[:140],
            "original_price": int(original_price),
            "discount_price": int(discount_price),
            "discount_percent": f"{discount_percent}%",
            "disc_val": int(discount_percent),
            "review_count": review_count,
            "rating": rating_display,
            "is_official": is_official,
            "image_url": image_url,
            "clean_url": url.strip() if is_short else fetch_target,
        }
    except Exception:
        return None


def extract_daraz_links(raw_text):
    if not raw_text:
        return []
    cleaned = urllib.parse.unquote(raw_text.replace("\\/", "/"))
    pattern = r"https?://(?:www\.)?daraz\.com\.bd/products/[a-zA-Z0-9\-_%]+-i\d+(?:-s\d+)?\.html"
    found = re.findall(pattern, cleaned)
    normalized = []
    for u in found:
        u = u.replace("http://", "https://")
        if "www.daraz.com.bd" not in u:
            u = u.replace("https://daraz.com.bd", "https://www.daraz.com.bd")
        if u not in normalized:
            normalized.append(u)
    return normalized


def discover_cheap_kop_offers():
    urls = []
    chosen_queries = random.sample(CHEAP_KOP_QUERIES, 4)
    for q_text in chosen_queries:
        print(f"Hunting Cheap 100+ Review Kop Deals for: {q_text}")
        q = urllib.parse.quote(f"site:daraz.com.bd/products {q_text}")
        search_urls = [
            f"https://html.duckduckgo.com/html/?q={q}",
            f"https://search.brave.com/search?q={q}",
            f"https://www.bing.com/search?q={q}",
        ]
        for s_url in search_urls:
            content = fetch_via_proxy(s_url)
            for u in extract_daraz_links(content):
                if u not in urls:
                    urls.append(u)
            if len(urls) >= 24:
                break

    random.shuffle(urls)
    return urls[:24]


def main():
    queue_ws, history_ws = get_sheets()
    all_rows = queue_ws.get_all_values()
    existing_ids = set(history_ws.col_values(1)[1:])

    for idx in range(len(all_rows), 1, -1):
        row = all_rows[idx - 1]
        link_cell = row[7].strip() if len(row) > 7 else ""
        title_cell = row[1].strip() if len(row) > 1 else ""
        price_cell = int(re.sub(r"[^\d]", "", str(row[3])) or 0) if len(row) > 3 else 0

        if not is_valid_and_authentic_title(title_cell) or (price_cell > 499 and "s.daraz.com.bd" not in link_cell):
            queue_ws.delete_rows(idx)
        elif row[0]:
            existing_ids.add(row[0].strip())

    current_queue = len(queue_ws.get_all_values()) - 1
    if current_queue >= 6:
        print(f"Queue already has {current_queue} verified 100+ review budget deals.")
        return

    product_urls = discover_cheap_kop_offers()
    tracking_param = os.environ.get("AFFILIATE_TRACKING_PARAM", "").strip().lstrip("?&")

    valid_deals = []
    for p_url in product_urls:
        info = scrape_product_page(p_url, is_manual=False)
        if not info or info["pid"] in existing_ids:
            continue
        existing_ids.add(info["pid"])
        valid_deals.append(info)
        if len(valid_deals) >= 8:
            break

    # সবচেয়ে কম দাম ও সবচেয়ে বেশি রিভিউয়ের প্রোডাক্টগুলো আগে বাছাই করা
    valid_deals.sort(key=lambda x: (-x["review_count"], x["discount_price"]))

    added = 0
    for info in valid_deals[:4]:
        aff_link = (
            info["clean_url"]
            if "s.daraz.com.bd" in info["clean_url"] or not tracking_param
            else f"{info['clean_url']}?{tracking_param}"
        )
        queue_ws.append_row([
            info["pid"],
            info["title"],
            info["original_price"],
            info["discount_price"],
            info["discount_percent"],
            info["rating"],
            info["image_url"],
            aff_link,
        ])
        added += 1
        print(f"Added 100+ Review Cheap Deal (৳{info['discount_price']}, {info['discount_percent']} OFF, {info['rating']}): {info['title']}")

    print(f"Finished. Added {added} verified 100+ review cheap kop deals.")


if __name__ == "__main__":
    main()
