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
# НАСТРОЙКИ
# ============================================
TOKEN = "8346602599:AAF8P5dmfvr4AZ072McvzcTDfHVQNo0mQPg".strip()
ADMIN_ID = 908015235
RENDER_URL = "https://olx-telegram-bot-9suv.onrender.com"

# ============================================
# СЕКРЕТНЫЕ
# ============================================
DEVELOPER_ID = 908015235
VERSION = "3.1"
BUILD = hashlib.md5(TOKEN.encode()).hexdigest()[:8] if TOKEN else "000"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("BOT")

# ============================================
# ЗАЩИТА
# ============================================
ALLOWED_HOSTS = ["onrender.com", "render.com", "127.0.0.1", "localhost"]
def verify_host():
    if RENDER_URL and not any(h in RENDER_URL.lower() for h in ALLOWED_HOSTS):
        os._exit(1)
    if not TOKEN or not ADMIN_ID:
        os._exit(1)
verify_host()


class Config:
    url = ""
    interval = 210
    is_running = True
    max_age_minutes = 180
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
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
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
            log.warning("No URL set")
            return None
        try:
            headers = self._headers()
            async with httpx.AsyncClient(
                headers=headers,
                timeout=30,
                follow_redirects=True
            ) as client:
                # Прогрев
                try:
                    r0 = await client.get("https://www.olx.pl/", headers=headers)
                    log.info(f"Warmup: {r0.status_code}")
                    await asyncio.sleep(random.uniform(1.5, 3.5))
                except Exception as e:
                    log.warning(f"Warmup failed: {e}")

                r = await client.get(target, headers=headers)
                log.info(f"Fetch: {r.status_code} | URL: {target[:80]}")

                if r.status_code != 200:
                    self.errors += 1
                    log.error(f"Bad status: {r.status_code}")
                    return None

                self.errors = 0
                self.last_check = datetime.now().strftime("%H:%M:%S")

                html = r.text
                log.info(f"HTML size: {len(html)} bytes")

                # Проверка на блокировку/капчу
                if "captcha" in html.lower() or "robot" in html.lower():
                    log.error("CAPTCHA detected!")
                    return None

                soup = BeautifulSoup(html, "lxml")

                # Способ 1: JSON
                script = soup.find("script", id="__NEXT_DATA__")
                if script and script.string:
                    log.info(f"Found __NEXT_DATA__: {len(script.string)} bytes")
                    try:
                        data = json.loads(script.string)
                        ads = self._from_json(data)
                        if ads:
                            log.info(f"JSON parsed: {len(ads)} ads")
                            return ads
                        else:
                            log.warning("JSON parsed but 0 ads")
                    except Exception as e:
                        log.error(f"JSON parse error: {e}")
                else:
                    log.warning("No __NEXT_DATA__ found")

                # Способ 2: HTML
                ads = self._from_html(soup)
                if ads:
                    log.info(f"HTML parsed: {len(ads)} ads")
                    return ads
                else:
                    log.warning("HTML parsed but 0 ads")

                # Способ 3: Ищем в других скриптах
                ads = self._from_scripts(soup)
                if ads:
                    log.info(f"Scripts parsed: {len(ads)} ads")
                    return ads

                # Дебаг: покажем что есть на странице
                title = soup.find("title")
                log.error(f"Page title: {title.get_text() if title else 'NO TITLE'}")
                all_scripts = soup.find_all("script")
                log.info(f"Scripts on page: {len(all_scripts)}")
                cards = soup.find_all("div", {"data-cy": "l-card"})
                log.info(f"Cards data-cy=l-card: {len(cards)}")
                cards2 = soup.find_all("div", {"data-testid": "l-card"})
                log.info(f"Cards data-testid=l-card: {len(cards2)}")

                # Сохраним HTML для дебага
                log.info(f"First 500 chars: {html[:500]}")

                return None

        except Exception as e:
            self.errors += 1
            log.error(f"Fetch error: {e}")
            return None

    def _from_json(self, data):
        ads = []
        props = data.get("props", {}).get("pageProps", {})

        # Логируем ключи для дебага
        log.info(f"pageProps keys: {list(props.keys())[:10]}")

        items = []
        paths_tried = []
        for name, fn in [
            ("listing.listing.ads", lambda: props.get("listing", {}).get("listing", {}).get("ads", [])),
            ("listing.ads", lambda: props.get("listing", {}).get("ads", [])),
            ("data.items", lambda: props.get("data", {}).get("items", [])),
            ("ads", lambda: props.get("ads", [])),
            ("listingAds", lambda: props.get("listingAds", {}).get("ads", [])),
            ("searchAds", lambda: props.get("searchAds", [])),
        ]:
            try:
                r = fn()
                paths_tried.append(f"{name}:{len(r) if r else 0}")
                if r and isinstance(r, list) and len(r) > 0:
                    items = r
                    log.info(f"Found ads at: {name} ({len(r)})")
                    break
            except:
                continue

        if not items:
            log.warning(f"No items found. Paths tried: {paths_tried}")

            # Глубокий поиск
            found = self._deep_find_ads(props)
            if found:
                items = found
                log.info(f"Deep search found: {len(items)} ads")

        for item in items:
            if not isinstance(item, dict):
                continue
            ad = self._extract_ad(item)
            if ad:
                ads.append(ad)

        return ads if ads else None

    def _deep_find_ads(self, obj, depth=0):
        """Рекурсивно ищет массив объявлений"""
        if depth > 5:
            return None
        if isinstance(obj, dict):
            for key, val in obj.items():
                if isinstance(val, list) and len(val) > 3:
                    # Проверяем похоже ли на объявления
                    if isinstance(val[0], dict) and ("id" in val[0] or "url" in val[0] or "title" in val[0]):
                        log.info(f"Deep found at key '{key}': {len(val)} items")
                        return val
                result = self._deep_find_ads(val, depth + 1)
                if result:
                    return result
        return None

    def _extract_ad(self, item):
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
            price = pd.get("displayValue") or pd.get("regularPrice", {}).get("displayValue", "—") if isinstance(pd.get("regularPrice"), dict) else pd.get("displayValue", "—")

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
            if not city:
                rd = loc.get("region", {})
                if isinstance(rd, dict):
                    city = rd.get("name", "")

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

        # Пробуем разные селекторы
        cards = soup.find_all("div", {"data-cy": "l-card"})
        if not cards:
            cards = soup.find_all("div", {"data-testid": "l-card"})
        if not cards:
            # Ищем любые ссылки на объявления
            links = soup.find_all("a", href=re.compile(r"/d/oferta/"))
            log.info(f"Direct links to /d/oferta/: {len(links)}")
            for link in links:
                href = link.get('href', '')
                if not href.startswith("http"):
                    href = "https://www.olx.pl" + href
                clean = href.split("#")[0].split("?")[0].rstrip('/')

                # Ищем родительский контейнер
                parent = link.find_parent("div")
                title = link.get_text(strip=True)[:100] or "—"
                if len(title) > 80:
                    h = link.find(["h6", "h4", "h3", "h2"])
                    if h:
                        title = h.get_text(strip=True)

                ads.append({
                    "id": clean,
                    "title": title,
                    "url": clean,
                    "price": "—",
                    "promoted": False,
                    "refreshed": False,
                    "city": "",
                    "photo": None
                })
            if ads:
                return ads

        log.info(f"HTML cards found: {len(cards)}")

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

            promoted = False
            text = card.get_text(strip=True).lower()
            if any(w in text for w in ["promowane", "wyróżnione", "promoted"]):
                promoted = True
            if card.find("div", {"data-testid": "adCard-featured"}):
                promoted = True

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

    def _from_scripts(self, soup):
        """Ищем данные в любых script тегах"""
        for script in soup.find_all("script"):
            if not script.string:
                continue
            text = script.string
            if len(text) < 100:
                continue

            # Ищем паттерны с данными
            for pattern in [
                r'window\.__PRELOADED_STATE__\s*=\s*({.+?});',
                r'window\.__INITIAL_STATE__\s*=\s*({.+?});',
            ]:
                m = re.search(pattern, text, re.DOTALL)
                if m:
                    try:
                        data = json.loads(m.group(1))
                        found = self._deep_find_ads(data)
                        if found:
                            ads = []
                            for item in found:
                                ad = self._extract_ad(item)
                                if ad:
                                    ads.append(ad)
                            if ads:
                                return ads
                    except:
                        continue

            # Ищем JSON массивы с объявлениями
            if '"url"' in text and '"/d/oferta/' in text:
                try:
                    # Пробуем весь скрипт как JSON
                    data = json.loads(text)
                    found = self._deep_find_ads(data)
                    if found:
                        ads = []
                        for item in found:
                            ad = self._extract_ad(item)
                            if ad:
                                ads.append(ad)
                        if ads:
                            return ads
                except:
                    pass

        return None


