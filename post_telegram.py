import os
import re
import json
import time
import requests
import gspread
from io import BytesIO
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont
from oauth2client.service_account import ServiceAccountCredentials

# --- কনফিগারেশন (Workflow Secrets অনুযায়ী) ---
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHAT_ID")
RAW_SHEET_ID = os.environ.get("SHEET_ID", "").strip()
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
FB_ACCESS_TOKEN = os.environ.get("FB_ACCESS_TOKEN")

# --- গুগল শিট কানেকশন ---
def get_spreadsheet():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    creds_dict = json.loads(creds_json)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    match = re.search(r"/d/([a-zA-Z0-9-_]+)", RAW_SHEET_ID)
    clean_id = match.group(1) if match else RAW_SHEET_ID

    try:
        return client.open_by_key(clean_id)
    except Exception:
        return client.open("Daraz Deals")

# --- প্রফেশনাল ডিল কার্ড ইমেজ তৈরি (১টি প্রোডাক্টের জন্য) ---
def create_deal_card(prod):
    card_w, card_h = 600, 680
    card = Image.new("RGB", (card_w, card_h), (245, 245, 245))
    draw = ImageDraw.Draw(card)

    try:
        font_price = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        font_old = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        font_badge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
    except:
        font_price = ImageFont.load_default()
        font_old = ImageFont.load_default()
        font_badge = ImageFont.load_default()

    # সাদা কার্ড ব্যাকগ্রাউন্ড
    draw.rectangle([10, 10, card_w - 10, card_h - 10], fill=(255, 255, 255), outline=(220, 220, 220), width=3)

    # প্রোডাক্ট ইমেজ ডাউনলোড ও রিসাইজ
    try:
        img_url = prod.get('image_url', '').strip()
        img_res = requests.get(img_url, timeout=15)
        img = Image.open(BytesIO(img_res.content)).convert("RGB")
        img = img.resize((560, 520), Image.Resampling.LANCZOS)
        card.paste(img, (20, 20))
    except Exception as e:
        print(f"Image load error: {e}")

    # ডিসকাউন্ট ব্যাজ
    discount_pct = str(prod.get('discount_percent', '')).strip()
    if discount_pct:
        draw.rectangle([450, 30, 575, 75], fill=(230, 46, 4))
        draw.text((468, 38), f"-{discount_pct}", fill=(255, 255, 255), font=font_badge)

    # নিচের অংশে প্রাইস ও রেটিং বসানো
    disc_price = prod.get('discount_price', '')
    orig_price = prod.get('original_price', '')
    rating_raw = str(prod.get('rating', '')).split('|')[0].strip()

    draw.text((28, 555), f"Tk {disc_price}", fill=(248, 86, 6), font=font_price)
    draw.text((230, 563), f"Tk {orig_price}", fill=(140, 140, 140), font=font_old)
    draw.text((28, 610), f"Rating: {rating_raw}", fill=(80, 80, 80), font=font_old)

    output_path = "deal_card.jpg"
    card.save(output_path, quality=90)
    return output_path

# --- ফেসবুক পেজে পোস্ট করার ফাংশন ---
def post_to_facebook(image_path, fb_caption):
    if not FB_PAGE_ID or not FB_ACCESS_TOKEN:
        print("FB_PAGE_ID বা FB_ACCESS_TOKEN পাওয়া যায়নি, ফেসবুক পোস্ট স্কিপ করা হলো।")
        return

    fb_url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos"

    try:
        with open(image_path, "rb") as photo:
            payload = {
                "caption": fb_caption,
                "access_token": FB_ACCESS_TOKEN
            }
            files = {"source": photo}
            res = requests.post(fb_url, data=payload, files=files, timeout=25)
            if res.status_code == 200:
                print("ফেসবুক পেজেও সফলভাবে পোস্ট হয়েছে!")
            else:
                print(f"ফেসবুক পোস্ট এরর: {res.text}")
    except Exception as e:
        print(f"ফেসবুক কানেকশন এরর: {e}")

# --- টেলিগ্রামে অটো-রিট্রাইসহ পোস্ট পাঠানোর ফাংশন ---
def send_telegram_with_retry(tg_url, payload, image_path, retries=3):
    for attempt in range(1, retries + 1):
        try:
            with open(image_path, "rb") as photo:
                files = {"photo": photo}
                response = requests.post(tg_url, data=payload, files=files, timeout=25)
                return response
        except Exception as e:
            print(f"টেলিগ্রাম কানেকশন চেষ্টা #{attempt} ব্যর্থ: {e}")
            if attempt < retries:
                time.sleep(3)
    return None

