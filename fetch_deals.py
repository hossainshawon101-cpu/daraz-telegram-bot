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

# সব ধরনের ক্যাটাগরির প্রোডাক্ট খোঁজার তালিকা
ALL_CATEGORIES = [
    # Electronics & Gadgets
    "smart watch", "tws earbuds", "power bank", "neckband", "bluetooth speaker",
    "fast charger", "ring light", "tripod", "wireless mouse", "keyboard", "router",
    # Fashion & Accessories
    "men t shirt", "panjabi", "sharee", "kurti", "women bag", "backpack",
    "leather wallet", "sunglasses", "sneakers", "hijab", "men watch",
    # Health, Beauty & Grooming
    "trimmer", "perfume", "body spray", "face wash", "sunscreen", "hair dryer",
    # Home, Kitchen & Living
    "electric kettle", "blender", "water bottle", "bedsheet", "led light",
    "kitchen organizer", "mop", "room curtain", "table lamp",
    # Baby, Toys, Sports & Daily Needs
    "kids toy", "dumbbell", "helmet", "honey", "green tea", "coffee"
]

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
    # ১. Jina Reader প্রক্সি
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

    # ২. AllOrigins প্রক্সি ব্যাকআপ
    try:
        encoded = urllib.parse.quote(target_url, safe="")
        r2 = requests.get(f"https://api.allorigins.win/raw?url={encoded}", timeout=25)
        if r2.status_code == 200 and len(r2.text) > 300:
            return r2.text
    except Exception:
        pass

    return ""

def extract_daraz_links(raw_text):
    if not raw_text:
        return []
    cleaned = raw_text.replace("\\/", "/")
    cleaned = urllib.parse.unquote(cleaned)
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

def fetch_sitemap_links():
    urls = []
    sitemap_index_urls = ["https://www.daraz.com.bd/sitemap.xml"]
    try:
        rob = requests.get("https://www.daraz.com.bd/robots.txt", headers=HEADERS, timeout=15)
        if rob.status_code == 200:
            for sm in re.findall(r"Sitemap:\s*(https?://\S+)", rob.text, re.I):
                if sm.strip() not in sitemap_index_urls:
                    sitemap_index_urls.append(sm.strip())
    except Exception:
        pass

    sub_sitemaps = []
    for sm_url in sitemap_index_urls[:2]:
        try:
            res = requests.get(sm_url, headers=HEADERS, timeout=20)
            xml_text = (
                gzip.decompress(res.content).decode("utf-8", errors="ignore")
                if (sm_url.endswith(".gz") or res.content[:2] == b"\x1f\x8b")
                else res.text
            )
            urls.extend(extract_daraz_links(xml_text))
            for loc in re.findall(r"<loc>(https?://[^<]+)</loc>", xml_text):
                if any(k in loc.lower() for k in ["product", "pdp", "item", "sitemap"]):
                    sub_sitemaps.append(loc.strip())
        except Exception:
            continue

    if not urls and sub_sitemaps:
        random.shuffle(sub_sitemaps)
        for sub in sub_sitemaps[:2]:
            try:
                res = requests.get(sub, headers=HEADERS, timeout=20)
                sub_text = (
                    gzip.decompress(res.content).decode("utf-8", errors="ignore")
                    if (sub.endswith(".gz") or res.content[:2] == b"\x1f\x8b")
                    else res.text
                )
                urls.extend(extract_daraz_links(sub_text))
                if len(urls) >= 20:
                    break
            except Exception:
                continue

    return list(dict.fromkeys(urls))

