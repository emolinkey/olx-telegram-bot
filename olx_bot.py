import os
import asyncio
import httpx
import random
import json
import threading
import logging
import re
import hashlib
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from flask import Flask

TOKEN = "8346602599:AAEwnr6M2pdGok_11btAtLJU81YvDoSqS7E".strip()
ADMIN_ID = 908015235
RENDER_URL = "https://olx-telegram-bot-9suv.onrender.com"
DEVELOPER_ID = 908015235
VERSION = "3.3"
BUILD = hashlib.md5(TOKEN.encode()).hexdigest()[:8] if TOKEN else "000"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("BOT")

ALLOWED_HOSTS = ["onrender.com", "render.com", "127.0.0.1", "localhost"]
def verify_host():
    if RENDER_URL and not any(h in RENDER_URL.lower() for h in ALLOWED_HOSTS):
        os._exit(1)
    if not TOKEN or not ADMIN_ID:
        os._exit(1)
verify_host()


class Config:
    url = "https://www.olx.pl/oferty/q-iphone/?search%5Bfilter_float_price:from%5D=100&search%5Bfilter_float_price:to%5D=4000"
    interval = 120          # 2 минуты — быстрее ловим
    is_running = True
    notify_sound = True


app = Flask('')

@app.route('/')
def home():
    return "OK"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))


