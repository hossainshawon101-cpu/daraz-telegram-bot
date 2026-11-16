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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def get_sheets():
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(os.environ["SHEET_ID"])
    return sheet.worksheet("Queue"), sheet.worksheet("Posted_History")

def scrape_product_page(url):
    try:
        res = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=20)
        final_url = res.url
        page = res.text

        pid_match = re.search(r"-i(\d+)", final_url)
        pid = pid_match.group(1) if pid_match else str(abs(hash(final_url)))[:10]

        title = ""
        image_url = ""
        discount_price = 0
        original_price = 0
        rating = 4.5

        # JSON-LD ডাটা থেকে তথ্য নেওয়া
        for ld_match in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
            try:
                data = json.loads(ld_match.strip())
                if isinstance(data, list):
                    data = data[0]
                if data.get("@type") == "Product":
                    title = html.unescape(str(data.get("name", ""))).strip()
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
                    break
            except Exception:
                continue

        # ব্যাকআপ মেটা ট্যাগ থেকে টাইটেল ও ছবি
        if not title:
            m_title = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', page)
            if m_title:
                title = html.unescape(m_title.group(1)).replace("| Daraz.com.bd", "").strip()

        if not image_url:
            m_img = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"', page)
            if m_img:
                image_url = m_img.group(1).strip()

        if image_url.startswith("//"):
            image_url = "https:" + image_url

        # ব্যাকআপ দাম বের করা
        if discount_price <= 0:
            m_price = re.search(r'"salePrice"\s*:\s*\{[^}]*"value"\s*:\s*([\d.]+)', page) or re.search(r'"price"\s*:\s*([\d.]+)', page)
            if m_price:
                discount_price = float(m_price.group(1))

        if original_price <= discount_price:
            m_orig = re.search(r'"originalPrice"\s*:\s*\{[^}]*"value"\s*:\s*([\d.]+)', page) or re.search(r'"originalPrice"\s*:\s*([\d.]+)', page)
            if m_orig:
                original_price = float(m_orig.group(1))

        if not title or discount_price <= 0:
            return None

        if original_price <= discount_price:
            original_price = round(discount_price * 1.25)

        discount_percent = max(5, round(((original_price - discount_price) / original_price) * 100))

        return {
            "pid": pid,
            "title": title[:140],
            "original_price": int(original_price),
            "discount_price": int(discount_price),
            "discount_percent": f"{discount_percent}%",
            "rating": rating,
            "image_url": image_url,
            "clean_url": final_url.split("?")[0],
        }
    except Exception as e:
        print(f"Scrape error for {url}: {e}")
        return None

def search_daraz_urls(keyword):
    urls = []
    query = urllib.parse.quote(f"site:daraz.com.bd/products/ {keyword}")
    search_endpoints = [
        f"https://html.duckduckgo.com/html/?q={query}",
        f"https://www.bing.com/search?q={query}",
    ]
    for s_url in search_endpoints:
        try:
            res = requests.get(s_url, headers=HEADERS, timeout=20)
            found = re.findall(r"https://www\.daraz\.com\.bd/products/[a-zA-Z0-9\-]+-i\d+-s\d+\.html", res.text)
            for u in found:
                if u not in urls:
                    urls.append(u)
            if len(urls) >= 8:
                break
        except Exception as e:
            print(f"Search warning: {e}")
    return urls

def main():
    queue_ws, history_ws = get_sheets()
    all_rows = queue_ws.get_all_values()
    existing_ids = set(queue_ws.col_values(1)[1:] + history_ws.col_values(1)[1:])

    # ধাপ ১: শিটের H কলামে আপনি নিজে কোনো লিংক পেস্ট করলে সেটির তথ্য অটো পূরণ করা
    for idx, row in enumerate(all_rows[1:], start=2):
        link_cell = row[7].strip() if len(row) > 7 else ""
        title_cell = row[1].strip() if len(row) > 1 else ""
        if link_cell.startswith("http") and not title_cell:
            info = scrape_product_page(link_cell)
            if info:
                updated = [
                    info["pid"],
                    info["title"],
                    info["original_price"],
                    info["discount_price"],
                    info["discount_percent"],
                    info["rating"],
                    info["image_url"],
                    link_cell,
                ]
                queue_ws.update(f"A{idx}:H{idx}", [updated])
                existing_ids.add(info["pid"])
                print(f"Auto-filled manual link row {idx}: {info['title']}")

    # ধাপ ২: অটোমেটিক নতুন ডিল খুঁজে শিটে যোগ করা
    categories = [
        "smart watch", "tws earbuds", "power bank", "trimmer",
        "bluetooth speaker", "backpack", "kitchen gadgets", "led light"
    ]
    chosen = random.choice(categories)
    print(f"Searching Daraz deals for: {chosen}")

    product_urls = search_daraz_urls(chosen)
    tracking_param = os.environ.get("AFFILIATE_TRACKING_PARAM", "").strip().lstrip("?&")

    added = 0
    for p_url in product_urls:
        if added >= 5:
            break
        info = scrape_product_page(p_url)
        if not info or info["pid"] in existing_ids:
            continue

        aff_link = f"{info['clean_url']}?{tracking_param}" if tracking_param else info["clean_url"]
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
        existing_ids.add(info["pid"])
        added += 1

    print(f"Added {added} new deals to Queue.")

if __name__ == "__main__":
    main()
