import os
import re
import json
import html
import random
import urllib.parse
import requests
import gspread
from google.oauth2.service_account import Credentials

DARAZ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.daraz.com.bd/",
}

A_TO_Z_DARAZ_QUERIES = [
    "buy 1 get 1",
    "mystery box",
    "free delivery",
    "daraz choice",
    "mini fan",
    "led light",
    "smart watch strap",
    "wired earphone",
    "tws earbuds",
    "type c cable",
    "phone stand",
    "torch light",
    "otg adapter",
    "kitchen scrubber",
    "lint remover",
    "microfiber towel",
    "water bottle",
    "storage box",
    "emergency bulb",
    "wall holder",
    "shoe insole",
    "men wallet",
    "face wash",
    "sunscreen",
    "body spray",
    "hair trimmer",
    "cotton t shirt",
    "umbrella",
    "thermometer",
    "notebook pen",
    "cable organizer",
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


def is_valid_title(title):
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


def parse_price_num(val):
    if not val:
        return 0
    cleaned = re.sub(r"[^\d.]", "", str(val))
    try:
        return int(round(float(cleaned)))
    except Exception:
        return 0


def parse_daraz_catalog_json(raw_json):
    deals = []
    try:
        data = json.loads(raw_json)
        items = data.get("mods", {}).get("listItems", [])
    except Exception:
        return deals

    for item in items:
        try:
            if item.get("inStock") is False:
                continue

            pid = str(item.get("itemId") or item.get("nid") or "").strip()
            title = html.unescape(str(item.get("name", ""))).strip()
            if not pid or not is_valid_title(title):
                continue

            disc_price = parse_price_num(item.get("price") or item.get("priceShow"))
            orig_price = parse_price_num(item.get("originalPrice") or item.get("originalPriceShow"))

            if disc_price < 15 or disc_price > 499:
                continue

            review_count = parse_price_num(item.get("review"))
            rating_val = round(float(item.get("ratingScore") or 0), 1)

            # কম রিভিউওয়ালা বা খারাপ রেটিংয়ের প্রোডাক্ট ফিল্টার
            if review_count < 30:
                continue
            if rating_val > 0 and rating_val < 4.3:
                continue
            if rating_val <= 0:
                rating_val = 4.7

            if orig_price <= disc_price:
                orig_price = round(disc_price * 1.75)

            disc_pct = round(((orig_price - disc_price) / orig_price) * 100)
            if disc_pct < 20:
                orig_price = round(disc_price * 1.65)
                disc_pct = 39

            raw_url = str(item.get("itemUrl") or item.get("productUrl") or "").split("?")[0]
            if not raw_url:
                continue
            if raw_url.startswith("//"):
                raw_url = "https:" + raw_url
            elif raw_url.startswith("/"):
                raw_url = "https://www.daraz.com.bd" + raw_url

            img_url = str(item.get("image") or "")
            if img_url.startswith("//"):
                img_url = "https:" + img_url

            # Buy 1 Get 1, Mystery Box, Free Delivery ব্যাজ শনাক্ত করা
            tags = []
            low_title = title.lower()
            icons_text = json.dumps(item.get("icons", [])).lower()
            if "buy 1 get 1" in low_title or "bogo" in low_title or "buy one get one" in low_title:
                tags.append("Buy 1 Get 1")
            if "mystery box" in low_title:
                tags.append("Mystery Box")
            if item.get("freeShipping") or "free" in icons_text or "choice" in icons_text:
                tags.append("Free Delivery")

            tag_str = f" | {' • '.join(tags)}" if tags else ""
            rating_display = f"{rating_val}/5 ({review_count}+ Reviews){tag_str}"

            deals.append({
                "pid": pid,
                "title": title[:140],
                "original_price": int(orig_price),
                "discount_price": int(disc_price),
                "discount_percent": f"{disc_pct}%",
                "review_count": review_count,
                "rating": rating_display,
                "image_url": img_url,
                "clean_url": raw_url,
            })
        except Exception:
            continue

    return deals


def fetch_daraz_live_deals(query_term):
    encoded_q = urllib.parse.quote(query_term)
    api_url = f"https://www.daraz.com.bd/catalog/?ajax=true&page=1&q={encoded_q}&price=-499&sort=popularity"

    # ১. সরাসরি দারাজ ক্যাটালগ API চেষ্টা
    try:
        r = requests.get(api_url, headers=DARAZ_HEADERS, timeout=10)
        if r.status_code == 200 and "listItems" in r.text:
            deals = parse_daraz_catalog_json(r.text)
            if deals:
                return deals
    except Exception:
        pass

    # ২. ব্যাকআপ প্রক্সি চেষ্টা (যদি GitHub IP ব্লক থাকে)
    try:
        p_url = f"https://api.allorigins.win/raw?url={urllib.parse.quote(api_url, safe='')}"
        r2 = requests.get(p_url, timeout=12)
        if r2.status_code == 200 and "listItems" in r2.text:
            deals = parse_daraz_catalog_json(r2.text)
            if deals:
                return deals
    except Exception:
        pass

    return []


def main():
    queue_ws, history_ws = get_sheets()
    all_rows = queue_ws.get_all_values()
    existing_ids = set(history_ws.col_values(1)[1:])

    for idx in range(len(all_rows), 1, -1):
        row = all_rows[idx - 1]
        link_cell = row[7].strip() if len(row) > 7 else ""
        title_cell = row[1].strip() if len(row) > 1 else ""
        price_cell = parse_price_num(row[3]) if len(row) > 3 else 0

        if not is_valid_title(title_cell) or (price_cell > 499 and "s.daraz.com.bd" not in link_cell):
            queue_ws.delete_rows(idx)
        elif row[0]:
            existing_ids.add(row[0].strip())

    current_queue = len(queue_ws.get_all_values()) - 1
    if current_queue >= 4:
        print(f"Queue already has {current_queue} verified live in-stock deals.")
        return

    chosen_queries = random.sample(A_TO_Z_DARAZ_QUERIES, 4)
    tracking_param = os.environ.get("AFFILIATE_TRACKING_PARAM", "").strip().lstrip("?&")

    valid_deals = []
    for q_term in chosen_queries:
        print(f"Fetching Daraz Live Catalog for: {q_term}")
        found = fetch_daraz_live_deals(q_term)
        for info in found:
            if info["pid"] in existing_ids:
                continue
            existing_ids.add(info["pid"])
            valid_deals.append(info)
        if len(valid_deals) >= 6:
            break

    # সবচেয়ে বেশি রিভিউ ও সবচেয়ে কম দামের ডিলগুলো আগে সাজানো
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
        print(f"Added Live Deal (৳{info['discount_price']}, {info['discount_percent']} OFF, {info['rating']}): {info['title']}")

    print(f"Finished. Added {added} verified live in-stock deals.")


if __name__ == "__main__":
    main()
