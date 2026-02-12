import os
import asyncio
import httpx
from bs4 import BeautifulSoup
from aiogram import Bot
import threading
from flask import Flask
from datetime import datetime
import random

# --- СЕРВЕР ---
app = Flask('')
@app.route('/')
def home():
    return "ONLINE"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- КОНФИГ ---
TOKEN = "8346602599:AAHzl__YrzL5--4a7enN02PlXLkjRxeD-z8"
CHAT_ID = "908015235"
OLX_URL = "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/q-pami%C4%99%C4%87-ram-ddr4-8gb/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=100&search%5Bfilter_float_price:to%5D=300"
PROXY = "http://nyntgqyu:2c5wo0xukywv@31.59.20.176:6754/"

class OLXProMonitor:
    def __init__(self):
        self.bot = Bot(token=TOKEN)
        self.seen_ads = set()

    async def fetch_ads(self):
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"}
        try:
            # Сначала пробуем с прокси
            async with httpx.AsyncClient(proxies=PROXY, headers=headers, timeout=15.0) as client:
                r = await client.get(OLX_URL)
                print(f"Попытка парсинга... Статус: {r.status_code}")
                
                if r.status_code != 200:
                    return []

                soup = BeautifulSoup(r.text, "html.parser")
                found = []
                # Более агрессивный поиск ссылок
                for a in soup.find_all("a", href=True):
                    if '/d/oferta/' in a['href']:
                        url = a['href'] if a['href'].startswith("http") else "https://www.olx.pl" + a['href']
                        clean = url.split("#")[0].split("?")[0]
                        if clean not in found: found.append(clean)
                return found
        except Exception as e:
            print(f"Ошибка запроса: {e}")
            return []

    async def run(self):
        print("!!! БОТ ЗАПУСКАЕТСЯ !!!")
        # Прямая проверка связи с тобой
        try:
            await self.bot.send_message(CHAT_ID, "🚀 Бот на связи! Начинаю поиск...")
        except Exception as e:
            print(f"КРИТИЧЕСКАЯ ОШИБКА ТЕЛЕГРАМ: {e}")

        while True:
            ads = await self.fetch_ads()
            print(f"Найдено сейчас: {len(ads)}")
            
            for ad in ads:
                if ad not in self.seen_ads:
                    if len(self.seen_ads) > 0: # Только для новых
                        await self.bot.send_message(CHAT_ID, f"🔥 НОВОЕ: {ad}")
                    self.seen_ads.add(ad)
            
            await asyncio.sleep(120) # Проверка каждые 2 минуты

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(OLXProMonitor().run())
