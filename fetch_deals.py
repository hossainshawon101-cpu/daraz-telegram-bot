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
    raw_sheet = os.environ.get("SHEET_ID", "").strip()
    m = re.search(r"/d/([a-zA-Z0-9-_]+)", raw_sheet)
    sheet_id = m.group(1) if m else raw_sheet
    try:
        sheet = client.open_by_key(sheet_id)
    except Exception:
        sheet = client.open("Daraz_Affiliate_Automation")
    return sheet.worksheet("Queue"), sheet.worksheet("Posted_History")

def scrape_product_page(url):
    try:
        clean_url = url.split("?")[0]
        if clean_url.startswith("//"):
            clean_url = "https:" + clean_url

        pid_match = re.search(r"-i(\d+)", clean_url)
        pid = pid_match.group(1) if pid_match else str(abs(hash(clean_url)))[:10]

        title = ""
        image_url = ""
        discount_price = 0
        original_price = 0
        rating = 4.6

        # Jina Reader প্রক্সি দিয়ে দারাজ পেজ পড়া (GitHub IP ব্লক এড়াতে)
        j_res = requests.get(
            f"https://r.jina.ai/{clean_url}",
            headers={"Accept": "text/plain"},
            timeout=25,
        )
        if j_res.status_code == 200:
            j_text = j_res.text
            top_section = j_text[:3000]

            m_title = re.search(r"^Title:\s*(.+)$", top_section, re.M) or re.search(r"^#\s+(.+)$", top_section, re.M)
            if m_title:
                title = html.unescape(m_title.group(1)).replace("| Daraz.com.bd", "").strip()

            # পেজের ওপরের অংশ থেকে আসল ও ডিসকাউন্ট দাম নেওয়া
            raw_prices = re.findall(r"৳\s*([\d,]+)", top_section)
            valid_prices = []
            for p in raw_prices:
                val = int(p.replace(",", ""))
                if val >= 30 and val not in valid_prices:
                    valid_prices.append(val)
                if len(valid_prices) >= 2:
                    break

            if valid_prices:
                discount_price = valid_prices[0]
                if len(valid_prices) > 1 and valid_prices[1] > discount_price:
                    original_price = valid_prices[1]

            m_img = re.search(r"https://[^\s\)\"']+lazcdn\.com[^\s\)\"']+\.(?:jpg|jpeg|png|webp)", j_text)
            if m_img:
                image_url = m_img.group(0)

        if not title or discount_price <= 0:
            return None

        if original_price <= discount_price:
            original_price = round(discount_price * 1.28)

        discount_percent = max(5, round(((original_price - discount_price) / original_price) * 100))

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
        print(f"Scrape error for {url}: {e}")
        return None

def discover_daraz_urls():
    urls = []
    keywords = [
        "smart watch", "tws earbuds", "power bank", "trimmer",
        "bluetooth speaker", "backpack", "led light", "wallet",
        "sunglasses", "kitchen gadgets", "perfume", "neckband"
    ]
    chosen = random.choice(keywords)
    print(f"Searching Daraz catalog for: {chosen}")

    search_targets = [
        f"https://r.jina.ai/https://www.daraz.com.bd/catalog/?q={urllib.parse.quote(chosen)}",
        f"https://r.jina.ai/https://www.bing.com/search?q={urllib.parse.quote('site:daraz.com.bd/products/ ' + chosen)}",
    ]

    for target in search_targets:
        try:
            res = requests.get(target, headers={"Accept": "text/plain"}, timeout=25)
            if res.status_code == 200:
                decoded = urllib.parse.unquote(res.text)
                found = re.findall(r"(?:https?:)?//www\.daraz\.com\.bd/products/[a-zA-Z0-9\-]+-i\d+-s\d+\.html", decoded)
                for u in found:
                    full_u = "https:" + u if u.startswith("//") else u
                    if full_u not in urls:
                        urls.append(full_u)
            if len(urls) >= 8:
                break
        except Exception as e:
            print(f"Discovery warning: {e}")

    random.shuffle(urls)
    return urls[:8]

def main():
    queue_ws, history_ws = get_sheets()
    all_rows = queue_ws.get_all_values()
    existing_ids = set(queue_ws.col_values(1)[1:] + history_ws.col_values(1)[1:])

    # ধাপ ১: শিটের H কলামে ম্যানুয়ালি পেস্ট করা কোনো লিংক থাকলে সেটির তথ্য পূরণ করা
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

    # শিটে ইতিমধ্যে ৫টি বা তার বেশি ডিল জমা থাকলে নতুন করে খোঁজার দরকার নেই
    current_queue_count = len(queue_ws.get_all_values()) - 1
    if current_queue_count >= 5:
        print(f"Queue already has {current_queue_count} deals. Skipping auto-discovery.")
        return

    # ধাপ ২: অটোমেটিক নতুন ডিল খুঁজে শিটে যোগ করা
    product_urls = discover_daraz_urls()
    print(f"Found {len(product_urls)} product URLs.")
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
        print(f"Added auto deal: {info['title']}")

    print(f"Total new deals added: {added}")

if __name__ == "__main__":
    main()
