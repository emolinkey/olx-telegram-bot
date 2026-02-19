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

app = Flask('')

@app.route('/')
def home(): return "SYSTEM ONLINE"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

class OLXProMonitor:
    def __init__(self):
        self.bot = Bot(token=TOKEN)
        self.seen_ads = set()
        self.client = None

    async def init_client(self):
        # Используем HTTP/2 для имитации реального браузера
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.google.com/",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-User": "?1"
        }
        self.client = httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True, http2=True)

    async def fetch_ads(self):
        try:
            if not self.client: await self.init_client()
            
            # Рандомная пауза перед запросом, чтобы не "частил"
            await asyncio.sleep(random.uniform(2, 5))
            
            r = await self.client.get(OLX_URL)
            print(f"📡 Статус OLX: {r.status_code}")
            sys.stdout.flush()

            if r.status_code == 403:
                print("❌ Бан 403! Сбрасываю сессию...")
                await self.client.aclose()
                self.client = None
                return []

            if r.status_code != 200: return []

            soup = BeautifulSoup(r.text, "html.parser")
            found = []

            # Поиск через JSON (самый надежный метод)
            next_script = soup.find("script", {"id": "__NEXT_DATA__"})
            if next_script and next_script.string:
                try:
                    data = json.loads(next_script.string)
                    # Глубокий поиск ссылок в JSON
                    items = data.get("props", {}).get("pageProps", {}).get("data", {}).get("items", [])
                    if not items: # Запасной путь в структуре
                        items = data.get("props", {}).get("pageProps", {}).get("listing", {}).get("listing", {}).get("ads", [])
                    
                    for item in items:
                        url = item.get("url")
                        if url:
                            clean = url.split("#")[0].split("?")[0].rstrip('/')
                            title = item.get("title", "Без названия")
                            # Достаем цену
                            price = "Цена не указана"
                            p_val = item.get("price", {})
                            if isinstance(p_val, dict):
                                price = p_val.get("displayValue", "—")
                            
                            found.append({"title": title, "url": clean, "price": price})
                except: pass

            # Если через JSON не вышло, ищем по старинке через HTML
            if not found:
                for a in soup.find_all("a", href=True):
                    if '/d/oferta/' in a['href']:
                        url = a['href'] if a['href'].startswith("http") else "https://www.olx.pl" + a['href']
                        clean = url.split("#")[0].split("?")[0].rstrip('/')
                        if not any(f['url'] == clean for f in found):
                            found.append({"title": "Объявление", "url": clean, "price": "Смотри по ссылке"})

            return found
        except Exception as e:
            print(f"⚠️ Ошибка запроса: {e}")
            return []

    async def run(self):
        threading.Thread(target=run_flask, daemon=True).start()
        print("🚀 БОТ ЗАПУЩЕН")
        sys.stdout.flush()

        try:
            await self.bot.send_message(CHAT_ID, "✅ Мониторинг RAM перезапущен!\nОбход защиты активен.")
        except: pass

        while True:
            ads = await self.fetch_ads()
            print(f"📊 Найдено: {len(ads)}")
            sys.stdout.flush()

            if ads:
                if not self.seen_ads:
                    # При первом запуске только запоминаем
                    self.seen_ads.update([ad['url'] for ad in ads])
                    await self.bot.send_message(CHAT_ID, f"📡 База создана ({len(ads)} шт). Ищу новинки...")
                else:
                    for ad in ads:
                        if ad['url'] not in self.seen_ads:
                            self.seen_ads.add(ad['url'])
                            msg = f"🆕 **НОВОЕ!**\n\n📦 {ad['title']}\n💰 {ad['price']}\n🔗 {ad['url']}"
                            await self.bot.send_message(CHAT_ID, msg)
            
            # Пауза 5-8 минут
            await asyncio.sleep(random.randint(300, 480))

if __name__ == "__main__":
    monitor = OLXProMonitor()
    asyncio.run(monitor.run())
