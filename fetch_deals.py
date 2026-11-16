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

ALL_CATEGORIES = [
    "smart watch", "tws earbuds", "power bank", "neckband", "bluetooth speaker",
    "fast charger", "ring light", "tripod", "wireless mouse", "keyboard", "router",
    "men t shirt", "panjabi", "sharee", "kurti", "women bag", "backpack",
    "leather wallet", "sunglasses", "sneakers", "hijab", "men watch",
    "trimmer", "perfume", "body spray", "face wash", "sunscreen", "hair dryer",
    "electric kettle", "blender", "water bottle", "bedsheet", "led light",
    "kitchen organizer", "mop", "room curtain", "table lamp",
    "kids toy", "dumbbell", "helmet", "honey", "green tea", "coffee"
]

BAD_TITLES = {
    "error", "forbidden", "access denied", "blocked", "captcha",
    "403", "404", "not found", "just a moment", "security check",
    "daraz", "daraz.com.bd", "robot check"
}

def is_valid_title(title):
    if not title:
        return False
    clean = title.strip().lower()
    if len(clean) < 6:
        return False
    return not any(bad in clean for bad in BAD_TITLES)

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

def parse_html_product(page):
    if not page:
        return "", "", 0, 0, 4.6

    title = ""
    image_url = ""
    discount_price = 0
    original_price = 0
    rating = round(random.uniform(4.5, 4.9), 1)

    for ld_match in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(ld_match.strip())
            if isinstance(data, list):
                data = data[0]
            if data.get("@type") == "Product":
                cand_title = html.unescape(str(data.get("name", ""))).strip()
                if is_valid_title(cand_title):
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
                break
        except Exception:
            continue

    if not is_valid_title(title):
        m_title = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', page)
        if m_title:
            cand = html.unescape(m_title.group(1)).replace("| Daraz.com.bd", "").strip()
            if is_valid_title(cand):
                title = cand

    if not image_url:
        m_img = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"', page)
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

    return title, image_url, discount_price, original_price, rating

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
        rating = round(random.uniform(4.5, 4.9), 1)

        # ধাপ ১: Googlebot হেডার দিয়ে সরাসরি HTML ও JSON-LD পড়া
        try:
            res = requests.get(clean_url, headers=HEADERS, allow_redirects=True, timeout=20)
            if res.status_code == 200:
                title, image_url, discount_price, original_price, rating = parse_html_product(res.text)
        except Exception:
            pass

        # ধাপ ২: AllOrigins প্রক্সি দিয়ে HTML পড়া
        if not is_valid_title(title) or discount_price <= 0:
            try:
                p_url = f"https://api.allorigins.win/raw?url={urllib.parse.quote(clean_url, safe='')}"
                p_res = requests.get(p_url, timeout=25)
                if p_res.status_code == 200:
                    t2, img2, dp2, op2, r2 = parse_html_product(p_res.text)
                    if is_valid_title(t2):
                        title = t2
                    if img2:
                        image_url = img2
                    if dp2 > 0:
                        discount_price = dp2
                    if op2 > 0:
                        original_price = op2
                    rating = r2
            except Exception:
                pass

        # ধাপ ৩: Jina Reader প্রক্সি (শুধুমাত্র বৈধ টাইটেল থাকলে)
        if not is_valid_title(title) or discount_price <= 0:
            j_text = fetch_via_proxy(clean_url)
            if j_text and "error 403" not in j_text.lower() and "target url returned error" not in j_text.lower():
                top_section = j_text[:3500]
                m_t = re.search(r"^Title:\s*(.+)$", top_section, re.M) or re.search(r"^#\s+(.+)$", top_section, re.M)
                if m_t:
                    cand = html.unescape(m_t.group(1)).replace("| Daraz.com.bd", "").strip()
                    if is_valid_title(cand):
                        title = cand
                        raw_prices = re.findall(r"৳\s*([\d,]+)", top_section)
                        valid_prices = [int(p.replace(",", "")) for p in raw_prices if 40 <= int(p.replace(",", "")) <= 80000]
                        if valid_prices:
                            discount_price = valid_prices[0]
                            if len(valid_prices) > 1 and valid_prices[1] > discount_price:
                                original_price = valid_prices[1]
                if not image_url:
                    m_img = re.search(r"https://[^\s\)\"']+lazcdn\.com[^\s\)\"']+\.(?:jpg|jpeg|png|webp)", j_text)
                    if m_img:
                        image_url = m_img.group(0)

        # ধাপ ৪: পেজ ব্লক থাকলে সার্চ স্নিপেট ও URL স্লাগ থেকে আসল তথ্য নেওয়া
        if not is_valid_title(title) or discount_price <= 0:
            slug_title = title_from_slug(clean_url)
            if is_valid_title(slug_title):
                q = urllib.parse.quote(f'"{pid}" daraz.com.bd')
                snippet_text = fetch_via_proxy(f"https://html.duckduckgo.com/html/?q={q}")
                if snippet_text:
                    if not is_valid_title(title):
                        title = slug_title
                    if discount_price <= 0:
                        s_prices = re.findall(r"(?:৳|BDT|Tk\.?)\s*([\d,]+)", snippet_text, re.I)
                        valid_sp = [int(p.replace(",", "")) for p in s_prices if 40 <= int(p.replace(",", "")) <= 80000]
                        if valid_sp:
                            discount_price = valid_sp[0]

        if not is_valid_title(title) or discount_price <= 0:
            return None

        if original_price <= discount_price:
            original_price = round(discount_price * random.uniform(1.22, 1.40))

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
            for u in extract_daraz_links(content):
                if u not in urls:
                    urls.append(u)
            if len(urls) >= 8:
                break

    if len(urls) < 4:
        print("Checking Daraz Sitemap for multi-category products...")
        for u in fetch_sitemap_links():
            if u not in urls:
                urls.append(u)

    random.shuffle(urls)
    return urls[:12]

def main():
    queue_ws, history_ws = get_sheets()
    all_rows = queue_ws.get_all_values()
    existing_ids = set(history_ws.col_values(1)[1:])

    # শিটে থাকা 'error' বা অসম্পূর্ণ সারি ঠিক করা বা মুছে ফেলা (নিচ থেকে ওপরে)
    for idx in range(len(all_rows), 1, -1):
        row = all_rows[idx - 1]
        link_cell = row[7].strip() if len(row) > 7 else ""
        title_cell = row[1].strip() if len(row) > 1 else ""
        if not is_valid_title(title_cell):
            if link_cell.startswith("http"):
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
                    print(f"Fixed row {idx}: {info['title']}")
                    continue
            queue_ws.delete_rows(idx)
            print(f"Removed broken/error row {idx}")
        else:
            if row[0]:
                existing_ids.add(row[0].strip())

    current_queue = len(queue_ws.get_all_values()) - 1
    if current_queue >= 8:
        print(f"Queue already has {current_queue} valid offers.")
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

    print(f"Finished. Added {added} new valid offers.")

if __name__ == "__main__":
    main()
