import os
import asyncio
import httpx
import random
import json
import threading
import logging
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from flask import Flask

TOKEN = "8346602599:AAGz22SEJw5dCJVxVXUAli-pf1Xzf424ZT4"
ADMIN_ID = 908015235
RENDER_URL = "https://olx-telegram-bot-1-hi5z.onrender.com"
VERSION = "2.1 PRO"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("OLX")


class Config:
    url = "https://www.olx.pl/elektronika/telefony/q-iphone-13-pro/?search%5Border%5D=created_at:desc&search%5Bfilter_float_price:from%5D=500&search%5Bfilter_float_price:to%5D=1500"
    interval = 300
    is_running = True
    proxy = None
    max_age_minutes = 30
    notify_sound = True
    show_age = True


class Stats:
    checks_total = 0
    checks_today = 0
    new_today = 0
    blocked_promoted = 0
    blocked_old = 0
    blocked_refreshed = 0
    blocked_no_date = 0
    last_reset_day = None

    @classmethod
    def daily_reset(cls):
        today = datetime.now().strftime("%Y-%m-%d")
        if cls.last_reset_day != today:
            cls.checks_today = 0
            cls.new_today = 0
            cls.last_reset_day = today


app = Flask('')


@app.route('/')
def home():
    return f"OLX Sniper v{VERSION} | Online"


def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))


