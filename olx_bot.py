import os, asyncio, httpx, random, sys, json, threading, logging
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from flask import Flask

# --- КОНФИГУРАЦИЯ ---
TOKEN = "8346602599:AAEauikfQJCI_cyZK5hiv3W0StWk9OMWPK0"
ADMIN_ID = 908015235

class Config:
    url = "https://www.olx.pl/elektronika/telefony/q-iphone-13-pro/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=500&search%5Bfilter_float_price:to%5D=1500"
    interval = 300
    is_running = True

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OLX_Sniper_Pro")

# --- ВЕБ-СЕРВЕР ---
app = Flask('')
@app.route('/')
def home(): return "<h1>OLX Sniper Pro: Online</h1>"

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
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "pl-PL,pl;q=0.9"
        }
        try:
            async with httpx.AsyncClient(http2=True, headers=headers, timeout=20.0) as client:
                r = await client.get(Config.url)
                if r.status_code != 200: return None
                
                soup = BeautifulSoup(r.text, "lxml")
                ads = []
                script = soup.find("script", id="__NEXT_DATA__")
                if script:
                    data = json.loads(script.string)
                    items = data.get("props", {}).get("pageProps", {}).get("data", {}).get("items", [])
                    for item in items:
                        if item.get("url"):
                            ads.append({
                                "url": item["url"].split('#')[0],
                                "title": item.get("title", "iPhone"),
                                "price": item.get("price", {}).get("displayValue", "?")
                            })
                return ads
        except Exception as e:
            logger.error(f"Ошибка сети: {e}")
            return None

# --- ГЛАВНАЯ ЛОГИКА ---
bot = Bot(token=TOKEN)
dp = Dispatcher()
parser = OLXParser()

async def monitoring():
    # Ждем 5 секунд, чтобы Render завершил старые процессы
    await asyncio.sleep(5)
    logger.info("Мониторинг запущен")
    
    while True:
        if Config.is_running:
            ads = await parser.fetch()
            if ads:
                if not parser.seen_ads:
                    parser.seen_ads.update([a['url'] for a in ads])
                    logger.info(f"База создана: {len(ads)} объявлений")
                else:
                    for ad in ads:
                        if ad['url'] not in parser.seen_ads:
                            parser.seen_ads.add(ad['url'])
                            msg = f"🔥 **НАЙДЕНО НОВОЕ ПРЕДЛОЖЕНИЕ!**\n\n📱 **{ad['title']}**\n💰 Цена: `{ad['price']}`\n\n🔗 [ОТКРЫТЬ НА OLX]({ad['url']})"
                            await bot.send_message(ADMIN_ID, msg, parse_mode="Markdown")
            
            await asyncio.sleep(Config.interval + random.randint(5, 30))
        else:
            await asyncio.sleep(10)

@dp.message(Command("start"))
async def start(m: types.Message):
    if m.from_user.id == ADMIN_ID:
        await m.answer("✅ **OLX Sniper Pro активен!**\n\nИспользуйте `/status` для проверки настроек.")

@dp.message(Command("status"))
async def status(m: types.Message):
    if m.from_user.id == ADMIN_ID:
        mode = "🟢 Активен" if Config.is_running else "🔴 На паузе"
        await m.answer(f"📊 **Текущий статус:**\n\nСостояние: {mode}\nВ базе: {len(parser.seen_ads)} объявлений\nИнтервал: {Config.interval} сек.")

async def start_app():
    # КЛЮЧЕВОЙ МОМЕНТ: Удаляем старые подключения, чтобы не было красных логов
    await bot.delete_webhook(drop_pending_updates=True)
    threading.Thread(target=run_flask, daemon=True).start()
    await asyncio.gather(dp.start_polling(bot), monitoring())

if __name__ == "__main__":
    asyncio.run(start_app())
