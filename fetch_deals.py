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

def parse_html_product(page, final_url):
    title = ""
    image_url = ""
    discount_price = 0
    original_price = 0
    rating = 4.5

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

    if discount_price <= 0:
        m_price = re.search(r'"salePrice"\s*:\s*\{[^}]*"value"\s*:\s*([\d.]+)', page) or re.search(r'"price"\s*:\s*([\d.]+)', page)
        if m_price:
            discount_price = float(m_price.group(1))

    if original_price <= discount_price:
        m_orig = re.search(r'"originalPrice"\s*:\s*\{[^}]*"value"\s*:\s*([\d.]+)', page) or re.search(r'"originalPrice"\s*:\s*([\d.]+)', page)
        if m_orig:
            original_price = float(m_orig.group(1))

    return title, image_url, discount_price, original_price, rating

def scrape_product_page(url):
    try:
        clean_url = url.split("?")[0]
        final_url = clean_url
        page = ""

        try:
            res = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=20)
            final_url = res.url.split("?")[0]
            page = res.text
        except Exception:
            pass

        pid_match = re.search(r"-i(\d+)", final_url)
        pid = pid_match.group(1) if pid_match else str(abs(hash(final_url)))[:10]

        title, image_url, discount_price, original_price, rating = parse_html_product(page, final_url)

        # ডাইরেক্ট ব্লক হলে প্রক্সি ব্যাকআপ থেকে ডাটা নেওয়া
        if not title or discount_price <= 0:
            try:
                proxy_url = f"https://api.allorigins.win/raw?url={urllib.parse.quote(final_url, safe='')}"
                p_res = requests.get(proxy_url, timeout=25)
                if p_res.status_code == 200:
                    title, image_url, discount_price, original_price, rating = parse_html_product(p_res.text, final_url)
            except Exception:
                pass

        # দ্বিতীয় ব্যাকআপ (Jina Reader)
        if not title or discount_price <= 0:
            try:
                j_res = requests.get(f"https://r.jina.ai/{final_url}", timeout=25)
                if j_res.status_code == 200:
                    j_text = j_res.text
                    if not title:
                        m_h = re.search(r"^#\s+(.+)$", j_text, re.M)
                        if m_h:
                            title = m_h.group(1).replace("| Daraz.com.bd", "").strip()
                    prices = [int(p.replace(",", "")) for p in re.findall(r"৳\s*([\d,]+)", j_text) if int(p.replace(",", "")) > 10]
                    if prices:
                        discount_price = min(prices)
                        if max(prices) > discount_price:
                            original_price = max(prices)
                    if not image_url:
                        m_laz = re.search(r"https://[^\s\)\"']+lazcdn\.com[^\s\)\"']+\.(?:jpg|jpeg|png|webp)", j_text)
                        if m_laz:
                            image_url = m_laz.group(0)
            except Exception:
                pass

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
            "clean_url": final_url,
        }
    except Exception as e:
        print(f"Scrape error for {url}: {e}")
        return None

def fetch_text_or_gz(url):
    res = requests.get(url, headers=HEADERS, timeout=20)
    if url.endswith(".gz") or res.content[:2] == b"\x1f\x8b":
        return gzip.decompress(res.content).decode("utf-8", errors="ignore")
    return res.text

def discover_daraz_urls():
    urls = []
    # ধাপ A: দারাজের নিজস্ব Sitemap থেকে সক্রিয় প্রোডাক্ট লিংক বের করা
    sitemap_candidates = ["https://www.daraz.com.bd/sitemap.xml"]
    try:
        rob = requests.get("https://www.daraz.com.bd/robots.txt", headers=HEADERS, timeout=15).text
        for sm in re.findall(r"Sitemap:\s*(https?://\S+)", rob, re.I):
            if sm not in sitemap_candidates:
                sitemap_candidates.append(sm.strip())
    except Exception:
        pass

    sub_sitemaps = []
    for sm_url in sitemap_candidates[:3]:
        try:
            xml_text = fetch_text_or_gz(sm_url)
            direct = re.findall(r"https://www\.daraz\.com\.bd/products/[a-zA-Z0-9\-]+-i\d+-s\d+\.html", xml_text)
            urls.extend(direct)
            for loc in re.findall(r"<loc>(https?://[^<]+)</loc>", xml_text):
                if "product" in loc.lower() or "pdp" in loc.lower() or "sitemap" in loc.lower():
                    sub_sitemaps.append(loc.strip())
        except Exception as e:
            print(f"Sitemap check note: {e}")

    if not urls and sub_sitemaps:
        random.shuffle(sub_sitemaps)
        for sub in sub_sitemaps[:3]:
            try:
                sub_text = fetch_text_or_gz(sub)
                found = re.findall(r"https://www\.daraz\.com\.bd/products/[a-zA-Z0-9\-]+-i\d+-s\d+\.html", sub_text)
                urls.extend(found)
                if len(urls) >= 20:
                    break
            except Exception:
                continue

    # ধাপ B: ব্যাকআপ হিসেবে সার্চ প্রক্সি ব্যবহার
    if not urls:
        kw = random.choice(["smart watch", "tws earbuds", "power bank", "trimmer", "backpack", "led light"])
        q = urllib.parse.quote(f"site:daraz.com.bd/products/ {kw}")
        try:
            r = requests.get(f"https://r.jina.ai/https://search.yahoo.com/search?p={q}", timeout=25)
            decoded = urllib.parse.unquote(r.text)
            urls.extend(re.findall(r"https://www\.daraz\.com\.bd/products/[a-zA-Z0-9\-]+-i\d+-s\d+\.html", decoded))
        except Exception:
            pass

    unique_urls = list(dict.fromkeys(urls))
    random.shuffle(unique_urls)
    return unique_urls[:10]

def main():
    queue_ws, history_ws = get_sheets()
    all_rows = queue_ws.get_all_values()
    existing_ids = set(queue_ws.col_values(1)[1:] + history_ws.col_values(1)[1:])

    # শিটের H কলামে ম্যানুয়ালি পেস্ট করা লিংক প্রসেস করা
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

    # অটোমেটিক নতুন প্রোডাক্ট খুঁজে শিটে যোগ করা
    product_urls = discover_daraz_urls()
    print(f"Discovered {len(product_urls)} candidate product URLs.")
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