class OLXParser:
    def __init__(self):
        self.seen = set()
        self.total_found = 0
        self.total_new = 0
        self.last_check = None
        self.errors = 0
        self.base_ready = False
        self.start_time = None
        self.history = []

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

                if r.status_code != 200:
                    self.errors += 1
                    return None

                self.errors = 0
                self.last_check = datetime.now().strftime("%H:%M:%S")
                soup = BeautifulSoup(r.text, "lxml")

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

                ads = []
                cards = soup.find_all("div", {"data-cy": "l-card"})
                for card in cards:
                    link = card.find("a", href=True)
                    if link and '/d/oferta/' in link.get('href', ''):
                        href = link['href']
                        if not href.startswith("http"):
                            href = "https://www.olx.pl" + href
                        clean = href.split("#")[0].split("?")[0].rstrip('/')
                        title_el = card.find("h6") or card.find("h4")
                        title = title_el.get_text(strip=True) if title_el else "?"
                        price_el = card.find("p", {"data-testid": "ad-price"})
                        price = price_el.get_text(strip=True) if price_el else "?"
                        ads.append({
                            "olx_id": clean,
                            "title": title,
                            "url": clean,
                            "price": price,
                            "promoted": False,
                            "created": None,
                            "refreshed": False,
                            "city": "",
                            "photo": None
                        })

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

            olx_id = str(item.get("id", ""))
            if not olx_id:
                continue

            url = item.get("url", "")
            if not url:
                continue
            if not url.startswith("http"):
                url = "https://www.olx.pl" + url
            url = url.split("#")[0].split("?")[0].rstrip('/')

            title = item.get("title", "?")

            price = "?"
            pd = item.get("price", {})
            if isinstance(pd, dict):
                price = pd.get("displayValue") or "?"

            promoted = False
            promo = item.get("promotion", {})
            if isinstance(promo, dict) and len(promo) > 0:
                promoted = True
            if item.get("isPromoted", False):
                promoted = True
            if item.get("isHighlighted", False):
                promoted = True
            # Дополнительная проверка на business
            if item.get("isBusiness", False):
                promoted = True
            partner = item.get("partner", {})
            if isinstance(partner, dict) and len(partner) > 0:
                promoted = True

            created = item.get("createdTime", "") or item.get("created_time", "") or ""
            last_refresh = item.get("lastRefreshTime", "") or item.get("last_refresh_time", "") or ""

            refreshed = False
            if created and last_refresh and created != last_refresh:
                refreshed = True

            city = ""
            loc = item.get("location", {})
            if isinstance(loc, dict):
                city_data = loc.get("city", {})
                if isinstance(city_data, dict):
                    city = city_data.get("name", "")
                if not city:
                    region_data = loc.get("region", {})
                    if isinstance(region_data, dict):
                        city = region_data.get("name", "")

            photo = None
            photos = item.get("photos", [])
            if photos and isinstance(photos, list) and len(photos) > 0:
                first = photos[0]
                if isinstance(first, dict):
                    photo = first.get("link", "")
                elif isinstance(first, str):
                    photo = first

            ads.append({
                "olx_id": olx_id,
                "title": title,
                "url": url,
                "price": price,
                "promoted": promoted,
                "created": created,
                "refreshed": refreshed,
                "city": city,
                "photo": photo
            })

        return ads

    def is_fresh(self, ad):
        """Строгая проверка свежести. Нет даты = блокируем."""
        created = ad.get("created", "")
        if not created:
            return False

        try:
            clean = created
            for tz in ["+01:00", "+02:00", "+00:00", "+03:00", "Z"]:
                clean = clean.replace(tz, "")

            if "T" not in clean:
                return False

            ad_time = datetime.fromisoformat(clean)

            # Пробуем UTC+1 (зима) и UTC+2 (лето)
            now_utc1 = datetime.utcnow() + timedelta(hours=1)
            now_utc2 = datetime.utcnow() + timedelta(hours=2)

            age1 = (now_utc1 - ad_time).total_seconds() / 60
            age2 = (now_utc2 - ad_time).total_seconds() / 60

            # Берём минимальный положительный возраст
            ages = [a for a in [age1, age2] if a >= -5]
            if not ages:
                return False

            age_minutes = min(ages)

            return age_minutes <= Config.max_age_minutes

        except:
            return False

    def get_age_str(self, ad):
        created = ad.get("created", "")
        if not created:
            return ""
        try:
            clean = created
            for tz in ["+01:00", "+02:00", "+00:00", "+03:00", "Z"]:
                clean = clean.replace(tz, "")
            if "T" not in clean:
                return ""
            ad_time = datetime.fromisoformat(clean)
            now = datetime.utcnow() + timedelta(hours=1)
            age_min = int((now - ad_time).total_seconds() / 60)
            if age_min < 0:
                now = datetime.utcnow() + timedelta(hours=2)
                age_min = int((now - ad_time).total_seconds() / 60)
            if age_min < 0:
                return ""
            if age_min < 1:
                return "только что"
            elif age_min < 60:
                return f"{age_min} мин назад"
            elif age_min < 1440:
                return f"{age_min // 60}ч {age_min % 60}м назад"
            else:
                return f"{age_min // 1440}д назад"
        except:
            return ""

    def add_to_history(self, ad):
        self.history.append({
            "title": ad['title'][:50],
            "price": ad['price'],
            "time": datetime.now().strftime("%H:%M"),
            "url": ad['url']
        })
        if len(self.history) > 50:
            self.history = self.history[-50:]


bot = Bot(token=TOKEN)
dp = Dispatcher()
parser = OLXParser()


def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статус", callback_data="status"),
            InlineKeyboardButton(text="🔍 Проверить", callback_data="check")
        ],
        [
            InlineKeyboardButton(text="⏸ Пауза", callback_data="pause"),
            InlineKeyboardButton(text="▶️ Старт", callback_data="resume")
        ],
        [
            InlineKeyboardButton(text="📈 Статистика", callback_data="stats"),
            InlineKeyboardButton(text="📜 История", callback_data="history")
        ],
        [
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")
        ]
    ])


def get_settings_keyboard():
    sound = "🔔" if Config.notify_sound else "🔕"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"⏱ Интервал: {Config.interval}с", callback_data="info_interval"),
            InlineKeyboardButton(text=f"🕐 Возраст: {Config.max_age_minutes}м", callback_data="info_age")
        ],
        [
            InlineKeyboardButton(text=f"{sound} Звук", callback_data="toggle_sound")
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")
        ]
    ])


