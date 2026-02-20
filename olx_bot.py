import os
import asyncio
import httpx
import random
import sys
import json
import threading
import logging
from datetime import datetime
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from flask import Flask

TOKEN = "8346602599:AAGz22SEJw5dCJVxVXUAli-pf1Xzf424ZT4"
ADMIN_ID = 908015235

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("OLX")

class Config:
    url = "https://www.olx.pl/elektronika/telefony/q-iphone-13-pro/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=500&search%5Bfilter_float_price:to%5D=1500"
    interval = 300
    is_running = True
    proxy = None

app = Flask('')

@app.route('/')
def home():
    return "OLX Sniper Online"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

class OLXParser:
    def __init__(self):
        self.seen_ads = set()
        self.total_found = 0
        self.total_new = 0
        self.last_check = None
        self.errors = 0

    async def fetch(self):
        try:
            v = random.choice(["120", "121", "122", "123", "124", "125"])
            headers = {
                "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/{v}.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pl-PL,pl;q=0.9",
                "Sec-Ch-Ua": f'"Chromium";v="{v}", "Google Chrome";v="{v}"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Upgrade-Insecure-Requests": "1",
            }

            async with httpx.AsyncClient(headers=headers, timeout=25, follow_redirects=True, proxies=Config.proxy) as client:
                try:
                    await client.get("https://www.olx.pl/")
                    await asyncio.sleep(random.uniform(1, 3))
                except:
                    pass

                r = await client.get(Config.url)
                log.info(f"OLX: {r.status_code}")

                if r.status_code != 200:
                    self.errors += 1
                    return None

                self.errors = 0
                self.last_check = datetime.now().strftime("%H:%M:%S")
                soup = BeautifulSoup(r.text, "lxml")
                ads = []

                script = soup.find("script", id="__NEXT_DATA__")
                if script and script.string:
                    try:
                        data = json.loads(script.string)
                        ads = self._parse_json(data)
                        if ads:
                            self.total_found = len(ads)
                            return ads
                    except:
                        pass

                cards = soup.find_all("div", {"data-cy": "l-card"})
                for card in cards:
                    link = card.find("a", href=True)
                    if link and '/d/oferta/' in link.get('href', ''):
                        href = link['href']
                        url = href if href.startswith("http") else "https://www.olx.pl" + href
                        clean = url.split("#")[0].split("?")[0].rstrip('/')
                        title_el = card.find("h6") or card.find("h4")
                        title = title_el.get_text(strip=True) if title_el else "?"
                        price_el = card.find("p", {"data-testid": "ad-price"})
                        price = price_el.get_text(strip=True) if price_el else "?"
                        ads.append({"title": title, "url": clean, "price": price})

                if not ads:
                    for a in soup.find_all("a", href=True):
                        if '/d/oferta/' in a['href']:
                            href = a['href']
                            url = href if href.startswith("http") else "https://www.olx.pl" + href
                            clean = url.split("#")[0].split("?")[0].rstrip('/')
                            ads.append({"title": a.get_text(strip=True)[:80] or "?", "url": clean, "price": "?"})

                self.total_found = len(ads)
                return ads if ads else None

        except Exception as e:
            self.errors += 1
            log.error(f"Ошибка: {e}")
            return None

    def _parse_json(self, data):
        ads = []
        props = data.get("props", {}).get("pageProps", {})
        items = []
        for fn in [
            lambda: props.get("listing", {}).get("listing", {}).get("ads", []),
            lambda: props.get("listing", {}).get("ads", []),
            lambda: props.get("data", {}).get("items", []),
            lambda: props.get("ads", []),
        ]:
            try:
                r = fn()
                if r and isinstance(r, list) and len(r) > 0:
                    items = r
                    break
            except:
                continue

        for item in items:
            if not isinstance(item, dict):
                continue
            url = item.get("url", "")
            if not url:
                continue
            if not url.startswith("http"):
                url = "https://www.olx.pl" + url
            clean = url.split("#")[0].split("?")[0].rstrip('/')
            title = item.get("title", "?")
            price = "?"
            pd = item.get("price", {})
            if isinstance(pd, dict):
                price = pd.get("displayValue") or "?"
            ads.append({"title": title, "url": clean, "price": price})
        return ads

bot = Bot(token=TOKEN)
dp = Dispatcher()
parser = OLXParser()

@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await msg.answer(
        "🎯 OLX Sniper Bot\n\n"
        "/status — статус\n"
        "/pause — пауза\n"
        "/resume — продолжить\n"
        "/interval 180 — интервал\n"
        "/url <ссылка> — сменить поиск\n"
        "/proxy <прокси> — прокси\n"
        "/noproxy — убрать прокси\n"
        "/check — проверить сейчас\n"
        "/reset — сбросить базу\n"
        "/stats — статистика"
    )

