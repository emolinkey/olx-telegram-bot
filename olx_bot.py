import os
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from aiogram import Bot
from flask import Flask
import threading
import random
import sys
import json

# --- КОНФИГ ---
TOKEN = "8346602599:AAGXzaXb6GxpAjK6EtbDqSLHfGC1I6mIE1c"
CHAT_ID = "908015235"
OLX_URL = "https://www.olx.pl/elektronika/komputery/podzespoly-i-czesci/q-pami%C4%99%C4%87-ram-ddr4-8gb/?search%5Bfilter_float_price%3Afrom%5D=100&search%5Bfilter_float_price%3Ato%5D=250&search%5Border%5D=created_at%3Adesc"

# --- ПРОКСИ ---
PROXY = {
    "server": "http://64.137.96.74:6641",
    "username": "nyntgqyu",
    "password": "2c5wo0xukywv"
}

# --- ВЕБ-СЕРВЕР ---
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
        self.browser = None
        self.playwright = None

    async def init_browser(self):
        """Запускаем настоящий Chrome"""
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled'
                ]
            )
            print("✅ Chrome запущен")
            sys.stdout.flush()
        except Exception as e:
            print(f"❌ Не удалось запустить Chrome: {e}")
            sys.stdout.flush()

    async def fetch_ads(self):
        try:
            if not self.browser:
                await self.init_browser()

            if not self.browser:
                return []

            # Создаём контекст с прокси и настройками браузера
            context = await self.browser.new_context(
                proxy=PROXY,
                viewport={"width": 1920, "height": 1080},
                locale="pl-PL",
                timezone_id="Europe/Warsaw",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )

            # Убираем признаки автоматизации
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['pl-PL', 'pl', 'en-US', 'en']});
                window.chrome = {runtime: {}};
            """)

            page = await context.new_page()

            try:
                # ШАГ 1: Главная страница — cookies
                print("🌐 Шаг 1: Главная OLX...")
                sys.stdout.flush()
                await page.goto("https://www.olx.pl/", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(random.randint(2000, 4000))

                # Принимаем cookies если есть кнопка
                try:
                    cookie_btn = page.locator("button#onetrust-accept-btn-handler")
                    if await cookie_btn.is_visible(timeout=3000):
                        await cookie_btn.click()
                        print("   🍪 Cookies приняты")
                        await page.wait_for_timeout(1000)
                except:
                    pass

                # ШАГ 2: Страница с объявлениями
                print("🔍 Шаг 2: Объявления...")
                sys.stdout.flush()
                await page.goto(OLX_URL, wait_until="domcontentloaded", timeout=30000)

                # Ждём загрузки объявлений
                try:
                    await page.wait_for_selector("[data-cy='l-card']", timeout=15000)
                    print("   ✅ Карточки загрузились!")
                except:
                    print("   ⚠️ Карточки не появились, жду ещё...")
                    await page.wait_for_timeout(5000)

                # Скроллим вниз для подгрузки
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                await page.wait_for_timeout(2000)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

                # Получаем HTML
                html = await page.content()
                print(f"   📄 HTML: {len(html)} символов")

                soup = BeautifulSoup(html, "html.parser")
                ads = []

                # === МЕТОД 1: __NEXT_DATA__ ===
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

                # === МЕТОД 2: data-cy карточки ===
                cards = soup.find_all("div", {"data-cy": "l-card"})
                print(f"   📋 Карточек: {len(cards)}")

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

                # === МЕТОД 3: Через JavaScript напрямую ===
                print("   🔧 Пробую JS извлечение...")
                try:
                    js_ads = await page.evaluate("""
                        () => {
                            const cards = document.querySelectorAll('[data-cy="l-card"]');
                            const results = [];
                            cards.forEach(card => {
                                const link = card.querySelector('a[href*="/d/oferta/"]');
                                const titleEl = card.querySelector('h6') || card.querySelector('h4');
                                const priceEl = card.querySelector('[data-testid="ad-price"]');
                                if (link) {
                                    results.push({
                                        title: titleEl ? titleEl.textContent.trim() : 'Без названия',
                                        url: link.href,
                                        price: priceEl ? priceEl.textContent.trim() : '?'
                                    });
                                }
                            });
                            return results;
                        }
                    """)
                    if js_ads:
                        for ad in js_ads:
                            ad['url'] = ad['url'].split("#")[0].split("?")[0].rstrip('/')
                        print(f"✅ [JS] → {len(js_ads)}")
                        return js_ads
                except Exception as e:
                    print(f"   ⚠️ JS: {e}")

                # === МЕТОД 4: Все ссылки ===
                for a in soup.find_all("a", href=True):
                    href = a['href']
                    if '/d/oferta/' in href:
                        url = href if href.startswith("http") else "https://www.olx.pl" + href
                        clean = url.split("#")[0].split("?")[0].rstrip('/')
                        existing = [x['url'] for x in ads]
                        if clean not in existing:
                            ads.append({
                                "title": a.get_text(strip=True)[:100] or "Без названия",
                                "url": clean,
                                "price": "?"
                            })

                if ads:
                    print(f"✅ [LINKS] → {len(ads)}")
                else:
                    preview = soup.get_text(separator=" ", strip=True)[:300]
                    print(f"⚠️ Пусто! Текст: {preview}")

                    # Скриншот для дебага
                    try:
                        await page.screenshot(path="/tmp/debug.png")
                        print("   📸 Скриншот сохранён")
                    except:
                        pass

                return ads

            finally:
                await context.close()

        except Exception as e:
            print(f"❌ Ошибка: {e}")
            sys.stdout.flush()
            # Перезапускаем браузер при ошибке
            try:
                if self.browser:
                    await self.browser.close()
                if self.playwright:
                    await self.playwright.stop()
            except:
                pass
            self.browser = None
            self.playwright = None
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
                    price = pd.get("displayValue", pd.get("regularPrice", {}).get("displayValue", "?"))
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
        print("🚀 БОТ СТАРТОВАЛ (Playwright Chrome)")
        print("🌐 Прокси: Испания")
        print("=" * 50)
        sys.stdout.flush()

        try:
            await self.bot.send_message(
                CHAT_ID,
                "✅ Мониторинг запущен!\n"
                "🖥 Движок: Chrome (Playwright)\n"
                "🌐 Прокси: Испания\n"
                "🔄 Проверка каждые 5-7 минут"
            )
        except Exception as e:
            print(f"❌ Telegram: {e}")

        fail_count = 0

        while True:
            try:
                ads = await self.fetch_ads()
                print(f"📊 Итого: {len(ads)}")
                sys.stdout.flush()

                if ads:
                    fail_count = 0
                    if not self.seen_ads:
                        for ad in ads:
                            self.seen_ads.add(ad['url'])
                        await self.bot.send_message(
                            CHAT_ID,
                            f"📡 База: {len(ads)} объявлений\n🔍 Слежу..."
                        )
                        print(f"✅ База: {len(ads)}")
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
                        if self.browser:
                            try:
                                await self.browser.close()
                            except:
                                pass
                        self.browser = None
                        try:
                            await self.bot.send_message(CHAT_ID, "⚠️ 5 неудач, перезапускаю Chrome...")
                        except:
                            pass

                sys.stdout.flush()

            except Exception as e:
                print(f"❌ Ошибка: {e}")
                self.browser = None

            delay = random.randint(300, 420)
            print(f"⏳ Через {delay // 60}м {delay % 60}с")
            sys.stdout.flush()
            await asyncio.sleep(delay)


if __name__ == "__main__":
    monitor = OLXProMonitor()
    asyncio.run(monitor.run())

