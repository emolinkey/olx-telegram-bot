import os, asyncio, httpx, random, sys, json, threading, logging
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.exceptions import TelegramNetworkError
from flask import Flask

# --- ДАННЫЕ ВЛАДЕЛЬЦА ---
TOKEN = "8346602599:AAGCJ4Lz0hLuwTyF4FSU21Q6Jh6as9ggtKg"
ADMIN_ID = 908015235

# --- ГЛОБАЛЬНЫЕ НАСТРОЙКИ ---
class Config:
    url = "https://www.olx.pl/elektronika/telefony/q-iphone-13-pro/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=500&search%5Bfilter_float_price:to%5D=1500"
    interval = 300 
    is_running = True

# Логирование для отладки
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OLX_Sniper")

# --- СЕРВЕР ДЛЯ RENDER ---
app = Flask('')
@app.route('/')
def home(): return "Бот активен и работает"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- ДВИЖОК ОБХОДА БЛОКИРОВОК ---
class OLXParser:
    def __init__(self):
        self.seen_ads = set()
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ]

    async def get_ads(self):
        headers = {
            "User-Agent": random.choice(self.user_agents),
            "Accept-Language": "pl-PL,pl;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.olx.pl/"
        }
        try:
            async with httpx.AsyncClient(http2=True, headers=headers, timeout=25.0, follow_redirects=True) as client:
                r = await client.get(Config.url)
                if r.status_code != 200:
                    logger.error(f"OLX ответил статусом: {r.status_code}")
                    return None
                
                soup = BeautifulSoup(r.text, "lxml")
                ads = []
                
                # Метод 1: Через JSON (самый надежный)
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
            logger.error(f"Ошибка при запросе: {e}")
            return None

# --- ЛОГИКА БОТА ---
bot = Bot(token=TOKEN)
dp = Dispatcher()
parser = OLXParser()

async def monitoring_loop():
    await asyncio.sleep(10) # Даем Render время закрыть старые копии
    logger.info("Цикл мониторинга запущен")
    
    while True:
        if Config.is_running:
            ads = await parser.get_ads()
            if ads:
                if not parser.seen_ads:
                    parser.seen_ads.update([a['url'] for a in ads])
                    logger.info(f"База инициализирована: {len(ads)} объявлений")
                else:
                    for ad in ads:
                        if ad['url'] not in parser.seen_ads:
                            parser.seen_ads.add(ad['url'])
                            text = f"🆕 **НОВОЕ ОБЪЯВЛЕНИЕ!**\n\n📱 {ad['title']}\n💰 Цена: {ad['price']}\n\n🔗 [ОТКРЫТЬ НА OLX]({ad['url']})"
                            try:
                                await bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
                            except Exception as e:
                                logger.error(f"Не смог отправить сообщение: {e}")
            
            await asyncio.sleep(Config.interval + random.randint(10, 60))
        else:
            await asyncio.sleep(30)

# Команды управления
@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    await m.answer("🤖 **OLX Sniper Pro готов к работе.**\n\n/status - проверить работу\n/toggle - пауза/старт")

@dp.message(Command("status"))
async def cmd_status(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    status = "✅ Работает" if Config.is_running else "⏸ На паузе"
    await m.answer(f"Статус: {status}\nОбъявлений в базе: {len(parser.seen_ads)}\nСсылка: `{Config.url}`", parse_mode="Markdown")

@dp.message(Command("toggle"))
async def cmd_toggle(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    Config.is_running = not Config.is_running
    await m.answer(f"Мониторинг: {'ВКЛ' if Config.is_running else 'ВЫКЛ'}")

async def main():
    # Удаляем вебхуки, чтобы не было конфликта (Conflict Error)
    await bot.delete_webhook(drop_pending_updates=True)
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Запуск мониторинга и команд одновременно
    await asyncio.gather(dp.start_polling(bot), monitoring_loop())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
