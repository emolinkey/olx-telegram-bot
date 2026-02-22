import os
import asyncio
import httpx
import random
import json
import threading
import logging
from datetime import datetime
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from flask import Flask

TOKEN = "8346602599:AAGz22SEJw5dCJVxVXUAli-pf1Xzf424ZT4"
ADMIN_ID = 908015235
RENDER_URL = "https://olx-telegram-bot-1-hi5z.onrender.com"

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


def clean_url(url):
    """Убираем tracking параметры, оставляем чистый URL"""
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://www.olx.pl" + url
    # Убираем всё после # и ?
    url = url.split("#")[0].split("?")[0].rstrip('/')
    # Убираем .html если есть
    if url.endswith(".html"):
        url = url[:-5]
    return url


class OLXParser:
    def __init__(self):
        self.seen = set()  # Храним чистые URL
        self.total_found = 0
        self.total_new = 0
        self.last_check = None
        self.errors = 0
        self.base_ready = False

    async def fetch(self, url=None):
        try:
            target_url = url or Config.url
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

                r = await client.get(target_url)
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
                        curl = clean_url(href)
                        if not curl:
                            continue
                        title_el = card.find("h6") or card.find("h4")
                        title = title_el.get_text(strip=True) if title_el else "?"
                        price_el = card.find("p", {"data-testid": "ad-price"})
                        price = price_el.get_text(strip=True) if price_el else "?"
                        ads.append({"key": curl, "title": title, "url": curl, "price": price})

                if not ads:
                    seen_urls = set()
                    for a in soup.find_all("a", href=True):
                        if '/d/oferta/' in a['href']:
                            curl = clean_url(a['href'])
                            if curl and curl not in seen_urls:
                                seen_urls.add(curl)
                                ads.append({"key": curl, "title": a.get_text(strip=True)[:80] or "?", "url": curl, "price": "?"})

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
            curl = clean_url(url)
            if not curl:
                continue

            title = item.get("title", "?")
            price = "?"
            pd = item.get("price", {})
            if isinstance(pd, dict):
                price = pd.get("displayValue") or "?"

            # Ключ = чистый URL (стабильный и уникальный)
            ads.append({"key": curl, "title": title, "url": curl, "price": price})
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
    b = "✅ Готова" if parser.base_ready else "⏳ Собирается"
    await msg.answer(
        f"📊 Статус\n\n{s}\nБаза: {b}\n"
        f"В базе: {len(parser.seen)}\n"
        f"Интервал: {Config.interval}с\nНовых: {parser.total_new}\n"
        f"Ошибок: {parser.errors}\nПроверка: {parser.last_check or 'нет'}\n"
        f"Прокси: {Config.proxy or 'нет'}"
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
    parser.seen.clear()
    parser.base_ready = False
    parser.total_new = 0
    await msg.answer("✅ URL обновлён, база сброшена")


@dp.message(Command("proxy"))
async def cmd_proxy(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        return await msg.answer("Пример: /proxy http://user:pass@ip:port")
    Config.proxy = parts[1].strip()
    await msg.answer("✅ Прокси установлен")


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
    new = [a for a in ads if a['key'] not in parser.seen]
    await msg.answer(f"Всего: {len(ads)} | В базе: {len(parser.seen)} | Новых: {len(new)}")


@dp.message(Command("reset"))
async def cmd_reset(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parser.seen.clear()
    parser.base_ready = False
    parser.total_new = 0
    await msg.answer("🗑 База очищена, соберу заново")


@dp.message(Command("stats"))
async def cmd_stats(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await msg.answer(
        f"📈 В базе: {len(parser.seen)} | Найдено: {parser.total_found} | "
        f"Новых: {parser.total_new} | Ошибок: {parser.errors}"
    )


async def keep_alive():
    while True:
        await asyncio.sleep(600)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.get(RENDER_URL)
            log.info("💓 Пинг")
        except:
            pass


async def collect_all_ads():
    all_ads = []
    seen_in_batch = set()
    sep = "&" if "?" in Config.url else "?"

    for page in range(1, 6):
        if page == 1:
            ads = await parser.fetch()
        else:
            ads = await parser.fetch(url=Config.url + f"{sep}page={page}")

        if ads:
            for ad in ads:
                if ad['key'] not in seen_in_batch:
                    seen_in_batch.add(ad['key'])
                    all_ads.append(ad)
            log.info(f"   Стр.{page}: +{len(ads)} (уникальных: {len(all_ads)})")
        else:
            break

        await asyncio.sleep(random.uniform(3, 6))

    return all_ads


async def silent_add(ads):
    """Молча добавляем в базу"""
    added = 0
    if ads:
        for ad in ads:
            if ad['key'] not in parser.seen:
                parser.seen.add(ad['key'])
                added += 1
    return added


async def monitoring_loop():
    await asyncio.sleep(5)

    try:
        await bot.send_message(ADMIN_ID, "🚀 OLX Sniper запущен!\n⏳ Калибровка (~20 мин)...")
    except Exception as e:
        log.error(f"Telegram: {e}")
        return

    # === ФАЗА 1: СБОР БАЗЫ (5 страниц) ===
    log.info("📦 ФАЗА 1: Сбор базы...")
    ads = await collect_all_ads()
    await silent_add(ads)
    log.info(f"   База: {len(parser.seen)}")

    # === ФАЗА 2: ПРОГРЕВ (5 проверок по ~1 мин) ===
    log.info("🔥 ФАЗА 2: Прогрев...")
    for i in range(5):
        await asyncio.sleep(random.uniform(40, 70))
        ads = await parser.fetch()
        added = await silent_add(ads)
        log.info(f"   Прогрев {i+1}/5: +{added} (база: {len(parser.seen)})")

    # === ФАЗА 3: ТИХИЕ ПРОВЕРКИ (3 по ~5 мин) ===
    log.info("🔇 ФАЗА 3: Тихие проверки...")
    for i in range(3):
        delay = Config.interval + random.randint(10, 60)
        log.info(f"   Тихая {i+1}/3: жду {delay // 60}м {delay % 60}с")
        await asyncio.sleep(delay)
        ads = await parser.fetch()
        added = await silent_add(ads)
        log.info(f"   Тихая {i+1}/3: +{added} (база: {len(parser.seen)})")

    parser.base_ready = True
    log.info(f"✅ Калибровка завершена. База: {len(parser.seen)}")

    try:
        await bot.send_message(
            ADMIN_ID,
            f"✅ Готово! База: {len(parser.seen)} объявлений\n"
            f"🔍 Присылаю ТОЛЬКО новые!\n"
            f"⏱ Интервал: ~{Config.interval // 60} мин"
        )
    except:
        pass

    # === ФАЗА 4: МОНИТОРИНГ ===
    log.info("👁 ФАЗА 4: Мониторинг")

    while True:
        if not Config.is_running:
            await asyncio.sleep(10)
            continue

        if not parser.base_ready:
            try:
                await bot.send_message(ADMIN_ID, "⏳ Пересобираю базу...")
            except:
                pass
            ads = await collect_all_ads()
            await silent_add(ads)
            for i in range(5):
                await asyncio.sleep(random.uniform(40, 70))
                ads = await parser.fetch()
                await silent_add(ads)
            for i in range(3):
                await asyncio.sleep(Config.interval + random.randint(10, 60))
                ads = await parser.fetch()
                await silent_add(ads)
            parser.base_ready = True
            try:
                await bot.send_message(ADMIN_ID, f"✅ База: {len(parser.seen)}")
            except:
                pass
            continue

        delay = Config.interval + random.randint(10, 60)
        log.info(f"⏳ Жду {delay // 60}м {delay % 60}с")
        await asyncio.sleep(delay)

        ads = await parser.fetch()
        if not ads:
            log.warning("Нет данных")
            continue

        new_count = 0
        for ad in ads:
            if ad['key'] not in parser.seen:
                parser.seen.add(ad['key'])
                parser.total_new += 1
                new_count += 1
                try:
                    await bot.send_message(
                        ADMIN_ID,
                        f"🆕 НОВОЕ ОБЪЯВЛЕНИЕ!\n\n"
                        f"📦 {ad['title']}\n"
                        f"💰 {ad['price']}\n"
                        f"🔗 {ad['url']}",
                        disable_web_page_preview=True
                    )
                    await asyncio.sleep(1)
                except Exception as e:
                    log.error(f"Отправка: {e}")

        if new_count:
            log.info(f"🆕 Отправлено: {new_count}")
        else:
            log.info(f"ℹ️ Новых нет (база: {len(parser.seen)})")


async def main():
    threading.Thread(target=run_flask, daemon=True).start()

    log.info("⏳ Жду 60 сек...")
    await asyncio.sleep(60)

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(5)

    log.info("🚀 OLX SNIPER ЗАПУЩЕН")

    logging.getLogger("aiogram.dispatcher").setLevel(logging.CRITICAL)
    logging.getLogger("aiogram.event").setLevel(logging.CRITICAL)

    await asyncio.gather(
        dp.start_polling(bot, skip_updates=True),
        monitoring_loop(),
        keep_alive()
    )


if __name__ == "__main__":
    asyncio.run(main())
