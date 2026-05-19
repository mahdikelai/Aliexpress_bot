import os
import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from telegram.constants import ParseMode
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
ALIEXPRESS_APP_KEY = os.getenv("ALIEXPRESS_APP_KEY")
ALIEXPRESS_APP_SECRET = os.getenv("ALIEXPRESS_APP_SECRET")
ALIEXPRESS_TRACKING_ID = os.getenv("ALIEXPRESS_TRACKING_ID", "default")
MIN_DISCOUNT_PERCENT = int(os.getenv("MIN_DISCOUNT_PERCENT", "40"))
MAX_PRICE_USD = float(os.getenv("MAX_PRICE_USD", "100"))
PRODUCTS_PER_RUN = int(os.getenv("PRODUCTS_PER_RUN", "5"))
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "60"))
KEYWORDS = os.getenv("SEARCH_KEYWORDS", "discount,sale,offer").split(",")

import urllib.request
import urllib.parse
import json
import hmac
import hashlib
import time

def aliexpress_request(keyword, page_size=20):
    try:
        app_key = ALIEXPRESS_APP_KEY
        app_secret = ALIEXPRESS_APP_SECRET
        timestamp = str(int(time.time() * 1000))
        method = "aliexpress.affiliate.product.query"

        params = {
            "app_key": app_key,
            "timestamp": timestamp,
            "sign_method": "hmac",
            "method": method,
            "keywords": keyword,
            "page_size": str(page_size),
            "page_no": "1",
            "tracking_id": ALIEXPRESS_TRACKING_ID,
            "fields": "product_id,product_title,target_sale_price,target_original_price,target_sale_price_currency,evaluate_rate,lastest_volume,promotion_link,product_main_image_url",
        }

        sorted_params = sorted(params.items())
        sign_str = app_secret + "".join(f"{k}{v}" for k, v in sorted_params) + app_secret
        sign = hmac.new(app_secret.encode(), sign_str.encode(), hashlib.md5).hexdigest().upper()
        params["sign"] = sign

        url = "https://gw.api.alibaba.com/openapi/param2/2/portals.open/api.listPromotionProduct/" + app_key
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.error(f"خطأ في API: {e}")
        return None

async def fetch_deals():
    deals = []
    seen = set()
    for keyword in KEYWORDS:
        keyword = keyword.strip()
        if not keyword:
            continue
        result = aliexpress_request(keyword)
        if not result:
            continue
        try:
            products = result.get("result", {}).get("products", {}).get("product", [])
            for p in products:
                pid = str(p.get("productId", ""))
                if pid in seen:
                    continue
                seen.add(pid)
                original = float(p.get("originalPrice", 0) or 0)
                sale = float(p.get("salePrice", 0) or 0)
                if original <= 0 or sale <= 0:
                    continue
                discount = round((1 - sale / original) * 100)
                if discount >= MIN_DISCOUNT_PERCENT and sale <= MAX_PRICE_USD:
                    deals.append({
                        "id": pid,
                        "title": p.get("productTitle", ""),
                        "image": p.get("imageUrl", ""),
                        "original_price": original,
                        "sale_price": sale,
                        "discount": discount,
                        "url": p.get("detailUrl", f"https://www.aliexpress.com/item/{pid}.html"),
                        "orders": p.get("volume", "N/A"),
                        "rating": p.get("evaluateRate", "N/A"),
                    })
        except Exception as e:
            logger.warning(f"خطأ في تحليل المنتج: {e}")
    deals.sort(key=lambda x: x["discount"], reverse=True)
    return deals[:PRODUCTS_PER_RUN]

def format_message(p):
    msg = (
        f"🔥 *تخفيض {p['discount']}%*\n\n"
        f"🛍 *{p['title'][:80]}{'...' if len(p['title']) > 80 else ''}*\n\n"
        f"💰 السعر الأصلي: ~${p['original_price']:.2f}~\n"
        f"✅ السعر بعد الخصم: *${p['sale_price']:.2f}*\n\n"
        f"📦 الطلبات: {p['orders']}\n"
        f"⭐ التقييم: {p['rating']}\n\n"
        f"🔗 [اشتري الآن]({p['url']})\n\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    return msg

async def send_deals():
    logger.info("🔍 جاري البحث عن تخفيضات...")
    deals = await fetch_deals()
    if not deals:
        logger.info("لم يتم العثور على تخفيضات.")
        return
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    for p in deals:
        try:
            caption = format_message(p)
            if p.get("image"):
                await bot.send_photo(chat_id=TELEGRAM_CHANNEL_ID, photo=p["image"], caption=caption, parse_mode=ParseMode.MARKDOWN)
            else:
                await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=caption, parse_mode=ParseMode.MARKDOWN)
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"خطأ في الإرسال: {e}")
    logger.info("✅ تم الإرسال!")

async def main():
    logger.info("🤖 بدء تشغيل البوت...")
    await send_deals()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_deals, "interval", minutes=CHECK_INTERVAL_MINUTES)
    scheduler.start()
    logger.info(f"⏱ كل {CHECK_INTERVAL_MINUTES} دقيقة سيتم البحث تلقائياً.")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
