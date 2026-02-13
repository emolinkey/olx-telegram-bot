import os
import asyncio
import httpx
from bs4 import BeautifulSoup
from aiogram import Bot
from flask import Flask
import threading
import random

# --- КОНФИГ ---
TOKEN = "8346602599:AAFj8lQ_cfMwBXIfOSl7SbA9J7qixcpaO68"
CHAT_ID = "908015235"
OLX_URL = "https://www.olx.pl/oferty/q-pami%C4%99%C4%87-ram-ddr4-8gb/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=100&search%5Bfilter_float_price:to%5D=250"
PROXY = "http://nyntgqyu:2c5wo0xukywv@31.59.20.176:6754/"

# --- ВЕБ-СЕРВЕР ---
app = Flask('')
@app.route('/')
def home(): return "SYSTEM ONLINE"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- МОНИТОР ---
class OLXProMonitor:
    def __init__(self):
        self.bot = Bot(token=TOKEN)
        self.seen_ads = set()
        self.client = None

    async def init_client(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        self.client = httpx.AsyncClient(proxies=PROXY, headers=headers, timeout=30.0, follow_redirects=True)

    async def fetch_ads(self):
        try:
            # Сначала "прогреваем" сессию, заходя на главную (если это первый раз)
            if not self.client: await self.init_client()
            
            r = await self.client.get(OLX_URL)
            print(f"Проверка OLX... Статус: {r.status_code}")
            
            if r.status_code == 403:
                print("ОЙ! OLX нас заблокировал (403). Пробую пересоздать сессию...")
                await self.init_client()
                return []

            soup = BeautifulSoup(r.text, "html.parser")
            found = []
            
            # Ищем ссылки на объявления по всем возможным признакам
            for a in soup.find_all("a", href=True):
                href = a['href']
                if '/d/oferta/' in href:
                    url = href if href.startswith("http") else "https://www.olx.pl" + href
                    clean = url.split("#")[0].split("?")[0].rstrip('/')
                    if clean not in found: found.append(clean)
            
            return found
        except Exception as e:
            print(f"Ошибка парсинга: {e}")
            return []

    async def run(self):
        threading.Thread(target=run_flask, daemon=True).start()
        print("!!! БОТ СТАРТОВАЛ !!!")
        
        # Сразу скажем тебе в ТГ, что мы начали
        await self.bot.send_message(CHAT_ID, "🔎 Начинаю активную охоту на RAM DDR4...")

        while True:
            ads = await self.fetch_ads()
            print(f"Найдено объявлений: {len(ads)}")
            
            if len(ads) > 0:
                # При первом запуске просто запоминаем, при следующих - присылаем новые
                if not self.seen_ads:
                    self.seen_ads.update(ads)
                    print(f"База инициализирована: {len(ads)} шт.")
                    # Чтобы ты видел, что бот реально что-то нашел:
                    await self.bot.send_message(CHAT_ID, f"✅ Вижу текущие объявления ({len(ads)} шт). Жду появления новых!")
                else:
                    for ad in ads:
                        if ad not in self.seen_ads:
                            self.seen_ads.add(ad)
                            await self.bot.send_message(CHAT_ID, f"🆕 **НАШЕЛ НОВОЕ!**\n\n{ad}")
            
            # Ждем 3-4 минуты (случайно, чтобы не спалиться)
            await asyncio.sleep(random.randint(180, 240))

if __name__ == "__main__":
    asyncio.run(OLXProMonitor().run())

