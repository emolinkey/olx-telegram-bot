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
                        url_full = href if href.startswith("http") else "https://www.olx.pl" + href
                        clean = url_full.split("#")[0].split("?")[0].rstrip('/')
                        title_el = card.find("h6") or card.find("h4")
                        title = title_el.get_text(strip=True) if title_el else "?"
                        price_el = card.find("p", {"data-testid": "ad-price"})
                        price = price_el.get_text(strip=True) if price_el else "?"
                        ads.append({"title": title, "url": clean, "price": price})

                if not ads:
                    seen = set()
                    for a in soup.find_all("a", href=True):
                        if '/d/oferta/' in a['href']:
                            href = a['href']
                            url_full = href if href.startswith("http") else "https://www.olx.pl" + href
                            clean = url_full.split("#")[0].split("?")[0].rstrip('/')
                            if clean not in seen:
                                seen.add(clean)
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
    b = "✅ Готова" if parser.base_ready else "⏳ Собирается"
    await msg.answer(
        f"📊 Статус\n\n{s}\nБаза: {b}\nВ базе: {len(parser.seen_ads)}\n"
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
    parser.seen_ads.clear()
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
    new = [a for a in ads if a['url'] not in parser.seen_ads]
    await msg.answer(f"Всего: {len(ads)} | В базе: {len(parser.seen_ads)} | Новых: {len(new)}")


@dp.message(Command("reset"))
async def cmd_reset(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parser.seen_ads.clear()
    parser.base_ready = False
    parser.total_new = 0
    await msg.answer("🗑 База очищена, соберу заново")


@dp.message(Command("stats"))
async def cmd_stats(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await msg.answer(
        f"📈 В базе: {len(parser.seen_ads)} | Найдено: {parser.total_found} | "
        f"Новых: {parser.total_new} | Ошибок: {parser.errors}"
    )


async def build_base():
    """Собираем базу с нескольких страниц МОЛЧА"""
    log.info("📦 Собираю базу...")

    # Страница 1
    ads = await parser.fetch()
    if ads:
        for ad in ads:
            parser.seen_ads.add(ad['url'])
        log.info(f"   Стр.1: +{len(ads)} (база: {len(parser.seen_ads)})")

    await asyncio.sleep(random.uniform(3, 6))

    # Страница 2
    sep = "&" if "?" in Config.url else "?"
    ads2 = await parser.fetch(url=Config.url + f"{sep}page=2")
    if ads2:
        for ad in ads2:
            parser.seen_ads.add(ad['url'])
        log.info(f"   Стр.2: +{len(ads2)} (база: {len(parser.seen_ads)})")

    await asyncio.sleep(random.uniform(3, 6))

    # Страница 3
    ads3 = await parser.fetch(url=Config.url + f"{sep}page=3")
    if ads3:
        for ad in ads3:
            parser.seen_ads.add(ad['url'])
        log.info(f"   Стр.3: +{len(ads3)} (база: {len(parser.seen_ads)})")

    # Делаем вторую проверку страницы 1 через паузу
    # чтобы поймать объявления которые могли появиться между запросами
    await asyncio.sleep(random.uniform(2, 4))
    ads_recheck = await parser.fetch()
    if ads_recheck:
        for ad in ads_recheck:
            parser.seen_ads.add(ad['url'])

    parser.base_ready = True
    log.info(f"✅ База готова: {len(parser.seen_ads)} объявлений")
    return len(parser.seen_ads)


async def monitoring_loop():
    await asyncio.sleep(5)

    # Приветствие
    try:
        await bot.send_message(ADMIN_ID, "🚀 OLX Sniper запущен!\n⏳ Собираю базу...")
    except Exception as e:
        log.error(f"Telegram: {e}")
        return

    # === СБОР БАЗЫ — НИЧЕГО НЕ ОТПРАВЛЯЕМ ===
    base_count = await build_base()

    try:
        await bot.send_message(
            ADMIN_ID,
            f"✅ База готова: {base_count} объявлений\n"
            f"🔍 Слежу ТОЛЬКО за новыми!\n"
            f"⏱ Интервал: ~{Config.interval // 60} мин"
        )
    except:
        pass

    # === ОСНОВНОЙ ЦИКЛ — ТОЛЬКО НОВЫЕ ===
    while True:
        if not Config.is_running:
            await asyncio.sleep(10)
            continue

        # Если база сброшена (/reset или /url) — собираем заново
        if not parser.base_ready:
            try:
                await bot.send_message(ADMIN_ID, "⏳ Собираю новую базу...")
            except:
                pass
            base_count = await build_base()
            try:
                await bot.send_message(ADMIN_ID, f"✅ Новая база: {base_count} объявлений")
            except:
                pass
            continue

        # Ждём перед проверкой
        delay = Config.interval + random.randint(10, 60)
        log.info(f"⏳ Жду {delay // 60}м {delay % 60}с")
        await asyncio.sleep(delay)

        # Проверяем
        ads = await parser.fetch()
        if not ads:
            log.warning("Не удалось получить данные")
            continue

        # Ищем новые
        new_count = 0
        for ad in ads:
            if ad['url'] not in parser.seen_ads:
                parser.seen_ads.add(ad['url'])
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
            log.info(f"🆕 Отправлено новых: {new_count}")
        else:
            log.info(f"ℹ️ Новых нет (база: {len(parser.seen_ads)})")


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