class OLXParser:
    def __init__(self):
        self.seen = set()
        self.last_check = None
        self.errors = 0
        self.base_ready = False
        self.start_time = None
        self.total_sent = 0

    def _headers(self):
        v = random.choice(["120", "121", "122", "123", "124", "125", "126"])
        p = random.choice(["0", "1", "2", "3"])
        return {
            "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.{p} Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
            "Accept-Encoding": "identity",
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Upgrade-Insecure-Requests": "1",
            "Connection": "keep-alive",
        }

    async def fetch(self, url=None):
        target = url or Config.url
        if not target:
            return None
        try:
            headers = self._headers()
            async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
                try:
                    await client.get("https://www.olx.pl/", headers=headers)
                    await asyncio.sleep(random.uniform(1.0, 2.0))
                except:
                    pass

                r = await client.get(target, headers=headers)

                if r.status_code != 200:
                    self.errors += 1
                    return None

                self.errors = 0
                self.last_check = datetime.now().strftime("%H:%M:%S")

                try:
                    html = r.text
                except:
                    try:
                        html = r.content.decode('utf-8', errors='replace')
                    except:
                        html = r.content.decode('latin-1', errors='replace')

                if not html.strip().startswith(('<', '<!', '\n<')):
                    headers2 = {"User-Agent": headers["User-Agent"], "Accept": "text/html"}
                    r2 = await client.get(target, headers=headers2)
                    html = r2.text
                    if not html.strip().startswith(('<', '<!', '\n<')):
                        try:
                            import brotli
                            html = brotli.decompress(r.content).decode('utf-8')
                        except:
                            return None

                soup = BeautifulSoup(html, "lxml")

                # JSON
                script = soup.find("script", id="__NEXT_DATA__")
                if script and script.string:
                    try:
                        data = json.loads(script.string)
                        ads = self._from_json(data)
                        if ads:
                            return ads
                    except:
                        pass

                # HTML
                ads = self._from_html(soup)
                if ads:
                    return ads

                return None

        except Exception as e:
            self.errors += 1
            log.error(f"Fetch: {e}")
            return None

    def _from_json(self, data):
        ads = []
        props = data.get("props", {}).get("pageProps", {})
        items = []
        for name, fn in [
            ("listing.listing.ads", lambda: props.get("listing", {}).get("listing", {}).get("ads", [])),
            ("listing.ads", lambda: props.get("listing", {}).get("ads", [])),
            ("data.items", lambda: props.get("data", {}).get("items", [])),
            ("ads", lambda: props.get("ads", [])),
        ]:
            try:
                r = fn()
                if r and isinstance(r, list) and len(r) > 0:
                    items = r
                    break
            except:
                continue

        if not items:
            found = self._deep_find(props)
            if found:
                items = found

        for item in items:
            if not isinstance(item, dict):
                continue
            ad = self._extract(item)
            if ad:
                ads.append(ad)
        return ads if ads else None

    def _deep_find(self, obj, depth=0):
        if depth > 5:
            return None
        if isinstance(obj, dict):
            for key, val in obj.items():
                if isinstance(val, list) and len(val) > 3:
                    if isinstance(val[0], dict) and ("id" in val[0] or "url" in val[0]):
                        return val
                result = self._deep_find(val, depth + 1)
                if result:
                    return result
        return None

    def _extract(self, item):
        olx_id = str(item.get("id", ""))
        if not olx_id:
            return None
        url = item.get("url", "")
        if not url:
            return None
        if not url.startswith("http"):
            url = "https://www.olx.pl" + url
        url = url.split("#")[0].split("?")[0].rstrip('/')

        title = item.get("title", "—")
        price = "—"
        pd = item.get("price", {})
        if isinstance(pd, dict):
            price = pd.get("displayValue") or "—"

        promoted = bool(
            item.get("isPromoted") or item.get("isHighlighted") or
            item.get("isBusiness") or
            (isinstance(item.get("promotion"), dict) and item["promotion"]) or
            (isinstance(item.get("partner"), dict) and item["partner"])
        )

        refreshed = False
        created = item.get("createdTime", "") or item.get("created_time", "") or ""
        last_refresh = item.get("lastRefreshTime", "") or item.get("last_refresh_time", "") or ""
        if created and last_refresh and created != last_refresh:
            refreshed = True

        city = ""
        loc = item.get("location", {})
        if isinstance(loc, dict):
            cd = loc.get("city", {})
            if isinstance(cd, dict):
                city = cd.get("name", "")

        photo = None
        photos = item.get("photos", [])
        if photos and isinstance(photos, list):
            first = photos[0]
            if isinstance(first, dict):
                photo = first.get("link", "")
            elif isinstance(first, str):
                photo = first

        return {
            "id": olx_id, "title": title, "url": url, "price": price,
            "promoted": promoted, "refreshed": refreshed, "city": city, "photo": photo
        }

    def _from_html(self, soup):
        ads = []
        cards = soup.find_all("div", {"data-cy": "l-card"})
        if not cards:
            cards = soup.find_all("div", {"data-testid": "l-card"})

        for card in cards:
            link = card.find("a", href=True)
            if not link or '/d/oferta/' not in link.get('href', ''):
                continue
            href = link['href']
            if not href.startswith("http"):
                href = "https://www.olx.pl" + href
            clean = href.split("#")[0].split("?")[0].rstrip('/')

            # ID из URL — берём только последнюю часть
            # https://www.olx.pl/d/oferta/iphone-13-pro-ID12345.html → ID12345
            url_id = clean.split("-")[-1].replace(".html", "") if "-" in clean else clean
            
            title_el = card.find("h6") or card.find("h4") or card.find("h3")
            title = title_el.get_text(strip=True) if title_el else "—"

            price_el = card.find("p", {"data-testid": "ad-price"})
            price = price_el.get_text(strip=True) if price_el else "—"

            # Promoted — проверяем несколько способов
            promoted = False
            card_text = card.get_text(strip=True).lower()
            if any(w in card_text for w in ["promowane", "wyróżnione", "promoted", "sponsorowane"]):
                promoted = True
            if card.find("div", {"data-testid": "adCard-featured"}):
                promoted = True
            # Проверяем data-атрибуты
            if card.get("data-featured"):
                promoted = True

            city = ""
            loc_el = card.find("p", {"data-testid": "location-date"})
            if loc_el and " - " in loc_el.get_text():
                city = loc_el.get_text(strip=True).split(" - ")[0]

            photo = None
            img = card.find("img", src=True)
            if img:
                photo = img.get("src", "")

            ads.append({
                "id": url_id, "title": title, "url": clean, "price": price,
                "promoted": promoted, "refreshed": False, "city": city, "photo": photo
            })

        return ads if ads else None


