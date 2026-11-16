import os
import re
import json
import html
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

def send_telegram_post(bot_token, chat_id, caption, image_url, aff_link):
    base_url = f"https://api.telegram.org/bot{bot_token}"
    reply_markup = json.dumps({
        "inline_keyboard": [[{"text": "🛒 Order Now on Daraz", "url": aff_link}]]
    })

    if image_url and image_url.startswith("http"):
        try:
            img_res = requests.get(
                image_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
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
                    timeout=25,
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
        timeout=20,
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

    safe_title = html.escape(title)
    caption = (
        f"🔥 <b>{safe_title}</b>\n\n"
        f"💰 <b>Offer Price:</b> ৳{disc_price} <s>৳{orig_price}</s>\n"
        f"📉 <b>Mega Discount:</b> {disc_pct} OFF\n"
        f"⭐ <b>Rating:</b> {rating}/5\n"
        f"🛡️ <b>Quality:</b> Verified Authentic & Top-Rated\n\n"
        f"👇 <b>অর্ডার করতে নিচের বাটনে ক্লিক করুন</b>"
    )

    send_telegram_post(bot_token, chat_id, caption, image_url, aff_link)
    print(f"Successfully posted authentic deal to {chat_id}: {title}")

    bd_time = datetime.now(timezone(timedelta(hours=6))).strftime("%Y-%m-%d %H:%M:%S")
    history_ws.append_row([pid, title, orig_price, disc_price, disc_pct, rating, image_url, aff_link, bd_time])
    queue_ws.delete_rows(2)
    print("Moved deal to Posted_History and removed from Queue.")

if __name__ == "__main__":
    main()
