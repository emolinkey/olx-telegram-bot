import os
import asyncio
import httpx
import random
import json
import threading
import logging
import re
import hashlib
import time
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from flask import Flask

TOKEN = "8346602599:AAH5JhZNnBDsi5HHPTCNGaEqCXKx0Tav11A".strip()
ADMIN_ID = 908015235
RENDER_URL = "https://olx-telegram-bot-9suv.onrender.com"
VERSION = "6.0"  # Обновлена версия
BUILD = hashlib.md5(TOKEN.encode()).hexdigest()[:8]
SEEN_FILE = "seen_ids.json"
LAST_CALIBRATION_FILE = "last_calibration.txt"

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
    # Новые параметры
    aggressive_filter = True  # Агрессивная фильтрация дубликатов
    deep_scan_pages = 5  # Сколько страниц сканировать при калибровке
    weekly_recalibration = True  # Еженедельная перекалибровка базы

app = Flask('')

@app.route('/')
def home():
    return "OK"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

# ============================================
# УЛУЧШЕННОЕ СОХРАНЕНИЕ БАЗЫ В ФАЙЛ
# ============================================

def save_seen(seen_set, recent_ads=None):
    """Сохраняет базу ID на диск с дополнительными метаданными"""
    try:
        data = {
            "ids": list(seen_set)[-8000:],  # Увеличили лимит до 8000
            "saved_at": datetime.now().isoformat(),
            "count": len(seen_set),
            "version": VERSION
        }
        
        # Добавляем последние объявления для дедупликации
        if recent_ads:
            data["recent_ads"] = recent_ads[-100:]
            
        with open(SEEN_FILE, 'w') as f:
            json.dump(data, f)
            
        log.info(f"Saved {len(seen_set)} IDs to disk")
    except Exception as e:
        log.error(f"Save error: {e}")

def load_seen():
    """Загружает базу ID с диска с проверкой целостности"""
    try:
        if os.path.exists(SEEN_FILE):
            with open(SEEN_FILE, 'r') as f:
                data = json.load(f)
                
            ids = set(data.get("ids", []))
            saved_at = data.get("saved_at", "")
            
            # Проверка целостности данных
            if not ids or len(ids) < 10:
                log.warning("Loaded database seems corrupted, starting fresh")
                return set(), []
                
            log.info(f"Loaded {len(ids)} IDs from disk (saved: {saved_at})")
            
            # Восстанавливаем последние объявления если есть
            recent_ads = data.get("recent_ads", [])
            return ids, recent_ads
    except Exception as e:
        log.error(f"Load error: {e}")
    
    return set(), []

def save_calibration_time():
    """Сохраняет время последней калибровки"""
    try:
        with open(LAST_CALIBRATION_FILE, 'w') as f:
            f.write(datetime.now().isoformat())
    except Exception as e:
        log.error(f"Error saving calibration time: {e}")

def check_calibration_needed():
    """Проверяет, нужна ли еженедельная перекалибровка"""
    if not Config.weekly_recalibration:
        return False
        
    try:
        if not os.path.exists(LAST_CALIBRATION_FILE):
            return True
            
        with open(LAST_CALIBRATION_FILE, 'r') as f:
            last_date = datetime.fromisoformat(f.read().strip())
            
        # Прошла неделя?
        delta = datetime.now() - last_date
        return delta.days >= 7
    except Exception as e:
        log.error(f"Error checking calibration: {e}")
        return True  # На всякий случай калибруемся

# ============================================
# УЛУЧШЕННЫЙ ПАРСЕР
# ============================================

