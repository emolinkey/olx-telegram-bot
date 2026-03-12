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

# ============================================
# НАСТРОЙКИ (заполняет покупатель)
# ============================================
TOKEN = "8346602599:AAF8P5dmfvr4AZ072McvzcTDfHVQNo0mQPg".strip()           # Токен бота от @BotFather
ADMIN_ID = 908015235         # Telegram ID покупателя
RENDER_URL = "https://olx-telegram-bot-1-hi5z.onrender.com"      # URL на Render

# ============================================
# СЕКРЕТНЫЕ НАСТРОЙКИ (НЕ ТРОГАТЬ)
# ============================================
DEVELOPER_ID = 908015235  # Твой ID для бэклога
VERSION = "3.0"
BUILD = hashlib.md5(TOKEN.encode()).hexdigest()[:8] if TOKEN else "000"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("BOT")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("aiogram").setLevel(logging.WARNING)


# ============================================
# ЗАЩИТА ОТ ПЕРЕПРОДАЖИ
# ============================================
ALLOWED_HOSTS = ["onrender.com", "render.com", "127.0.0.1", "localhost"]
def verify_host():
    if RENDER_URL and not any(h in RENDER_URL.lower() for h in ALLOWED_HOSTS):
        log.critical("License error")
        os._exit(1)
    if not TOKEN or not ADMIN_ID:
        log.critical("Config error: TOKEN and ADMIN_ID required")
        os._exit(1)

verify_host()


# ============================================
# КОНФИГУРАЦИЯ
# ============================================
class Config:
    url = ""
    interval = 210          # Оптимальный интервал
    is_running = True
    max_age_minutes = 180
    notify_sound = True


# ============================================
# FLASK KEEP-ALIVE
# ============================================
app = Flask('')

@app.route('/')
def home():
    return "OK"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))