@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return await msg.answer("⛔ Доступ запрещён")
    await msg.answer(
        f"🎯 *OLX Sniper Bot v{VERSION}*\n\n"
        f"Автоматический мониторинг OLX\n\n"
        f"*Команды:*\n"
        f"├ /status — статус\n"
        f"├ /check — проверить\n"
        f"├ /pause /resume — пауза\n"
        f"├ /interval `180` — интервал\n"
        f"├ /age `30` — макс возраст\n"
        f"├ /url `<ссылка>` — поиск\n"
        f"├ /proxy `<прокси>` — прокси\n"
        f"├ /noproxy — без прокси\n"
        f"├ /history — находки\n"
        f"├ /filters — фильтры\n"
        f"├ /reset — сброс\n"
        f"└ /stats — статистика",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard()
    )


@dp.callback_query(lambda c: c.data == "back_main")
async def cb_back(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text(
        f"🎯 *OLX Sniper v{VERSION}*\n\nВыбери действие:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard()
    )


@dp.callback_query(lambda c: c.data == "settings")
async def cb_settings(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text(
        "⚙️ *Настройки*\n\n"
        f"Интервал: {Config.interval}с\n"
        f"Макс возраст: {Config.max_age_minutes} мин\n"
        f"Звук: {'🔔 Вкл' if Config.notify_sound else '🔕 Выкл'}\n\n"
        "Команды:\n`/interval 180`\n`/age 30`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_settings_keyboard()
    )


@dp.callback_query(lambda c: c.data == "toggle_sound")
async def cb_sound(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    Config.notify_sound = not Config.notify_sound
    await callback.answer(f"Звук {'вкл 🔔' if Config.notify_sound else 'выкл 🔕'}")
    await cb_settings(callback)


@dp.callback_query(lambda c: c.data == "status")
async def cb_status(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    s = "🟢 Работает" if Config.is_running else "🔴 Пауза"
    b = "✅ Готова" if parser.base_ready else "⏳ Собирается"
    uptime = "—"
    if parser.start_time:
        delta = datetime.now() - parser.start_time
        h = int(delta.total_seconds() // 3600)
        m = int((delta.total_seconds() % 3600) // 60)
        uptime = f"{h}ч {m}м"
    await callback.message.edit_text(
        f"📊 *Статус*\n\n"
        f"{s} | База: {b}\n"
        f"В базе: `{len(parser.seen)}` ID\n"
        f"Аптайм: {uptime}\n"
        f"Проверка: {parser.last_check or '—'}\n"
        f"Ошибок: {parser.errors}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard()
    )


@dp.callback_query(lambda c: c.data == "check")
async def cb_check(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer("🔍 Проверяю...")
    ads = await parser.fetch()
    if not ads:
        await callback.message.edit_text("❌ Нет данных", reply_markup=get_main_keyboard())
        return
    new_ids = [a for a in ads if a['olx_id'] not in parser.seen]
    fresh = [a for a in new_ids if parser.is_fresh(a) and not a['promoted'] and not a['refreshed']]
    promoted = len([a for a in ads if a['promoted']])
    await callback.message.edit_text(
        f"🔍 *Проверка*\n\n"
        f"Всего: {len(ads)}\nPromoted: {promoted}\n"
        f"В базе: {len(parser.seen)}\nНовых: {len(new_ids)}\n"
        f"Пройдут фильтр: {len(fresh)}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard()
    )


@dp.callback_query(lambda c: c.data == "pause")
async def cb_pause(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    Config.is_running = False
    await callback.answer("⏸ Пауза")
    await cb_status(callback)


@dp.callback_query(lambda c: c.data == "resume")
async def cb_resume(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    Config.is_running = True
    await callback.answer("▶️ Запущено")
    await cb_status(callback)


@dp.callback_query(lambda c: c.data == "stats")
async def cb_stats(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    Stats.daily_reset()
    await callback.message.edit_text(
        f"📈 *Статистика*\n\n"
        f"Проверок: {Stats.checks_total} (сегодня: {Stats.checks_today})\n"
        f"Новых: {parser.total_new} (сегодня: {Stats.new_today})\n\n"
        f"*Заблокировано:*\n"
        f"├ Promoted: {Stats.blocked_promoted}\n"
        f"├ Refreshed: {Stats.blocked_refreshed}\n"
        f"├ Старых: {Stats.blocked_old}\n"
        f"└ Без даты: {Stats.blocked_no_date}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard()
    )


@dp.callback_query(lambda c: c.data == "history")
async def cb_history(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    if not parser.history:
        await callback.message.edit_text("📜 Пусто", reply_markup=get_main_keyboard())
        return
    lines = []
    for h in parser.history[-10:]:
        lines.append(f"`{h['time']}` | {h['price']} | {h['title']}")
    await callback.message.edit_text(
        "📜 *Последние находки:*\n\n" + "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard()
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("info_"))
async def cb_info(callback: types.CallbackQuery):
    await callback.answer("Используй команды для изменения")


@dp.message(Command("status"))
async def cmd_status(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    s = "🟢 Работает" if Config.is_running else "🔴 Пауза"
    b = "✅" if parser.base_ready else "⏳"
    uptime = ""
    if parser.start_time:
        d = datetime.now() - parser.start_time
        uptime = f"\nАптайм: {d.days}д {int(d.seconds//3600)}ч {int(d.seconds%3600//60)}м"
    await msg.answer(
        f"📊 {s} | База: {b} ({len(parser.seen)})\n"
        f"Интервал: {Config.interval}с | Возраст: {Config.max_age_minutes}м\n"
        f"Новых: {parser.total_new} | Ошибок: {parser.errors}{uptime}",
        reply_markup=get_main_keyboard()
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
            await msg.answer("60-3600")
    except:
        await msg.answer("`/interval 180`", parse_mode=ParseMode.MARKDOWN)


@dp.message(Command("age"))
async def cmd_age(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        m = int(msg.text.split()[1])
        if 5 <= m <= 1440:
            Config.max_age_minutes = m
            await msg.answer(f"✅ Возраст: {m} мин")
        else:
            await msg.answer("5-1440")
    except:
        await msg.answer("`/age 30`", parse_mode=ParseMode.MARKDOWN)


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
    parser.total_new = 0
    await msg.answer("✅ URL обновлён, база сброшена")


@dp.message(Command("proxy"))
async def cmd_proxy(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        return await msg.answer("`/proxy http://user:pass@ip:port`", parse_mode=ParseMode.MARKDOWN)
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
        return await msg.answer("❌ Нет данных")
    new_ids = [a for a in ads if a['olx_id'] not in parser.seen]
    fresh = [a for a in new_ids if parser.is_fresh(a) and not a['promoted'] and not a['refreshed']]
    await msg.answer(
        f"Всего: {len(ads)} | Новых: {len(new_ids)} | Пройдут фильтр: {len(fresh)}"
    )


@dp.message(Command("filters"))
async def cmd_filters(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await msg.answer(
        f"🛡 *Фильтры:*\n\n"
        f"├ 🚫 Promoted → блок\n"
        f"├ 🔄 Refreshed → блок\n"
        f"├ ❌ Без даты → блок\n"
        f"├ ⏰ Старше {Config.max_age_minutes}м → блок\n"
        f"└ 🔢 Дубликаты → блок\n\n"
        f"Заблокировано: P:{Stats.blocked_promoted} R:{Stats.blocked_refreshed} "
        f"O:{Stats.blocked_old} N:{Stats.blocked_no_date}",
        parse_mode=ParseMode.MARKDOWN
    )


@dp.message(Command("history"))
async def cmd_history(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    if not parser.history:
        return await msg.answer("📜 Пусто")
    lines = [f"`{h['time']}` | {h['price']} | {h['title']}" for h in parser.history[-15:]]
    await msg.answer("📜 *Находки:*\n\n" + "\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@dp.message(Command("reset"))
async def cmd_reset(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    c = len(parser.seen)
    parser.seen.clear()
    parser.base_ready = False
    parser.total_new = 0
    parser.history.clear()
    await msg.answer(f"🗑 Очищено {c} ID")


@dp.message(Command("stats"))
async def cmd_stats(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    Stats.daily_reset()
    uptime = "—"
    if parser.start_time:
        d = datetime.now() - parser.start_time
        uptime = f"{d.days}д {int(d.seconds//3600)}ч {int(d.seconds%3600//60)}м"
    await msg.answer(
        f"📈 *Статистика*\n\n"
        f"Аптайм: {uptime}\n"
        f"Проверок: {Stats.checks_total} ({Stats.checks_today} сегодня)\n"
        f"Новых: {parser.total_new} ({Stats.new_today} сегодня)\n\n"
        f"Blocked: P:{Stats.blocked_promoted} R:{Stats.blocked_refreshed} "
        f"O:{Stats.blocked_old} N:{Stats.blocked_no_date}\n"
        f"База: {len(parser.seen)}",
        parse_mode=ParseMode.MARKDOWN
    )


async def keep_alive():
    while True:
        await asyncio.sleep(600)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.get(RENDER_URL)
        except:
            pass


async def collect_pages(pages=7):
    all_ads = {}
    sep = "&" if "?" in Config.url else "?"
    for page in range(1, pages + 1):
        if page == 1:
            ads = await parser.fetch()
        else:
            ads = await parser.fetch(url=Config.url + f"{sep}page={page}")
        if ads:
            for ad in ads:
                all_ads[ad['olx_id']] = ad
            log.info(f"   Стр.{page}: +{len(ads)} (уник: {len(all_ads)})")
        else:
            break
        await asyncio.sleep(random.uniform(3, 6))
    return list(all_ads.values())


async def add_to_base(ads):
    added = 0
    if ads:
        for ad in ads:
            if ad['olx_id'] not in parser.seen:
                parser.seen.add(ad['olx_id'])
                added += 1
    return added


async def monitoring_loop():
    await asyncio.sleep(5)
    parser.start_time = datetime.now()

    try:
        await bot.send_message(
            ADMIN_ID,
            f"🚀 *OLX Sniper v{VERSION}*\n\n⏳ Калибровка (~25 мин)...",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        log.error(f"Telegram: {e}")
        return

    # ФАЗА 1: 7 страниц
    log.info("📦 ФАЗА 1: Сбор базы...")
    ads = await collect_pages(7)
    await add_to_base(ads)
    log.info(f"   База: {len(parser.seen)}")

    # ФАЗА 2: 5 прогревов
    log.info("🔥 ФАЗА 2: Прогрев...")
    for i in range(5):
        await asyncio.sleep(random.uniform(40, 70))
        ads = await parser.fetch()
        added = await add_to_base(ads)
        log.info(f"   Прогрев {i+1}/5: +{added} ({len(parser.seen)})")

    # ФАЗА 3: 5 тихих
    log.info("🔇 ФАЗА 3: Тихие...")
    for i in range(5):
        delay = Config.interval + random.randint(10, 60)
        log.info(f"   Тихая {i+1}/5: жду {delay//60}м {delay%60}с")
        await asyncio.sleep(delay)
        ads = await parser.fetch()
        added = await add_to_base(ads)
        log.info(f"   Тихая {i+1}/5: +{added} ({len(parser.seen)})")

    parser.base_ready = True
    log.info(f"✅ Калибровка: {len(parser.seen)}")

    try:
        await bot.send_message(
            ADMIN_ID,
            f"✅ *Калибровка завершена!*\n\n"
            f"📦 База: {len(parser.seen)}\n"
            f"🛡 Фильтры: promoted, refreshed, без даты, старше {Config.max_age_minutes}м\n"
            f"⏱ Интервал: ~{Config.interval//60} мин",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_keyboard()
        )
    except:
        pass

    # ФАЗА 4: Мониторинг
    log.info("👁 ФАЗА 4: Мониторинг")

    while True:
        if not Config.is_running:
            await asyncio.sleep(10)
            continue

        if not parser.base_ready:
            try:
                await bot.send_message(ADMIN_ID, "⏳ Пересборка базы...")
            except:
                pass
            ads = await collect_pages(7)
            await add_to_base(ads)
            for i in range(5):
                await asyncio.sleep(random.uniform(40, 70))
                a = await parser.fetch()
                await add_to_base(a)
            for i in range(5):
                await asyncio.sleep(Config.interval + random.randint(10, 60))
                a = await parser.fetch()
                await add_to_base(a)
            parser.base_ready = True
            try:
                await bot.send_message(ADMIN_ID, f"✅ База: {len(parser.seen)}", reply_markup=get_main_keyboard())
            except:
                pass
            continue

        delay = Config.interval + random.randint(10, 60)
        log.info(f"⏳ Жду {delay//60}м {delay%60}с")
        await asyncio.sleep(delay)

        Stats.daily_reset()
        Stats.checks_total += 1
        Stats.checks_today += 1

        ads = await parser.fetch()
        if not ads:
            log.warning("Нет данных")
            continue

        new_count = 0
        for ad in ads:
            # Уже в базе
            if ad['olx_id'] in parser.seen:
                continue

            # Добавляем в базу СРАЗУ чтобы не повторялось
            parser.seen.add(ad['olx_id'])

            # ФИЛЬТР 1: promoted
            if ad['promoted']:
                Stats.blocked_promoted += 1
                log.info(f"   🚫 Promoted: {ad['title'][:40]}")
                continue

            # ФИЛЬТР 2: refreshed
            if ad['refreshed']:
                Stats.blocked_refreshed += 1
                log.info(f"   🔄 Refreshed: {ad['title'][:40]}")
                continue

            # ФИЛЬТР 3: нет даты
            if not ad.get('created'):
                Stats.blocked_no_date += 1
                log.info(f"   ❌ Без даты: {ad['title'][:40]}")
                continue

            # ФИЛЬТР 4: старое
            if not parser.is_fresh(ad):
                Stats.blocked_old += 1
                log.info(f"   ⏰ Старое: {ad['title'][:40]} ({ad['created'][:16]})")
                continue

            # ПРОШЛО ВСЕ ФИЛЬТРЫ
            parser.total_new += 1
            Stats.new_today += 1
            new_count += 1
            parser.add_to_history(ad)

            age_str = ""
            if Config.show_age:
                age = parser.get_age_str(ad)
                if age:
                    age_str = f"\n⏱ {age}"

            city_str = ""
            if ad.get('city'):
                city_str = f"\n📍 {ad['city']}"

            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"🆕 *НОВОЕ ОБЪЯВЛЕНИЕ!*\n\n"
                    f"📦 {ad['title']}\n"
                    f"💰 {ad['price']}{city_str}{age_str}\n"
                    f"🔗 [Открыть на OLX]({ad['url']})",
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=False,
                    disable_notification=not Config.notify_sound
                )
                await asyncio.sleep(1)
            except Exception as e:
                # Если Markdown ломает ссылку — без Markdown
                try:
                    await bot.send_message(
                        ADMIN_ID,
                        f"🆕 НОВОЕ ОБЪЯВЛЕНИЕ!\n\n"
                        f"📦 {ad['title']}\n"
                        f"💰 {ad['price']}{city_str}{age_str}\n"
                        f"🔗 {ad['url']}",
                        disable_web_page_preview=True,
                        disable_notification=not Config.notify_sound
                    )
                except:
                    log.error(f"Отправка: {e}")

        if new_count:
            log.info(f"🆕 Отправлено: {new_count}")
        else:
            log.info(f"ℹ️ Новых нет ({len(parser.seen)})")


async def main():
    threading.Thread(target=run_flask, daemon=True).start()

    log.info("⏳ Жду 60 сек...")
    await asyncio.sleep(60)

    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(5)

    log.info(f"🚀 OLX SNIPER v{VERSION}")

    logging.getLogger("aiogram.dispatcher").setLevel(logging.CRITICAL)
    logging.getLogger("aiogram.event").setLevel(logging.CRITICAL)

    await asyncio.gather(
        dp.start_polling(bot, skip_updates=True),
        monitoring_loop(),
        keep_alive()
    )


if __name__ == "__main__":
    asyncio.run(main())
