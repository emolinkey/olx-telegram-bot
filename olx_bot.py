import os
import asyncio
import httpx
from bs4 import BeautifulSoup
from aiogram import Bot
from flask import Flask
import threading
import random
import sys
import json

# --- КОНФИГ ---
TOKEN = "8346602599:AAEauikfQJCI_cyZK5hiv3W0StWk9OMWPK0"
CHAT_ID = "908015235"
OLX_URL = "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/q-pami%C4%99%C4%87-ram-ddr4-8gb/?search%5Bfilter_float_price%3Afrom%5D=100&search%5Bfilter_float_price%3Ato%5D=250&search%5Border%5D=created_at%3Adesc"

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
app = Flask('')
@app.route('/')
def home(): return "БОТ РАБОТАЕТ"

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
            "Accept-Language": "pl-PL,pl;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        # ИСПРАВЛЕНО: Убрали 'proxies', работаем напрямую через HTTP/2
        self.client = httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True, http2=True)

    async def fetch_ads(self):
        try:
            if not self.client: await self.init_client()
            
            # Рандомная пауза, чтобы не злить OLX
            await asyncio.sleep(random.uniform(2, 5))
            
            r = await self.client.get(OLX_URL)
            print(f"📡 Статус: {r.status_code}")
            sys.stdout.flush()

            if r.status_code != 200:
                print(f"⚠️ Ошибка доступа: {r.status_code}")
                if r.status_code == 403:
                    await self.client.aclose()
                    self.client = None # Сброс сессии при бане
                return []

            soup = BeautifulSoup(r.text, "html.parser")
            found = []

            # Ищем данные в скрытом JSON (самый точный метод)
            script = soup.find("script", {"id": "__NEXT_DATA__"})
            if script and script.string:
                try:
                    data = json.loads(script.string)
                    items = data.get("props", {}).get("pageProps", {}).get("data", {}).get("items", [])
                    if not items:
                        items = data.get("props", {}).get("pageProps", {}).get("listing", {}).get("listing", {}).get("ads", [])
                    
                    for item in items:
                        url = item.get("url")
                        if url:
                            clean = url.split("#")[0].split("?")[0].rstrip('/')
                            title = item.get("title", "RAM DDR4")
                            price = item.get("price", {}).get("displayValue", "?")
                            found.append({"title": title, "url": clean, "price": price})
                except: pass

            # Если JSON пуст, ищем по ссылкам
            if not found:
                for a in soup.find_all("a", href=True):
                    if '/d/oferta/' in a['href']:
                        u = a['href'] if a['href'].startswith("http") else "https://www.olx.pl" + a['href']
                        clean = u.split("#")[0].split("?")[0].rstrip('/')
                        if not any(f['url'] == clean for f in found):
                            found.append({"title": "Объявление", "url": clean, "price": "Проверь цену"})
            
            return found
        except Exception as e:
            print(f"❌ Ошибка при парсинге: {e}")
            return []

    async def run(self):
        threading.Thread(target=run_flask, daemon=True).start()
        print("!!! БОТ СТАРТОВАЛ !!!")
        sys.stdout.flush()
        
        try:
            await self.bot.send_message(CHAT_ID, "🚀 Бот запущен! Исправлена ошибка с 'proxies'. Начинаю поиск...")
        except: pass

        while True:
            ads = await self.fetch_ads()
            print(f"🔎 Найдено: {len(ads)} шт.")
            sys.stdout.flush()
            
            if ads:
                if not self.seen_ads:
                    self.seen_ads.update([ad['url'] for ad in ads])
                    await self.bot.send_message(CHAT_ID, f"📡 База создана ({len(ads)} шт). Жду новые объявления!")
                else:
                    for ad in ads:
                        if ad['url'] not in self.seen_ads:
                            self.seen_ads.add(ad['url'])
                            msg = f"🆕 **НАШЕЛ НОВОЕ!**\n\n📦 {ad['title']}\n💰 {ad['price']}\n🔗 {ad['url']}"
                            await self.bot.send_message(CHAT_ID, msg)
            
            await asyncio.sleep(random.randint(300, 500))

if __name__ == "__main__":
    monitor = OLXProMonitor()
    asyncio.run(monitor.run())