class OLXParser:
    def __init__(self):
        self.seen, self.recent_ads = load_seen()  # Загружаем с диска!
        self.last_check = None
        self.errors = 0
        self.base_ready = False
        self.start_time = None
        self.total_sent = 0
        self.checks = 0
        self.save_counter = 0
        self.recent_titles = {}  # Для отслеживания дубликатов
        self.last_page_count = 0
        self.consecutive_errors = 0
        self.proxy_list = []  # Можно добавить список прокси

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
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
        }

    def _make_id(self, href):
        if not href.startswith("http"):
            href = "https://www.olx.pl" + href
        clean = href.split("#")[0].split("?")[0].rstrip('/')
        parts = clean.split('/')
        return parts[-1] if parts else clean

    def add_to_seen(self, ad_id, title=None, price=None):
        """Добавляет ID в базу и отслеживает заголовки для дедупликации"""
        self.seen.add(ad_id)
        
        # Добавляем хеш заголовка+цены для дедупликации
        if title and price and Config.aggressive_filter:
            key = f"{title.lower()}:{price.replace(' ', '')}"
            hash_key = hashlib.md5(key.encode()).hexdigest()
            self.recent_titles[hash_key] = time.time()
            
            # Очистка старых записей (старше 24 часов)
            now = time.time()
            self.recent_titles = {k: v for k, v in self.recent_titles.items() 
                                 if now - v < 86400}
        
        self.save_counter += 1
        # Сохраняем каждые 10 добавлений
        if self.save_counter >= 10:
            save_seen(self.seen, self.recent_ads)
            self.save_counter = 0

    def is_duplicate(self, title, price):
        """Проверяет, не дубликат ли объявление на основе заголовка+цены"""
        if not Config.aggressive_filter or not title or not price:
            return False
            
        key = f"{title.lower()}:{price.replace(' ', '')}"
        hash_key = hashlib.md5(key.encode()).hexdigest()
        return hash_key in self.recent_titles

    async def fetch(self, url=None):
        target = url or Config.url
        if not target:
            return None

        if "created_at" not in target:
            sep = "&" if "?" in target else "?"
            target += f"{sep}search%5Border%5D=created_at:desc"

        try:
            headers = self._headers()
            
            # Добавляем случайную задержку для имитации человека
            jitter = random.uniform(0.5, 2.0) 
            await asyncio.sleep(jitter)
            
            async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
                try:
                    # Предварительный запрос на главную страницу (имитация поведения браузера)
                    await client.get("https://www.olx.pl/", headers=headers)
                    await asyncio.sleep(random.uniform(0.8, 1.5))
                except:
                    pass

                # Основной запрос к целевой странице
                r = await client.get(target, headers=headers)
                
                # Обработка ошибок HTTP
                if r.status_code != 200:
                    self.errors += 1
                    self.consecutive_errors += 1
                    
                    # Если много ошибок подряд - увеличиваем задержку
                    if self.consecutive_errors >= 3:
                        log.warning(f"Multiple consecutive errors ({self.consecutive_errors}), increasing delay")
                        await asyncio.sleep(random.uniform(30, 60))
                    
                    return None

                # Сброс счетчика ошибок при успешном запросе
                self.consecutive_errors = 0
                self.errors = 0
                self.last_check = datetime.now().strftime("%H:%M:%S")

                try:
                    html = r.text
                except:
                    html = r.content.decode('utf-8', errors='replace')

                # Проверка на валидный HTML
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
                
                # Проверка на защиту от ботов или капчу
                if "captcha" in html.lower() or "robot" in html.lower() or "automated" in html.lower():
                    log.warning("Captcha or anti-bot detected! Sleeping for recovery...")
                    await asyncio.sleep(random.uniform(180, 300))  # Длительная пауза
                    return None
                
                # Парсинг результатов
                ads = self._from_html(soup)
                if ads:
                    return ads

                # Попытка парсить через JSON API (новый формат OLX)
                script = soup.find("script", id="__NEXT_DATA__")
                if script and script.string:
                    try:
                        data = json.loads(script.string)
                        return self._from_json(data)
                    except Exception as e:
                        log.error(f"JSON parse error: {e}")
                return None

        except Exception as e:
            self.errors += 1
            self.consecutive_errors += 1
            log.error(f"Fetch error: {e}")
            return None

    def _from_html(self, soup):
        ads = []
        
        # Ищем разные форматы карточек объявлений
        cards = soup.find_all("div", {"data-cy": "l-card"})
        if not cards:
            cards = soup.find_all("div", {"data-testid": "l-card"})
        if not cards:
            cards = soup.find_all("div", class_=lambda c: c and ('css-1sw7q4x' in c or 'offer-card' in c))
            
        if not cards:
            log.warning("No cards found in HTML - site structure may have changed")
            return None

        self.last_page_count = len(cards)

        for card in cards:
            try:
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

                price_el = card.find("p", {"data-testid": "ad-price"}) or card.find("p", class_=lambda c: c and ('price' in c.lower()))
                price = price_el.get_text(strip=True) if price_el else "—"

                city = ""
                loc_el = card.find("p", {"data-testid": "location-date"}) or card.find("p", class_=lambda c: c and ('location' in c.lower()))
                if loc_el:
                    txt = loc_el.get_text(strip=True)
                    if " - " in txt:
                        city = txt.split(" - ")[0].strip()

                # Улучшенное определение промо-объявлений
                promoted = False
                
                # Метод 1: Проверка по тексту
                card_lower = card.get_text(strip=True).lower()
                if any(w in card_lower for w in ["promowane", "wyróżnione", "promoted", "sponsorowane", "odświeżone"]):
                    promoted = True
                
                # Метод 2: Проверка по классам и атрибутам
                if card.find("div", {"data-testid": "adCard-featured"}):
                    promoted = True
                if card.find(attrs={"data-testid": re.compile(r"promoted|featured|highlight")}):
                    promoted = True
                if card.find(class_=lambda c: c and any(p in c.lower() for p in ['promoted', 'premium', 'highlighted', 'featured'])):
                    promoted = True
                    
                # Метод 3: Проверка на специальные иконки
                if card.find("svg") and "promowane" in str(card).lower():
                    promoted = True

                # Фото объявления
                photo = None
                img = card.find("img", src=True)
                if img and img.get("src", "").startswith("http"):
                    photo = img["src"]

                # Отметка времени (если есть)
                time_stamp = None
                time_el = card.find(text=re.compile(r'dzisiaj|wczoraj|godz'))
                if time_el:
                    time_stamp = time_el.strip()

                ads.append({
                    "id": ad_id, 
                    "title": title, 
                    "url": url,
                    "price": price, 
                    "city": city, 
                    "photo": photo,
                    "promoted": promoted,
                    "time": time_stamp
                })
                
            except Exception as e:
                log.error(f"Card parse error: {e}")
                continue

        return ads if ads else None

    def _from_json(self, data):
        ads = []
        props = data.get("props", {}).get("pageProps", {})
        items = []
        
        # Несколько возможных путей для доступа к объявлениям в JSON
        for fn in [
            lambda: props.get("listing", {}).get("listing", {}).get("ads", []),
            lambda: props.get("listing", {}).get("ads", []),
            lambda: props.get("ads", []),
            lambda: props.get("initialData", {}).get("listing", {}).get("ads", []),
        ]:
            try:
                r = fn()
                if r and isinstance(r, list) and len(r) > 0:
                    items = r
                    break
            except:
                continue

        for item in items:
            try:
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
                
                # Цена
                price = "—"
                pd = item.get("price", {})
                if isinstance(pd, dict):
                    price = pd.get("displayValue") or "—"

                # Улучшенное определение промо
                promoted = bool(
                    item.get("isPromoted") or 
                    item.get("isHighlighted") or
                    item.get("isBusiness") or
                    item.get("isUrgent") or
                    item.get("isPremium") or
                    (isinstance(item.get("promotion"), dict) and item["promotion"]) or
                    (isinstance(item.get("partner"), dict) and item["partner"]) or
                    (isinstance(item.get("badge"), dict) and item["badge"])
                )

                # Город
                city = ""
                loc = item.get("location", {})
                if isinstance(loc, dict):
                    cd = loc.get("city", {})
                    if isinstance(cd, dict):
                        city = cd.get("name", "")
                    elif isinstance(cd, str):
                        city = cd

                # Фото
                photo = None
                photos = item.get("photos", [])
                if photos and isinstance(photos, list):
                    first = photos[0]
                    if isinstance(first, dict):
                        photo = first.get("link", "") or first.get("url", "")
                    elif isinstance(first, str):
                        photo = first

                # Время публикации
                time_stamp = None
                if "pushupTimestamp" in item or "createdTime" in item:
                    time_stamp = item.get("pushupTimestamp") or item.get("createdTime")

                ads.append({
                    "id": ad_id, 
                    "title": title, 
                    "url": url,
                    "price": price, 
                    "city": city, 
                    "photo": photo,
                    "promoted": promoted,
                    "time": time_stamp
                })
                
            except Exception as e:
                log.error(f"Item parse error: {e}")
                continue

        return ads if ads else None

