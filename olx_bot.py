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

TOKEN = "8346602599:AAF8P5dmfvr4AZ072McvzcTDfHVQNo0mQPg".strip()
ADMIN_ID = 908015235
RENDER_URL = "https://olx-telegram-bot-9suv.onrender.com"
VERSION = "5.0"
BUILD = hashlib.md5(TOKEN.encode()).hexdigest()[:8]
SEEN_FILE = "seen_ids.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("BOT")

ALLOWED_HOSTS = ["onrender.com", "render.com", "127.0.0.1", "localhost"]
if RENDER_URL and not any(h in RENDER_URL.lower() for h in ALLOWED_HOSTS):
    os._exit(1)


class Config:
    url = "https://www.olx.pl/oferty/q-iphone/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=100&search%5Bfilter_float_price:to%5D=4000"
    interval = 90
    is_running = True
    notify_sound = True


app = Flask('')

@app.route('/')
def home():
    return "OK"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))


# ============================================
# СОХРАНЕНИЕ БАЗЫ В ФАЙЛ
# ============================================
def save_seen(seen_set):
    """Сохраняет базу ID на диск — переживает перезапуски"""
    try:
        data = {
            "ids": list(seen_set)[-5000:],  # Храним последние 5000
            "saved_at": datetime.now().isoformat(),
            "count": len(seen_set)
        }
        with open(SEEN_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        log.error(f"Save error: {e}")


def load_seen():
    """Загружает базу ID с диска"""
    try:
        if os.path.exists(SEEN_FILE):
            with open(SEEN_FILE, 'r') as f:
                data = json.load(f)
            ids = set(data.get("ids", []))
            saved_at = data.get("saved_at", "")
            log.info(f"Loaded {len(ids)} IDs from disk (saved: {saved_at})")
            return ids
    except Exception as e:
        log.error(f"Load error: {e}")
    return set()


# ============================================
# ПАРСЕР
# ============================================
class OLXParser:
    def __init__(self):
        self.seen = load_seen()  # Загружаем с диска!
        self.last_check = None
        self.errors = 0
        self.base_ready = False
        self.start_time = None
        self.total_sent = 0
        self.checks = 0
        self.save_counter = 0

    def _headers(self):
        v = random.choice(["122", "123", "124", "125", "126"])
        return {
            "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9",
            "Accept-Encoding": "identity",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Upgrade-Insecure-Requests": "1",
        }

    def _make_id(self, href):
        if not href.startswith("http"):
            href = "https://www.olx.pl" + href
        clean = href.split("#")[0].split("?")[0].rstrip('/')
        parts = clean.split('/')
        return parts[-1] if parts else clean

    def add_to_seen(self, ad_id):
        self.seen.add(ad_id)
        self.save_counter += 1
        # Сохраняем каждые 10 добавлений
        if self.save_counter >= 10:
            save_seen(self.seen)
            self.save_counter = 0

    async def fetch(self, url=None):
        target = url or Config.url
        if not target:
            return None

        if "created_at" not in target:
            sep = "&" if "?" in target else "?"
            target += f"{sep}search%5Border%5D=created_at:desc"

        try:
            headers = self._headers()
            async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
                try:
                    await client.get("https://www.olx.pl/", headers=headers)
                    await asyncio.sleep(random.uniform(0.8, 1.5))
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
                    html = r.content.decode('utf-8', errors='replace')

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
                ads = self._from_html(soup)
                if ads:
                    return ads

                script = soup.find("script", id="__NEXT_DATA__")
                if script and script.string:
                    try:
                        data = json.loads(script.string)
                        return self._from_json(data)
                    except:
                        pass
                return None

        except Exception as e:
            self.errors += 1
            log.error(f"Fetch: {e}")
            return None

    def _from_html(self, soup):
        ads = []
        cards = soup.find_all("div", {"data-cy": "l-card"})
        if not cards:
            cards = soup.find_all("div", {"data-testid": "l-card"})
        if not cards:
            return None

        for card in cards:
            link = card.find("a", href=True)
            if not link or '/d/oferta/' not in link.get('href', ''):
                continue

            href = link['href']
            if not href.startswith("http"):
                href = "https://www.olx.pl" + href
            url = href.split("#")[0].split("?")[0].rstrip('/')
            ad_id = self._make_id(href)

            title_el = card.find("h6") or card.find("h4") or card.find("h3")
            title = title_el.get_text(strip=True) if title_el else "—"

            price_el = card.find("p", {"data-testid": "ad-price"})
            price = price_el.get_text(strip=True) if price_el else "—"

            city = ""
            loc_el = card.find("p", {"data-testid": "location-date"})
            if loc_el:
                txt = loc_el.get_text(strip=True)
                if " - " in txt:
                    city = txt.split(" - ")[0].strip()

            promoted = False
            card_lower = card.get_text(strip=True).lower()
            if any(w in card_lower for w in ["promowane", "wyróżnione", "promoted", "sponsorowane"]):
                promoted = True
            if card.find("div", {"data-testid": "adCard-featured"}):
                promoted = True
            if card.find(attrs={"data-testid": re.compile(r"promoted|featured|highlight")}):
                promoted = True

            photo = None
            img = card.find("img", src=True)
            if img and img.get("src", "").startswith("http"):
                photo = img["src"]

            ads.append({
                "id": ad_id, "title": title, "url": url,
                "price": price, "city": city, "photo": photo,
                "promoted": promoted,
            })

        return ads if ads else None

    def _from_json(self, data):
        ads = []
        props = data.get("props", {}).get("pageProps", {})
        items = []
        for fn in [
            lambda: props.get("listing", {}).get("listing", {}).get("ads", []),
            lambda: props.get("listing", {}).get("ads", []),
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
            url = url.split("#")[0].split("?")[0].rstrip('/')
            ad_id = self._make_id(url)

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

            ads.append({
                "id": ad_id, "title": title, "url": url,
                "price": price, "city": city, "photo": photo,
                "promoted": promoted,
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
        await msg.answer("👋 *OLX Sniper*\n\n`/url https://www.olx.pl/...`", parse_mode=ParseMode.MARKDOWN)
    else:
        await msg.answer("🎯 *OLX Sniper — работает*", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())

@dp.message(Command("url"))
async def cmd_url(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2 or "olx.pl" not in parts[1]:
        return await msg.answer("`/url https://www.olx.pl/...`", parse_mode=ParseMode.MARKDOWN)
    new_url = parts[1].strip()
    if "created_at" not in new_url:
        sep = "&" if "?" in new_url else "?"
        new_url += f"{sep}search%5Border%5D=created_at:desc"
    Config.url = new_url
    parser.seen.clear()
    parser.base_ready = False
    parser.total_sent = 0
    # Удаляем файл базы при смене поиска
    if os.path.exists(SEEN_FILE):
        os.remove(SEEN_FILE)
    await msg.answer("✅ *Поиск обновлён!*\n⏳ Сборка базы ~2 мин...", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())

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
    await msg.answer("🔍...")
    ads = await parser.fetch()
    if not ads:
        return await msg.answer(f"❌ 0 | Err: {parser.errors}")
    new = [a for a in ads if a['id'] not in parser.seen]
    promo = [a for a in ads if a['promoted']]
    
    file_exists = "✅" if os.path.exists(SEEN_FILE) else "❌"
    
    txt = (
        f"📋 *Диагностика*\n\n"
        f"На странице: {len(ads)}\n"
        f"Новых (не в базе): {len(new)}\n"
        f"Promoted: {len(promo)}\n"
        f"В базе: {len(parser.seen)}\n"
        f"Файл базы: {file_exists}\n"
        f"Проверок: {parser.checks}\n"
        f"Отправлено: {parser.total_sent}\n\n"
        f"*Топ-5 на странице:*"
    )
    for a in ads[:5]:
        flag = "🚫" if a['promoted'] else ("🆕" if a['id'] not in parser.seen else "📦")
        txt += f"\n{flag} {a['price']} | {a['title'][:25]}"
    
    await msg.answer(txt, parse_mode=ParseMode.MARKDOWN)


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
    await cb.answer("🔍")
    ads = await parser.fetch()
    if not ads:
        try:
            await cb.message.edit_text("⚠️ Нет данных", reply_markup=kb_main())
        except:
            pass
        return
    new = [a for a in ads if a['id'] not in parser.seen and not a['promoted']]
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
            f"⚙️ Интервал: {Config.interval}с\nЗвук: {'🔔' if Config.notify_sound else '🔕'}\n`/interval 90`",
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
    t = (
        f"📊 {s} | База: {b} ({len(parser.seen)})\n"
        f"Поиск: {q}\n"
        f"Отправлено: {parser.total_sent}\n"
        f"Проверок: {parser.checks}\n"
        f"Аптайм: {up}\n"
        f"Проверка: {parser.last_check or '—'}"
    )
    try:
        if edit_msg:
            await edit_msg.edit_text(t, reply_markup=kb_main())
        else:
            await bot.send_message(chat_id, t, reply_markup=kb_main())
    except:
        pass


# ============================================
# КАЛИБРОВКА
# ============================================
async def collect_base():
    """
    ТИХАЯ сборка базы — добавляет ВСЕ существующие ID.
    Ничего не отправляет. После этого любой НОВЫЙ ID = реально новое.
    """
    had_before = len(parser.seen)
    sep = "&" if "?" in Config.url else "?"

    # 3 страницы × 2 попытки
    for page in range(1, 4):
        target = Config.url if page == 1 else Config.url + f"{sep}page={page}"
        for attempt in range(2):
            ads = await parser.fetch(target)
            if ads:
                for a in ads:
                    parser.add_to_seen(a['id'])
                log.info(f"Base p{page}: {len(parser.seen)}")
                break
            await asyncio.sleep(5)
        await asyncio.sleep(random.uniform(2, 4))

    # 3 контрольных проверки стр.1
    for i in range(3):
        await asyncio.sleep(random.uniform(20, 35))
        ads = await parser.fetch()
        if ads:
            for a in ads:
                parser.add_to_seen(a['id'])
            log.info(f"Verify {i+1}: {len(parser.seen)}")

    # Финальное сохранение
    save_seen(parser.seen)
    
    added = len(parser.seen) - had_before
    log.info(f"Calibration done: {len(parser.seen)} total (+{added} new)")
    return len(parser.seen)


# ============================================
# МОНИТОРИНГ
# ============================================
async def monitoring_loop():
    await asyncio.sleep(5)
    parser.start_time = datetime.now()

    while not Config.url:
        await asyncio.sleep(5)

    log.info(f"Start v{VERSION} | Loaded from disk: {len(parser.seen)}")

    # Если база загружена с диска и достаточно большая — быстрый старт
    if len(parser.seen) > 50:
        log.info("Fast start — base loaded from disk")
        parser.base_ready = True

        try:
            await bot.send_message(
                ADMIN_ID,
                f"🚀 *Бот перезапущен!*\n\n"
                f"📦 База загружена: {len(parser.seen)}\n"
                f"⏱ Проверка каждые ~{Config.interval}с\n\n"
                f"Мониторинг продолжается.",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
            )
        except:
            pass

        # Быстрая дозагрузка — 1 страница чтобы поймать то что пропустили
        ads = await parser.fetch()
        if ads:
            for a in ads:
                parser.add_to_seen(a['id'])
            save_seen(parser.seen)
            log.info(f"Quick sync: {len(parser.seen)}")

    else:
        # Полная калибровка
        try:
            await bot.send_message(ADMIN_ID, "⏳ *Первый запуск — сборка базы ~2 мин...*\n\nПосле этого только новые объявления.", parse_mode=ParseMode.MARKDOWN)
        except:
            return

        base = await collect_base()
        parser.base_ready = True

        try:
            await bot.send_message(
                ADMIN_ID,
                f"✅ *Готово!*\n\n"
                f"📦 В базе: {base} объявлений\n"
                f"⏱ Проверка каждые ~{Config.interval}с\n\n"
                f"🎯 Теперь вы будете получать ТОЛЬКО новые объявления.",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
            )
        except:
            pass

    # ============ ОСНОВНОЙ ЦИКЛ ============
    while True:
        if not Config.is_running or not Config.url:
            await asyncio.sleep(10)
            continue

        if not parser.base_ready:
            await collect_base()
            parser.base_ready = True
            continue

        delay = Config.interval + random.randint(5, 20)
        await asyncio.sleep(delay)

        # Проверяем ТОЛЬКО стр.1 — там новые объявления
        ads = await parser.fetch()
        if not ads:
            continue

        parser.checks += 1
        sent = 0

        for ad in ads:
            # В базе = старое, пропускаем
            if ad['id'] in parser.seen:
                continue

            # Добавляем сразу
            parser.add_to_seen(ad['id'])

            # Promoted — пропускаем
            if ad['promoted']:
                log.info(f"SKIP promo: {ad['title'][:30]}")
                continue

            # ===== РЕАЛЬНО НОВОЕ — ОТПРАВЛЯЕМ =====
            parser.total_sent += 1
            sent += 1

            city = f"\n📍 {ad['city']}" if ad.get('city') else ""
            log.info(f"🆕 #{parser.total_sent}: {ad['title'][:40]} | {ad['price']}")

            try:
                if ad.get('photo') and ad['photo'].startswith("http"):
                    try:
                        await bot.send_photo(
                            ADMIN_ID, photo=ad['photo'],
                            caption=(
                                f"🆕 *Новое объявление!*\n\n"
                                f"📦 {ad['title']}\n"
                                f"💰 {ad['price']}{city}\n\n"
                                f"🔗 [Открыть на OLX]({ad['url']})"
                            ),
                            parse_mode=ParseMode.MARKDOWN,
                            disable_notification=not Config.notify_sound
                        )
                    except:
                        raise Exception()
                else:
                    raise Exception()
            except:
                try:
                    await bot.send_message(
                        ADMIN_ID,
                        f"🆕 *Новое объявление!*\n\n"
                        f"📦 {ad['title']}\n"
                        f"💰 {ad['price']}{city}\n\n"
                        f"🔗 [Открыть на OLX]({ad['url']})",
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

        if sent:
            log.info(f"✅ Sent: {sent} | Base: {len(parser.seen)}")
            save_seen(parser.seen)  # Сохраняем после отправки
        else:
            if parser.checks % 20 == 0:
                log.info(f"Check #{parser.checks} ok | Base: {len(parser.seen)}")
                save_seen(parser.seen)  # Периодическое сохранение


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