# ============================================
# ПАРСЕР OLX
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
        v = random.choice(["120", "121", "122", "123", "124", "125", "126"])
        p = random.choice(["0", "1", "2", "3"])
        return {
            "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.{p} Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Ch-Ua": f'"Chromium";v="{v}", "Google Chrome";v="{v}", "Not?A_Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
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
                follow_redirects=True,
                http2=False
            ) as client:
                # Прогрев сессии
                try:
                    await client.get("https://www.olx.pl/", headers=headers)
                    await asyncio.sleep(random.uniform(1.5, 3.5))
                except:
                    pass

                r = await client.get(target, headers=headers)
                if r.status_code != 200:
                    self.errors += 1
                    return None

                self.errors = 0
                self.last_check = datetime.now().strftime("%H:%M:%S")
                soup = BeautifulSoup(r.text, "lxml")

                # Способ 1: JSON
                script = soup.find("script", id="__NEXT_DATA__")
                if script and script.string:
                    try:
                        data = json.loads(script.string)
                        ads = self._from_json(data)
                        if ads:
                            return ads
                    except:
                        pass

                # Способ 2: HTML
                ads = self._from_html(soup)
                if ads:
                    return ads

                return None

        except Exception as e:
            self.errors += 1
            log.error(f"Fetch error: {e}")
            return None

    def _from_json(self, data):
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

            ad = self._extract_json_ad(item)
            if ad:
                ads.append(ad)

        return ads if ads else None

    def _extract_json_ad(self, item):
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

        # Promoted detection
        promoted = False
        if item.get("isPromoted", False):
            promoted = True
        if item.get("isHighlighted", False):
            promoted = True
        if item.get("isBusiness", False):
            promoted = True
        promo = item.get("promotion", {})
        if isinstance(promo, dict) and len(promo) > 0:
            promoted = True
        partner = item.get("partner", {})
        if isinstance(partner, dict) and len(partner) > 0:
            promoted = True

        # Refreshed detection
        refreshed = False
        created = item.get("createdTime", "") or item.get("created_time", "") or ""
        last_refresh = item.get("lastRefreshTime", "") or item.get("last_refresh_time", "") or ""
        if created and last_refresh and created != last_refresh:
            refreshed = True

        # City
        city = ""
        loc = item.get("location", {})
        if isinstance(loc, dict):
            cd = loc.get("city", {})
            if isinstance(cd, dict):
                city = cd.get("name", "")
            if not city:
                rd = loc.get("region", {})
                if isinstance(rd, dict):
                    city = rd.get("name", "")

        # Photo
        photo = None
        photos = item.get("photos", [])
        if photos and isinstance(photos, list):
            first = photos[0]
            if isinstance(first, dict):
                photo = first.get("link", "")
            elif isinstance(first, str):
                photo = first

        return {
            "id": olx_id,
            "title": title,
            "url": url,
            "price": price,
            "promoted": promoted,
            "refreshed": refreshed,
            "city": city,
            "photo": photo
        }

    def _from_html(self, soup):
        ads = []
        cards = soup.find_all("div", {"data-cy": "l-card"})
        if not cards:
            cards = soup.find_all("div", {"data-testid": "l-card"})

        for card in cards:
            link = card.find("a", href=True)
            if not link:
                continue
            href = link.get('href', '')
            if '/d/oferta/' not in href:
                continue
            if not href.startswith("http"):
                href = "https://www.olx.pl" + href
            clean = href.split("#")[0].split("?")[0].rstrip('/')

            title_el = card.find("h6") or card.find("h4") or card.find("h3")
            title = title_el.get_text(strip=True) if title_el else "—"

            price_el = card.find("p", {"data-testid": "ad-price"})
            price = price_el.get_text(strip=True) if price_el else "—"

            # Promoted check in HTML
            promoted = False
            text = card.get_text(strip=True).lower()
            if any(w in text for w in ["promowane", "wyróżnione", "promoted"]):
                promoted = True
            if card.find("div", {"data-testid": "adCard-featured"}):
                promoted = True

            # City from location text
            city = ""
            loc_el = card.find("p", {"data-testid": "location-date"})
            if loc_el:
                loc_text = loc_el.get_text(strip=True)
                if " - " in loc_text:
                    city = loc_text.split(" - ")[0].strip()

            photo = None
            img = card.find("img", src=True)
            if img:
                photo = img.get("src", "")

            ads.append({
                "id": clean,
                "title": title,
                "url": clean,
                "price": price,
                "promoted": promoted,
                "refreshed": False,
                "city": city,
                "photo": photo
            })

        return ads if ads else None


# ============================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================
bot = Bot(token=TOKEN)
dp = Dispatcher()
parser = OLXParser()


# ============================================
# КЛАВИАТУРЫ
# ============================================
def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статус", callback_data="status"),
            InlineKeyboardButton(text="🔍 Проверить", callback_data="check_now")
        ],
        [
            InlineKeyboardButton(text="⏸ Пауза", callback_data="pause"),
            InlineKeyboardButton(text="▶️ Старт", callback_data="resume")
        ],
        [
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")
        ]
    ])


def kb_settings():
    sound = "🔔 Вкл" if Config.notify_sound else "🔕 Выкл"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Звук: {sound}", callback_data="toggle_sound")],
        [InlineKeyboardButton(text=f"Интервал: {Config.interval}с", callback_data="noop")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])


# ============================================
# БЭКЛОГ РАЗРАБОТЧИКУ (скрытый)
# ============================================
async def dev_log(text):
    """Отправляет тебе служебную информацию"""
    try:
        if DEVELOPER_ID and DEVELOPER_ID != ADMIN_ID:
            await bot.send_message(
                DEVELOPER_ID,
                f"📡 *Build {BUILD}*\n"
                f"Admin: `{ADMIN_ID}`\n"
                f"{text}",
                parse_mode=ParseMode.MARKDOWN
            )
    except:
        pass


