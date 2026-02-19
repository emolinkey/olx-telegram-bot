import os, asyncio, httpx, random, sys, json, threading, logging
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from flask import Flask

TOKEN = "8346602599:AAEauikfQJCI_cyZK5hiv3W0StWk9OMWPK0"
ADMIN_ID = 908015235

class Config:
    url = "https://www.olx.pl/elektronika/telefony/q-iphone-13-pro/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=500&search%5Bfilter_float_price:to%5D=1500"
    interval = 300
    is_running = True

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OLX_Sniper_Pro")

app = Flask('')
@app.route('/')
def home(): return "Бот работает"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

class OLXParser:
    def __init__(self):
        self.seen_ads = set()

    async def fetch(self):
        # Улучшенные заголовки для обхода 403 ошибки
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        try:
            # Используем http2=True для имитации реального браузера
            async with httpx.AsyncClient(http2=True, headers=headers, timeout=30.0, follow_redirects=True) as client:
                r = await client.get(Config.url)
                logger.info(f"Статус OLX: {r.status_code}")
                
                if r.status_code != 200: return None
                
                soup = BeautifulSoup(r.text, "lxml")
                ads = []
                script = soup.find("script", id="__NEXT_DATA__")
                if script:
                    data = json.loads(script.string)
                    # Ищем товары в разных частях JSON (OLX часто меняет их местами)
                    items = data.get("props", {}).get("pageProps", {}).get("data", {}).get("items", [])
                    if not items:
                        items = data.get("props", {}).get("pageProps", {}).get("listing", {}).get("listing", {}).get("ads", [])
                    
                    for item in items:
                        url = item.get("url")
                        if url:
                            ads.append({
                                "url": url.split('#')[0],
                                "title": item.get("title", "iPhone 13 Pro"),
                                "price": item.get("price", {}).get("displayValue", "?")
                            })
                return ads
        except Exception as e:
            logger.error(f"Ошибка парсинга: {e}")
            return None

bot = Bot(token=TOKEN)
dp = Dispatcher()
parser = OLXParser()

async def monitoring():
    await asyncio.sleep(10) # Пауза для закрытия старых копий
    while True:
        if Config.is_running:
            ads = await parser.fetch()
            if ads:
                if not parser.seen_ads:
                    parser.seen_ads.update([a['url'] for a in ads])
                    logger.info(f"База создана: {len(ads)} шт.")
                else:
                    for ad in ads:
                        if ad['url'] not in parser.seen_ads:
                            parser.seen_ads.add(ad['url'])
                            msg = f"🆕 **НОВОЕ!**\n\n📱 {ad['title']}\n💰 Цена: {ad['price']}\n🔗 [Открыть]({ad['url']})"
                            await bot.send_message(ADMIN_ID, msg, parse_mode="Markdown")
            await asyncio.sleep(Config.interval + random.randint(10, 50))
        else:
            await asyncio.sleep(10)

async def start_app():
    # Эта команда убивает конфликт (красные логи)
    await bot.delete_webhook(drop_pending_updates=True)
    threading.Thread(target=run_flask, daemon=True).start()
    await asyncio.gather(dp.start_polling(bot), monitoring())

if __name__ == "__main__":
    asyncio.run(start_app())