# --- মেইন ফাংশন ---
def main():
    ss = get_spreadsheet()
    queue_sheet = ss.worksheet("Queue")
    raw_records = queue_sheet.get_all_records()

    records = []
    for row in raw_records:
        clean_row = {str(k).strip().lower(): v for k, v in row.items()}
        records.append(clean_row)

    if len(records) < 1:
        print("Queue শিটে কোনো প্রোডাক্ট নেই।")
        return

    prod = records[0]
    print("১টি প্রোডাক্ট নেওয়া হয়েছে, ডিল কার্ড তৈরি হচ্ছে...")

    # ১. ডিল কার্ড ছবি তৈরি
    image_path = create_deal_card(prod)

    # ২. ক্লিন ক্যাপশন তৈরি (কোনো লম্বা URL ছাড়াই, নিচে ১টি সিঙ্গেল অর্ডার বাটন থাকবে)
    price = prod.get('discount_price', '')
    orig_price = prod.get('original_price', '')
    discount = str(prod.get('discount_percent', '')).strip()
    rating = str(prod.get('rating', '')).strip()
    title = str(prod.get('title', '')).strip()
    raw_link = str(prod.get('affiliate_link') or prod.get('link') or prod.get('product_url') or "").strip()

    tg_caption = (
        f"🔥 <b>{discount} OFF ফ্ল্যাশ ডিল!</b>\n\n"
        f"📦 <b>{title}</b>\n\n"
        f"💰 অফার প্রাইস: <b>{price} টাকা</b> (আগের দাম <s>{orig_price} টাকা</s>)\n"
        f"⭐ রেটিং: {rating}\n\n"
        f"👇 <b>অর্ডার করতে নিচের বাটনে ক্লিক করুন:</b>"
    )

    fb_caption = (
        f"🔥 {discount} OFF ফ্ল্যাশ ডিল!\n\n"
        f"📦 {title}\n\n"
        f"💰 অফার প্রাইস: {price} টাকা (আগের দাম {orig_price} টাকা)\n"
        f"⭐ রেটিং: {rating}\n\n"
        f"🛒 অর্ডার লিংক:\n{raw_link}"
    )

    reply_markup = json.dumps({
        "inline_keyboard": [
            [{"text": f"🛒 দারাজে অর্ডার করুন (৳{price})", "url": raw_link}]
        ]
    })

    # ৩. টেলিগ্রামে পোস্ট পাঠানো (৩ বার পর্যন্ত অটো-রিট্রাইসহ)
    tg_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": CHAT_ID,
        "caption": tg_caption,
        "parse_mode": "HTML",
        "reply_markup": reply_markup
    }
    response = send_telegram_with_retry(tg_url, payload, image_path)

    if response and response.status_code == 200:
        print("টেলিগ্রামে সফলভাবে পোস্ট হয়েছে!")
        
        # ৪. ফেসবুক পেজে পোস্ট পাঠানো
        post_to_facebook(image_path, fb_caption)

        # ৫. Posted_History ট্যাবে বাংলাদেশ সময়সহ (DATE AND TIME) ঠিক পরবর্তী খালি রো-তে সেভ করা
        try:
            history_sheet = ss.worksheet("Posted_History")
            rows_to_move = queue_sheet.get_values("A2:H2")
            if rows_to_move:
                bd_tz = timezone(timedelta(hours=6))
                now_bd = datetime.now(bd_tz).strftime("%Y-%m-%d %H:%M:%S")
                enriched_rows = [row + [now_bd] for row in rows_to_move]
                
                existing_col_a = history_sheet.col_values(1)
                next_row = len(existing_col_a) + 1
                
                history_sheet.update(f"A{next_row}:I{next_row}", enriched_rows, value_input_option="USER_ENTERED")
                print(f"Posted_History ট্যাবে {next_row} নম্বর রো-তে সময়সহ ({now_bd}) সেভ হয়েছে।")
        except Exception as e:
            print(f"History সেভ করতে সামান্য সমস্যা: {e}")

        # ৬. Queue থেকে পোস্ট হয়ে যাওয়া রো ডিলিট করা
        queue_sheet.delete_rows(2)
        print("পোস্টকৃত রো Queue থেকে সরানো হয়েছে।")
    else:
        err_msg = response.text if response else "Connection failed after 3 retries"
        print(f"টেলিগ্রামে পোস্ট করতে সমস্যা হয়েছে: {err_msg}")

if __name__ == "__main__":
    main()
