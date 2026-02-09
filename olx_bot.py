import asyncio, logging, sqlite3, os, httpx
from datetime import datetime
from bs4 import BeautifulSoup
from aiogram import Bot

# === КОНФИГ (Эти данные покупатель меняет под себя) ===
TOKEN = "8346602599:AAHzl__YrzL5--4a7enN02PlXLkjRxeD-z8"
CHAT_ID = 908015235
OLX_URL = "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/q-pami%C4%99%C4%87-ram-ddr4-8gb/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=100&search%5Bfilter_float_price:to%5D=250"

CHECK_INTERVAL = 60
HEARTBEAT_INTERVAL = 3600
# Путь к базе данных (автоматически определяется сервером)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bot_database.db")
# ======================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.cursor = self.conn.cursor()
        self.cursor.execute('CREATE TABLE IF NOT EXISTS seen_links (link TEXT PRIMARY KEY)')
        self.conn.commit()

    def is_new_and_add(self, link):
        self.cursor.execute('SELECT 1 FROM seen_links WHERE link = ?', (link,))
        if not self.cursor.fetchone():
            self.cursor.execute('INSERT INTO seen_links VALUES (?)', (link,))
            self.conn.commit()
            return True
        return False

    def count(self):
        return self.cursor.execute('SELECT COUNT(*) FROM seen_links').fetchone()[0]

class OLXProMonitor:
    def __init__(self):
        self.bot, self.db = Bot(token=TOKEN), Database()
        self.start_time = datetime.now()
        self.last_heartbeat = datetime.now()
        self.is_first_run = self.db.count() == 0

    async def fetch_ads(self):
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"}
        async with httpx.AsyncClient(timeout=30.0, http2=True) as client:
            try:
                r = await client.get(OLX_URL, headers=headers)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                ads = []
                for card in soup.select('div[data-cy="l-card"]'):
                    l = card.find("a")
                    if l and "promoted" not in l.get("href", ""):
                        h = l.get("href")
                        link = "https://www.olx.pl" + h.split('?')[0] if h.startswith('/') else h.split('?')[0]
                        ads.append({
                            "link": link,
                            "price": card.find("p", {"data-testid": "ad-price"}).get_text(strip=True) if card.find("p", {"data-testid": "ad-price"}) else "N/A",
                            "img": card.find("img").get("src") if card.find("img") else None
                        })
                return ads
            except Exception as e:
                logger.error(f"Ошибка запроса: {e}"); return []

    async def run(self):
        try:
            await self.bot.send_message(CHAT_ID, "✅ <b>Бот запущен в облаке!</b>", parse_mode="HTML")
        except: pass

        while True:
            if (datetime.now() - self.last_heartbeat).total_seconds() >= HEARTBEAT_INTERVAL:
                uptime = str(datetime.now() - self.start_time).split('.')[0]
                try: await self.bot.send_message(CHAT_ID, f"🛡 <b>Heartbeat</b>\nUptime: <code>{uptime}</code>", parse_mode="HTML")
                except: pass
                self.last_heartbeat = datetime.now()

            ads = await self.fetch_ads()
            if self.is_first_run:
                for ad in ads: self.db.is_new_and_add(ad["link"])
                self.is_first_run = False
            else:
                for ad in reversed(ads):
                    if self.db.is_new_and_add(ad["link"]):
                        cap = f"🆕 <b>НОВОЕ ОБЪЯВЛЕНИЕ</b>\n\n💰 Цена: <b>{ad['price']}</b>\n🔗 <a href='{ad['link']}'>Открыть</a>"
                        try:
                            if ad["img"]: await self.bot.send_photo(CHAT_ID, ad["img"], caption=cap, parse_mode="HTML")
                            else: await self.bot.send_message(CHAT_ID, cap, parse_mode="HTML")
                        except: pass
                        await asyncio.sleep(2)
            await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(OLXProMonitor().run())