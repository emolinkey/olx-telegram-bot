import os
import asyncio
import httpx
from bs4 import BeautifulSoup
from aiogram import Bot
import threading
from flask import Flask

# --- МИНИ-СЕРВЕР ДЛЯ RENDER ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    # Render дает порт в переменной окружения PORT, по умолчанию 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
# ------------------------------

TOKEN = "8346602599:AAHzl__YrzL5--4a7enN02PlXLkjRxeD-z8"
CHAT_ID = "908015235"
OLX_URL = "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/q-pami%C4%99%C4%87-ram-ddr4-8gb/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=100&search%5Bfilter_float_price:to%5D=300" # Подставь сюда свою ссылку!

class OLXProMonitor:
    def __init__(self):
        self.bot = Bot(token=TOKEN)
        self.seen_ads = set()

    async def fetch_ads(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        proxy_url = "http://nyntgqyu:2c5wo0xukywv@31.59.20.176:6754/"
        
        try:
            async with httpx.AsyncClient(proxies=proxy_url, headers=headers, timeout=30.0) as client:
                r = await client.get(OLX_URL)
                if r.status_code != 200: return []
                soup = BeautifulSoup(r.text, "html.parser")
                ads = soup.find_all("div", {"data-cy": "l-card"})
                res = []
                for ad in ads:
                    link = ad.find("a")
                    if link:
                        href = link.get("href")
                        full_url = href if href.startswith("http") else "https://www.olx.pl" + href
                        res.append(full_url.split("#")[0].split("?")[0])
                return res
        except:
            return []

    async def run(self):
        await self.bot.send_message(CHAT_ID, "🚀 Бот запущен на Render и готов к работе!")
        while True:
            ads = await self.fetch_ads()
            for ad in ads:
                if ad not in self.seen_ads:
                    if self.seen_ads: # Не спамим при первом запуске
                        await self.bot.send_message(CHAT_ID, f"✨ Новое объявление!\n{ad}")
                    self.seen_ads.add(ad)
            await asyncio.sleep(300) # Проверка каждые 5 минут

if __name__ == "__main__":
    # Запускаем Flask в отдельном потоке
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Запускаем бота
    monitor = OLXProMonitor()
    asyncio.run(monitor.run())