bot = Bot(token=TOKEN)
dp = Dispatcher()
parser = OLXParser()


def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статус", callback_data="status"),
         InlineKeyboardButton(text="🔍 Проверить", callback_data="check_now")],
        [InlineKeyboardButton(text="⏸ Пауза", callback_data="pause"),
         InlineKeyboardButton(text="▶️ Старт", callback_data="resume")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")]
    ])


def kb_settings():
    sound = "🔔" if Config.notify_sound else "🔕"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Звук: {sound}", callback_data="toggle_sound")],
        [InlineKeyboardButton(text=f"Интервал: {Config.interval}с", callback_data="noop")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])


@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    if not Config.url:
        await msg.answer("👋 *Добро пожаловать!*\n\nОтправьте ссылку:\n`/url https://www.olx.pl/...`", parse_mode=ParseMode.MARKDOWN)
    else:
        await msg.answer("🎯 *OLX Sniper*\n\nБот работает.", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())


@dp.message(Command("url"))
async def cmd_url(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2 or "olx.pl" not in parts[1]:
        return await msg.answer("`/url https://www.olx.pl/...`", parse_mode=ParseMode.MARKDOWN)
    Config.url = parts[1].strip()
    parser.seen.clear()
    parser.base_ready = False
    parser.total_sent = 0
    await msg.answer("✅ *Поиск обновлён!*\n⏳ Собираю базу (~3 мин)...", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())


@dp.message(Command("interval"))
async def cmd_interval(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        sec = int(msg.text.split()[1])
        if 60 <= sec <= 600:
            Config.interval = sec
            await msg.answer(f"✅ Интервал: {sec}с")
        else:
            await msg.answer("60-600")
    except:
        await msg.answer(f"`/interval {Config.interval}`", parse_mode=ParseMode.MARKDOWN)


@dp.message(Command("pause"))
async def cmd_pause(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    Config.is_running = False
    await msg.answer("⏸ Пауза", reply_markup=kb_main())


@dp.message(Command("resume"))
async def cmd_resume(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    Config.is_running = True
    await msg.answer("▶️ Запущено", reply_markup=kb_main())


@dp.message(Command("status"))
async def cmd_status(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await send_status(msg.chat.id)


@dp.message(Command("debug"))
async def cmd_debug(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await msg.answer("🔍 Тест...")
    ads = await parser.fetch()
    if ads:
        # Считаем новые
        new = [a for a in ads if a['id'] not in parser.seen]
        promoted = [a for a in ads if a['promoted']]
        sample = ads[0]
        await msg.answer(
            f"✅ Всего: {len(ads)}\n"
            f"🆕 Новых: {len(new)}\n"
            f"🚫 Promoted: {len(promoted)}\n"
            f"📦 В базе: {len(parser.seen)}\n\n"
            f"Пример ID: {sample['id'][:30]}\n"
            f"Title: {sample['title'][:40]}\n"
            f"Price: {sample['price']}"
        )
    else:
        await msg.answer(f"❌ 0 объявлений\nErrors: {parser.errors}")


@dp.callback_query(lambda c: c.data == "status")
async def cb_status(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    await cb.answer()
    await send_status(cb.message.chat.id, cb.message)


@dp.callback_query(lambda c: c.data == "check_now")
async def cb_check(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    await cb.answer("🔍...")
    if not Config.url:
        return await cb.message.edit_text("⚠️ `/url ...`", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())
    ads = await parser.fetch()
    if not ads:
        return await cb.message.edit_text(f"⚠️ Нет данных", reply_markup=kb_main())
    new = [a for a in ads if a['id'] not in parser.seen]
    try:
        await cb.message.edit_text(
            f"🔍 На стр: {len(ads)} | База: {len(parser.seen)} | Новых: {len(new)}",
            reply_markup=kb_main()
        )
    except:
        pass


@dp.callback_query(lambda c: c.data == "pause")
async def cb_pause(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    Config.is_running = False
    await cb.answer("⏸")
    await send_status(cb.message.chat.id, cb.message)


@dp.callback_query(lambda c: c.data == "resume")
async def cb_resume(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    Config.is_running = True
    await cb.answer("▶️")
    await send_status(cb.message.chat.id, cb.message)


@dp.callback_query(lambda c: c.data == "settings")
async def cb_settings(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    await cb.answer()
    try:
        await cb.message.edit_text(
            f"⚙️ Интервал: {Config.interval}с\nЗвук: {'🔔' if Config.notify_sound else '🔕'}\n\n`/interval 120`",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb_settings()
        )
    except:
        pass


@dp.callback_query(lambda c: c.data == "toggle_sound")
async def cb_sound(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    Config.notify_sound = not Config.notify_sound
    await cb.answer("ok")
    try:
        await cb_settings(cb)
    except:
        pass


@dp.callback_query(lambda c: c.data == "back")
async def cb_back(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    try:
        await cb.message.edit_text("🎯 OLX Sniper", reply_markup=kb_main())
    except:
        pass


@dp.callback_query(lambda c: c.data == "noop")
async def cb_noop(cb: types.CallbackQuery):
    await cb.answer(f"/interval {Config.interval}")


async def send_status(chat_id, edit_msg=None):
    s = "🟢" if Config.is_running else "🔴"
    b = "✅" if parser.base_ready else "⏳"
    up = "—"
    if parser.start_time:
        d = datetime.now() - parser.start_time
        up = f"{int(d.total_seconds()//3600)}ч {int(d.total_seconds()%3600//60)}м"
    q = "—"
    if Config.url and "q-" in Config.url:
        try:
            q = Config.url.split("q-")[1].split("/")[0].split("?")[0].replace("-", " ")
        except:
            q = "✅"
    elif Config.url:
        q = "✅"
    t = f"📊 {s} | База: {b} ({len(parser.seen)})\nПоиск: {q}\nОтправлено: {parser.total_sent}\nАптайм: {up}\nПроверка: {parser.last_check or '—'}"
    try:
        if edit_msg:
            await edit_msg.edit_text(t, reply_markup=kb_main())
        else:
            await bot.send_message(chat_id, t, reply_markup=kb_main())
    except:
        pass


# ============================================
# БЫСТРАЯ КАЛИБРОВКА (3 мин вместо 15)
# ============================================
async def collect_base():
    """Быстрая сборка базы — только 2 страницы + 2 проверки"""
    sep = "&" if "?" in Config.url else "?"
    
    # 2 страницы вместо 4
    for page in range(1, 3):
        target = Config.url if page == 1 else Config.url + f"{sep}page={page}"
        ads = await parser.fetch(target)
        if ads:
            for a in ads:
                parser.seen.add(a['id'])
            log.info(f"Base p{page}: +{len(ads)} ({len(parser.seen)})")
        else:
            log.warning(f"Base p{page}: fail")
            if page == 1:
                await asyncio.sleep(10)
                ads = await parser.fetch(target)
                if ads:
                    for a in ads:
                        parser.seen.add(a['id'])
        await asyncio.sleep(random.uniform(2, 4))

    # 2 проверки вместо 6
    for i in range(2):
        await asyncio.sleep(random.uniform(30, 50))
        ads = await parser.fetch()
        if ads:
            for a in ads:
                parser.seen.add(a['id'])
            log.info(f"Check {i+1}: {len(parser.seen)}")

    return len(parser.seen)


async def monitoring_loop():
    await asyncio.sleep(5)
    parser.start_time = datetime.now()

    while not Config.url:
        await asyncio.sleep(5)

    log.info(f"Calibrating: {Config.url[:80]}")

    try:
        await bot.send_message(ADMIN_ID, "⏳ *Собираю базу (~3 мин)...*", parse_mode=ParseMode.MARKDOWN)
    except:
        return

    base = await collect_base()
    parser.base_ready = True
    log.info(f"Ready: {base} ads in base")

    try:
        await bot.send_message(
            ADMIN_ID,
            f"✅ *Готово!*\n📦 База: {base}\n⏱ Проверка каждые ~{Config.interval}с\n\nНовые объявления будут приходить сюда.",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
        )
    except:
        pass

    # ============================================
    # ОСНОВНОЙ ЦИКЛ
    # ============================================
    while True:
        if not Config.is_running or not Config.url:
            await asyncio.sleep(10)
            continue

        if not parser.base_ready:
            await collect_base()
            parser.base_ready = True
            continue

        # Ждём
        delay = Config.interval + random.randint(5, 30)
        await asyncio.sleep(delay)

        # Проверяем
        ads = await parser.fetch()
        if not ads:
            log.warning("No ads")
            continue

        # Ищем новые
        sent = 0
        skipped_promoted = 0
        
        for ad in ads:
            if ad['id'] in parser.seen:
                continue

            # Добавляем сразу
            parser.seen.add(ad['id'])

            if ad['promoted']:
                skipped_promoted += 1
                continue

            if ad.get('refreshed'):
                continue

            # НОВОЕ — ОТПРАВЛЯЕМ
            parser.total_sent += 1
            sent += 1
            city = f"\n📍 {ad['city']}" if ad.get('city') else ""

            log.info(f"🆕 NEW: {ad['title'][:50]} | {ad['price']} | ID:{ad['id'][:20]}")

            # Отправка
            try:
                if ad.get('photo') and ad['photo'].startswith("http"):
                    try:
                        await bot.send_photo(
                            ADMIN_ID, photo=ad['photo'],
                            caption=f"🆕 *Новое объявление!*\n\n📦 {ad['title']}\n💰 {ad['price']}{city}\n\n🔗 [Открыть на OLX]({ad['url']})",
                            parse_mode=ParseMode.MARKDOWN,
                            disable_notification=not Config.notify_sound
                        )
                    except:
                        raise Exception("photo_fail")
                else:
                    raise Exception("no_photo")
            except:
                try:
                    await bot.send_message(
                        ADMIN_ID,
                        f"🆕 *Новое объявление!*\n\n📦 {ad['title']}\n💰 {ad['price']}{city}\n\n🔗 [Открыть на OLX]({ad['url']})",
                        parse_mode=ParseMode.MARKDOWN,
                        disable_notification=not Config.notify_sound
                    )
                except:
                    try:
                        await bot.send_message(
                            ADMIN_ID,
                            f"🆕 {ad['title']}\n💰 {ad['price']}\n🔗 {ad['url']}",
                            disable_notification=not Config.notify_sound
                        )
                    except Exception as e:
                        log.error(f"Send: {e}")

            await asyncio.sleep(0.3)

        # Логирование
        if sent:
            log.info(f"✅ Sent: {sent} | Promoted skip: {skipped_promoted} | Base: {len(parser.seen)}")
        else:
            new_count = len([a for a in ads if a['id'] not in parser.seen])
            log.info(f"— No new | Ads: {len(ads)} | Base: {len(parser.seen)}")


async def keep_alive():
    while True:
        await asyncio.sleep(600)
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                await c.get(RENDER_URL)
        except:
            pass


async def main():
    threading.Thread(target=run_flask, daemon=True).start()
    log.info("Starting in 15s...")
    await asyncio.sleep(15)
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(3)
    log.info(f"OLX Sniper v{VERSION}")
    await asyncio.gather(
        dp.start_polling(bot, skip_updates=True),
        monitoring_loop(),
        keep_alive()
    )


if __name__ == "__main__":
    asyncio.run(main())
