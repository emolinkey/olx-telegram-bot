import os
import asyncio
import requests
from bs4 import BeautifulSoup
from aiogram import Bot
from flask import Flask
import threading
import random
import sys
import json
import time

TOKEN = "8346602599:AAFj8lQ_cfMwBXIfOSl7SbA9J7qixcpaO68"
CHAT_ID = "908015235"
OLX_URL = "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/q-pami%C4%99%C4%87-ram-ddr4-8gb/?search%5Bfilter_float_price%3Afrom%5D=100&search%5Bfilter_float_price%3Ato%5D=250&search%5Border%5D=created_at%3Adesc"

PROXIES = {
    "http": "http://nyntgqyu:2c5wo0xukywv@64.137.96.74:6641",
    "https": "http://nyntgqyu:2c5wo0xukywv@64.137.96.74:6641"
}

app = Flask('')

@app.route('/')
def home():
    return "SYSTEM ONLINE"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


class OLXProMonitor:
    def __init__(self):
        self.bot = Bot(token=TOKEN)
        self.seen_ads = set()
        self.session = None

    def create_session(self):
        self.session = requests.Session()
        self.session.proxies = PROXIES
        chrome_ver = random.choice(["120", "121", "122", "123", "124", "125"])
        self.session.headers = {
            "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_ver}.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Ch-Ua": f'"Chromium";v="{chrome_ver}", "Google Chrome";v="{chrome_ver}", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
        }
        print(f"✅ Сессия создана (Chrome {chrome_ver} + прокси Испания)")
        sys.stdout.flush()

    def fetch_ads_sync(self):
        try:
            if not self.session:
                self.create_session()

            print("🌐 Шаг 1: Главная...")
            sys.stdout.flush()
            try:
                r1 = self.session.get("https://www.olx.pl/", timeout=30, allow_redirects=True)
                print(f"   Главная: {r1.status_code}, cookies: {len(self.session.cookies)}")
                time.sleep(random.uniform(3, 6))
            except Exception as e:
                print(f"   ⚠️ Главная: {e}")
                time.sleep(2)

            print("🌐 Шаг 2: Категория...")
            sys.stdout.flush()
            try:
                self.session.headers["Referer"] = "https://www.olx.pl/"
                r2 = self.session.get(
                    "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/",
                    timeout=30, allow_redirects=True
                )
                print(f"   Категория: {r2.status_code}")
                time.sleep(random.uniform(2, 4))
            except Exception as e:
                print(f"   ⚠️ Категория: {e}")
                time.sleep(2)

            print("🔍 Шаг 3: Объявления...")
            sys.stdout.flush()
            self.session.headers["Referer"] = "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/"
            r = self.session.get(OLX_URL, timeout=30, allow_redirects=True)
            print(f"📡 Статус: {r.status_code}")
            sys.stdout.flush()

            if r.status_code == 403:
                print("❌ 403 — пересоздаю сессию")
                self.session = None
                return []

            if r.status_code != 200:
                print(f"❌ Статус {r.status_code}")
                return []

            soup = BeautifulSoup(r.text, "lxml")
            ads = []

            # МЕТОД 1: __NEXT_DATA__
            next_script = soup.find("script", {"id": "__NEXT_DATA__"})
            if next_script and next_script.string:
                try:
                    data = json.loads(next_script.string)
                    ads = self.parse_next_data(data)
                    if ads:
                        print(f"✅ [NEXT_DATA] → {len(ads)}")
                        return ads
                except Exception as e:
                    print(f"   ⚠️ NEXT_DATA: {e}")

            # МЕТОД 2: JSON скрипты
            json_scripts = soup.find_all("script", {"type": "application/json"})
            print(f"📋 JSON скриптов: {len(json_scripts)}")
            for i, script in enumerate(json_scripts):
                try:
                    if script.string and len(script.string) > 100:
                        data = json.loads(script.string)
                        found = self.deep_search(data)
                        if found:
                            print(f"✅ [JSON #{i}] → {len(found)}")
                            return found
                except:
                    continue

            # МЕТОД 3: HTML карточки
            cards = soup.find_all("div", {"data-cy": "l-card"})
            print(f"📋 HTML карточек: {len(cards)}")
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
                    ads.append({"title": title, "url": clean, "price": price})

            if ads:
                print(f"✅ [HTML] → {len(ads)}")
                return ads

            # МЕТОД 4: Все ссылки
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
                print(f"✅ [LINKS] → {len(ads)}")
            else:
                preview = soup.get_text(separator=" ", strip=True)[:300]
                print(f"⚠️ Пусто! Текст: {preview}")

            return ads

        except requests.exceptions.ProxyError as e:
            print(f"❌ Прокси: {e}")
            self.session = None
            return []
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            self.session = None
            return []

    def parse_next_data(self, data):
        ads = []
        try:
            props = data.get("props", {}).get("pageProps", {})
            items = []
            paths = [
                lambda: props.get("listing", {}).get("listing", {}).get("ads", []),
                lambda: props.get("listing", {}).get("ads", []),
                lambda: props.get("ads", []),
                lambda: props.get("data", {}).get("ads", []),
                lambda: props.get("data", {}).get("listing", {}).get("ads", []),
            ]
            for fn in paths:
                try:
                    r = fn()
                    if r and isinstance(r, list) and len(r) > 0:
                        items = r
                        break
                except:
                    continue

            if not items:
                return self.deep_search(data)

            for item in items:
                if not isinstance(item, dict):
                    continue
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
                    price = (pd.get("displayValue") or
                            pd.get("regularPrice", {}).get("displayValue") or
                            f"{pd.get('value', '?')} {pd.get('currency', '')}")
                elif pd:
                    price = str(pd)
                ads.append({"title": title, "url": clean, "price": price})
        except Exception as e:
            print(f"⚠️ parse_next_data: {e}")
        return ads

    def deep_search(self, data, results=None, depth=0):
        if results is None:
            results = []
        if depth > 15:
            return results
        if isinstance(data, dict):
            url = data.get("url", "")
            title = data.get("title", "")
            if url and title and "/d/oferta/" in str(url):
                if not url.startswith("http"):
                    url = "https://www.olx.pl" + url
                clean = url.split("#")[0].split("?")[0].rstrip('/')
                existing = [r["url"] for r in results]
                if clean not in existing:
                    price = "?"
                    p = data.get("price", {})
                    if isinstance(p, dict):
                        price = p.get("displayValue", "?")
                    results.append({"title": title, "url": clean, "price": price})
            for v in data.values():
                self.deep_search(v, results, depth + 1)
        elif isinstance(data, list):
            for item in data:
                self.deep_search(item, results, depth + 1)
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
        print("🚀 БОТ СТАРТОВАЛ (requests + прокси)")
        print("🌐 Прокси: Испания")
        print("=" * 50)
        sys.stdout.flush()

        try:
            await self.bot.send_message(
                CHAT_ID,
                "✅ Мониторинг запущен!\n🌐 Прокси: Испания\n🔄 Каждые 5-7 минут"
            )
        except Exception as e:
            print(f"❌ Telegram: {e}")

        fail_count = 0

        while True:
            try:
                loop = asyncio.get_event_loop()
                ads = await loop.run_in_executor(None, self.fetch_ads_sync)
                print(f"📊 Итого: {len(ads)}")
                sys.stdout.flush()

                if ads:
                    fail_count = 0
                    if not self.seen_ads:
                        for ad in ads:
                            self.seen_ads.add(ad['url'])
                        await self.bot.send_message(
                            CHAT_ID,
                            f"📡 База: {len(ads)} объявлений\n🔍 Слежу за новыми..."
                        )
                        print(f"✅ База: {len(ads)}")
                    else:
                        new_count = 0
                        for ad in ads:
                            if ad['url'] not in self.seen_ads:
                                self.seen_ads.add(ad['url'])
                                new_count += 1
                                try:
                                    await self.bot.send_message(
                                        CHAT_ID, self.format_message(ad)
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
                        self.session = None

                sys.stdout.flush()

            except Exception as e:
                print(f"❌ Ошибка: {e}")
                self.session = None

            delay = random.randint(300, 420)
            print(f"⏳ Через {delay // 60}м {delay % 60}с")
            sys.stdout.flush()
            await asyncio.sleep(delay)


if __name__ == "__main__":
    monitor = OLXProMonitor()
    asyncio.run(monitor.run())
