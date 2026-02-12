import os
import asyncio
import httpx
from bs4 import BeautifulSoup
from aiogram import Bot
import threading
from flask import Flask
from datetime import datetime
import random

# --- НАСТРОЙКИ МИНИ-СЕРВЕРА ---
app = Flask('')
@app.route('/')
def home():
    return f"OLX Sniper Active. System time: {datetime.now().strftime('%H:%M:%S')}"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- КОНФИГ ---
TOKEN = "8346602599:AAHzl__YrzL5--4a7enN02PlXLkjRxeD-z8"
CHAT_ID = "908015235"
OLX_URL = "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/q-pami%C4%99%C4%87-ram-ddr4-8gb/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=100&search%5Bfilter_float_price:to%5D=300"
PROXY = "http://nyntgqyu:2c5wo0xukywv@31.59.20.176:6754/"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
]

class OLXProMonitor:
    def __init__(self):
        self.bot = Bot(token=TOKEN)
        self.seen_ads = set()
        self.first_run = True
        self.last_log_time = datetime.now()

    async def fetch_ads(self):
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/",
            "Cache-Control": "no-cache"
        }
        
        try:
            async with httpx.AsyncClient(proxies=PROXY, headers=headers, timeout=30.0, follow_redirects=True) as client:
                r = await client.get(OLX_URL)
                if r.status_code != 200:
                    print(f"(!) Ошибка OLX: {r.status_code}")
                    return []

                soup = BeautifulSoup(r.text, "html.parser")
                found_urls = []
                
                # Ищем по атрибуту, который OLX использует для заголовков объявлений
                links = soup.find_all("a", href=True)
                for a in links:
                    href = a['href']
                    if '/d/oferta/' in href:
                        # Формируем чистую ссылку
                        full_url = href if href.startswith("http") else "https://www.olx.pl" + href
                        clean_url = full_url.split("#")[0].split("?")[0].rstrip('/')
                        if clean_url not in found_urls:
                            found_urls.append(clean_url)
                
                return found_urls
        except Exception as e:
            print(f"(!) Ошибка сети: {e}")
            return []

    async def run(self):
        print("Бот запущен. Начинаю мониторинг...")
        
        while True:
            ads = await self.fetch_ads()
            
            # Отправляем "отчет о жизни" раз в 2 часа, чтобы ты не волновался
            if (datetime.now() - self.last_log_time).total_seconds() > 7200:
                await self.bot.send_message(CHAT_ID, f"📡 Сигнал стабильный. Проверил OLX, вижу {len(ads)} объявлений. Жду новые...")
                self.last_log_time = datetime.now()

            new_ads_found = []
            for ad in ads:
                if ad not in self.seen_ads:
                    self.seen_ads.add(ad)
                    if not self.first_run:
                        new_ads_found.append(ad)
            
            # Отправляем только по одному сообщению, чтобы не спамить
            for new_ad in new_ads_found:
                try:
                    await self.bot.send_message(CHAT_ID, f"🔥 **НАШЕЛ НОВОЕ!**\n\n🔗 {new_ad}")
                    await asyncio.sleep(1) # Задержка перед следующим сообщением
                except Exception as e:
                    print(f"Ошибка отправки: {e}")

            if self.first_run:
                print(f"База обновлена. Вижу {len(self.seen_ads)} активных товаров.")
                self.first_run = False
            
            # Проверка каждые 3 минуты (180 сек) для большей скорости
            await asyncio.sleep(180)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    monitor = OLXProMonitor()
    asyncio.run(monitor.run())
