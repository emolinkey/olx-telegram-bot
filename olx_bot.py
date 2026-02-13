import os
import asyncio
import httpx
from bs4 import BeautifulSoup
from aiogram import Bot
from flask import Flask
import threading
import random
import sys

# --- КОНФИГ ---
TOKEN = "8346602599:AAFj8lQ_cfMwBXIfOSl7SbA9J7qixcpaO68"
CHAT_ID = "908015235"
# Чистая ссылка — работает стабильнее всего
OLX_URL = "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/q-pami%C4%99%C4%87-ram-ddr4-8gb/?search%5Bfilter_float_price%3Afrom%5D=100&search%5Bfilter_float_price%3Ato%5D=250&search%5Border%5D=created_at%3Adesc"

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
        # Максимально "человеческие" заголовки
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/",
            "Upgrade-Insecure-Requests": "1"
        }
        # Работаем БЕЗ прокси (через европейский IP Render-а)
        self.client = httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True)

    async def fetch_ads(self):
        try:
            if not self.client: await self.init_client()
            r = await self.client.get(OLX_URL)
            
            # Если OLX все же выдал 403, пробуем пересоздать клиент
            if r.status_code == 403:
                print("Статус 403: OLX временно ограничил доступ. Ждем...")
                await self.client.aclose()
                self.client = None
                return []

            print(f"Проверка OLX... Статус: {r.status_code}")
            
            if r.status_code != 200: return []

            soup = BeautifulSoup(r.text, "html.parser")
            found = []
            
            # Ищем ссылки в карточках товаров (data-cy="listing-ad-title" - самый точный селектор)
            for a in soup.find_all("a", href=True):
                href = a['href']
                if '/d/oferta/' in href:
                    # Убираем мусор из ссылки
                    url = href if href.startswith("http") else "https://www.olx.pl" + href
                    clean = url.split("#")[0].split("?")[0].rstrip('/')
                    if clean not in found:
                        found.append(clean)
            
            return found
        except Exception as e:
            print(f"Ошибка парсинга: {e}")
            return []

    async def run(self):
        threading.Thread(target=run_flask, daemon=True).start()
        print("!!! МОНИТОРИНГ ЗАПУЩЕН !!!")
        sys.stdout.flush()
        
        try:
            await self.bot.send_message(CHAT_ID, "🚀 Охота началась! Ищу DDR4 8GB (100-250 PLN)...")
        except Exception as e:
            print(f"ТГ Ошибка: {e}")

        while True:
            ads = await self.fetch_ads()
            print(f"Результат: {len(ads)} объявлений.")
            sys.stdout.flush()
            
            if ads:
                # Если это первый запуск — просто запоминаем базу
                if not self.seen_ads:
                    self.seen_ads.update(ads)
                    count = len(ads)
                    await self.bot.send_message(CHAT_ID, f"✅ База обновлена. Вижу {count} активных товаров. Жду новые!")
                else:
                    # Ищем новинки
                    for ad in ads:
                        if ad not in self.seen_ads:
                            self.seen_ads.add(ad)
                            print(f"НОВОЕ: {ad}")
                            await self.bot.send_message(CHAT_ID, f"🆕 **НАШЕЛ НОВОЕ!**\n\n{ad}")
            
            # Интервал проверки от 3 до 5 минут (рандомно, чтобы не забанили)
            await asyncio.sleep(random.randint(180, 300))

if __name__ == "__main__":
    monitor = OLXProMonitor()
    asyncio.run(monitor.run())