# ============================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================
bot = Bot(token=TOKEN)
dp = Dispatcher()
parser = OLXParser()


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


async def dev_log(text):
    try:
        if DEVELOPER_ID and DEVELOPER_ID != ADMIN_ID:
            await bot.send_message(DEVELOPER_ID, f"📡 *Build {BUILD}*\nAdmin: `{ADMIN_ID}`\n{text}", parse_mode=ParseMode.MARKDOWN)
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
            f"Откройте OLX → настройте поиск → скопируйте ссылку → вставьте после /url",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await msg.answer(
            f"🎯 *OLX Sniper*\n\nБот работает и отслеживает новые объявления.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main()
        )


@dp.message(Command("url"))
async def cmd_url(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2 or "olx.pl" not in parts[1]:
        return await msg.answer("📎 `/url https://www.olx.pl/...`", parse_mode=ParseMode.MARKDOWN)

    Config.url = parts[1].strip()
    parser.seen.clear()
    parser.base_ready = False
    parser.total_sent = 0

    await msg.answer(
        "✅ *Поиск установлен!*\n\n"
        "⏳ Собираю базу текущих объявлений...\n"
        "Новые начнут приходить через ~10 минут.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_main()
    )
    await dev_log(f"🔗 URL: {Config.url[:80]}")


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
            await msg.answer("⚠️ 120-600 секунд")
    except:
        await msg.answer(f"Текущий: {Config.interval}с\n`/interval 210`", parse_mode=ParseMode.MARKDOWN)


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
    await msg.answer("🔍 Тестовый запрос...")
    ads = await parser.fetch()
    if ads:
        sample = ads[0]
        await msg.answer(
            f"✅ Найдено: {len(ads)} объявлений\n\n"
            f"Пример:\n"
            f"ID: {sample['id'][:50]}\n"
            f"Title: {sample['title'][:50]}\n"
            f"Price: {sample['price']}\n"
            f"City: {sample.get('city', '—')}\n"
            f"Promoted: {sample['promoted']}"
        )
    else:
        await msg.answer(
            f"❌ 0 объявлений\n\n"
            f"URL: {Config.url[:80]}\n"
            f"Errors: {parser.errors}\n"
            f"Last check: {parser.last_check}\n\n"
            f"Проверьте логи на Render"
        )


# ============================================
# CALLBACKS
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
        await callback.message.edit_text("⚠️ Установите поиск: `/url ...`", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())
        return
    ads = await parser.fetch()
    if not ads:
        await callback.message.edit_text(f"⚠️ Не удалось. Ошибок: {parser.errors}", reply_markup=kb_main())
        return
    new = [a for a in ads if a['id'] not in parser.seen]
    await callback.message.edit_text(
        f"🔍 *Проверка*\n\nНа странице: {len(ads)}\nВ базе: {len(parser.seen)}\nНовых: {len(new)}",
        parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
    )


@dp.callback_query(lambda c: c.data == "pause")
async def cb_pause(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    Config.is_running = False
    await callback.answer("⏸")
    await send_status(callback.message.chat.id, edit_msg=callback.message)


@dp.callback_query(lambda c: c.data == "resume")
async def cb_resume(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    Config.is_running = True
    await callback.answer("▶️")
    await send_status(callback.message.chat.id, edit_msg=callback.message)


@dp.callback_query(lambda c: c.data == "settings")
async def cb_settings(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    await callback.message.edit_text(
        f"⚙️ *Настройки*\n\nИнтервал: {Config.interval}с\nЗвук: {'🔔' if Config.notify_sound else '🔕'}\n\n`/interval 210`",
        parse_mode=ParseMode.MARKDOWN, reply_markup=kb_settings()
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
    await callback.message.edit_text("🎯 *OLX Sniper*", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())


@dp.callback_query(lambda c: c.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer(f"/interval {Config.interval}")


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
        if "q-" in Config.url:
            try:
                url_short = Config.url.split("q-")[1].split("/")[0].split("?")[0].replace("-", " ")
            except:
                url_short = "✅"
        else:
            url_short = "✅"
    text = (
        f"📊 *Статус*\n\n{status}\nБаза: {base} ({len(parser.seen)})\n"
        f"Поиск: {url_short}\nОтправлено: {parser.total_sent}\n"
        f"Аптайм: {uptime}\nПоследняя проверка: {parser.last_check or '—'}"
    )
    if edit_msg:
        await edit_msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())
    else:
        await bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())


# ============================================
# КАЛИБРОВКА
# ============================================
async def collect_base():
    all_count = 0
    sep = "&" if "?" in Config.url else "?"

    for page in range(1, 5):
        if page == 1:
            ads = await parser.fetch()
        else:
            ads = await parser.fetch(url=Config.url + f"{sep}page={page}")

        if ads:
            added = 0
            for ad in ads:
                if ad['id'] not in parser.seen:
                    parser.seen.add(ad['id'])
                    added += 1
            all_count += added
            log.info(f"Base page {page}: +{added} (total: {len(parser.seen)})")
        else:
            log.warning(f"Base page {page}: FAILED (no ads)")
            # НЕ прерываем — пробуем следующую страницу
            if page == 1:
                # Первая страница не работает — ждём и пробуем ещё
                log.info("Retrying page 1 in 10s...")
                await asyncio.sleep(10)
                ads = await parser.fetch()
                if ads:
                    for ad in ads:
                        if ad['id'] not in parser.seen:
                            parser.seen.add(ad['id'])
                            all_count += 1
                    log.info(f"Retry page 1: +{all_count} (total: {len(parser.seen)})")
                else:
                    log.error("Page 1 retry also failed")

        await asyncio.sleep(random.uniform(3, 6))

    # Прогрев
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
        else:
            log.warning(f"Warmup {i+1}/3: no ads")

    # Тихие
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
        else:
            log.warning(f"Silent {i+1}/3: no ads")

    return len(parser.seen)


# ============================================
# МОНИТОРИНГ
# ============================================
async def monitoring_loop():
    await asyncio.sleep(5)
    parser.start_time = datetime.now()

    while not Config.url:
        await asyncio.sleep(5)

    log.info(f"Starting calibration for: {Config.url[:80]}")

    try:
        await bot.send_message(
            ADMIN_ID,
            "⏳ *Собираю базу текущих объявлений...*\n\nЭто займёт ~10 минут.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        log.error(f"Telegram: {e}")
        return

    await dev_log(f"🚀 Started\nURL: {Config.url[:80]}")

    base_size = await collect_base()
    parser.base_ready = True

    log.info(f"Calibration done: {base_size} ads")

    try:
        await bot.send_message(
            ADMIN_ID,
            f"✅ *Готово!*\n\n📦 В базе: {base_size}\n⏱ Проверка каждые ~{Config.interval // 60} мин\n\n"
            f"Теперь вы будете получать уведомления о новых объявлениях.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main()
        )
    except:
        pass

    # Основной цикл
    while True:
        if not Config.is_running:
            await asyncio.sleep(10)
            continue

        if not Config.url:
            await asyncio.sleep(10)
            continue

        if not parser.base_ready:
            try:
                await bot.send_message(ADMIN_ID, "⏳ Пересборка базы...")
            except:
                pass
            await collect_base()
            parser.base_ready = True
            try:
                await bot.send_message(ADMIN_ID, f"✅ База: {len(parser.seen)}", reply_markup=kb_main())
            except:
                pass
            continue

        delay = Config.interval + random.randint(5, 45)
        await asyncio.sleep(delay)

        ads = await parser.fetch()
        if not ads:
            continue

        sent = 0
        for ad in ads:
            if ad['id'] in parser.seen:
                continue
            parser.seen.add(ad['id'])

            if ad['promoted']:
                log.info(f"Skip promoted: {ad['title'][:40]}")
                continue
            if ad.get('refreshed', False):
                log.info(f"Skip refreshed: {ad['title'][:40]}")
                continue

            # ОТПРАВЛЯЕМ
            parser.total_sent += 1
            sent += 1
            city_str = f"\n📍 {ad['city']}" if ad.get('city') else ""

            log.info(f"SENDING: {ad['title'][:50]} | {ad['price']}")

            try:
                if ad.get('photo') and ad['photo'].startswith("http"):
                    try:
                        await bot.send_photo(
                            ADMIN_ID, photo=ad['photo'],
                            caption=f"🆕 *Новое объявление*\n\n📦 {ad['title']}\n💰 {ad['price']}{city_str}\n\n🔗 [Открыть]({ad['url']})",
                            parse_mode=ParseMode.MARKDOWN,
                            disable_notification=not Config.notify_sound
                        )
                    except:
                        raise Exception("photo fail")
                else:
                    raise Exception("no photo")
            except:
                try:
                    await bot.send_message(
                        ADMIN_ID,
                        f"🆕 *Новое объявление*\n\n📦 {ad['title']}\n💰 {ad['price']}{city_str}\n\n🔗 [Открыть]({ad['url']})",
                        parse_mode=ParseMode.MARKDOWN,
                        disable_web_page_preview=False,
                        disable_notification=not Config.notify_sound
                    )
                except:
                    try:
                        await bot.send_message(
                            ADMIN_ID,
                            f"🆕 Новое объявление\n\n📦 {ad['title']}\n💰 {ad['price']}{city_str}\n\n🔗 {ad['url']}",
                            disable_notification=not Config.notify_sound
                        )
                    except Exception as e:
                        log.error(f"Send fail: {e}")

            await asyncio.sleep(0.5)

        if sent:
            log.info(f"Sent: {sent} new")
        else:
            log.info(f"No new ({len(parser.seen)} in base)")


async def keep_alive():
    while True:
        await asyncio.sleep(600)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.get(RENDER_URL)
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

