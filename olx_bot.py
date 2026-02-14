import os
import asyncio
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from aiogram import Bot
from flask import Flask
import threading
import random
import sys
import json
import re

# --- КОНФИГ ---
TOKEN = "8346602599:AAFj8lQ_cfMwBXIfOSl7SbA9J7qixcpaO68"
CHAT_ID = "908015235"
OLX_URL = "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/q-pami%C4%99%C4%87-ram-ddr4-8gb/?search%5Bfilter_float_price%3Afrom%5D=100&search%5Bfilter_float_price%3Ato%5D=250&search%5Border%5D=created_at%3Adesc"

# --- ПРОКСИ ---
PROXY = "http://nyntgqyu:2c5wo0xukywv@64.137.96.74:6641"

# --- ВЕБ-СЕРВЕР ---
app = Flask('')

@app.route('/')
def home():
    return "SYSTEM ONLINE"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- МОНИТОР ---
class OLXProMonitor:
    def __init__(self):
        self.bot = Bot(token=TOKEN)
        self.seen_ads = set()

    async def fetch_ads(self):
        try:
            await asyncio.sleep(random.uniform(2, 5))

            async with AsyncSession(
                impersonate="chrome120",
                proxy=PROXY,
                timeout=30
            ) as session:

                # Сначала заходим на главную — получаем cookies
                print("🌐 Захожу на главную OLX...")
                sys.stdout.flush()
                await session.get("https://www.olx.pl/", impersonate="chrome120")
                await asyncio.sleep(random.uniform(1, 3))

                # Теперь запрашиваем страницу с объявлениями
                print("🔍 Запрашиваю объявления...")
                sys.stdout.flush()
                r = await session.get(OLX_URL, impersonate="chrome120")
                print(f"📡 Статус: {r.status_code}")
                sys.stdout.flush()

                if r.status_code != 200:
                    print(f"❌ Ошибка: статус {r.status_code}")
                    return []

                soup = BeautifulSoup(r.text, "html.parser")
                ads = []

                # === МЕТОД 1: __NEXT_DATA__ (самый надёжный) ===
                next_data = soup.find("script", {"id": "__NEXT_DATA__"})
                if next_data:
                    try:
                        data = json.loads(next_data.string)
                        ads = self.parse_next_data(data)
                        if ads:
                            print(f"✅ [NEXT_DATA] Найдено: {len(ads)}")
                            return ads
                    except Exception as e:
                        print(f"⚠️ [NEXT_DATA] Ошибка: {e}")

                # === МЕТОД 2: JSON в script тегах ===
                for script in soup.find_all("script", {"type": "application/json"}):
                    try:
                        data = json.loads(script.string)
                        found = self.deep_search(data)
                        if found:
                            print(f"✅ [JSON] Найдено: {len(found)}")
                            return found
                    except:
                        continue

                # === МЕТОД 3: data-cy карточки ===
                cards = soup.find_all("div", {"data-cy": "l-card"})
                print(f"📋 [HTML] Карточек: {len(cards)}")

                for card in cards:
                    link = card.find("a", href=True)
                    if link and '/d/oferta/' in link.get('href', ''):
                        href = link['href']
                        url = href if href.startswith("http") else "https://www.olx.pl" + href
                        clean = url.split("#")[0].split("?")[0].rstrip('/')

                        title_el = card.find("h6") or card.find("h4") or card.find("h3")
                        title = title_el.get_text(strip=True) if title_el else "Без названия"

                        price_el = card.find("p", {"data-testid": "ad-price"})
                        price = price_el.get_text(strip=True) if price_el else "?"

                        ads.append({
                            "title": title,
                            "url": clean,
                            "price": price
                        })

                if ads:
                    return ads

                # === МЕТОД 4: все ссылки /d/oferta/ ===
                seen = set()
                for a in soup.find_all("a", href=True):
                    href = a['href']
                    if '/d/oferta/' in href:
                        url = href if href.startswith("http") else "https://www.olx.pl" + href
                        clean = url.split("#")[0].split("?")[0].rstrip('/')
                        if clean not in seen:
                            seen.add(clean)
                            ads.append({
                                "title": a.get_text(strip=True)[:100] or "Без названия",
                                "url": clean,
                                "price": "?"
                            })

                print(f"📋 [LINKS] Найдено: {len(ads)}")

                # Если вообще ничего — сохраняем HTML для дебага
                if not ads:
                    preview = r.text[:500]
                    print(f"⚠️ Страница пустая. Превью:\n{preview}")

                return ads

        except Exception as e:
            print(f"❌ Ошибка парсинга: {e}")
            sys.stdout.flush()
            return []

    def parse_next_data(self, data):
        """Парсим __NEXT_DATA__ от Next.js"""
        ads = []
        try:
            props = data.get("props", {}).get("pageProps", {})

            # Ищем объявления в разных местах структуры
            items = []

            # Путь 1
            listing = props.get("listing", {})
            if isinstance(listing, dict):
                items = listing.get("listing", {}).get("ads", [])

            # Путь 2
            if not items:
                items = props.get("ads", [])

            # Путь 3
            if not items:
                data_field = props.get("data", {})
                if isinstance(data_field, dict):
                    items = data_field.get("ads", [])

            # Путь 4 — рекурсивный поиск
            if not items:
                return self.deep_search(data)

            for item in items:
                url = item.get("url", "")
                if not url:
                    continue
                if not url.startswith("http"):
                    url = "https://www.olx.pl" + url
                clean = url.split("#")[0].split("?")[0].rstrip('/')

                title = item.get("title", "Без названия")

                price = "?"
                price_data = item.get("price", {})
                if isinstance(price_data, dict):
                    price = price_data.get("displayValue",
                            price_data.get("regularPrice", {}).get("displayValue", "?"))
                elif price_data:
                    price = str(price_data)

                ads.append({
                    "title": title,
                    "url": clean,
                    "price": price
                })

        except Exception as e:
            print(f"⚠️ parse_next_data ошибка: {e}")

        return ads

    def deep_search(self, data, results=None):
        """Рекурсивно ищем объявления в любой JSON структуре"""
        if results is None:
            results = []

        if isinstance(data, dict):
            url = data.get("url", "")
            title = data.get("title", "")
            if url and title and "/d/oferta/" in str(url):
                if not url.startswith("http"):
                    url = "https://www.olx.pl" + url
                clean = url.split("#")[0].split("?")[0].rstrip('/')

                price = "?"
                p = data.get("price", {})
                if isinstance(p, dict):
                    price = p.get("displayValue", "?")

                if clean not in [r["url"] for r in results]:
                    results.append({
                        "title": title,
                        "url": clean,
                        "price": price
                    })

            for v in data.values():
                self.deep_search(v, results)

        elif isinstance(data, list):
            for item in data:
                self.deep_search(item, results)

        return results

    def format_message(self, ad):
        return (
            f"🆕 НОВОЕ ОБЪЯВЛЕНИЕ!\n\n"
            f"📦 {ad['title']}\n"
            f"💰 {ad['price']}\n"
            f"🔗 {ad['url']}"
        )

    async def run(self):
        threading.Thread(target=run_flask, daemon=True).start()
        print("=" * 50)
        print("🚀 БОТ СТАРТОВАЛ (curl_cffi + прокси)")
        print(f"🌐 Прокси: Испания")
        print(f"🔒 TLS: имитация Chrome 120")
        print("=" * 50)
        sys.stdout.flush()

        try:
            await self.bot.send_message(
                CHAT_ID,
                "✅ Мониторинг запущен!\n"
                "🌐 Прокси: Испания\n"
                "🔒 Режим: Chrome имитация\n"
                "🔄 Проверка каждые 5-7 минут"
            )
        except Exception as e:
            print(f"❌ Telegram ошибка: {e}")

        fail_count = 0

        while True:
            try:
                ads = await self.fetch_ads()
                print(f"📊 Всего объявлений: {len(ads)}")
                sys.stdout.flush()

                if ads:
                    fail_count = 0

                    if not self.seen_ads:
                        for ad in ads:
                            self.seen_ads.add(ad['url'])
                        await self.bot.send_message(
                            CHAT_ID,
                            f"📡 База собрана: {len(ads)} объявлений\n"
                            f"🔍 Отслеживаю новые..."
                        )
                        print(f"✅ База: {len(ads)} шт")
                    else:
                        new_count = 0
                        for ad in ads:
                            if ad['url'] not in self.seen_ads:
                                self.seen_ads.add(ad['url'])
                                new_count += 1
                                try:
                                    await self.bot.send_message(
                                        CHAT_ID,
                                        self.format_message(ad)
                                    )
                                    await asyncio.sleep(1)
                                except Exception as e:
                                    print(f"❌ Ошибка отправки: {e}")

                        if new_count:
                            print(f"🆕 Новых: {new_count}")
                        else:
                            print("ℹ️ Новых нет")
                else:
                    fail_count += 1
                    print(f"⚠️ Пусто ({fail_count}/5)")

                    if fail_count >= 5:
                        fail_count = 0
                        await self.bot.send_message(
                            CHAT_ID,
                            "⚠️ 5 неудачных попыток подряд.\n"
                            "Возможно прокси умер или OLX сменил защиту."
                        )

                sys.stdout.flush()

            except Exception as e:
                print(f"❌ Критическая ошибка: {e}")
                sys.stdout.flush()

            delay = random.randint(300, 420)
            print(f"⏳ Следующая через {delay // 60}м {delay % 60}с")
            sys.stdout.flush()
            await asyncio.sleep(delay)


if __name__ == "__main__":
    monitor = OLXProMonitor()
    asyncio.run(monitor.run())