def discover_all_category_offers():
    urls = []

    # ধাপ A: সার্চ ইঞ্জিন প্রক্সির মাধ্যমে র‍্যান্ডম ক্যাটাগরি খোঁজা
    chosen_cats = random.sample(ALL_CATEGORIES, 2)
    for cat in chosen_cats:
        print(f"Searching category: {cat}")
        q = urllib.parse.quote(f"site:daraz.com.bd/products {cat}")
        search_urls = [
            f"https://html.duckduckgo.com/html/?q={q}",
            f"https://search.brave.com/search?q={q}",
            f"https://www.bing.com/search?q={q}",
        ]
        for s_url in search_urls:
            content = fetch_via_proxy(s_url)
            found = extract_daraz_links(content)
            for u in found:
                if u not in urls:
                    urls.append(u)
            if len(urls) >= 8:
                break

    # ধাপ B: সার্চ ইঞ্জিনে লিংক কম পেলে দারাজের Sitemap থেকে সব ক্যাটাগরির লিংক নেওয়া
    if len(urls) < 4:
        print("Checking Daraz Sitemap for multi-category products...")
        sm_links = fetch_sitemap_links()
        for u in sm_links:
            if u not in urls:
                urls.append(u)

    random.shuffle(urls)
    return urls[:12]

def scrape_product_page(url):
    try:
        clean_url = url.split("?")[0]
        if clean_url.startswith("//"):
            clean_url = "https:" + clean_url

        pid_match = re.search(r"-i(\d+)", clean_url)
        pid = pid_match.group(1) if pid_match else str(abs(hash(clean_url)))[:10]

        page_text = fetch_via_proxy(clean_url)
        if not page_text:
            return None

        title = ""
        image_url = ""
        discount_price = 0
        original_price = 0
        rating = round(random.uniform(4.5, 4.9), 1)

        top_section = page_text[:4000]
        m_title = (
            re.search(r"^Title:\s*(.+)$", top_section, re.M)
            or re.search(r"^#\s+(.+)$", top_section, re.M)
            or re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', page_text)
        )
        if m_title:
            title = html.unescape(m_title.group(1)).replace("| Daraz.com.bd", "").strip()

        raw_prices = re.findall(r"৳\s*([\d,]+)", top_section)
        valid_prices = []
        for p in raw_prices:
            val = int(p.replace(",", ""))
            if 40 <= val <= 80000 and val not in valid_prices:
                valid_prices.append(val)
            if len(valid_prices) >= 2:
                break

        if valid_prices:
            discount_price = valid_prices[0]
            if len(valid_prices) > 1 and valid_prices[1] > discount_price:
                original_price = valid_prices[1]

        m_img = re.search(
            r"https://[^\s\)\"']+lazcdn\.com[^\s\)\"']+\.(?:jpg|jpeg|png|webp)",
            page_text,
        )
        if m_img:
            image_url = m_img.group(0)

        if not title or discount_price <= 0:
            return None

        if original_price <= discount_price:
            original_price = round(discount_price * random.uniform(1.25, 1.45))

        discount_percent = max(10, round(((original_price - discount_price) / original_price) * 100))

        return {
            "pid": pid,
            "title": title[:140],
            "original_price": int(original_price),
            "discount_price": int(discount_price),
            "discount_percent": f"{discount_percent}%",
            "rating": rating,
            "image_url": image_url,
            "clean_url": clean_url,
        }
    except Exception as e:
        print(f"Scrape error: {e}")
        return None

def main():
    queue_ws, history_ws = get_sheets()
    all_rows = queue_ws.get_all_values()
    existing_ids = set(queue_ws.col_values(1)[1:] + history_ws.col_values(1)[1:])

    # শিটে কোনো খালি সারি থাকলে তা পূরণ করা
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

    # শিটে ইতিমধ্যে ৮টি বা তার বেশি অফার জমা থাকলে নতুন করে না খোঁজা
    current_queue = len(queue_ws.get_all_values()) - 1
    if current_queue >= 8:
        print(f"Queue already has {current_queue} offers ready.")
        return

    product_urls = discover_all_category_offers()
    print(f"Discovered {len(product_urls)} candidate links across categories.")
    tracking_param = os.environ.get("AFFILIATE_TRACKING_PARAM", "").strip().lstrip("?&")

    added = 0
    for p_url in product_urls:
        if added >= 4:
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
        print(f"Auto-added: {info['title']}")

    print(f"Finished. Added {added} new offers.")

if __name__ == "__main__":
    main()
