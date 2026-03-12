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

TOKEN = "8346602599:AAGxQrRSZFlZai0HL03YBXKh6OJpRBAVDho".strip()
ADMIN_ID = 908015235
RENDER_URL = "https://olx-telegram-bot-9suv.onrender.com"
DEVELOPER_ID = 908015235
VERSION = "3.2"
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
    url = "https://www.olx.pl/oferty/q-iphone-13-pro-max-256gb/?search%5Bfilter_float_price:from%5D=100&search%5Bfilter_float_price:to%5D=2000"
    interval = 210
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
            async with httpx.AsyncClient(
                headers=headers,
                timeout=30,
                follow_redirects=True
            ) as client:
                try:
                    await client.get("https://www.olx.pl/", headers=headers)
                    await asyncio.sleep(random.uniform(1.5, 3.0))
                except:
                    pass

                r = await client.get(target, headers=headers)
                log.info(f"Status: {r.status_code} | Size: {len(r.content)} | Encoding: {r.encoding}")

                if r.status_code != 200:
                    self.errors += 1
                    return None

                self.errors = 0
                self.last_check = datetime.now().strftime("%H:%M:%S")

                # Декодируем контент
                try:
                    html = r.text
                except:
                    try:
                        html = r.content.decode('utf-8', errors='replace')
                    except:
                        html = r.content.decode('latin-1', errors='replace')

                log.info(f"Text size: {len(html)} | Starts with: {html[:50]}")

                # Проверяем что HTML нормальный
                if not html.strip().startswith(('<', '<!', '\n<')):
                    # Всё ещё сжатые данные
                    log.error("Response is still compressed/binary!")

                    # Попробуем без Accept-Encoding вообще
                    headers2 = {
                        "User-Agent": headers["User-Agent"],
                        "Accept": "text/html",
                    }
                    r2 = await client.get(target, headers=headers2)
                    html = r2.text
                    log.info(f"Retry: Size={len(html)} | Starts: {html[:50]}")

                    if not html.strip().startswith(('<', '<!', '\n<')):
                        log.error("Still binary after retry")

                        # Последняя попытка — brotli декодирование
                        try:
                            import brotli
                            html = brotli.decompress(r.content).decode('utf-8')
                            log.info(f"Brotli decoded: {len(html)} | Starts: {html[:50]}")
                        except ImportError:
                            log.error("brotli not installed, trying zlib")
                            try:
                                import zlib
                                html = zlib.decompress(r.content, 16 + zlib.MAX_WBITS).decode('utf-8')
                                log.info(f"Gzip decoded: {len(html)}")
                            except:
                                import gzip
                                try:
                                    html = gzip.decompress(r.content).decode('utf-8')
                                    log.info(f"Gzip2 decoded: {len(html)}")
                                except:
                                    log.error("Cannot decode response")
                                    return None
                        except:
                            log.error("Brotli decode failed")
                            return None

                soup = BeautifulSoup(html, "lxml")

                # Способ 1: JSON
                script = soup.find("script", id="__NEXT_DATA__")
                if script and script.string:
                    log.info(f"__NEXT_DATA__: {len(script.string)} bytes")
                    try:
                        data = json.loads(script.string)
                        ads = self._from_json(data)
                        if ads:
                            log.info(f"JSON: {len(ads)} ads")
                            return ads
                    except Exception as e:
                        log.error(f"JSON error: {e}")

                # Способ 2: HTML
                ads = self._from_html(soup)
                if ads:
                    log.info(f"HTML: {len(ads)} ads")
                    return ads

                # Дебаг
                title = soup.find("title")
                log.warning(f"Title: {title.get_text() if title else 'NONE'}")
                log.warning(f"Scripts: {len(soup.find_all('script'))}")
                log.warning(f"Divs: {len(soup.find_all('div'))}")
                log.warning(f"Links /d/oferta/: {len(soup.find_all('a', href=re.compile(r'/d/oferta/')))}")

                return None

        except Exception as e:
            self.errors += 1
            log.error(f"Fetch error: {e}")
            return None

    def _from_json(self, data):
        ads = []
        props = data.get("props", {}).get("pageProps", {})
        log.info(f"Keys: {list(props.keys())[:10]}")

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
                    log.info(f"Path: {name} ({len(r)})")
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
            item.get("isPromoted") or
            item.get("isHighlighted") or
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
        if not cards:
            links = soup.find_all("a", href=re.compile(r"/d/oferta/"))
            for link in links:
                href = link.get('href', '')
                if not href.startswith("http"):
                    href = "https://www.olx.pl" + href
                clean = href.split("#")[0].split("?")[0].rstrip('/')
                h = link.find(["h6", "h4", "h3", "h2"])
                title = h.get_text(strip=True) if h else link.get_text(strip=True)[:80]
                ads.append({
                    "id": clean, "title": title, "url": clean, "price": "—",
                    "promoted": False, "refreshed": False, "city": "", "photo": None
                })
            return ads if ads else None

        for card in cards:
            link = card.find("a", href=True)
            if not link or '/d/oferta/' not in link.get('href', ''):
                continue
            href = link['href']
            if not href.startswith("http"):
                href = "https://www.olx.pl" + href
            clean = href.split("#")[0].split("?")[0].rstrip('/')

            title_el = card.find("h6") or card.find("h4") or card.find("h3")
            title = title_el.get_text(strip=True) if title_el else "—"

            price_el = card.find("p", {"data-testid": "ad-price"})
            price = price_el.get_text(strip=True) if price_el else "—"

            promoted = any(w in card.get_text(strip=True).lower() for w in ["promowane", "wyróżnione"])

            city = ""
            loc_el = card.find("p", {"data-testid": "location-date"})
            if loc_el and " - " in loc_el.get_text():
                city = loc_el.get_text(strip=True).split(" - ")[0]

            photo = None
            img = card.find("img", src=True)
            if img:
                photo = img.get("src", "")

            ads.append({
                "id": clean, "title": title, "url": clean, "price": price,
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


async def dev_log(text):
    try:
        if DEVELOPER_ID and DEVELOPER_ID != ADMIN_ID:
            await bot.send_message(DEVELOPER_ID, f"📡 {BUILD}\n{text}")
    except:
        pass


@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    if not Config.url:
        await msg.answer(
            "👋 *Добро пожаловать!*\n\n"
            "Отправьте ссылку на поиск OLX:\n"
            "`/url https://www.olx.pl/...`",
            parse_mode=ParseMode.MARKDOWN
        )
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
    await msg.answer(
        "✅ *Поиск установлен!*\n\n⏳ Собираю базу (~10 мин)...",
        parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
    )


@dp.message(Command("interval"))
async def cmd_interval(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        sec = int(msg.text.split()[1])
        if 120 <= sec <= 600:
            Config.interval = sec
            await msg.answer(f"✅ Интервал: {sec}с")
        else:
            await msg.answer("120-600")
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
        s = ads[0]
        await msg.answer(f"✅ {len(ads)} объявлений\n\nПример:\n{s['title'][:50]}\n{s['price']}\nPromoted: {s['promoted']}")
    else:
        await msg.answer(f"❌ 0 объявлений\nErrors: {parser.errors}\nURL: {Config.url[:60]}")


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
        return await cb.message.edit_text(f"⚠️ Нет данных. Err: {parser.errors}", reply_markup=kb_main())
    new = [a for a in ads if a['id'] not in parser.seen]
    await cb.message.edit_text(
        f"🔍 На стр: {len(ads)} | База: {len(parser.seen)} | Новых: {len(new)}",
        reply_markup=kb_main()
    )


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
            f"⚙️ Интервал: {Config.interval}с\nЗвук: {'🔔' if Config.notify_sound else '🔕'}\n\n`/interval 210`",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb_settings()
        )
    except Exception:
        pass


@dp.callback_query(lambda c: c.data == "toggle_sound")
async def cb_sound(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    Config.notify_sound = not Config.notify_sound
    await cb.answer("ok")
    await cb_settings(cb)


@dp.callback_query(lambda c: c.data == "back")
async def cb_back(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    await cb.message.edit_text("🎯 OLX Sniper", reply_markup=kb_main())


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
    except Exception:
        pass


async def collect_base():
    sep = "&" if "?" in Config.url else "?"
    for page in range(1, 5):
        target = Config.url if page == 1 else Config.url + f"{sep}page={page}"
        ads = await parser.fetch(target)
        if ads:
            added = sum(1 for a in ads if a['id'] not in parser.seen and not parser.seen.add(a['id']))
            # seen.add returns None, so `not None` = True, counting works
            # Fix: proper counting
            pass
        await asyncio.sleep(random.uniform(3, 6))

    # Recalculate
    for page in range(1, 5):
        target = Config.url if page == 1 else Config.url + f"{sep}page={page}"
        ads = await parser.fetch(target)
        if ads:
            for a in ads:
                parser.seen.add(a['id'])
            log.info(f"Base p{page}: +{len(ads)} (total: {len(parser.seen)})")
        else:
            log.warning(f"Base p{page}: failed")
            if page == 1:
                await asyncio.sleep(15)
                ads = await parser.fetch(target)
                if ads:
                    for a in ads:
                        parser.seen.add(a['id'])
                    log.info(f"Base p1 retry: {len(ads)}")
        await asyncio.sleep(random.uniform(3, 6))

    for i in range(3):
        await asyncio.sleep(random.uniform(45, 75))
        ads = await parser.fetch()
        if ads:
            for a in ads:
                parser.seen.add(a['id'])
            log.info(f"Warm {i+1}: {len(parser.seen)}")

    for i in range(3):
        await asyncio.sleep(Config.interval + random.randint(10, 40))
        ads = await parser.fetch()
        if ads:
            for a in ads:
                parser.seen.add(a['id'])
            log.info(f"Silent {i+1}: {len(parser.seen)}")

    return len(parser.seen)


async def monitoring_loop():
    await asyncio.sleep(5)
    parser.start_time = datetime.now()

    while not Config.url:
        await asyncio.sleep(5)

    log.info(f"Calibrating: {Config.url[:80]}")

    try:
        await bot.send_message(ADMIN_ID, "⏳ *Собираю базу...*\n~10 минут.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        log.error(f"TG: {e}")
        return

    base = await collect_base()
    parser.base_ready = True
    log.info(f"Calibrated: {base}")

    try:
        await bot.send_message(
            ADMIN_ID,
            f"✅ *Готово!*\n📦 База: {base}\n⏱ Каждые ~{Config.interval//60} мин",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
        )
    except:
        pass

    while True:
        if not Config.is_running or not Config.url:
            await asyncio.sleep(10)
            continue

        if not parser.base_ready:
            await collect_base()
            parser.base_ready = True
            continue

        await asyncio.sleep(Config.interval + random.randint(5, 45))

        ads = await parser.fetch()
        if not ads:
            continue

        sent = 0
        for ad in ads:
            if ad['id'] in parser.seen:
                continue
            parser.seen.add(ad['id'])

            if ad['promoted'] or ad.get('refreshed'):
                continue

            parser.total_sent += 1
            sent += 1
            city = f"\n📍 {ad['city']}" if ad.get('city') else ""

            log.info(f"NEW: {ad['title'][:50]} | {ad['price']}")

            try:
                if ad.get('photo') and ad['photo'].startswith("http"):
                    await bot.send_photo(
                        ADMIN_ID, photo=ad['photo'],
                        caption=f"🆕 *Новое!*\n\n📦 {ad['title']}\n💰 {ad['price']}{city}\n\n🔗 [Открыть]({ad['url']})",
                        parse_mode=ParseMode.MARKDOWN, disable_notification=not Config.notify_sound
                    )
                else:
                    raise Exception()
            except:
                try:
                    await bot.send_message(
                        ADMIN_ID,
                        f"🆕 *Новое!*\n\n📦 {ad['title']}\n💰 {ad['price']}{city}\n\n🔗 [Открыть]({ad['url']})",
                        parse_mode=ParseMode.MARKDOWN, disable_notification=not Config.notify_sound
                    )
                except:
                    try:
                        await bot.send_message(ADMIN_ID, f"🆕 {ad['title']}\n💰 {ad['price']}\n🔗 {ad['url']}")
                    except Exception as e:
                        log.error(f"Send: {e}")

            await asyncio.sleep(0.5)

        if sent:
            log.info(f"Sent: {sent}")


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
    log.info("Starting in 30s...")
    await asyncio.sleep(30)
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(3)
    log.info(f"OLX Sniper v{VERSION} build {BUILD}")
    await asyncio.gather(
        dp.start_polling(bot, skip_updates=True),
        monitoring_loop(),
        keep_alive()
    )


if __name__ == "__main__":
    asyncio.run(main())


