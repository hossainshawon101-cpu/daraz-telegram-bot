import os
import re
import time
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
    raw_rating = str(rating)

    # স্পেশাল অফার ট্যাগ আলাদা করা (Buy 1 Get 1 / Mystery Box / Free Delivery)
    offer_badge = "🔥 কোপ অফার"
    if "buy 1 get 1" in raw_rating.lower() or "buy 1 get 1" in title.lower():
        offer_badge = "🎁 BUY 1 GET 1 FREE অফার"
    elif "mystery box" in raw_rating.lower() or "mystery box" in title.lower():
        offer_badge = "📦 MYSTERY BOX স্পেশাল ডিল"
    elif "free delivery" in raw_rating.lower():
        offer_badge = "🚚 FREE DELIVERY কোপ ডিল"

    rating_only = raw_rating.split("|")[0].strip()
    if "/" not in rating_only:
        rating_only = f"{rating_only}/5 (100+ Verified Reviews)"

    try:
        saved_amount = max(0, int(float(orig_price)) - int(float(disc_price)))
    except Exception:
        saved_amount = 0

    save_badge = f" [সাশ্রয় ৳{saved_amount}!]" if saved_amount >= 25 else ""

    templates = [
        (
            f"🚨 <b>【 {offer_badge} — {disc_pct} OFF 】</b>\n\n"
            f"📦 <b>{safe_title}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💥 <b>অফার প্রাইস:  <u>মাত্র ৳{disc_price} টাকা!</u></b>\n"
            f"🏷️ <b>রেগুলার দাম:</b> <s>৳{orig_price}</s>{save_badge}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⭐ <b>কাস্টমার রিভিউ:</b> <b>{rating_only}</b>\n"
            f"🛡️ <b>গ্যারান্টি:</b> ১০০% ভেরিফায়েড ও টপ-রেটেড সেলার\n"
            f"🚚 <b>টিপস:</b> Choice-এর আরও ২টি পণ্যের সাথে নিলে ফ্রি ডেলিভারি!\n\n"
            f"✅ স্টক শেষ হওয়ার আগেই নিচের বাটন থেকে অর্ডার করুন 👇"
        ),
        (
            f"⚡ <b>【 {offer_badge} | {disc_pct} ছাড় 】</b>\n\n"
            f"✨ <b>{safe_title}</b>\n\n"
            f"💰 <b>স্পেশাল ডিল প্রাইস:  <u>৳{disc_price} টাকা মাত্র</u></b> <s>(৳{orig_price})</s>{save_badge}\n\n"
            f"🌟 <b>বিশ্বাসযোগ্যতা:</b> <b>{rating_only}</b>\n"
            f"🚚 একসাথে ৩টি Choice পণ্য অর্ডার করলে ডেলিভারি চার্জ একদম ফ্রি!\n\n"
            f"🛒 সরাসরি দারাজ থেকে কিনতে নিচে ক্লিক করুন 👇"
        ),
        (
            f"🔥 <b>【 লোয়েস্ট প্রাইস অ্যালার্ট — {disc_pct} OFF 】</b>\n\n"
            f"🛍️ <b>{safe_title}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💸 <b>আজকের দাম:  <u>৳{disc_price} টাকা</u></b> (আগের দাম <s>৳{orig_price}</s>)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ <b>কাস্টমার রেটিং:</b> <b>{rating_only}</b>\n"
            f"🎁 <b>স্পেশাল সুবিধা:</b> {offer_badge} + Free Delivery টিপস\n\n"
            f"👇 অফারটি লুফে নিতে এখনই বাটনে চাপুন:"
        ),
    ]

    button_labels = [
        f"🛒 মাত্র ৳{disc_price}-এ অর্ডার করুন",
        f"🔥 ৳{disc_price} ডিলটি লুফে নিন",
        "🛍️ এখনই দারাজে অর্ডার করুন",
        "⚡ অফার প্রাইসে কিনুন",
    ]

    fb_caption = (
        f"🚨 【 {offer_badge} — {disc_pct} OFF 】\n\n"
        f"📦 {title}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💥 অফার প্রাইস:  👉 মাত্র ৳{disc_price} টাকা! 👈\n"
        f"🏷️ আগের দাম: ৳{orig_price}{save_badge}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⭐ কাস্টমার রিভিউ: {rating_only}\n"
        f"🛡️ ১০০% ভেরিফায়েড ও অরিজিনাল প্রোডাক্ট (কাস্টমার রিভিউ দেখে নিশ্চিত হয়ে কিনুন)\n"
        f"🚚 টিপস: Choice-এর আরও ২টি পণ্যের সাথে নিলে ফ্রি ডেলিভারি পাবেন!\n\n"
        f"👇 সরাসরি দারাজ থেকে কেনার লিংক প্রথম কমেন্টে (First Comment) দেওয়া আছে!\n"
        f"📢 আরও Buy 1 Get 1, Mystery Box ও কোপ ডিল পেতে Telegram Channel-এ জয়েন করুন: https://t.me/newarea101\n\n"
        f"#DarazKopOffer #Buy1Get1 #MysteryBox #FreeDelivery #BestDealsBD"
    )

    return random.choice(templates), random.choice(button_labels), fb_caption


def download_image_bytes(image_url):
    if not image_url or not image_url.startswith("http"):
        return None
    try:
        img_res = requests.get(
            image_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if img_res.status_code == 200 and len(img_res.content) > 1000:
            return img_res.content
    except Exception as e:
        print("Image download error:", e)
    return None


def send_telegram_post(bot_token, chat_id, caption, button_text, img_bytes, aff_link):
    base_url = f"https://api.telegram.org/bot{bot_token}"
    reply_markup = json.dumps({
        "inline_keyboard": [[{"text": button_text, "url": aff_link}]]
    })

    if img_bytes:
        try:
            res = requests.post(
                f"{base_url}/sendPhoto",
                data={
                    "chat_id": chat_id,
                    "caption": caption,
                    "parse_mode": "HTML",
                    "reply_markup": reply_markup,
                },
                files={"photo": ("deal.jpg", img_bytes, "image/jpeg")},
                timeout=20,
            ).json()
            if res.get("ok"):
                return True
        except Exception as e:
            print("
