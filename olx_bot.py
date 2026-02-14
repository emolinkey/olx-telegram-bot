import os
import asyncio
import cloudscraper
from bs4 import BeautifulSoup
from aiogram import Bot
from flask import Flask
import threading
import random
import sys
import json

# --- КОНФИГ ---
TOKEN = "8346602599:AAFj8lQ_cfMwBXIfOSl7SbA9J7qixcpaO68"
CHAT_ID = "908015235"
OLX_URL = "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/q-pami%C4%99%C4%87-ram-ddr4-8gb/?search%5Bfilter_float_price%3Afrom%5D=100&search%5Bfilter_float_price%3Ato%5D=250&search%5Border%5D=created_at%3Adesc"

# --- ПРОКСИ ---
PROXY = "http://nyntgqyu:2c5wo0xukywv@64.137.96.74:6641"
PROXIES = {
    "http": PROXY,
    "https": PROXY
}

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
        self.scraper = None

    def create_scraper(self):
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            },
            delay=5
        )
        self.scraper.proxies = PROXIES
        self.scraper.headers.update({
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/",
        })
        print("✅ Scraper создан (Chrome имитация + прокси)")
        sys.stdout.flush()

    def fetch_ads_sync(self):
        try:
            if not self.scraper:
                self.create_scraper()

            # Сначала заходим на главную — получаем cookies
            print("🌐 Захожу на главную OLX...")
            sys.stdout.flush()

            try:
                self.scraper.get("https://www.olx.pl/", timeout=30)
                import time
                time.sleep(random.uniform(2, 4))
            except Exception as e:
                print(f"⚠️ Главная страница: {e}")

            # Запрашиваем объявления
            print("🔍 Запрашиваю объявления...")
            sys.stdout.flush()

            r = self.scraper.get(OLX_URL, timeout=30)
            print(f"📡 Статус: {r.status_code}")
            sys.stdout.flush()

            if r.status_code == 403:
                print("❌ 403 — пересоздаю scraper...")
                self.scraper = None
                return []

            if r.status_code != 200:
                print(f"❌ Статус: {r.status_code}")
                return []

            soup = BeautifulSoup(r.text, "html.parser")
            ads = []

            # === МЕТОД 1: __NEXT_DATA__ ===
            next_data = soup.find("script", {"id": "__NEXT_DATA__"})
            if next_data and next_data.string:
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
                    if script.string:
                        data = json.loads(script.string)
                        found = self.deep_search(data)
                        if found:
                            print(f"✅ [JSON] Найдено: {len(found)}")
                            return found
                except:
                    continue

            # === МЕТОД 3: data-cy карточки ===
            cards = soup.find_all("div", {"data-cy": "l-card"})
            print(f"📋 [HTML] Карточек data-cy: {len(cards)}")

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
                print(f"✅ [HTML cards] Найдено: {len(ads)}")
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
                        text = a.get_text(strip=True)[:100]
                        ads.append({
                            "title": text if text else "Без названия",
                            "url": clean,
                            "price": "?"
                        })

            if ads:
                print(f"✅ [LINKS] Найдено: {len(ads)}")
            else:
                # Дебаг — показываем начало страницы
                text_preview = soup.get_text()[:300].strip()
                print(f"⚠️ Ничего не найдено. Текст страницы:\n{text_preview}")

            return ads

        except Exception as e:
            print(f"❌ Ошибка: {e}")
            sys.stdout.flush()
            self.scraper = None
            return []

    def parse_next_data(self, data):
        ads = []
        try:
            props = data.get("props", {}).get("pageProps", {})

            items = []

            # Путь 1
            listing = props.get("listing", {})
            if isinstance(listing, dict):
                inner = listing.get("listing", {})
                if isinstance(inner, dict):
                    items = inner.get("ads", [])

            # Путь 2
            if not items:
                items = props.get("ads", [])

            # Путь 3
            if not items:
                d = props.get("data", {})
                if isinstance(d, dict):
                    items = d.get("ads", [])

            # Путь 4 — глубокий поиск
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
                pd = item.get("price", {})
                if isinstance(pd, dict):
                    price = pd.get("displayValue",
                            pd.get("regularPrice", {}).get("displayValue", "?"))
                elif pd:
                    price = str(pd)

                ads.append({
                    "title": title,
                    "url": clean,
                    "price": price
                })

        except Exception as e:
            print(f"⚠️ parse_next_data: {e}")

        return ads

    def deep_search(self, data, results=None):
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

                existing_urls = [r["url"] for r in results]
                if clean not in existing_urls:
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
        print("🚀 БОТ СТАРТОВАЛ")
        print("🔒 Движок: cloudscraper (Chrome)")
        print("🌐 Прокси: Испания")
        print("=" * 50)
        sys.stdout.flush()

        try:
            await self.bot.send_message(
                CHAT_ID,
                "✅ Мониторинг запущен!\n"
                "🔒 Движок: cloudscraper\n"
                "🌐 Прокси: Испания\n"
                "🔄 Проверка каждые 5-7 минут"
            )
        except Exception as e:
            print(f"❌ Telegram ошибка: {e}")

        fail_count = 0

        while True:
            try:
                # cloudscraper синхронный — запускаем в потоке
                loop = asyncio.get_event_loop()
                ads = await loop.run_in_executor(None, self.fetch_ads_sync)

                print(f"📊 Всего: {len(ads)}")
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
                                    print(f"❌ Отправка: {e}")

                        if new_count:
                            print(f"🆕 Новых: {new_count}")
                        else:
                            print("ℹ️ Новых нет")
                else:
                    fail_count += 1
                    print(f"⚠️ Пусто ({fail_count}/5)")

                    if fail_count >= 5:
                        fail_count = 0
                        self.scraper = None
                        try:
                            await self.bot.send_message(
                                CHAT_ID,
                                "⚠️ 5 неудач подряд.\n"
                                "Пересоздаю scraper..."
                            )
                        except:
                            pass

                sys.stdout.flush()

            except Exception as e:
                print(f"❌ Критическая ошибка: {e}")
                sys.stdout.flush()
                self.scraper = None

            delay = random.randint(300, 420)
            print(f"⏳ Следующая через {delay // 60}м {delay % 60}с")
            sys.stdout.flush()
            await asyncio.sleep(delay)


if __name__ == "__main__":
    monitor = OLXProMonitor()
    asyncio.run(monitor.run())