# Инициализация Telegram бота
bot = Bot(token=TOKEN)
dp = Dispatcher()
parser = OLXParser()

def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статус", callback_data="status"),
         InlineKeyboardButton(text="🔍 Проверить", callback_data="check_now")],
        [InlineKeyboardButton(text="⏸ Пауза", callback_data="pause"),
         InlineKeyboardButton(text="▶️ Старт", callback_data="resume")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
         InlineKeyboardButton(text="🔄 Калибровка", callback_data="recalibrate")]
    ])

def kb_settings():
    sound = "🔔" if Config.notify_sound else "🔕"
    filter_mode = "✅" if Config.aggressive_filter else "❌"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Звук: {sound}", callback_data="toggle_sound"),
         InlineKeyboardButton(text=f"Дубликаты: {filter_mode}", callback_data="toggle_filter")],
        [InlineKeyboardButton(text=f"Интервал: {Config.interval}с", callback_data="interval"),
         InlineKeyboardButton(text=f"Глубина: {Config.deep_scan_pages}", callback_data="depth")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])

@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    if not Config.url:
        await msg.answer("👋 OLX Sniper v6.0\n\n/url https://www.olx.pl/...", parse_mode=ParseMode.MARKDOWN)
    else:
        await msg.answer("🎯 OLX Sniper v6.0 — работает", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())

