import os
import re
import json
import requests
import gspread
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from oauth2client.service_account import ServiceAccountCredentials

# --- কনফিগারেশন (Workflow Secrets অনুযায়ী) ---
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
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

# --- লম্বা লিংক শর্ট করার ফাংশন (TinyURL) ---
def shorten_url(long_url):
    try:
        res = requests.get(f"http://tinyurl.com/api-create.php?url={long_url}", timeout=10)
        if res.status_code == 200:
            return res.text
    except Exception as e:
        print(f"URL Shorten Error: {e}")
    return long_url

# --- ৩x২ গ্রিড কোলাজ ইমেজ তৈরি ---
def create_collage(products):
    card_w, card_h = 400, 480
    cols = 3
    rows = 2 if len(products) > 3 else 1
    collage = Image.new("RGB", (card_w * cols, card_h * rows), (245, 245, 245))
    draw = ImageDraw.Draw(collage)

    try:
        font_price = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        font_old = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        font_badge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    except:
        font_price = ImageFont.load_default()
        font_old = ImageFont.load_default()
        font_badge = ImageFont.load_default()

    for idx, prod in enumerate(products):
        r = idx // cols
        c = idx % cols
        x_offset = c * card_w
        y_offset = r * card_h

        # সাদা কার্ড ব্যাকগ্রাউন্ড
        draw.rectangle([x_offset + 5, y_offset + 5, x_offset + card_w - 5, y_offset + card_h - 5], fill=(255, 255, 255), outline=(220, 220, 220), width=2)

        # প্রোডাক্ট ইমেজ ডাউনলোড ও রিসাইজ
        try:
            img_res = requests.get(prod['image_url'], timeout=15)
            img = Image.open(BytesIO(img_res.content)).convert("RGB")
            img = img.resize((380, 360), Image.Resampling.LANCZOS)
            collage.paste(img, (x_offset + 10, y_offset + 10))
        except Exception as e:
            print(f"Image load error: {e}")

        # ডিসকাউন্ট ব্যাজ
        discount_pct = str(prod.get('discount_percent', '')).strip()
        if discount_pct:
            draw.rectangle([x_offset + 295, y_offset + 15, x_offset + 385, y_offset + 48], fill=(230, 46, 4))
            draw.text((x_offset + 308, y_offset + 21), f"-{discount_pct}", fill=(255, 255, 255), font=font_badge)

        # নিচের অংশে প্রাইস ও রেটিং বসানো
        disc_price = prod.get('discount_price', '')
        orig_price = prod.get('original_price', '')
        rating_raw = str(prod.get('rating', '')).split('|')[0].strip()

        draw.text((x_offset + 18, y_offset + 382), f"৳ {disc_price}", fill=(248, 86, 6), font=font_price)
        draw.text((x_offset + 165, y_offset + 390), f"৳{orig_price}", fill=(140, 140, 140), font=font_old)
        draw.text((x_offset + 18, y_offset + 425), f"⭐ {rating_raw}", fill=(80, 80, 80), font=font_old)

    output_path = "collage.jpg"
    collage.save(output_path, quality=90)
    return output_path

# --- ফেসবুক পেজে কোলাজ পোস্ট করার ফাংশন ---
def post_to_facebook(image_path, caption_html):
    if not FB_PAGE_ID or not FB_ACCESS_TOKEN:
        print("FB_PAGE_ID বা FB_ACCESS_TOKEN পাওয়া যায়নি, ফেসবুক পোস্ট স্কিপ করা হলো।")
        return

    fb_caption = re.sub(r'<[^>]+>', '', caption_html)
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
                print("ফেসবুক পেজেও সফলভাবে কোলাজ পোস্ট হয়েছে!")
            else:
                print(f"ফেসবুক পোস্ট এরর: {res.text}")
    except Exception as e:
        print(f"ফেসবুক কানেকশন এরর: {e}")

# --- মেইন ফাংশন ---
def main():
    ss = get_spreadsheet()
    queue_sheet = ss.worksheet("Queue")
    records = queue_sheet.get_all_records()

    # কমপক্ষে ৩টি প্রোডাক্ট থাকলেই পোস্ট করবে (সর্বোচ্চ ৬টি নেবে)
    if len(records) < 3:
        print(f"Queue শিটে মাত্র {len(records)}টি প্রোডাক্ট আছে। কমপক্ষে ৩টি হলে পোস্ট করা হবে।")
        return

    count = min(6, len(records))
    selected_products = records[:count]
    print(f"{count}টি প্রোডাক্ট নেওয়া হয়েছে, কোলাজ তৈরি হচ্ছে...")

    # ১. কোলাজ ছবি তৈরি
    image_path = create_collage(selected_products)

    # ২. ক্লিন ক্যাপশন তৈরি
    caption_lines = [f"⚡ <b>আজকের সেরা {count}টি ফ্ল্যাশ ডিল! যেটা লাগবে দ্রুত অর্ডার করুন:</b>\n"]
    
    for prod in selected_products:
        price = prod['discount_price']
        raw_title = str(prod['title']).strip()
        short_title = raw_title[:38] + "..." if len(raw_title) > 38 else raw_title
        
        short_link = shorten_url(prod['affiliate_link'])
        
        caption_lines.append(f"✅ <b>{price} টাকায়</b> {short_title}\n👉 {short_link}")

    caption_text = "\n".join(caption_lines)

    # ৩. টেলিগ্রামে পোস্ট পাঠানো
    tg_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(image_path, "rb") as photo:
        payload = {
            "chat_id": CHAT_ID,
            "caption": caption_text,
            "parse_mode": "HTML"
        }
        files = {"photo": photo}
        response = requests.post(tg_url, data=payload, files=files)

    if response.status_code == 200:
        print("টেলিগ্রামে সফলভাবে কোলাজ পোস্ট হয়েছে!")
        
        # ৪. ফেসবুক পেজে পোস্ট পাঠানো
        post_to_facebook(image_path, caption_text)

        # ৫. Posted_History ট্যাবে রেকর্ড সেভ করা
        try:
            history_sheet = ss.worksheet("Posted_History")
            rows_to_move = queue_sheet.get_values(f"A2:H{count + 1}")
            if rows_to_move:
                history_sheet.append_rows(rows_to_move)
                print("Posted_History ট্যাবে রেকর্ড সেভ হয়েছে।")
        except Exception as e:
            print(f"History সেভ করতে সামান্য সমস্যা: {e}")

        # ৬. Queue থেকে পোস্ট হয়ে যাওয়া রো ডিলিট করা
        queue_sheet.delete_rows(2, count + 1)
        print(f"পোস্টকৃত {count}টি রো Queue থেকে সরানো হয়েছে।")
    else:
        print(f"টেলিগ্রামে পোস্ট করতে সমস্যা হয়েছে: {response.text}")

if __name__ == "__main__":
    main()
