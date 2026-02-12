import os
import asyncio
import httpx
from bs4 import BeautifulSoup
from aiogram import Bot
from flask import Flask
import threading

# --- КОНФИГ ---
TOKEN = "8346602599:AAHzl__YrzL5--4a7enN02PlXLkjRxeD-z8"
CHAT_ID = "908015235"
OLX_URL = "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/q-pami%C4%99%C4%87-ram-ddr4-8gb/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=100&search%5Bfilter_float_price:to%5D=300"
PROXY = "http://nyntgqyu:2c5wo0xukywv@31.59.20.176:6754/"

# --- ВЕБ-СЕРВЕР ---
app = Flask('')
@app.route('/')
def home(): return "Бот работает!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- МОНИТОР ---
class OLXProMonitor:
    def __init__(self):
        self.bot = Bot(token=TOKEN)
        self.seen_ads = set()

    async def fetch_ads(self):
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"}
        try:
            async with httpx.AsyncClient(proxies=PROXY, headers=headers, timeout=20.0, follow_redirects=True) as client:
                r = await client.get(OLX_URL)
                if r.status_code != 200:
                    # Если ошибка, бот шепнет в ТГ, что его не пускают
                    print(f"Ошибка OLX: {r.status_code}")
                    return []
                
                soup = BeautifulSoup(r.text, "html.parser")
                found = []
                for a in soup.find_all("a", href=True):
                    href = a['href']
                    if '/d/oferta/' in href:
                        url = href if href.startswith("http") else "https://www.olx.pl" + href
                        clean = url.split("#")[0].split("?")[0]
                        if clean not in found: found.append(clean)
                return found
        except Exception as e:
            print(f"Ошибка сети: {e}")
            return []

    async def run(self):
        # Запускаем веб-сервер внутри асинхронного цикла
        threading.Thread(target=run_flask, daemon=True).start()
        
        print("!!! СТАРТ МОНИТОРИНГА !!!")
        try:
            await self.bot.send_message(CHAT_ID, "✅ Бот успешно запущен на Render и начинает поиск!")
        except Exception as e:
            print(f"Ошибка ТГ: {e}")

        while True:
            ads = await self.fetch_ads()
            print(f"Найдено объявлений: {len(ads)}")
            
            # Если бот вообще ничего не видит, возможно, прокси забанен
            if not ads and self.seen_ads:
                # Мы не спамим, просто пишем в консоль
                print("Предупреждение: не найдено ни одного объявления. Проверь прокси.")

            for ad in ads:
                if ad not in self.seen_ads:
                    if self.seen_ads: # Отправляем только новые
                        await self.bot.send_message(CHAT_ID, f"🆕 **НОВОЕ ОБЪЯВЛЕНИЕ!**\n\n{ad}")
                    self.seen_ads.add(ad)
            
            await asyncio.sleep(180) # Проверка каждые 3 минуты

if __name__ == "__main__":
    monitor = OLXProMonitor()
    asyncio.run(monitor.run())