@dp.message(Command("status"))
async def cmd_status(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    s = "🟢 Работает" if Config.is_running else "🔴 Пауза"
    await msg.answer(
        f"📊 Статус\n\n{s}\nИнтервал: {Config.interval}с\n"
        f"В базе: {len(parser.seen_ads)}\nОшибок: {parser.errors}\n"
        f"Проверка: {parser.last_check or 'нет'}\nПрокси: {Config.proxy or 'нет'}"
    )

@dp.message(Command("pause"))
async def cmd_pause(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    Config.is_running = False
    await msg.answer("⏸ Пауза")

@dp.message(Command("resume"))
async def cmd_resume(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    Config.is_running = True
    await msg.answer("▶️ Возобновлено")

@dp.message(Command("interval"))
async def cmd_interval(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        sec = int(msg.text.split()[1])
        if 60 <= sec <= 3600:
            Config.interval = sec
            await msg.answer(f"✅ Интервал: {sec}с")
        else:
            await msg.answer("60-3600 сек")
    except:
        await msg.answer("Пример: /interval 180")

@dp.message(Command("url"))
async def cmd_url(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2 or "olx.pl" not in parts[1]:
        return await msg.answer("Пример: /url https://www.olx.pl/...")
    Config.url = parts[1].strip()
    parser.seen_ads.clear()
    await msg.answer(f"✅ URL обновлён, база сброшена")

@dp.message(Command("proxy"))
async def cmd_proxy(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        return await msg.answer("Пример: /proxy http://user:pass@ip:port")
    Config.proxy = parts[1].strip()
    await msg.answer(f"✅ Прокси установлен")

@dp.message(Command("noproxy"))
async def cmd_noproxy(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    Config.proxy = None
    await msg.answer("✅ Прокси убран")

@dp.message(Command("check"))
async def cmd_check(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await msg.answer("🔍 Проверяю...")
    ads = await parser.fetch()
    if not ads:
        return await msg.answer("❌ Ничего не найдено")
    new = [a for a in ads if a['url'] not in parser.seen_ads]
    await msg.answer(f"Всего: {len(ads)} | Новых: {len(new)}")

@dp.message(Command("reset"))
async def cmd_reset(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parser.seen_ads.clear()
    await msg.answer("🗑 База очищена")

@dp.message(Command("stats"))
async def cmd_stats(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await msg.answer(
        f"📈 В базе: {len(parser.seen_ads)} | Найдено: {parser.total_found} | "
        f"Новых: {parser.total_new} | Ошибок: {parser.errors}"
    )

async def monitoring_loop():
    await asyncio.sleep(5)
    try:
        await bot.send_message(ADMIN_ID, "🚀 OLX Sniper запущен!\nНапиши /start")
    except Exception as e:
        log.error(f"Telegram: {e}")
        return

    # ПЕРВЫЙ ЗАПУСК: собираем базу БЕЗ отправки
    log.info("Собираю начальную базу...")
    first_ads = await parser.fetch()
    if first_ads:
        parser.seen_ads.update(a['url'] for a in first_ads)
        log.info(f"База собрана: {len(first_ads)} объявлений (не отправляю)")
        try:
            await bot.send_message(
                ADMIN_ID,
                f"📡 База собрана: {len(first_ads)} объявлений\n"
                f"🔍 Теперь слежу ТОЛЬКО за новыми!"
            )
        except:
            pass
    else:
        log.warning("Не удалось собрать базу, попробую позже")

    # ОСНОВНОЙ ЦИКЛ: отправляю только новые
    while True:
        if Config.is_running:
            delay = Config.interval + random.randint(10, 60)
            log.info(f"Жду {delay // 60}м {delay % 60}с")
            await asyncio.sleep(delay)

            ads = await parser.fetch()
            if ads:
                if not parser.seen_ads:
                    # База пустая (первый сбор не удался) — просто сохраняем
                    parser.seen_ads.update(a['url'] for a in ads)
                    log.info(f"База собрана: {len(ads)}")
                    try:
                        await bot.send_message(ADMIN_ID, f"📡 База: {len(ads)} объявлений")
                    except:
                        pass
                else:
                    # Ищем ТОЛЬКО новые
                    for ad in ads:
                        if ad['url'] not in parser.seen_ads:
                            parser.seen_ads.add(ad['url'])
                            parser.total_new += 1
                            try:
                                await bot.send_message(
                                    ADMIN_ID,
                                    f"🆕 НОВОЕ!\n\n📦 {ad['title']}\n💰 {ad['price']}\n🔗 {ad['url']}",
                                    disable_web_page_preview=True
                                )
                                log.info(f"🆕 {ad['title']}")
                                await asyncio.sleep(1)
                            except:
                                pass
        else:
            await asyncio.sleep(10)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    threading.Thread(target=run_flask, daemon=True).start()
    log.info("🚀 OLX SNIPER ЗАПУЩЕН")
    await asyncio.gather(
        dp.start_polling(bot, skip_updates=True),
        monitoring_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())


