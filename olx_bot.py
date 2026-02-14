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
import re

# --- КОНФИГ ---
TOKEN = "8346602599:AAFj8lQ_cfMwBXIfOSl7SbA9J7qixcpaO68"
CHAT_ID = "908015235"
OLX_URL = "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/q-pami%C4%99%C4%87-ram-ddr4-8gb/?search%5Bfilter_float_price%3Afrom%5D=100&search%5Bfilter_float_price%3Ato%5D=250&search%5Border%5D=created_at%3Adesc"

# --- ПРОКСИ ---
PROXY_HOST = "64.137.96.74"
PROXY_PORT = "6641"
PROXY_USER = "nyntgqyu"
PROXY_PASS = "2c5wo0xukywv"
PROXY_URL = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"

# --- OLX API ---
OLX_API_URL = "https://www.olx.pl/api/v1/offers/"
API_PARAMS = {
    "offset": "0",
    "limit": "40",
    "category_id": "1590",
    "query": "pamięć ram ddr4 8gb",
    "sort_by": "created_at:desc",
    "filter_float_price:from": "100",
    "filter_float_price:to": "250",
    "currency": "PLN"
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
        self.client = None
        self.method = "api"

    async def init_client(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/125.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.olx.pl/",
            "Origin": "https://www.olx.pl",
            "Connection": "keep-alive",
            "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        # ========== ПРОКСИ ПОДКЛЮЧЕНИЕ ==========
        proxy_mounts = {
            "http://": httpx.AsyncHTTPTransport(proxy=PROXY_URL),
            "https://": httpx.AsyncHTTPTransport(proxy=PROXY_URL),
        }

        self.client = httpx.AsyncClient(
            headers=headers,
            timeout=30.0,
            follow_redirects=True,
            mounts=proxy_mounts
        )
        # =========================================

        print(f"✅ HTTP клиент создан")
        print(f"🌐 Прокси: {PROXY_HOST}:{PROXY_PORT} (Испания)")
        sys.stdout.flush()

    async def fetch_via_api(self):
        try:
            if not self.client:
                await self.init_client()

            await asyncio.sleep(random.uniform(1, 3))

            r = await self.client.get(OLX_API_URL, params=API_PARAMS)
            print(f"[API] Статус: {r.status_code}")
            sys.stdout.flush()

            if r.status_code == 403:
                print("[API] Блокировка 403, пересоздаю клиент...")
                await self.client.aclose()
                self.client = None
                return []

            if r.status_code != 200:
                print(f"[API] Неожиданный статус: {r.status_code}")
                return []

            data = r.json()
            ads = []

            for item in data.get("data", []):
                ad_id = str(item.get("id", ""))
                title = item.get("title", "Без названия")
                url = item.get("url", "")

                price = "Цена не указана"
                for param in item.get("params", []):
                    if param.get("key") == "price":
                        price_val = param.get("value", {})
                        if isinstance(price_val, dict):
                            price = f"{price_val.get('value', '?')} {price_val.get('currency', 'PLN')}"
                        else:
                            price = str(price_val)
                        break

                if ad_id and url:
                    clean_url = url.split("#")[0].split("?")[0].rstrip('/')
                    ads.append({
                        "id": ad_id,
                        "title": title,
                        "url": clean_url,
                        "price": price
                    })

            return ads

        except json.JSONDecodeError:
            print("[API] Ответ не JSON, переключаюсь на HTML")
            self.method = "html"
            return []
        except Exception as e:
            print(f"[API] Ошибка: {e}")
            sys.stdout.flush()
            return []

    async def fetch_via_html(self):
        try:
            if not self.client:
                await self.init_client()

            self.client.headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

            await asyncio.sleep(random.uniform(2, 5))

            r = await self.client.get(OLX_URL)
            print(f"[HTML] Статус: {r.status_code}")
            sys.stdout.flush()

            if r.status_code == 403:
                await self.client.aclose()
                self.client = None
                return []

            if r.status_code != 200:
                return []

            soup = BeautifulSoup(r.text, "html.parser")
            ads = []

            for script in soup.find_all("script", {"type": "application/json"}):
                try:
                    json_data = json.loads(script.string)
                    ads_from_json = self.extract_from_json(json_data)
                    if ads_from_json:
                        return ads_from_json
                except:
                    continue

            for script in soup.find_all("script", {"id": "__NEXT_DATA__"}):
                try:
                    json_data = json.loads(script.string)
                    ads_from_json = self.extract_from_next_data(json_data)
                    if ads_from_json:
                        return ads_from_json
                except:
                    continue

            cards = soup.find_all("div", {"data-cy": "l-card"})
            if not cards:
                cards = soup.find_all("div", class_=re.compile(r"offer-wrapper|listing-grid"))

            print(f"[HTML] Найдено карточек: {len(cards)}")

            for card in cards:
                link = card.find("a", href=True)
                if link and '/d/oferta/' in link['href']:
                    href = link['href']
                    url = href if href.startswith("http") else "https://www.olx.pl" + href
                    clean_url = url.split("#")[0].split("?")[0].rstrip('/')

                    title_el = card.find("h6") or card.find("h4") or card.find("h3")
                    title = title_el.get_text(strip=True) if title_el else "Без названия"

                    price_el = card.find("p", {"data-testid": "ad-price"}) or card.find(
                        "p", class_=re.compile(r"price"))
                    price = price_el.get_text(strip=True) if price_el else "Цена не указана"

                    ad_id = clean_url.split("-")[-1].replace(".html", "")
                    ads.append({
                        "id": ad_id,
                        "title": title,
                        "url": clean_url,
                        "price": price
                    })

            if not ads:
                seen_urls = set()
                for a in soup.find_all("a", href=True):
                    href = a['href']
                    if '/d/oferta/' in href:
                        url = href if href.startswith("http") else "https://www.olx.pl" + href
                        clean_url = url.split("#")[0].split("?")[0].rstrip('/')
                        if clean_url not in seen_urls:
                            seen_urls.add(clean_url)
                            ad_id = clean_url.split("-")[-1].replace(".html", "")
                            ads.append({
                                "id": ad_id,
                                "title": a.get_text(strip=True)[:100] or "Без названия",
                                "url": clean_url,
                                "price": "Цена не указана"
                            })

            return ads

        except Exception as e:
            print(f"[HTML] Ошибка: {e}")
            sys.stdout.flush()
            return []

    def extract_from_json(self, data, ads=None):
        if ads is None:
            ads = []

        if isinstance(data, dict):
            if "url" in data and "title" in data and ("/d/oferta/" in str(data.get("url", ""))):
                url = data["url"]
                if not url.startswith("http"):
                    url = "https://www.olx.pl" + url
                clean_url = url.split("#")[0].split("?")[0].rstrip('/')
                ads.append({
                    "id": str(data.get("id", clean_url.split("-")[-1])),
                    "title": data.get("title", "Без названия"),
                    "url": clean_url,
                    "price": str(data.get("price", {}).get("displayValue", "Цена не указана"))
                })
            for v in data.values():
                self.extract_from_json(v, ads)
        elif isinstance(data, list):
            for item in data:
                self.extract_from_json(item, ads)

        return ads

    def extract_from_next_data(self, data):
        ads = []
        try:
            props = data.get("props", {}).get("pageProps", {})
            listing = props.get("listing", {}) or props.get("data", {})
            items = listing.get("listing", {}).get("ads", []) or listing.get("ads", [])

            if not items:
                return self.extract_from_json(data)

            for item in items:
                url = item.get("url", "")
                if not url.startswith("http"):
                    url = "https://www.olx.pl" + url
                clean_url = url.split("#")[0].split("?")[0].rstrip('/')

                price = "Цена не указана"
                if "price" in item:
                    price_data = item["price"]
                    if isinstance(price_data, dict):
                        price = price_data.get("displayValue",
                                    price_data.get("regularPrice", {}).get("displayValue", "?"))
                    else:
                        price = str(price_data)

                ads.append({
                    "id": str(item.get("id", "")),
                    "title": item.get("title", "Без названия"),
                    "url": clean_url,
                    "price": price
                })

        except Exception as e:
            print(f"[NEXT_DATA] Ошибка: {e}")

        return ads

    async def fetch_ads(self):
        ads = []

        if self.method == "api":
            ads = await self.fetch_via_api()
            if not ads:
                print("⚠️ API не дал результатов, пробую HTML...")
                ads = await self.fetch_via_html()
        else:
            ads = await self.fetch_via_html()
            if not ads:
                print("⚠️ HTML не дал результатов, пробую API...")
                self.method = "api"
                ads = await self.fetch_via_api()

        return ads

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
        print(f"📡 Метод: {self.method}")
        print(f"🌐 Прокси: {PROXY_HOST}:{PROXY_PORT} (Испания)")
        print("=" * 50)
        sys.stdout.flush()

        try:
            await self.bot.send_message(
                CHAT_ID,
                "✅ Мониторинг запущен!\n"
                f"🌐 Прокси: Испания ({PROXY_HOST})\n"
                "🔄 Проверяю OLX каждые 5-7 минут..."
            )
        except Exception as e:
            print(f"❌ Ошибка Telegram: {e}")
            sys.stdout.flush()

        fail_count = 0
        MAX_FAILS = 5

        while True:
            try:
                ads = await self.fetch_ads()
                print(f"📊 Найдено объявлений: {len(ads)}")
                sys.stdout.flush()

                if ads:
                    fail_count = 0

                    if not self.seen_ads:
                        for ad in ads:
                            self.seen_ads.add(ad['url'])
                        msg = f"📡 База собрана: {len(ads)} объявлений\n🔍 Отслеживаю новые..."
                        await self.bot.send_message(CHAT_ID, msg)
                        print(f"✅ Первичная база: {len(ads)} шт")
                    else:
                        new_count = 0
                        for ad in ads:
                            if ad['url'] not in self.seen_ads:
                                self.seen_ads.add(ad['url'])
                                new_count += 1
                                try:
                                    await self.bot.send_message(CHAT_ID, self.format_message(ad))
                                    await asyncio.sleep(1)
                                except Exception as e:
                                    print(f"❌ Ошибка отправки: {e}")
                        if new_count:
                            print(f"🆕 Отправлено новых: {new_count}")
                        else:
                            print("ℹ️ Новых объявлений нет")
                else:
                    fail_count += 1
                    print(f"⚠️ Пустой результат ({fail_count}/{MAX_FAILS})")

                    if fail_count >= MAX_FAILS:
                        print("🔄 Переключаю метод парсинга...")
                        self.method = "html" if self.method == "api" else "api"
                        fail_count = 0
                        if self.client:
                            await self.client.aclose()
                            self.client = None

                sys.stdout.flush()

            except Exception as e:
                print(f"❌ Критическая ошибка: {e}")
                sys.stdout.flush()
                if self.client:
                    try:
                        await self.client.aclose()
                    except:
                        pass
                    self.client = None

            delay = random.randint(300, 420)
            print(f"⏳ Следующая проверка через {delay // 60} мин {delay % 60} сек")
            sys.stdout.flush()
            await asyncio.sleep(delay)


if __name__ == "__main__":
    monitor = OLXProMonitor()
    asyncio.run(monitor.run())

