import os, asyncio, httpx, random, sys, json, threading, logging
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from flask import Flask

# --- НАСТРОЙКИ (Клиент сможет менять их сам через команды) ---
TOKEN = "8346602599:AAGCJ4Lz0hLuwTyF4FSU21Q6Jh6as9ggtKg"
ADMIN_ID = 908015235 # Твой ID

class Config:
    url = "https://www.olx.pl/elektronika/telefony/q-iphone-13-pro/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=500&search%5Bfilter_float_price:to%5D=1500"
    interval = 300 # секунд (5 минут)
    is_running = True

# --- ЛОГИРОВАНИЕ ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OLX_Sniper")

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
app = Flask('')
@app.route('/')
def home(): return "<h1>OLX Sniper Pro is Active</h1>"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- ОСНОВНОЙ ДВИЖОК ПАРСИНГА ---
class OLXSniper:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.seen_ads = set()
        self.client = None
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ]

    async def get_client(self):
        if self.client: await self.client.aclose()
        self.client = httpx.AsyncClient(
            http2=True,
            headers={
                "User-Agent": random.choice(self.user_agents),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate, br",
            },
            timeout=20.0,
            follow_redirects=True
        )
        return self.client

    async def scrape(self):
        try:
            client = await self.get_client()
            response = await client.get(Config.url)
            
            if response.status_code == 403:
                logger.warning("🚫 Доступ заблокирован (403). Меняю тактику...")
                return "BAN"
            
            if response.status_code != 200: return []

            soup = BeautifulSoup(response.text, "lxml")
            ads = []

            # 1. Попытка через JSON (самый быстрый и точный метод)
            script = soup.find("script", id="__NEXT_DATA__")
            if script:
                data = json.loads(script.string)
                items = data.get("props", {}).get("pageProps", {}).get("data", {}).get("items", [])
                for item in items:
                    if item.get("url"):
                        ads.append({
                            "url": item["url"].split('#')[0],
                            "title": item.get("title", "Без названия"),
                            "price": item.get("price", {}).get("displayValue", "Цена не указана")
                        })
            
            # 2. Запасной вариант (парсинг HTML)
            if not ads:
                for card in soup.select('div[data-cy="l-card"]'):
                    link = card.select_one('a[href*="/d/oferta/"]')
                    if link:
                        ads.append({
                            "url": "https://www.olx.pl" + link['href'].split('#')[0] if not link['href'].startswith('http') else link['href'].split('#')[0],
                            "title": card.select_one('h6').text if card.select_one('h6') else "OLX Объявление",
                            "price": card.select_one('p[data-testid="ad-price"]').text if card.select_one('p[data-testid="ad-price"]') else "---"
                        })
            return ads
        except Exception as e:
            logger.error(f"Ошибка парсинга: {e}")
            return []

async def main_loop(bot: Bot, sniper: OLXSniper):
    await bot.send_message(ADMIN_ID, "✅ **Система OLX Sniper Pro запущена!**\nНачинаю мониторинг...")
    
    while True:
        if Config.is_running:
            result = await sniper.scrape()
            
            if result == "BAN":
                await bot.send_message(ADMIN_ID, "⚠️ **Внимание:** OLX временно ограничил доступ. Сплю 15 минут для обхода защиты.")
                await asyncio.sleep(900)
                continue

            if result:
                # Если это первый запуск — просто запоминаем базу
                if not sniper.seen_ads:
                    sniper.seen_ads.update([a['url'] for a in result])
                    await bot.send_message(ADMIN_ID, f"📊 База собрана: {len(result)} объявлений.")
                else:
                    for ad in result:
                        if ad['url'] not in sniper.seen_ads:
                            sniper.seen_ads.add(ad['url'])
                            text = f"🆕 **НАЙДЕНО НОВОЕ!**\n\n🔹 **{ad['title']}**\n💰 Цена: {ad['price']}\n\n🔗 [ОТКРЫТЬ ОБЪЯВЛЕНИЕ]({ad['url']})"
                            await bot.send_message(ADMIN_ID, text, parse_mode="Markdown")

            # Рандомная задержка для имитации человека
            await asyncio.sleep(Config.interval + random.randint(-20, 40))
        else:
            await asyncio.sleep(10)

# --- ТЕЛЕГРАМ КОМАНДЫ (Интерфейс для клиента) ---
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    menu = (
        "🎮 **Управление OLX Sniper Pro**\n\n"
        "🔗 `/url ССЫЛКА` — изменить ссылку поиска\n"
        "⏲ `/time МИНУТЫ` — интервал проверки (мин)\n"
        "⏯ `/toggle` — запуск/пауза бота\n"
        "📊 `/status` — текущие настройки"
    )
    await message.answer(menu, parse_mode="Markdown")

@dp.message(Command("url"))
async def cmd_url(message: types.Message):
    new_url = message.text.replace("/url ", "").strip()
    if "olx.pl" in new_url:
        Config.url = new_url
        await message.answer("✅ Ссылка обновлена!")
    else:
        await message.answer("❌ Ошибка: Вставьте корректную ссылку на OLX.pl")

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    state = "🟢 Работает" if Config.is_running else "🔴 На паузе"
    await message.answer(f"ℹ️ **Статус:** {state}\n⏲ **Интервал:** {Config.interval//60} мин\n🔗 **URL:** {Config.url}")

@dp.message(Command("toggle"))
async def cmd_toggle(message: types.Message):
    Config.is_running = not Config.is_running
    await message.answer(f"♻️ Бот {'запущен' if Config.is_running else 'остановлен'}")

async def run_bot():
    sniper = OLXSniper(bot)
    # Запускаем мониторинг в фоне
    asyncio.create_task(main_loop(bot, sniper))
    # Запускаем обработку команд
    await dp.start_polling(bot)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(run_bot())
