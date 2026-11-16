import os
import re
import json
import html
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
    title = row[1] if len(row) > 1 else ""
    orig_price = row[2] if len(row) > 2 else ""
    disc_price = row[3] if len(row) > 3 else ""
    disc_pct = row[4] if len(row) > 4 else ""
    rating = row[5] if len(row) > 5 else "4.5"
    image_url = row[6] if len(row) > 6 else ""
    aff_link = row[7] if len(row) > 7 else ""

    if not title or not aff_link:
        print("Row 2 is incomplete, skipping.")
        return

    tracking_param = os.environ.get("AFFILIATE_TRACKING_PARAM", "").strip().lstrip("?&")
    if tracking_param and "exlaz=" not in aff_link and "s.daraz.com.bd" not in aff_link:
        sep = "&" if "?" in aff_link else "?"
        aff_link = f"{aff_link}{sep}{tracking_param}"

    safe_title = html.escape(title)
    safe_link = html.escape(aff_link, quote=True)
    caption = (
        f"🔥 <b>{safe_title}</b>\n\n"
        f"💰 <b>Offer Price:</b> ৳{disc_price} <s>৳{orig_price}</s>\n"
        f"📉 <b>Discount:</b> {disc_pct} OFF\n"
        f"⭐ <b>Rating:</b> {rating}/5\n\n"
        f"👉 <a href=\"{safe_link}\"><b>এখানে ক্লিক করে দারাজ থেকে অর্ডার করুন</b></a>"
    )

    send_telegram_post(bot_token, chat_id, caption, image_url, aff_link)
    print(f"Successfully posted to {chat_id}: {title}")

    bd_time = datetime.now(timezone(timedelta(hours=6))).strftime("%Y-%m-%d %H:%M:%S")
    history_ws.append_row([pid, title, orig_price, disc_price, disc_pct, rating, image_url, aff_link, bd_time])
    queue_ws.delete_rows(2)
    print("Moved deal to Posted_History and removed from Queue.")

if __name__ == "__main__":
    main()
