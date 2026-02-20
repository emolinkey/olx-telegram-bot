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
        self.seen_ids = set()
        self.total_found = 0
        self.total_new = 0
        self.last_check = None
        self.errors = 0
        self.base_ready = False
        self.warmup_done = False
        self.check_count = 0

    def _extract_id(self, url):
        """Извлекаем уникальный ID объявления из URL"""
        # URL: https://www.olx.pl/d/oferta/iphone-13-pro-CID99-ID19tZx6.html
        # ID: ID19tZx6
        clean = url.split("#")[0].split("?")[0].rstrip('/')
        # Берём последнюю часть после последнего дефиса
        parts = clean.rstrip('.html').split('-')
        if parts:
            return parts[-1]  # например ID19tZx6
        return clean

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
                        ad_id = self._extract_id(clean)
                        ads.append({"id": ad_id, "title": title, "url": clean, "price": price})

                if not ads:
                    seen = set()
                    for a in soup.find_all("a", href=True):
                        if '/d/oferta/' in a['href']:
                            href = a['href']
                            url_full = href if href.startswith("http") else "https://www.olx.pl" + href
                            clean = url_full.split("#")[0].split("?")[0].rstrip('/')
                            if clean not in seen:
                                seen.add(clean)
                                ad_id = self._extract_id(clean)
                                ads.append({"id": ad_id, "title": a.get_text(strip=True)[:80] or "?", "url": clean, "price": "?"})

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

            # Используем OLX ID если есть, иначе из URL
            ad_id = str(item.get("id", "")) or self._extract_id(clean)

            title = item.get("title", "?")
            price = "?"
            pd = item.get("price", {})
            if isinstance(pd, dict):
                price = pd.get("displayValue") or "?"
            ads.append({"id": ad_id, "title": title, "url": clean, "price": price})
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
    w = "✅ Да" if parser.warmup_done else f"⏳ Проверка {parser.check_count}/3"
    await msg.answer(
        f"📊 Статус\n\n{s}\nБаза: {b}\nПрогрев: {w}\n"
        f"В базе: {len(parser.seen_ids)} ID\n"
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
    parser.seen_ids.clear()
    parser.base_ready = False
    parser.warmup_done = False
    parser.check_count = 0
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
    new = [a for a in ads if a['id'] not in parser.seen_ids]
    await msg.answer(f"Всего: {len(ads)} | В базе: {len(parser.seen_ids)} | Новых: {len(new)}")


@dp.message(Command("reset"))
async def cmd_reset(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parser.seen_ids.clear()
    parser.base_ready = False
    parser.warmup_done = False
    parser.check_count = 0
    parser.total_new = 0
    await msg.answer("🗑 База очищена, соберу заново")


@dp.message(Command("stats"))
async def cmd_stats(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await msg.answer(
        f"📈 В базе: {len(parser.seen_ids)} | Найдено: {parser.total_found} | "
        f"Новых: {parser.total_new} | Ошибок: {parser.errors}"
    )


async def collect_all_ads():
    """Собираем ВСЕ объявления с 5 страниц"""
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
                if ad['id'] not in seen_in_batch:
                    seen_in_batch.add(ad['id'])
                    all_ads.append(ad)
            log.info(f"   Стр.{page}: +{len(ads)} (уникальных: {len(all_ads)})")
        else:
            break

        await asyncio.sleep(random.uniform(3, 6))

    return all_ads


async def monitoring_loop():
    await asyncio.sleep(5)

    # Приветствие
    try:
        await bot.send_message(ADMIN_ID, "🚀 OLX Sniper запущен!\n⏳ Собираю базу (~3 мин)...")
    except Exception as e:
        log.error(f"Telegram: {e}")
        return

    # === ФАЗА 1: СБОР БАЗЫ (5 страниц, молча) ===
    log.info("📦 ФАЗА 1: Сбор базы...")
    ads = await collect_all_ads()
    if ads:
        for ad in ads:
            parser.seen_ids.add(ad['id'])
    log.info(f"   После сбора: {len(parser.seen_ids)} ID")

    # === ФАЗА 2: ПРОГРЕВ (3 проверки, молча — добираем пропущенные) ===
    log.info("🔥 ФАЗА 2: Прогрев (3 проверки)...")
    try:
        await bot.send_message(ADMIN_ID, f"📦 База: {len(parser.seen_ids)} ID\n🔥 Прогрев (3 проверки, ~3 мин)...")
    except:
        pass

    for i in range(3):
        await asyncio.sleep(random.uniform(30, 60))
        ads = await parser.fetch()
        if ads:
            added = 0
            for ad in ads:
                if ad['id'] not in parser.seen_ids:
                    parser.seen_ids.add(ad['id'])
                    added += 1
            log.info(f"   Прогрев {i+1}/3: добавлено {added} (база: {len(parser.seen_ids)})")
            parser.check_count = i + 1

    parser.base_ready = True
    parser.warmup_done = True
    log.info(f"✅ Прогрев завершён. База: {len(parser.seen_ids)} ID")

    try:
        await bot.send_message(
            ADMIN_ID,
            f"✅ Готово! База: {len(parser.seen_ids)} объявлений\n"
            f"🔍 Теперь присылаю ТОЛЬКО новые!\n"
            f"⏱ Интервал: ~{Config.interval // 60} мин"
        )
    except:
        pass

    # === ФАЗА 3: МОНИТОРИНГ (только новые) ===
    log.info("👁 ФАЗА 3: Мониторинг")

    while True:
        if not Config.is_running:
            await asyncio.sleep(10)
            continue

        # Если база сброшена
        if not parser.base_ready:
            try:
                await bot.send_message(ADMIN_ID, "⏳ Пересобираю базу...")
            except:
                pass

            ads = await collect_all_ads()
            if ads:
                for ad in ads:
                    parser.seen_ids.add(ad['id'])

            for i in range(3):
                await asyncio.sleep(random.uniform(30, 60))
                check = await parser.fetch()
                if check:
                    for ad in check:
                        parser.seen_ids.add(ad['id'])

            parser.base_ready = True
            parser.warmup_done = True

            try:
                await bot.send_message(ADMIN_ID, f"✅ База пересобрана: {len(parser.seen_ids)} ID")
            except:
                pass
            continue

        # Ждём
        delay = Config.interval + random.randint(10, 60)
        log.info(f"⏳ Жду {delay // 60}м {delay % 60}с")
        await asyncio.sleep(delay)

        # Проверяем страницу 1
        ads = await parser.fetch()
        if not ads:
            log.warning("Нет данных")
            continue

        # Ищем новые
        new_count = 0
        for ad in ads:
            if ad['id'] not in parser.seen_ids:
                parser.seen_ids.add(ad['id'])
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
            log.info(f"ℹ️ Новых нет (база: {len(parser.seen_ids)})")


async def main():
    threading.Thread(target=run_flask, daemon=True).start()

    log.info("⏳ Жду 60 сек (убиваю старую копию)...")
    await asyncio.sleep(60)

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(5)

    log.info("🚀 OLX SNIPER ЗАПУЩЕН")

    # Подавляем Conflict в логах
    logging.getLogger("aiogram.dispatcher").setLevel(logging.CRITICAL)
    logging.getLogger("aiogram.event").setLevel(logging.CRITICAL)

    await asyncio.gather(
        dp.start_polling(bot, skip_updates=True),
        monitoring_loop()
    )


if __name__ == "__main__":
    asyncio.run(main())


