import os
import re
import json
import html
import random
import urllib.parse
from datetime import datetime, timezone, timedelta
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


def build_clean_affiliate_link(raw_url, tracking_param):
    if "s.daraz.com.bd" in raw_url:
        return raw_url.strip()

    base_url = raw_url.split("?")[0]
    m_slug = re.search(
        r"^(https?://[^/]+/products/)([a-zA-Z0-9\-]+)(-i\d+(?:-s\d+)?\.html)$",
        base_url,
    )
    if m_slug:
        short_slug = "-".join(m_slug.group(2).split("-")[:3]) or "deal"
        base_url = f"{m_slug.group(1)}{short_slug}{m_slug.group(3)}"

    exlaz_val = ""
    for src in (raw_url, tracking_param):
        m_ex = re.search(r"(?:^|[?&])(exlaz=[^&]+)", src)
        if m_ex:
            exlaz_val = m_ex.group(1)
            break

    if exlaz_val:
        if "%25" in exlaz_val:
            exlaz_val = urllib.parse.unquote(exlaz_val)
        return f"{base_url}?{exlaz_val}"

    clean_tp = tracking_param.strip().lstrip("?&")
    if clean_tp:
        return f"{base_url}?{clean_tp}"
    return raw_url


def build_human_style_post(title, orig_price, disc_price, disc_pct, rating):
    safe_title = html.escape(title)
    try:
        saved_amount = max(0, int(float(orig_price)) - int(float(disc_price)))
    except Exception:
        saved_amount = 0

    save_line = f" (সাশ্রয় হচ্ছে ৳{saved_amount}!)" if saved_amount >= 50 else ""

    templates = [
        (
            f"🔥 <b>আজকের সেরা ডিল: {safe_title}</b>\n\n"
            f"নিত্যদিনের প্রয়োজনে দারুণ একটি কালেকশন এখন বিশাল ছাড়ে পাওয়া যাচ্ছে!\n\n"
            f"💸 <b>অফার প্রাইস:</b> ৳{disc_price} <s>৳{orig_price}</s>{save_line}\n"
            f"🏷️ <b>ডিসকাউন্ট:</b> {disc_pct} OFF\n"
            f"⭐ <b>কাস্টমার রেটিং:</b> {rating}/5 (১০০% অরিজিনাল)\n\n"
            f"স্টক শেষ হওয়ার আগেই নিচের বাটন থেকে দেখে নিন 👇"
        ),
        (
            f"⚡ <b>ফ্ল্যাশ অফার অ্যালার্ট! ({disc_pct} ছাড়)</b>\n\n"
            f"📦 <b>{safe_title}</b>\n\n"
            f"আগের দাম <s>৳{orig_price}</s> টাকা হলেও এখন পাচ্ছেন মাত্র <b>৳{disc_price} টাকায়</b>{save_line}।\n"
            f"✅ ভেরিফায়েড সেলার ও {rating}/5 রিভিউ স্কোর।\n\n"
            f"সরাসরি দারাজ থেকে অর্ডার করতে নিচে চাপুন 👇"
        ),
        (
            f"🛍️ <b>বাজেটের মধ্যে দারুণ অফার — {disc_pct} OFF!</b>\n\n"
            f"✨ {safe_title}\n\n"
            f"💰 <b>ডিসকাউন্ট মূল্য:</b> ৳{disc_price} (রেগুলার <s>৳{orig_price}</s>)\n"
            f"🌟 <b>রেটিং:</b> {rating}/5 | অরিজিনাল প্রোডাক্ট\n\n"
            f"অফারটি সীমিত সময়ের জন্য, এখনই চেক করুন 👇"
        ),
        (
            f"💥 <b>মেগা সেভিংস ডিল!</b>\n\n"
            f"<b>{safe_title}</b>\n\n"
            f"এখন কিনলে সরাসরি <b>{disc_pct} ছাড়</b> পাচ্ছেন! অফার প্রাইস মাত্র <b>৳{disc_price}</b> (আগের দাম <s>৳{orig_price}</s>){save_line}।\n"
            f"🛡️ কোয়ালিটি চেকড ও টপ-রেটেড ({rating}/5)।\n\n"
            f"নিচের বাটনে ক্লিক করে অর্ডার কনফার্ম করুন 👇"
        ),
    ]

    button_labels = [
        "🛒 অর্ডার করুন দারাজে",
        "🔥 ডিলটি লুফে নিন",
        "🛍️ অফার প্রাইসে কিনুন",
        "⚡ এখনই দারাজে দেখুন",
        "🛒 Order Now on Daraz",
    ]

    return random.choice(templates), random.choice(button_labels)