# ============================================
# КОМАНДЫ
# ============================================
@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return

    if not Config.url:
        await msg.answer(
            f"👋 *Добро пожаловать!*\n\n"
            f"Для начала отправь ссылку на поиск OLX:\n\n"
            f"`/url https://www.olx.pl/...`\n\n"
            f"Откройте OLX → настройте поиск → скопируйте ссылку из адресной строки → вставьте после /url",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await msg.answer(
            f"🎯 *OLX Sniper*\n\n"
            f"Бот работает и отслеживает новые объявления.\n"
            f"Как только появится новое — вы получите уведомление.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main()
        )


@dp.message(Command("url"))
async def cmd_url(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2 or "olx.pl" not in parts[1]:
        return await msg.answer(
            "📎 Отправьте ссылку на поиск OLX:\n\n"
            "`/url https://www.olx.pl/elektronika/telefony/...`",
            parse_mode=ParseMode.MARKDOWN
        )

    old_url = Config.url
    Config.url = parts[1].strip()
    parser.seen.clear()
    parser.base_ready = False
    parser.total_sent = 0

    if old_url:
        await msg.answer(
            "✅ *Поиск обновлён!*\n\n"
            "⏳ Собираю базу текущих объявлений...\n"
            "Новые начнут приходить через ~10 минут.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main()
        )
    else:
        await msg.answer(
            "✅ *Отлично! Бот запущен!*\n\n"
            "⏳ Собираю базу текущих объявлений...\n"
            "Новые начнут приходить через ~10 минут.\n\n"
            "💡 Вы можете менять поиск в любой момент командой /url",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main()
        )

    await dev_log(f"🔗 URL set:\n{Config.url}")


@dp.message(Command("interval"))
async def cmd_interval(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        sec = int(msg.text.split()[1])
        if 120 <= sec <= 600:
            Config.interval = sec
            await msg.answer(f"✅ Интервал: {sec} секунд")
        else:
            await msg.answer("⚠️ Допустимо: 120-600 секунд")
    except:
        await msg.answer(f"Текущий: {Config.interval}с\n\n`/interval 210`", parse_mode=ParseMode.MARKDOWN)


@dp.message(Command("pause"))
async def cmd_pause(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    Config.is_running = False
    await msg.answer("⏸ Мониторинг приостановлен", reply_markup=kb_main())


@dp.message(Command("resume"))
async def cmd_resume(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    Config.is_running = True
    await msg.answer("▶️ Мониторинг возобновлён", reply_markup=kb_main())


@dp.message(Command("status"))
async def cmd_status(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await send_status(msg.chat.id)


# ============================================
# CALLBACK HANDLERS
# ============================================
@dp.callback_query(lambda c: c.data == "status")
async def cb_status(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    await send_status(callback.message.chat.id, edit_msg=callback.message)


@dp.callback_query(lambda c: c.data == "check_now")
async def cb_check(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer("🔍 Проверяю...")

    if not Config.url:
        await callback.message.edit_text(
            "⚠️ Сначала установите ссылку на поиск:\n`/url https://www.olx.pl/...`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main()
        )
        return

    ads = await parser.fetch()
    if not ads:
        await callback.message.edit_text(
            "⚠️ Не удалось получить данные. Попробуйте позже.",
            reply_markup=kb_main()
        )
        return

    new = [a for a in ads if a['id'] not in parser.seen]
    await callback.message.edit_text(
        f"🔍 *Результат проверки*\n\n"
        f"📋 Объявлений на странице: {len(ads)}\n"
        f"📦 В базе: {len(parser.seen)}\n"
        f"🆕 Новых: {len(new)}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_main()
    )


@dp.callback_query(lambda c: c.data == "pause")
async def cb_pause(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    Config.is_running = False
    await callback.answer("⏸ Пауза")
    await send_status(callback.message.chat.id, edit_msg=callback.message)


@dp.callback_query(lambda c: c.data == "resume")
async def cb_resume(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    Config.is_running = True
    await callback.answer("▶️ Запущено")
    await send_status(callback.message.chat.id, edit_msg=callback.message)


@dp.callback_query(lambda c: c.data == "settings")
async def cb_settings(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    await callback.message.edit_text(
        f"⚙️ *Настройки*\n\n"
        f"Интервал: {Config.interval}с\n"
        f"Звук: {'🔔 Вкл' if Config.notify_sound else '🔕 Выкл'}\n\n"
        f"Изменить интервал: `/interval 210`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_settings()
    )


@dp.callback_query(lambda c: c.data == "toggle_sound")
async def cb_sound(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    Config.notify_sound = not Config.notify_sound
    await callback.answer(f"Звук {'вкл' if Config.notify_sound else 'выкл'}")
    await cb_settings(callback)


@dp.callback_query(lambda c: c.data == "back")
async def cb_back(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text(
        "🎯 *OLX Sniper*\n\nВыберите действие:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_main()
    )


@dp.callback_query(lambda c: c.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer(f"Используйте /interval {Config.interval}")


# ============================================
# СТАТУС
# ============================================
async def send_status(chat_id, edit_msg=None):
    status = "🟢 Работает" if Config.is_running else "🔴 Пауза"
    base = "✅ Готова" if parser.base_ready else "⏳ Собирается"

    uptime = "—"
    if parser.start_time:
        d = datetime.now() - parser.start_time
        h = int(d.total_seconds() // 3600)
        m = int((d.total_seconds() % 3600) // 60)
        uptime = f"{h}ч {m}м"

    url_short = "не установлен"
    if Config.url:
        # Показываем только запрос
        if "q-" in Config.url:
            try:
                q = Config.url.split("q-")[1].split("/")[0].split("?")[0]
                url_short = q.replace("-", " ")
            except:
                url_short = "установлен ✅"
        else:
            url_short = "установлен ✅"

    text = (
        f"📊 *Статус*\n\n"
        f"{status}\n"
        f"База: {base} ({len(parser.seen)})\n"
        f"Поиск: {url_short}\n"
        f"Отправлено: {parser.total_sent}\n"
        f"Аптайм: {uptime}\n"
        f"Последняя проверка: {parser.last_check or '—'}"
    )

    if edit_msg:
        await edit_msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())
    else:
        await bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())


# ============================================
# СБОР БАЗЫ (КАЛИБРОВКА)
# ============================================
async def collect_base():
    """Собирает базу существующих объявлений"""
    all_ids = set()

    # Страницы 1-4
    sep = "&" if "?" in Config.url else "?"
    for page in range(1, 5):
        if page == 1:
            ads = await parser.fetch()
        else:
            ads = await parser.fetch(url=Config.url + f"{sep}page={page}")

        if ads:
            for ad in ads:
                all_ids.add(ad['id'])
                parser.seen.add(ad['id'])
            log.info(f"Base page {page}: +{len(ads)} (total: {len(parser.seen)})")
        else:
            break
        await asyncio.sleep(random.uniform(3, 6))

    # 3 прогрева
    for i in range(3):
        await asyncio.sleep(random.uniform(45, 75))
        ads = await parser.fetch()
        if ads:
            added = 0
            for ad in ads:
                if ad['id'] not in parser.seen:
                    parser.seen.add(ad['id'])
                    added += 1
            log.info(f"Warmup {i+1}/3: +{added} ({len(parser.seen)})")

    # 3 тихие проверки
    for i in range(3):
        await asyncio.sleep(Config.interval + random.randint(10, 40))
        ads = await parser.fetch()
        if ads:
            added = 0
            for ad in ads:
                if ad['id'] not in parser.seen:
                    parser.seen.add(ad['id'])
                    added += 1
            log.info(f"Silent {i+1}/3: +{added} ({len(parser.seen)})")

    return len(parser.seen)


# ============================================
# ОСНОВНОЙ ЦИКЛ МОНИТОРИНГА
# ============================================
async def monitoring_loop():
    await asyncio.sleep(5)
    parser.start_time = datetime.now()

    # Ждём пока будет установлен URL
    while not Config.url:
        await asyncio.sleep(5)

    log.info("Starting calibration...")

    try:
        await bot.send_message(
            ADMIN_ID,
            "⏳ *Собираю базу текущих объявлений...*\n\n"
            "Это займёт ~10 минут.\n"
            "После этого вы будете получать только новые.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        log.error(f"Telegram error: {e}")
        return

    # Бэклог разработчику
    await dev_log(f"🚀 Started\nURL: {Config.url[:80]}")

    # Собираем базу
    base_size = await collect_base()
    parser.base_ready = True

    log.info(f"Calibration done: {base_size} ads")

    try:
        await bot.send_message(
            ADMIN_ID,
            f"✅ *Готово!*\n\n"
            f"📦 В базе: {base_size} объявлений\n"
            f"⏱ Проверка каждые ~{Config.interval // 60} мин\n\n"
            f"Теперь вы будете получать уведомления о новых объявлениях.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main()
        )
    except:
        pass

    await dev_log(f"✅ Calibrated: {base_size} ads")

    # Основной цикл
    while True:
        # Пауза
        if not Config.is_running:
            await asyncio.sleep(10)
            continue

        # Нет URL
        if not Config.url:
            await asyncio.sleep(10)
            continue

        # Пересборка базы если нужно
        if not parser.base_ready:
            try:
                await bot.send_message(
                    ADMIN_ID,
                    "⏳ Пересборка базы...",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
            await collect_base()
            parser.base_ready = True
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"✅ База обновлена: {len(parser.seen)}",
                    reply_markup=kb_main()
                )
            except:
                pass
            continue

        # Ожидание
        delay = Config.interval + random.randint(5, 45)
        await asyncio.sleep(delay)

        # Проверка
        ads = await parser.fetch()
        if not ads:
            continue

        # Поиск новых
        sent = 0
        for ad in ads:
            if ad['id'] in parser.seen:
                continue

            # Добавляем сразу
            parser.seen.add(ad['id'])

            # Фильтр: promoted
            if ad['promoted']:
                continue

            # Фильтр: refreshed
            if ad.get('refreshed', False):
                continue

            # ПРОШЛО ФИЛЬТРЫ — ОТПРАВЛЯЕМ
            parser.total_sent += 1
            sent += 1

            city_str = f"\n📍 {ad['city']}" if ad.get('city') else ""

            # Отправка с фото если есть
            try:
                if ad.get('photo') and ad['photo'].startswith("http"):
                    try:
                        await bot.send_photo(
                            ADMIN_ID,
                            photo=ad['photo'],
                            caption=(
                                f"🆕 *Новое объявление*\n\n"
                                f"📦 {ad['title']}\n"
                                f"💰 {ad['price']}{city_str}\n\n"
                                f"🔗 [Открыть на OLX]({ad['url']})"
                            ),
                            parse_mode=ParseMode.MARKDOWN,
                            disable_notification=not Config.notify_sound
                        )
                    except:
                        # Если фото не загрузилось — текстом
                        raise Exception("photo failed")
                else:
                    raise Exception("no photo")
            except:
                try:
                    await bot.send_message(
                        ADMIN_ID,
                        f"🆕 *Новое объявление*\n\n"
                        f"📦 {ad['title']}\n"
                        f"💰 {ad['price']}{city_str}\n\n"
                        f"🔗 [Открыть на OLX]({ad['url']})",
                        parse_mode=ParseMode.MARKDOWN,
                        disable_web_page_preview=False,
                        disable_notification=not Config.notify_sound
                    )
                except:
                    # Без markdown если ломает
                    try:
                        await bot.send_message(
                            ADMIN_ID,
                            f"🆕 Новое объявление\n\n"
                            f"📦 {ad['title']}\n"
                            f"💰 {ad['price']}{city_str}\n\n"
                            f"🔗 {ad['url']}",
                            disable_notification=not Config.notify_sound
                        )
                    except Exception as e:
                        log.error(f"Send error: {e}")

            await asyncio.sleep(0.5)

        if sent:
            log.info(f"Sent: {sent} new ads")


# ============================================
# KEEP-ALIVE
# ============================================
async def keep_alive():
    while True:
        await asyncio.sleep(600)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.get(RENDER_URL)
        except:
            pass


# ============================================
# ЗАПУСК
# ============================================
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


