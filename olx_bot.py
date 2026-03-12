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

TOKEN = "8346602599:AAGU9X8O61wOCejtx9-8sF6Xi-VABY6B3mY".strip()
ADMIN_ID = 908015235
RENDER_URL = "https://olx-telegram-bot-9suv.onrender.com"
DEVELOPER_ID = 908015235
VERSION = "4.0"
BUILD = hashlib.md5(TOKEN.encode()).hexdigest()[:8]

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
# ПАРСЕР
# ============================================
class OLXParser:
    def __init__(self):
        self.seen = set()
        self.last_check = None
        self.errors = 0
        self.base_ready = False
        self.start_time = None
        self.total_sent = 0

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

    def _clean_url(self, href):
        """Единый ID из URL"""
        if not href.startswith("http"):
            href = "https://www.olx.pl" + href
        return href.split("#")[0].split("?")[0].rstrip('/')

    async def fetch(self, url=None):
        target = url or Config.url
        if not target:
            return None

        # Гарантируем сортировку по дате
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
                ads = self._parse_page(soup)
                if ads:
                    log.info(f"Parsed: {len(ads)} ads")
                return ads

        except Exception as e:
            self.errors += 1
            log.error(f"Fetch: {e}")
            return None

    def _parse_page(self, soup):
        """Единый парсер — сначала HTML карточки, потом JSON"""
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

            url = self._clean_url(link['href'])

            title_el = card.find("h6") or card.find("h4") or card.find("h3")
            title = title_el.get_text(strip=True) if title_el else "—"

            price_el = card.find("p", {"data-testid": "ad-price"})
            price = price_el.get_text(strip=True) if price_el else "—"

            # ====== ДАТА И ГОРОД ======
            date_text = ""
            city = ""
            loc_el = card.find("p", {"data-testid": "location-date"})
            if not loc_el:
                # Пробуем другие селекторы
                for el in card.find_all(["p", "span"]):
                    txt = el.get_text(strip=True)
                    if any(w in txt.lower() for w in ["dzisiaj", "wczoraj", "odświeżono", "sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]):
                        loc_el = el
                        break

            if loc_el:
                full_text = loc_el.get_text(strip=True)
                if " - " in full_text:
                    parts = full_text.split(" - ", 1)
                    city = parts[0].strip()
                    date_text = parts[1].strip()
                else:
                    date_text = full_text

            # ====== АНАЛИЗ ДАТЫ ======
            is_refreshed = False
            is_today = False
            is_old = False
            minutes_ago = None

            dt_lower = date_text.lower()

            # Обновлённое (переподнятое)
            if "odświeżono" in dt_lower:
                is_refreshed = True

            # Сегодня
            elif "dzisiaj" in dt_lower:
                is_today = True
                # Извлекаем время "Dzisiaj o 14:30" или "Dzisiaj 14:30"
                m = re.search(r'(\d{1,2}):(\d{2})', date_text)
                if m:
                    try:
                        ad_h, ad_m = int(m.group(1)), int(m.group(2))
                        now = datetime.utcnow() + timedelta(hours=1)  # CET
                        ad_time = now.replace(hour=ad_h, minute=ad_m, second=0)
                        diff = (now - ad_time).total_seconds() / 60
                        if diff < 0:
                            now2 = datetime.utcnow() + timedelta(hours=2)  # CEST
                            diff = (now2 - ad_time).total_seconds() / 60
                        if diff >= 0:
                            minutes_ago = int(diff)
                    except:
                        pass

            # Вчера
            elif "wczoraj" in dt_lower:
                is_old = True

            # Дата типа "8 mar" или "12 lut"
            elif re.search(r'\d{1,2}\s+(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paź|lis|gru)', dt_lower):
                is_old = True

            # Нет даты вообще
            else:
                is_old = True

            # ====== PROMOTED ======
            promoted = False
            card_text_lower = card.get_text(strip=True).lower()
            if any(w in card_text_lower for w in ["promowane", "wyróżnione", "promoted", "sponsorowane"]):
                promoted = True
            if card.find("div", {"data-testid": "adCard-featured"}):
                promoted = True
            if card.find(attrs={"data-testid": re.compile(r"promoted|featured|highlight")}):
                promoted = True

            # ====== ФОТО ======
            photo = None
            img = card.find("img", src=True)
            if img:
                src = img.get("src", "")
                if src.startswith("http"):
                    photo = src

            ads.append({
                "id": url,
                "title": title,
                "url": url,
                "price": price,
                "city": city,
                "photo": photo,
                "promoted": promoted,
                "refreshed": is_refreshed,
                "is_today": is_today,
                "is_old": is_old,
                "minutes_ago": minutes_ago,
                "date_text": date_text,
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
            url = self._clean_url(url)

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
            created = item.get("createdTime", "") or ""
            last_refresh = item.get("lastRefreshTime", "") or ""
            if created and last_refresh and created != last_refresh:
                refreshed = True

            # Определяем возраст из JSON
            is_today = False
            is_old = False
            minutes_ago = None
            if created:
                try:
                    clean_dt = created
                    for tz in ["+01:00", "+02:00", "+00:00", "Z"]:
                        clean_dt = clean_dt.replace(tz, "")
                    ad_time = datetime.fromisoformat(clean_dt)
                    now = datetime.utcnow() + timedelta(hours=1)
                    diff = (now - ad_time).total_seconds() / 60
                    if diff < 0:
                        now = datetime.utcnow() + timedelta(hours=2)
                        diff = (now - ad_time).total_seconds() / 60
                    if 0 <= diff <= 1440:
                        is_today = True
                        minutes_ago = int(diff)
                    else:
                        is_old = True
                except:
                    pass

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
                "id": url,
                "title": title,
                "url": url,
                "price": price,
                "city": city,
                "photo": photo,
                "promoted": promoted,
                "refreshed": refreshed,
                "is_today": is_today,
                "is_old": is_old,
                "minutes_ago": minutes_ago,
                "date_text": created[:16] if created else "",
            })

        return ads if ads else None


# ============================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================
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


# ============================================
# КОМАНДЫ
# ============================================
@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    if not Config.url:
        await msg.answer("👋 *OLX Sniper*\n\nОтправьте ссылку:\n`/url https://www.olx.pl/...`", parse_mode=ParseMode.MARKDOWN)
    else:
        await msg.answer("🎯 *OLX Sniper*\n\nБот работает.", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())

@dp.message(Command("url"))
async def cmd_url(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2 or "olx.pl" not in parts[1]:
        return await msg.answer("`/url https://www.olx.pl/...`", parse_mode=ParseMode.MARKDOWN)
    new_url = parts[1].strip()
    # Добавляем сортировку если нет
    if "created_at" not in new_url:
        sep = "&" if "?" in new_url else "?"
        new_url += f"{sep}search%5Border%5D=created_at:desc"
    Config.url = new_url
    parser.seen.clear()
    parser.base_ready = False
    parser.total_sent = 0
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
    await msg.answer("🔍 Тест...")
    ads = await parser.fetch()
    if not ads:
        return await msg.answer(f"❌ 0 | Err: {parser.errors}")

    new = [a for a in ads if a['id'] not in parser.seen]
    today = [a for a in ads if a.get('is_today')]
    old = [a for a in ads if a.get('is_old')]
    refreshed = [a for a in ads if a.get('refreshed')]
    promoted = [a for a in ads if a.get('promoted')]

    # Покажем первые 3 объявления с деталями
    details = ""
    for a in ads[:3]:
        age = f"{a['minutes_ago']}м" if a.get('minutes_ago') is not None else "?"
        flags = ""
        if a['promoted']:
            flags += "🚫P "
        if a['refreshed']:
            flags += "🔄R "
        if a['is_old']:
            flags += "⏰OLD "
        if a['is_today']:
            flags += "✅NEW "
        details += f"\n{flags}| {age} | {a['price']} | {a['title'][:30]}"

    await msg.answer(
        f"📋 *Анализ страницы*\n\n"
        f"Всего: {len(ads)}\n"
        f"✅ Сегодня: {len(today)}\n"
        f"⏰ Старые: {len(old)}\n"
        f"🔄 Обновлённые: {len(refreshed)}\n"
        f"🚫 Promoted: {len(promoted)}\n"
        f"🆕 Новых (не в базе): {len(new)}\n"
        f"📦 В базе: {len(parser.seen)}\n"
        f"\n*Топ-3:*{details}",
        parse_mode=ParseMode.MARKDOWN
    )


# ============================================
# CALLBACKS
# ============================================
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
    ads = await parser.fetch()
    if not ads:
        try:
            await cb.message.edit_text("⚠️ Нет данных", reply_markup=kb_main())
        except:
            pass
        return
    new = [a for a in ads if a['id'] not in parser.seen]
    today = [a for a in new if a.get('is_today') and not a['promoted'] and not a['refreshed']]
    try:
        await cb.message.edit_text(
            f"🔍 Всего: {len(ads)} | Новых: {len(new)} | Свежих: {len(today)}",
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
            f"⚙️ Интервал: {Config.interval}с\nЗвук: {'🔔' if Config.notify_sound else '🔕'}\n\n`/interval 90`",
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
# БЫСТРАЯ КАЛИБРОВКА (2 мин)
# ============================================
async def collect_base():
    # Страница 1 — три раза с паузами
    for i in range(3):
        ads = await parser.fetch()
        if ads:
            for a in ads:
                parser.seen.add(a['id'])
            log.info(f"Base {i+1}/3: {len(parser.seen)}")
        await asyncio.sleep(random.uniform(25, 40))
    return len(parser.seen)


# ============================================
# МОНИТОРИНГ
# ============================================
async def monitoring_loop():
    await asyncio.sleep(5)
    parser.start_time = datetime.now()

    while not Config.url:
        await asyncio.sleep(5)

    log.info(f"Start: {Config.url[:80]}")

    try:
        await bot.send_message(ADMIN_ID, "⏳ *Сборка базы ~2 мин...*", parse_mode=ParseMode.MARKDOWN)
    except:
        return

    base = await collect_base()
    parser.base_ready = True
    log.info(f"Ready: {base}")

    try:
        await bot.send_message(
            ADMIN_ID,
            f"✅ *Готово!*\n📦 База: {base}\n⏱ Каждые ~{Config.interval}с\n\n"
            f"🎯 Только новые объявления, опубликованные сегодня.\n"
            f"🚫 Promoted, обновлённые, старые — отфильтрованы.",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
        )
    except:
        pass

    # ОСНОВНОЙ ЦИКЛ
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

        ads = await parser.fetch()
        if not ads:
            continue

        sent = 0
        for ad in ads:
            # Уже видели
            if ad['id'] in parser.seen:
                continue

            # Добавляем в базу
            parser.seen.add(ad['id'])

            # === ФИЛЬТР 1: Promoted ===
            if ad['promoted']:
                log.info(f"SKIP promoted: {ad['title'][:35]}")
                continue

            # === ФИЛЬТР 2: Обновлённое (Odświeżono) ===
            if ad['refreshed']:
                log.info(f"SKIP refreshed: {ad['title'][:35]}")
                continue

            # === ФИЛЬТР 3: Старое (не сегодня) ===
            if ad['is_old']:
                log.info(f"SKIP old [{ad['date_text']}]: {ad['title'][:35]}")
                continue

            # === ФИЛЬТР 4: Если сегодня но больше 60 минут назад ===
            if ad.get('minutes_ago') is not None and ad['minutes_ago'] > 60:
                log.info(f"SKIP >60m [{ad['minutes_ago']}m]: {ad['title'][:35]}")
                continue

            # ===== ПРОШЛО ВСЕ ФИЛЬТРЫ — ОТПРАВЛЯЕМ =====
            parser.total_sent += 1
            sent += 1

            city = f"\n📍 {ad['city']}" if ad.get('city') else ""
            age = ""
            if ad.get('minutes_ago') is not None:
                if ad['minutes_ago'] < 1:
                    age = "\n⚡ Только что!"
                elif ad['minutes_ago'] < 5:
                    age = f"\n⚡ {ad['minutes_ago']} мин назад"
                else:
                    age = f"\n⏱ {ad['minutes_ago']} мин назад"

            log.info(f"🆕 SEND: {ad['title'][:40]} | {ad['price']} | {ad.get('minutes_ago', '?')}m")

            # Отправка с фото
            try:
                if ad.get('photo') and ad['photo'].startswith("http"):
                    try:
                        await bot.send_photo(
                            ADMIN_ID, photo=ad['photo'],
                            caption=(
                                f"🆕 *Новое объявление!*\n\n"
                                f"📦 {ad['title']}\n"
                                f"💰 {ad['price']}{city}{age}\n\n"
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
                # Текстом
                try:
                    await bot.send_message(
                        ADMIN_ID,
                        f"🆕 *Новое объявление!*\n\n"
                        f"📦 {ad['title']}\n"
                        f"💰 {ad['price']}{city}{age}\n\n"
                        f"🔗 [Открыть на OLX]({ad['url']})",
                        parse_mode=ParseMode.MARKDOWN,
                        disable_notification=not Config.notify_sound
                    )
                except:
                    try:
                        await bot.send_message(
                            ADMIN_ID,
                            f"🆕 {ad['title']}\n💰 {ad['price']}{city}\n🔗 {ad['url']}",
                            disable_notification=not Config.notify_sound
                        )
                    except Exception as e:
                        log.error(f"Send: {e}")

            await asyncio.sleep(0.3)

        if sent:
            log.info(f"✅ Sent: {sent}")


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