def send_telegram_post(bot_token, chat_id, caption, button_text, image_url, aff_link):
    base_url = f"https://api.telegram.org/bot{bot_token}"
    reply_markup = json.dumps({
        "inline_keyboard": [[{"text": button_text, "url": aff_link}]]
    })

    if image_url and image_url.startswith("http"):
        try:
            img_res = requests.get(
                image_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=12,
            )
            if img_res.status_code == 200 and len(img_res.content) > 1000:
                res = requests.post(
                    f"{base_url}/sendPhoto",
                    data={
                        "chat_id": chat_id,
                        "caption": caption,
                        "parse_mode": "HTML",
                        "reply_markup": reply_markup,
                    },
                    files={"photo": ("deal.jpg", img_res.content, "image/jpeg")},
                    timeout=20,
                ).json()
                if res.get("ok"):
                    return True
        except Exception as e:
            print("Image upload fallback:", e)

    res = requests.post(
        f"{base_url}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": caption,
            "parse_mode": "HTML",
            "reply_markup": reply_markup,
            "disable_web_page_preview": True,
        },
        timeout=15,
    ).json()
    if not res.get("ok"):
        raise RuntimeError(f"Telegram API Error: {res}")
    return True


def main():
    bot_token = (
        os.environ.get("TELEGRAM_BOT_TOKEN")
        or os.environ.get("BOT_TOKEN")
        or ""
    ).strip()
    chat_id = (
        os.environ.get("TELEGRAM_CHAT_ID")
        or os.environ.get("CHAT_ID")
        or os.environ.get("CHANNEL_ID")
        or "@newarea101"
    ).strip()

    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN secret is missing!")

    queue_ws, history_ws = get_sheets()
    rows = queue_ws.get_all_values()

    if len(rows) <= 1:
        print("Queue is empty. Nothing to post right now.")
        return

    row = rows[1]
    pid = row[0] if len(row) > 0 else ""
    title = row[1].strip() if len(row) > 1 else ""
    orig_price = row[2] if len(row) > 2 else ""
    disc_price = row[3] if len(row) > 3 else ""
    disc_pct = row[4] if len(row) > 4 else ""
    rating = row[5] if len(row) > 5 else "4.7"
    image_url = row[6] if len(row) > 6 else ""
    raw_aff_link = row[7] if len(row) > 7 else ""

    if not title or len(title) < 6 or "error" in title.lower() or not raw_aff_link:
        print(f"Skipping invalid row: {title}")
        queue_ws.delete_rows(2)
        return

    disc_num = int(re.sub(r"[^\d]", "", str(disc_pct)) or 0)
    if disc_num < 40 and "s.daraz.com.bd" not in raw_aff_link:
        print(f"Skipping deal under 40% ({disc_pct}): {title}")
        queue_ws.delete_rows(2)
        return

    tracking_param = os.environ.get("AFFILIATE_TRACKING_PARAM", "")
    aff_link = build_clean_affiliate_link(raw_aff_link, tracking_param)
    caption, button_text = build_human_style_post(title, orig_price, disc_price, disc_pct, rating)

    send_telegram_post(bot_token, chat_id, caption, button_text, image_url, aff_link)
    print(f"Successfully posted natural deal to {chat_id}: {title}")

    bd_time = datetime.now(timezone(timedelta(hours=6))).strftime("%Y-%m-%d %H:%M:%S")
    history_ws.append_row([pid, title, orig_price, disc_price, disc_pct, rating, image_url, aff_link, bd_time])
    queue_ws.delete_rows(2)
    print("Moved deal to Posted_History and removed from Queue.")


if __name__ == "__main__":
    main()