@dp.message(Command("url"))
async def cmd_url(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2 or "olx.pl" not in parts[1]:
        return await msg.answer("/url https://www.olx.pl/...", parse_mode=ParseMode.MARKDOWN)
    
    new_url = parts[1].strip()
    if "created_at" not in new_url:
        sep = "&" if "?" in new_url else "?"
        new_url += f"{sep}search%5Border%5D=created_at:desc"
        
    Config.url = new_url
    parser.seen.clear()
    parser.recent_titles.clear()
    parser.recent_ads.clear()
    parser.base_ready = False
    parser.total_sent = 0
    
    # Удаляем файл базы при смене поиска
    if os.path.exists(SEEN_FILE):
        os.remove(SEEN_FILE)
        
    await msg.answer("✅ Поиск обновлён!\n⏳ Сборка базы ~2-3 мин...", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())

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
        await msg.answer(f"/interval {Config.interval}", parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("debug"))
async def cmd_debug(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await msg.answer("🔍 Диагностика...")
    ads = await parser.fetch()
    
    if not ads:
        return await msg.answer(f"❌ 0 | Ошибок: {parser.errors}")
        
    new = [a for a in ads if a['id'] not in parser.seen]
    promo = [a for a in ads if a['promoted']]
    dupes = []
    
    for a in new:
        if parser.is_duplicate(a['title'], a['price']):
            dupes.append(a)

    file_exists = "✅" if os.path.exists(SEEN_FILE) else "❌"
    calibration = "—"
    if os.path.exists(LAST_CALIBRATION_FILE):
        try:
            with open(LAST_CALIBRATION_FILE, 'r') as f:
                cal_date = datetime.fromisoformat(f.read().strip())
                delta = datetime.now() - cal_date
                calibration = f"{delta.days}д {delta.seconds//3600}ч назад"
        except:
            calibration = "ошибка"

    txt = (
        f"📋 *Диагностика*\n\n"
        f"На странице: {len(ads)}\n"
        f"Новых (не в базе): {len(new)}\n"
        f"Дубликатов: {len(dupes)}\n"
        f"Promoted: {len(promo)}\n"
        f"В базе: {len(parser.seen)}\n"
        f"Хешей заголовков: {len(parser.recent_titles)}\n"
        f"Файл базы: {file_exists}\n"
        f"Последняя калибровка: {calibration}\n"
        f"Проверок: {parser.checks}\n"
        f"Отправлено: {parser.total_sent}\n\n"
        f"*Топ-5 на странице:*"
    )
    
    for a in ads[:5]:
        flag = "🚫" if a['promoted'] else "🆕" if a['id'] not in parser.seen else "📦"
        if not a['promoted'] and a['id'] not in parser.seen and parser.is_duplicate(a['title'], a['price']):
            flag = "⚠️"  # Дубликат
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
            f"⚙️ *Настройки*\n\n"
            f"• Интервал: {Config.interval}с\n"
            f"• Звук: {'Вкл' if Config.notify_sound else 'Выкл'}\n"
            f"• Фильтр дубликатов: {'Вкл' if Config.aggressive_filter else 'Выкл'}\n"
            f"• Глубина сканирования: {Config.deep_scan_pages} стр.\n\n"
            f"Используйте кнопки ниже для настройки или\n"
            f"/interval 90 - для прямого изменения интервала",
            parse_mode=ParseMode.MARKDOWN, 
            reply_markup=kb_settings()
        )
    except:
        pass

@dp.callback_query(lambda c: c.data == "toggle_sound")
async def cb_sound(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    Config.notify_sound = not Config.notify_sound
    await cb.answer(f"Звук: {'вкл' if Config.notify_sound else 'выкл'}")
    try:
        await cb_settings(cb)
    except:
        pass

@dp.callback_query(lambda c: c.data == "toggle_filter")
async def cb_filter(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    Config.aggressive_filter = not Config.aggressive_filter
    await cb.answer(f"Фильтр дубликатов: {'вкл' if Config.aggressive_filter else 'выкл'}")
    try:
        await cb_settings(cb)
    except:
        pass

@dp.callback_query(lambda c: c.data == "interval")
async def cb_interval_change(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    # Циклически меняем интервал
    intervals = [60, 90, 120, 180, 300, 60]
    current_idx = intervals.index(Config.interval) if Config.interval in intervals else 0
    Config.interval = intervals[(current_idx + 1) % len(intervals)]
    await cb.answer(f"Интервал: {Config.interval}с")
    try:
        await cb_settings(cb)
    except:
        pass

@dp.callback_query(lambda c: c.data == "depth")
async def cb_depth_change(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    # Циклически меняем глубину сканирования
    depths = [3, 5, 8, 10, 3]
    current_idx = depths.index(Config.deep_scan_pages) if Config.deep_scan_pages in depths else 0
    Config.deep_scan_pages = depths[(current_idx + 1) % len(depths)]
    await cb.answer(f"Глубина: {Config.deep_scan_pages} стр.")
    try:
        await cb_settings(cb)
    except:
        pass

@dp.callback_query(lambda c: c.data == "recalibrate")
async def cb_recalibrate(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    await cb.answer("⏳ Запуск калибровки...")
    try:
        await cb.message.edit_text(
            "⏳ *Запуск калибровки базы*\n\n"
            "Бот соберёт информацию о текущих объявлениях,\n"
            "чтобы не показывать их как новые.\n\n"
            "Это займёт 2-3 минуты...",
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        pass
        
    # Принудительная полная перекалибровка
    parser.base_ready = False
    await collect_base(forced=True)
    parser.base_ready = True
    
    # Обновляем метку времени калибровки
    save_calibration_time()
    
    try:
        await cb.message.edit_text(
            f"✅ *Калибровка завершена*\n\n"
            f"• Объявлений в базе: {len(parser.seen)}\n"
            f"• Хешей заголовков: {len(parser.recent_titles)}\n\n"
            f"Теперь бот будет показывать только новые объявления.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main()
        )
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
    await cb.answer(f"Используйте /interval {Config.interval} для изменения")

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
        f"📊 *Статус бота*\n\n"
        f"• Статус: {s} {'Работает' if Config.is_running else 'На паузе'}\n"
        f"• База: {b} ({len(parser.seen)} ID)\n"
        f"• Поиск: {q}\n"
        f"• Отправлено: {parser.total_sent}\n"
        f"• Проверок: {parser.checks}\n"
        f"• Интервал: ~{Config.interval}с\n"
        f"• Аптайм: {up}\n"
        f"• Последняя проверка: {parser.last_check or '—'}"
    )
    
    try:
        if edit_msg:
            await edit_msg.edit_text(t, reply_markup=kb_main(), parse_mode=ParseMode.MARKDOWN)
        else:
            await bot.send_message(chat_id, t, reply_markup=kb_main(), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        log.error(f"Status error: {e}")

# ============================================
# УЛУЧШЕННАЯ КАЛИБРОВКА
# ============================================

async def collect_base(forced=False):
    """
    Улучшенная система сборки базы данных - собирает все существующие ID
    для предотвращения повторной отправки старых объявлений как новых.
    """
    had_before = len(parser.seen)
    sep = "&" if "?" in Config.url else "?"

    # Определяем количество страниц для сканирования
    pages_to_scan = Config.deep_scan_pages
    
    log.info(f"Starting base calibration. Scanning {pages_to_scan} pages...")
    
    if forced:
        # При принудительной перекалибровке очищаем детектор дубликатов
        parser.recent_titles.clear()
    
    # Сначала проверяем первую страницу, чтобы быстрее начать получать новые объявления
    ads = await parser.fetch(Config.url)
    if ads:
        for a in ads:
            parser.add_to_seen(a['id'], a['title'], a['price'])
            # Добавляем в базу дубликатов
            if Config.aggressive_filter:
                parser.is_duplicate(a['title'], a['price'])  # Это добавит в recent_titles
        log.info(f"Base p1: {len(parser.seen)}")
    
    # Затем сканируем оставшиеся страницы (2..N)
    for page in range(2, pages_to_scan + 1):
        target = Config.url + f"{sep}page={page}"
        for attempt in range(2):
            ads = await parser.fetch(target)
            if ads:
                for a in ads:
                    parser.add_to_seen(a['id'], a['title'], a['price'])
                    # Добавляем в базу дубликатов
                    if Config.aggressive_filter:
                        parser.is_duplicate(a['title'], a['price'])
                log.info(f"Base p{page}: {len(parser.seen)}")
                break
            await asyncio.sleep(5)
        # Случайная задержка между страницами для имитации человека
        await asyncio.sleep(random.uniform(3, 5))

    # 2 контрольные проверки первой страницы для уверенности
    for i in range(2):
        await asyncio.sleep(random.uniform(20, 30))
        ads = await parser.fetch()
        if ads:
            for a in ads:
                parser.add_to_seen(a['id'], a['title'], a['price'])
            log.info(f"Verify {i+1}: {len(parser.seen)}")

    # Сохраняем в файл
    save_seen(parser.seen, parser.recent_ads)
    
    # Обновляем время последней калибровки
    save_calibration_time()

    added = len(parser.seen) - had_before
    log.info(f"Calibration done: {len(parser.seen)} total (+{added} new)")
    
    # Сохраняем несколько объявлений для проверки дубликатов
    if ads:
        parser.recent_ads = ads[:30]  # Сохраняем 30 последних для алгоритма
    
    return len(parser.seen)

# ============================================
# УЛУЧШЕННЫЙ МОНИТОРИНГ
# ============================================

async def monitoring_loop():
    await asyncio.sleep(5)
    parser.start_time = datetime.now()

    while not Config.url:
        await asyncio.sleep(5)

    log.info(f"Start OLX Sniper v{VERSION} | Loaded from disk: {len(parser.seen)}")

    # Проверка на необходимость еженедельной перекалибровки
    recalibration_needed = check_calibration_needed()
    
    # Если база загружена с диска и достаточно большая — быстрый старт
    if len(parser.seen) > 50 and not recalibration_needed:
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
        except Exception as e:
            log.error(f"Send restart message error: {e}")

        # Быстрая дозагрузка — 1 страница чтобы поймать то что пропустили
        ads = await parser.fetch()
        if ads:
            for a in ads:
                parser.add_to_seen(a['id'], a['title'], a['price'])
            # Сохраняем несколько для алгоритма дубликатов
            parser.recent_ads = ads[:30]
            save_seen(parser.seen, parser.recent_ads)
            log.info(f"Quick sync: {len(parser.seen)}")

    elif recalibration_needed:
        # Еженедельная перекалибровка
        try:
            await bot.send_message(
                ADMIN_ID,
                f"⏳ *Еженедельная перекалибровка базы...*\n\n"
                f"Это занимает ~2-3 минуты. После этого будут показаны только новые объявления.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            log.error(f"Send weekly calibration message error: {e}")
            
        await collect_base(forced=True)
        parser.base_ready = True
        
        try:
            await bot.send_message(
                ADMIN_ID,
                f"✅ *Еженедельная калибровка завершена*\n\n"
                f"📦 В базе: {len(parser.seen)} объявлений\n"
                f"⏱ Проверка каждые ~{Config.interval}с\n\n"
                f"🎯 Теперь вы будете получать ТОЛЬКО новые объявления.",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
            )
        except Exception as e:
            log.error(f"Send calibration done message error: {e}")
            
    else:
        # Полная калибровка при первом запуске
        try:
            await bot.send_message(
                ADMIN_ID, 
                "⏳ *Первый запуск — сборка базы ~2-3 мин...*\n\nПосле этого только новые объявления.", 
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            log.error(f"Send first start message error: {e}")

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
        except Exception as e:
            log.error(f"Send calibration done message error: {e}")

    # ============ ОСНОВНОЙ ЦИКЛ МОНИТОРИНГА ============
    while True:
        if not Config.is_running or not Config.url:
            await asyncio.sleep(10)
            continue

        if not parser.base_ready:
            await collect_base()
            parser.base_ready = True
            continue

        # Случайная задержка для имитации человеческого поведения
        jitter = random.randint(-5, 20)
        delay = max(60, Config.interval + jitter)  # Минимум 60 секунд
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

            # Проверка на дубликат по заголовку и цене
            if parser.is_duplicate(ad['title'], ad['price']):
                log.info(f"SKIP duplicate content: {ad['title'][:30]}")
                parser.add_to_seen(ad['id'], ad['title'], ad['price'])
                continue

            # Promoted — пропускаем
            if ad['promoted']:
                log.info(f"SKIP promoted: {ad['title'][:30]}")
                parser.add_to_seen(ad['id'], ad['title'], ad['price'])
                continue

            # ===== РЕАЛЬНО НОВОЕ — ОТПРАВЛЯЕМ =====
            parser.total_sent += 1
            sent += 1
            
            # Добавляем в список недавних объявлений для обнаружения дубликатов
            parser.recent_ads.append(ad)
            if len(parser.recent_ads) > 100:
                parser.recent_ads.pop(0)
            
            # Добавляем в базу просмотренных и в базу дубликатов
            parser.add_to_seen(ad['id'], ad['title'], ad['price'])

            city = f"\n📍 {ad['city']}" if ad.get('city') else ""
            time_info = f"\n⏱ {ad['time']}" if ad.get('time') else ""
            
            log.info(f"🆕 #{parser.total_sent}: {ad['title'][:40]} | {ad['price']}")

            try:
                if ad.get('photo') and ad['photo'].startswith("http"):
                    try:
                        await bot.send_photo(
                            ADMIN_ID, photo=ad['photo'],
                            caption=(
                                f"🆕 *Новое объявление!*\n\n"
                                f"📦 {ad['title']}\n"
                                f"💰 {ad['price']}{city}{time_info}\n\n"
                                f"🔗 [Открыть на OLX]({ad['url']})"
                            ),
                            parse_mode=ParseMode.MARKDOWN,
                            disable_notification=not Config.notify_sound
                        )
                    except Exception as e:
                        log.error(f"Send photo error: {e}")
                        raise Exception()
                else:
                    raise Exception()
            except:
                try:
                    await bot.send_message(
                        ADMIN_ID,
                        f"🆕 *Новое объявление!*\n\n"
                        f"📦 {ad['title']}\n"
                        f"💰 {ad['price']}{city}{time_info}\n\n"
                        f"🔗 [Открыть на OLX]({ad['url']})",
                        parse_mode=ParseMode.MARKDOWN,
                        disable_notification=not Config.notify_sound
                    )
                except Exception as e:
                    log.error(f"Send message error: {e}")
                    try:
                        await bot.send_message(
                            ADMIN_ID,
                            f"🆕 {ad['title']}\n💰 {ad['price']}\n🔗 {ad['url']}",
                            disable_notification=not Config.notify_sound
                        )
                    except Exception as e:
                        log.error(f"Send fallback message error: {e}")

            # Небольшая пауза между отправкой сообщений
            await asyncio.sleep(0.5)

        if sent:
            log.info(f"✅ Sent: {sent} | Base: {len(parser.seen)}")
            save_seen(parser.seen, parser.recent_ads)  # Сохраняем после отправки
        else:
            if parser.checks % 20 == 0:
                log.info(f"Check #{parser.checks} ok | Base: {len(parser.seen)}")
                save_seen(parser.seen, parser.recent_ads)  # Периодическое сохранение

        # Проверяем необходимость еженедельной калибровки
        if check_calibration_needed():
            log.info("Weekly recalibration needed")
            await bot.send_message(
                ADMIN_ID,
                f"⏳ *Запланированная перекалибровка*\n\nНачинаю еженедельную перекалибровку базы...",
                parse_mode=ParseMode.MARKDOWN
            )
            await collect_base(forced=True)
            await bot.send_message(
                ADMIN_ID,
                f"✅ *Калибровка завершена*\n\n📦 В базе: {len(parser.seen)} объявлений",
                parse_mode=ParseMode.MARKDOWN
            )

async def keep_alive():
    while True:
        await asyncio.sleep(600)
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                await c.get(RENDER_URL)
        except:
            pass

async def main():
    # Запуск Flask для поддержки хостинга на render.com
    threading.Thread(target=run_flask, daemon=True).start()
    
    log.info("Starting in 15s...")
    await asyncio.sleep(15)
    
    # Удаляем вебхук и пропускаем накопившиеся обновления
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(3)
    
    log.info(f"OLX Sniper v{VERSION} (build {BUILD}) starting...")
    
    await asyncio.gather(
        dp.start_polling(bot, skip_updates=True),
        monitoring_loop(),
        keep_alive()
    )

if __name__ == "__main__":
    asyncio.run(main())
