import os
import re
import json
import html
import random
import urllib.parse
import requests
import gspread
from google.oauth2.service_account import Credentials

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
    # প্রক্সি ১: Jina Reader
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

    # প্রক্সি ২: AllOrigins ব্যাকআপ
    try:
        encoded = urllib.parse.quote(target_url, safe="")
        r2 = requests.get(f"https://api.allorigins.win/raw?url={encoded}", timeout=25)
        if r2.status_code == 200 and len(r2.text) > 300:
            return r2.text
    except Exception:
        pass

    return ""

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

        top_section = page_text[:3500]
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
            if 40 <= val <= 50000 and val not in valid_prices:
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

def discover_daraz_offers():
    urls = []
    offer_keywords = [
        "flash sale", "smart watch", "tws earbuds", "power bank",
        "trimmer", "bluetooth speaker", "backpack", "led light",
        "wallet", "sunglasses", "kitchen gadgets", "perfume",
        "neckband", "mobile stand", "wireless mouse", "fashion bag"
    ]
    chosen = random.choice(offer_keywords)
    print(f"Auto-hunting Daraz deals for: {chosen}")

    sources = [
        f"https://www.daraz.com.bd/catalog/?q={urllib.parse.quote(chosen)}&sort=order",
        f"https://www.daraz.com.bd/wow/gcp/route/daraz/bd/upr/router?pha=true&hybrid=1&wx_navbar_transparent=true&wh_pid=%2Flazada%2Fmegascenario%2Fbd%2Fflash-sale",
        f"https://www.bing.com/search?q={urllib.parse.quote('site:daraz.com.bd/products/ ' + chosen)}",
    ]

    for src in sources:
        content = fetch_via_proxy(src)
        if not content:
            continue
        decoded = urllib.parse.unquote(content)
        found = re.findall(
            r"(?:https?:)?//www\.daraz\.com\.bd/products/[a-zA-Z0-9\-]+-i\d+-s\d+\.html",
            decoded,
        )
        for u in found:
            full_u = "https:" + u if u.startswith("//") else u
            if full_u not in urls:
                urls.append(full_u)
        if len(urls) >= 10:
            break

    random.shuffle(urls)
    return urls[:10]

def main():
    queue_ws, history_ws = get_sheets()
    all_rows = queue_ws.get_all_values()
    existing_ids = set(queue_ws.col_values(1)[1:] + history_ws.col_values(1)[1:])

    # শিটে কোনো অসম্পূর্ণ সারি থাকলে তা পূরণ করা
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

    # শিটে ইতিমধ্যে ৬টি বা তার বেশি অফার জমা থাকলে নতুন করে না খোঁজা
    current_queue = len(queue_ws.get_all_values()) - 1
    if current_queue >= 6:
        print(f"Queue has {current_queue} offers ready. No need to fetch more right now.")
        return

    # অটোমেটিক নতুন অফার খুঁজে শিটে যোগ করা
    product_urls = discover_daraz_offers()
    print(f"Discovered {len(product_urls)} offer links.")
    tracking_param = os.environ.get("AFFILIATE_TRACKING_PARAM", "").strip().lstrip("?&")

    added = 0
    for p_url in product_urls:
        if added >= 3:
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
        print(f"Auto-added offer: {info['title']}")

    print(f"Finished. Added {added} new offers.")

if __name__ == "__main__":
    main()
