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
    return f"{base_url}?{clean_tp}" if clean_tp else raw_url


def build_human_style_post(title, orig_price, disc_price, disc_pct, rating):
    safe_title = html.escape(title)
    raw_rating = str(rating)

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

    tg_caption = (
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
    )

    button_text = f"🛒 মাত্র ৳{disc_price}-এ অর্ডার করুন"

    fb_caption = (
        f"🚨 【 {offer_badge} — {disc_pct} OFF 】\n\n"
        f"📦 {title}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💥 অফার প্রাইস:  👉 মাত্র ৳{disc_price} টাকা! 👈\n"
        f"🏷️ আগের দাম: ৳{orig_price}{save_badge}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⭐ কাস্টমার রিভিউ: {rating_only}\n"
        f"🛡️ ১০০% ভেরিফায়েড ও অরিজিনাল প্রোডাক্ট\n"
        f"🚚 টিপস: Choice-এর আরও ২টি পণ্যের সাথে নিলে ফ্রি ডেলিভারি পাবেন!\n\n"
        f"👇 সরাসরি দারাজ থেকে কেনার লিংক প্রথম কমেন্টে (First Comment) দেওয়া আছে!\n"
        f"📢 আরও কোপ ডিল পেতে Telegram Channel-এ জয়েন করুন: https://t.me/newarea101\n\n"
        f"#DarazKopOffer #Buy1Get1 #MysteryBox #FreeDelivery #BestDealsBD"
    )

    return tg_caption, button_text, fb_caption


def download_image_bytes(image_url):
    if not image_url or not image_url.startswith("http"):
        return None
    try:
        r = requests.get(image_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code == 200 and len(r.content) > 1000:
            return r.content
    except Exception:
        pass
    return None


def send_telegram_post(bot_token, chat_id, caption, button_text, img_bytes, aff_link):
    base_url = f"https://api.telegram.org/bot{bot_token}"
    markup = json.dumps({"inline_keyboard": [[{"text": button_text, "url": aff_link}]]})

    if img_bytes:
        try:
            res = requests.post(
                f"{base_url}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML", "reply_markup": markup},
                files={"photo": ("deal.jpg", img_bytes, "image/jpeg")},
                timeout=20,
            ).json()
            if res.get("ok"):
                return True
        except Exception:
            pass

    res = requests.post(
        f"{base_url}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": caption,
            "parse_mode": "HTML",
            "reply_markup": markup,
            "disable_web_page_preview": True,
        },
        timeout=15,
    ).json()
    if not res.get("ok"):
        raise RuntimeError(f"Telegram API Error: {res}")
    return True


def post_to_facebook_page(page_id, access_token, fb_caption, img_bytes, image_url, aff_link):
    if not page_id or not access_token:
        print("Facebook Secrets not set. Skipping FB.")
        return

    try:
        graph_base = f"https://graph.facebook.com/v20.0/{page_id}"
        post_id = ""
        photo_id = ""

        if img_bytes:
            res = requests.post(
                f"{graph_base}/photos",
                data={"caption": fb_caption, "access_token": access_token},
                files={"source": ("deal.jpg", img_bytes, "image/jpeg")},
                timeout=25,
            ).json()
            post_id = res.get("post_id") or ""
            photo_id = res.get("id") or ""

        if not post_id and not photo_id and image_url and image_url.startswith("http"):
            res = requests.post(
                f"{graph_base}/photos",
                data={"url": image_url, "caption": fb_caption, "access_token": access_token},
                timeout=20,
            ).json()
            post_id = res.get("post_id") or ""
            photo_id = res.get("id") or ""

        if not post_id and not photo_id:
            res = requests.post(
                f"{graph_base}/feed",
                data={"message": fb_caption, "access_token": access_token},
                timeout=20,
            ).json()
            post_id = res.get("id") or ""

        target_ids = [tid for tid in [post_id, photo_id] if tid]
        if target_ids:
            time.sleep(3)
            comment_id = ""
            comment_msg = f"✅ সরাসরি দারাজ থেকে কেনার লিংক 👇\n{aff_link}"

            for tid in target_ids:
                c_res = requests.post(
                    f"https://graph.facebook.com/v20.0/{tid}/comments",
                    data={"message": comment_msg, "access_token": access_token},
                    timeout=15,
                ).json()
                if c_res.get("id"):
                    comment_id = c_res["id"]
                    break
                print("FB comment retry:", c_res)

            if not comment_id:
                fallback_caption = fb_caption.replace(
                    "👇 সরাসরি দারাজ থেকে কেনার লিংক প্রথম কমেন্টে (First Comment) দেওয়া আছে!",
                    f"✅ সরাসরি দারাজ থেকে কেনার লিংক 👇\n{aff_link}",
                )
                requests.post(
                    f"https://graph.facebook.com/v20.0/{target_ids[0]}",
                    data={"message": fallback_caption, "access_token": access_token},
                    timeout=15,
                )
                print(f"FB Post updated with link fallback: {target_ids[0]}")
            else:
                print(f"Successfully posted to FB (Post ID: {target_ids[0]}, Comment ID: {comment_id})")
        else:
            print("Facebook post failed:", res)
    except Exception as e:
        print("Facebook posting error:", e)


def main():
    bot_token = (os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("CHAT_ID") or "@newarea101").strip()

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
    rating = row[5] if len(row) > 5 else "4.7/5 (100+ Reviews)"
    image_url = row[6] if len(row) > 6 else ""
    raw_aff_link = row[7] if len(row) > 7 else ""

    if not title or len(title) < 6 or "error" in title.lower() or not raw_aff_link:
        queue_ws.delete_rows(2)
        return

    tracking_param = os.environ.get("AFFILIATE_TRACKING_PARAM", "")
    aff_link = build_clean_affiliate_link(raw_aff_link, tracking_param)
    tg_caption, button_text, fb_caption = build_human_style_post(
        title, orig_price, disc_price, disc_pct, rating
    )

    img_bytes = download_image_bytes(image_url)
    send_telegram_post(bot_token, chat_id, tg_caption, button_text, img_bytes, aff_link)
    print(f"Successfully posted deal to Telegram {chat_id}: {title}")

    fb_page_id = os.environ.get("FB_PAGE_ID", "").strip()
    fb_token = os.environ.get("FB_ACCESS_TOKEN", "").strip()
    post_to_facebook_page(fb_page_id, fb_token, fb_caption, img_bytes, image_url, aff_link)

    bd_time = datetime.now(timezone(timedelta(hours=6))).strftime("%Y-%m-%d %H:%M:%S")
    history_ws.append_row([pid, title, orig_price, disc_price, disc_pct, rating, image_url, aff_link, bd_time])
    queue_ws.delete_rows(2)
    print("Moved deal to Posted_History and removed from Queue.")


if __name__ == "__main__":
    main()
