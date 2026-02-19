import os, asyncio, httpx, random, sys, json, threading, logging
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from flask import Flask

# --- ДАННЫЕ ---
TOKEN = "8346602599:AAEauikfQJCI_cyZK5hiv3W0StWk9OMWPK0"
ADMIN_ID = 908015235

class Config:
    url = "https://www.olx.pl/elektronika/telefony/q-iphone-13-pro/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=500&search%5Bfilter_float_price:to%5D=1500"
    interval = 300
    is_running = True

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OLX_Sniper")

# --- СЕРВЕР ---
app = Flask('')
@app.route('/')
def home(): return "Бот в сети"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- ПАРСЕР ---
class OLXParser:
    def __init__(self):
        self.seen_ads = set()

    async def fetch(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "pl-PL,pl;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive"
        }
        try:
            async with httpx.AsyncClient(http2=True, headers=headers, timeout=25.0) as client:
                r = await client.get(Config.url)
                logger.info(f"Статус OLX: {r.status_code}")
                if r.status_code != 200: return None
                
                soup = BeautifulSoup(r.text, "lxml")
                script = soup.find("script", id="__NEXT_DATA__")
                if not script: return None
                
                data = json.loads(script.string)
                items = data.get("props", {}).get("pageProps", {}).get("data", {}).get("items", [])
                if not items:
                    items = data.get("props", {}).get("pageProps", {}).get("listing", {}).get("listing", {}).get("ads", [])
                
                ads = []
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
            logger.error(f"Ошибка парсера: {e}")
            return None

# --- ЗАПУСК ---
bot = Bot(token=TOKEN)
dp = Dispatcher()
parser = OLXParser()

async def monitoring():
    await asyncio.sleep(15) # Ждем, пока старые копии бота закроются
    logger.info("Цикл мониторинга запущен")
    while True:
        if Config.is_running:
            ads = await parser.fetch()
            if ads:
                if not parser.seen_ads:
                    parser.seen_ads.update([a['url'] for a in ads])
                    logger.info(f"База готова: {len(ads)} шт.")
                else:
                    for ad in ads:
                        if ad['url'] not in parser.seen_ads:
                            parser.seen_ads.add(ad['url'])
                            msg = f"🆕 **НАЙДЕНО!**\n\n📱 {ad['title']}\n💰 {ad['price']}\n🔗 [Открыть]({ad['url']})"
                            await bot.send_message(ADMIN_ID, msg, parse_mode="Markdown")
            await asyncio.sleep(Config.interval + random.randint(10, 30))
        else:
            await asyncio.sleep(10)

@dp.message(Command("start"))
async def start(m: types.Message):
    if m.from_user.id == ADMIN_ID:
        await m.answer("✅ Бот запущен!")

async def start_app():
    # ГЛАВНОЕ: удаляем старые запросы для устранения ConflictError
    await bot.delete_webhook(drop_pending_updates=True)
    threading.Thread(target=run_flask, daemon=True).start()
    await asyncio.gather(dp.start_polling(bot, skip_updates=True), monitoring())

if __name__ == "__main__":
    asyncio.run(start_app())
