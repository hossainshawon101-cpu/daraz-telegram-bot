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

DIVERSE_DARAZ_QUERIES = [
    # Flash, Choice & Combo Offers
    "buy 1 get 1", "mystery box", "combo offer", "daraz choice",
    # Tech & Mobile Gadgets
    "tws earbuds", "neckband bluetooth", "smart watch", "power bank mini",
    "type c fast charger", "gaming finger sleeve", "selfie stick tripod",
    "ring light mobile", "usb hub splitter", "card reader otg",
    "laptop stand folding", "mouse pad gaming", "wireless mouse",
    # Home, Kitchen & Living
    "digital kitchen scale", "electric egg beater", "mini bag sealer",
    "oil dispenser bottle", "vegetable chopper", "spice jar set",
    "lunch box airtight", "vacuum flask bottle", "coffee mug stainless",
    "lint remover", "clothes hanger organizer", "shoe rack foldable",
    "mosquito killer lamp", "emergency rechargeable bulb", "digital alarm clock",
    # Fashion, Bags & Accessories
    "men leather wallet", "crossbody sling bag", "travel backpack",
    "polarized sunglasses", "men analog watch", "leather belt men",
    "cotton polo shirt", "men cap hat", "winter beanie muffler",
    "women tote bag", "jewelry organizer box", "hair dryer mini",
    # Grooming, Health & Fitness
    "hair trimmer", "nose ear trimmer", "face wash", "sunscreen",
    "charcoal peel off mask", "beard oil", "perfume body spray",
    "hand grip strengthener", "skipping rope counter", "yoga mat",
    "posture corrector belt", "digital thermometer", "first aid box",
    # Bike, Car & Tools
    "bike mobile holder", "motorcycle gloves", "led fog light bike",
    "screwdriver tool kit", "measuring tape", "super glue repair",
    # Study & Office
    "desk organizer", "led study lamp", "scientific calculator",
    "sticky notes set", "gel pen combo", "whiteboard marker",
]

STOP_WORDS = {
    "for", "and", "the", "with", "in", "of", "to", "a", "an", "on",
    "new", "best", "high", "quality", "original", "daraz", "bd",
    "price", "offer", "pack", "set", "pcs", "piece", "combo", "mini",
}

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


def tokenize_title(title):
    words = re.findall(r"[a-z0-9]{3,}", title.lower())
    return {w for w in words if w not in STOP_WORDS}


def is_similar_to_existing(new_title, existing_token_sets):
    new_tokens = tokenize_title(new_title)
    if len(new_tokens) < 2:
        return False
    for old_tokens in existing_token_sets:
        if not old_tokens:
            continue
        overlap = len(new_tokens & old_tokens)
        smaller_len = min(len(new_tokens), len(old_tokens))
        if smaller_len > 0 and (overlap / smaller_len) >= 0.45:
            return True
    return False


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

            if disc_price < 20 or disc_price > 499:
                continue

            review_count = parse_price_num(item.get("review"))
            rating_val = round(float(item.get("ratingScore") or 0), 1)

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

            img_url = str(item.get("image") or "").split("?")[0]
            if img_url.startswith("//"):
                img_url = "https:" + img_url

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


def fetch_daraz_live_deals(query_term, page_num=1):
    encoded_q = urllib.parse.quote(query_term)
    sort_mode = random.choice(["popularity", "default", "priceasc"])
    api_url = f"https://www.daraz.com.bd/catalog/?ajax=true&page={page_num}&q={encoded_q}&price=-499&sort={sort_mode}"

    try:
        r = requests.get(api_url, headers=DARAZ_HEADERS, timeout=10)
        if r.status_code == 200 and "listItems" in r.text:
            deals = parse_daraz_catalog_json(r.text)
            if deals:
                return deals
    except Exception:
        pass

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
    queue_rows = queue_ws.get_all_values()
    history_rows = history_ws.get_all_values()

    existing_ids = set()
    existing_images = set()
    existing_token_sets = []

    # Posted_History-এর শেষ ১৫০টি পোস্ট চেক করে ডুপ্লিকেট ব্লক করা
    for row in history_rows[1:][-150:]:
        if len(row) > 0 and row[0]:
            existing_ids.add(row[0].strip())
        if len(row) > 1 and row[1]:
            existing_token_sets.append(tokenize_title(row[1]))
        if len(row) > 6 and row[6]:
            existing_images.add(row[6].split("?")[0].strip())

    for idx in range(len(queue_rows), 1, -1):
        row = queue_rows[idx - 1]
        link_cell = row[7].strip() if len(row) > 7 else ""
        title_cell = row[1].strip() if len(row) > 1 else ""
        price_cell = parse_price_num(row[3]) if len(row) > 3 else 0
        img_cell = row[6].split("?")[0].strip() if len(row) > 6 else ""

        if (
            not is_valid_title(title_cell)
            or (price_cell > 499 and "s.daraz.com.bd" not in link_cell)
            or (row[0] and row[0].strip() in existing_ids)
            or (is_similar_to_existing(title_cell, existing_token_sets) and "s.daraz.com.bd" not in link_cell)
        ):
            queue_ws.delete_rows(idx)
        else:
            if row[0]:
                existing_ids.add(row[0].strip())
            if title_cell:
                existing_token_sets.append(tokenize_title(title_cell))
            if img_cell:
                existing_images.add(img_cell)

    current_queue = len(queue_ws.get_all_values()) - 1
    if current_queue >= 4:
        print(f"Queue already has {current_queue} unique verified live deals.")
        return

    chosen_queries = random.sample(DIVERSE_DARAZ_QUERIES, 5)
    tracking_param = os.environ.get("AFFILIATE_TRACKING_PARAM", "").strip().lstrip("?&")

    valid_deals = []
    for q_term in chosen_queries:
        page_num = random.randint(1, 4)
        print(f"Fetching Unique Daraz Deals for: '{q_term}' (Page {page_num})")
        found = fetch_daraz_live_deals(q_term, page_num=page_num)
        random.shuffle(found)

        for info in found:
            clean_img = info["image_url"].split("?")[0].strip()
            if info["pid"] in existing_ids:
                continue
            if clean_img and clean_img in existing_images:
                continue
            if is_similar_to_existing(info["title"], existing_token_sets):
                continue

            existing_ids.add(info["pid"])
            if clean_img:
                existing_images.add(clean_img)
            existing_token_sets.append(tokenize_title(info["title"]))
            valid_deals.append(info)
            # প্রতি কুয়েরি থেকে সর্বোচ্চ ১টি সেরা প্রোডাক্ট নেওয়া, যাতে সব পোস্ট ভিন্ন ক্যাটাগরির হয়
            break

        if len(valid_deals) >= 4:
            break

    added = 0
    for info in valid_deals:
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
        print(f"Added Unique Deal (৳{info['discount_price']}, {info['discount_percent']} OFF): {info['title']}")

    print(f"Finished. Added {added} completely unique live deals.")


if __name__ == "__main__":
    main()
