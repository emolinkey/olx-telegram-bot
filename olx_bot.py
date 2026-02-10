import asyncio, logging, sqlite3, os, httpx
from datetime import datetime
from bs4 import BeautifulSoup
from aiogram import Bot

# === КОНФИГ (Эти данные покупатель меняет под себя) ===
TOKEN = "8346602599:AAHzl__YrzL5--4a7enN02PlXLkjRxeD-z8"
CHAT_ID = 908015235
OLX_URL = "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/q-pami%C4%99%C4%87-ram-ddr4-8gb/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=100&search%5Bfilter_float_price:to%5D=300"

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
     # Вот этот блок ты полностью обновляешь
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/",
            "Cache-Control": "max-age=0",
            "Sec-Ch-Ua": '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }
        # И строку запуска клиента тоже меняем (ставим False и добавляем headers)
    async def fetch_ads(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/"
        }
        
        # Данные твоего прокси от Webshare
        proxy_url = "http://nyntgqyu:2c5wo0xukywv@31.59.20.176:6754/"

        try:
            async with httpx.AsyncClient(
                proxies=proxy_url, 
                headers=headers, 
                timeout=30.0, 
                http2=False,
                follow_redirects=True
            ) as client:
                r = await client.get(OLX_URL)
                if r.status_code != 200:
                    print(f"Ошибка {r.status_code} через прокси")
                    return []
                
                soup = BeautifulSoup(r.text, "html.parser")
                # Ищем все блоки объявлений
                ads = soup.find_all("div", {"data-cy": "l-card"})
                
                res = []
                for ad in ads:
                    link_tag = ad.find("a")
                    if not link_tag:
                        continue
                    
                    href = link_tag.get("href")
                    if not href:
                        continue
                        
                    # Формируем полную ссылку
                    full_url = href if href.startswith("http") else "https://www.olx.pl" + href
                    # Убираем параметры отслеживания для чистоты ссылки
                    clean_url = full_url.split("#")[0].split("?")[0]
                    res.append(clean_url)
                
                return res
        except Exception as e:
            print(f"Ошибка при запросе: {e}")
            return []

    async def run(self):
        try:
            await self.bot.send_message(CHAT_ID, "🔎 Бот запущен и начал поиск...")
        except Exception as e:
            print(f"Ошибка отправки: {e}")
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

import threading
from flask import Flask

app = Flask('')

@app.route('/')
def home():
    return "I am alive"

def run_flask():
    app.run(host='0.0.0.0', port=10000)

# Запускаем "сайт" в отдельном потоке, чтобы он не мешал боту
if __name__ == "__main__":
    t = threading.Thread(target=run_flask)
    t.start()
    
    # Тут запускается твой основной бот
    import asyncio
    monitor = OLXProMonitor()
    asyncio.run(monitor.run())








