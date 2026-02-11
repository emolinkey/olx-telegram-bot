import os
import asyncio
import httpx
from bs4 import BeautifulSoup
from aiogram import Bot
import threading
from flask import Flask
from datetime import datetime

# --- НАСТРОЙКИ МИНИ-СЕРВЕРА ---
app = Flask('')

@app.route('/')
def home():
    return f"OLX Bot is Alive! Last check at: {datetime.now().strftime('%H:%M:%S')}"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- НАСТРОЙКИ БОТА ---
TOKEN = "8346602599:AAHzl__YrzL5--4a7enN02PlXLkjRxeD-z8"
CHAT_ID = "908015235"
OLX_URL = "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/q-pami%C4%99%C4%87-ram-ddr4-8gb/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=100&search%5Bfilter_float_price:to%5D=300"
PROXY = "http://nyntgqyu:2c5wo0xukywv@31.59.20.176:6754/"

class OLXProMonitor:
    def __init__(self):
        self.bot = Bot(token=TOKEN)
        self.seen_ads = set()
        self.first_run = True

    async def fetch_ads(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "pl-PL,pl;q=0.9",
        }
        
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Проверяю OLX...")
            async with httpx.AsyncClient(proxies=PROXY, headers=headers, timeout=30.0, follow_redirects=True) as client:
                r = await client.get(OLX_URL)
                
                if r.status_code != 200:
                    print(f"(!) Ошибка доступа: {r.status_code}")
                    return []

                soup = BeautifulSoup(r.text, "html.parser")
                # Ищем все ссылки, которые ведут на объявления
                all_links = soup.find_all("a", href=True)
                found_urls = []
                
                for a in all_links:
                    url = a['href']
                    # Фильтруем только прямые ссылки на офферы
                    if '/d/oferta/' in url or 'olx.pl/d/oferta/' in url:
                        full_url = url if url.startswith("http") else "https://www.olx.pl" + url
                        clean_url = full_url.split("#")[0].split("?")[0]
                        if clean_url not in found_urls:
                            found_urls.append(clean_url)
                
                print(f"(+) Успешно! Найдено объявлений: {len(found_urls)}")
                return found_urls
        except Exception as e:
            print(f"(!) Ошибка при запросе: {e}")
            return []

    async def run(self):
        print("Бот официально запущен и готов к охоте!")
        await self.bot.send_message(CHAT_ID, "✅ **Бот-охотник запущен!**\nИщу DDR4 RAM (100-300 PLN)...")
        
        while True:
            ads = await self.fetch_ads()
            
            new_count = 0
            for ad in ads:
                if ad not in self.seen_ads:
                    self.seen_ads.add(ad)
                    # Если это не первый запуск — отправляем в ТГ
                    if not self.first_run:
                        await self.bot.send_message(CHAT_ID, f"🆕 **НОВОЕ ОБЪЯВЛЕНИЕ!**\n\n🔗 {ad}")
                        new_count += 1
            
            if self.first_run:
                print(f"Первый запуск: запомнил {len(self.seen_ads)} объявлений и молчу.")
                self.first_run = False
            elif new_count > 0:
                print(f"Отправлено новых объявлений: {new_count}")

            # Ждем 5 минут перед следующей проверкой
            await asyncio.sleep(300)

if __name__ == "__main__":
    # Запуск веб-заглушки для Render
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Запуск основного монитора
    monitor = OLXProMonitor()
    try:
        asyncio.run(monitor.run())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")









