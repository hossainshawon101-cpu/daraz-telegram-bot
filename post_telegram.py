import os
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
    sheet = client.open_by_key(os.environ["SHEET_ID"])
    return sheet.worksheet("Queue"), sheet.worksheet("Posted_History")

def send_telegram_post(bot_token, chat_id, caption, image_url):
    base_url = f"https://api.telegram.org/bot{bot_token}"
    
    if image_url and image_url.startswith("http"):
        res = requests.post(
            f"{base_url}/sendPhoto",
            data={
                "chat_id": chat_id,
                "photo": image_url,
                "caption": caption,
                "parse_mode": "HTML",
            },
            timeout=20,
        ).json()
        if res.get("ok"):
            return True
        print("Photo send failed, falling back to text:", res)

    res = requests.post(
        f"{base_url}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": caption,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
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
    image_url = row[6] if len(row) >
