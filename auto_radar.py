import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import os
from pathlib import Path
import sqlite3
import threading
import time
import requests
import random
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

# =====================================
# TELEGRAM
# =====================================
# UNESI TELEGRAM PODATKE DIREKTNO OVDE. Ne stavljaj ih u poruke/javni GitHub.
# Koristi NOVI bot token ako je prethodni token bio objavljen u kodu ili četu.
BOT_TOKEN = "OVDE_UNESI_NOVI_TELEGRAM_BOT_TOKEN"
CHAT_ID = "OVDE_UNESI_TELEGRAM_CHAT_ID"
NUM_PAGES = 10

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        try:
            log("TELEGRAM ERROR: Nedostaju TELEGRAM_BOT_TOKEN ili TELEGRAM_CHAT_ID. Proveri BOT_TOKEN i CHAT_ID na početku koda.")
        except NameError:
            print("TELEGRAM ERROR: Nedostaju TELEGRAM_BOT_TOKEN ili TELEGRAM_CHAT_ID. Proveri BOT_TOKEN i CHAT_ID na početku koda.")
        return False

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        response = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": str(message)},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(result.get("description", "Telegram API nije potvrdio slanje."))
        return True
    except Exception as exc:
        # Do not silently swallow Telegram errors; expose them in the activity log.
        try:
            log(f"TELEGRAM ERROR: {exc}")
        except NameError:
            print(f"TELEGRAM ERROR: {exc}")
        return False

def test_telegram():
    success = send_telegram("✅ Auto Radar: test poruka. Telegram veza radi.")
    if success:
        try:
            log("TELEGRAM: Test poruka je uspešno poslata.")
            messagebox.showinfo("Telegram", "Test poruka je poslata. Proveri Telegram.", parent=root)
        except NameError:
            print("Telegram test uspešan.")
    else:
        try:
            messagebox.showerror("Telegram", "Poruka nije poslata. Proveri TELEGRAM ERROR u logu i BOT_TOKEN/CHAT_ID na početku koda.", parent=root)
        except NameError:
            print("Telegram test neuspešan.")

def build_page_urls(base_url):
    urls = []

    for i in range(1, NUM_PAGES + 1):
        if i == 1:
            urls.append(base_url)
        else:
            if "page=" in base_url:
                urls.append(re.sub(r"page=\d+", f"page={i}", base_url))
            else:
                sep = "&" if "?" in base_url else "?"
                urls.append(f"{base_url}{sep}page={i}")

    return urls

# =====================================
# BRAND / MODEL PARSER
# =====================================

def extract_brand_model(url):
    match = re.search(r"/auto-oglasi/\d+/([^/?#]+)", url)

    if not match:
        return "Unknown", "Unknown"

    slug = match.group(1)
    parts = slug.split("-")

    brand = parts[0].capitalize() if parts else "Unknown"
    model = parts[1].upper() if len(parts) > 1 else "Unknown"

    return brand, model




# =====================================
# DATABASE
# =====================================
conn = sqlite3.connect("PolovniRadar.db", check_same_thread=False)
cursor = conn.cursor()

db_lock = threading.RLock()

with db_lock:
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS radars (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        url TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cars (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT,
        model TEXT,
        price INTEGER,
        km INTEGER,
        year INTEGER,
        url TEXT UNIQUE,
        ad_id TEXT UNIQUE,
        created_at TEXT
    )
    """)

    cursor.execute("PRAGMA table_info(cars)")
    columns = [row[1] for row in cursor.fetchall()]

    if "ad_id" not in columns:
        cursor.execute("ALTER TABLE cars ADD COLUMN ad_id TEXT")

    conn.commit()

# =====================================
# SIMILAR CARS QUERY
# =====================================

def get_similar_cars(brand, model, year):
    if year is None:
        return []

    with db_lock:
        cursor.execute("""
            SELECT price, km, year FROM cars
            WHERE brand=? AND model=?
        """, (brand, model))

        rows = cursor.fetchall()

    similar = []

    for price, km, car_year in rows:
        if price is None or km is None or car_year is None:
            continue

        if abs(car_year - year) <= 2:
            similar.append((price, km, car_year))

    return similar

   
# =====================================
# CAR ANALYTICS ENGINE (ADDED)
# =====================================

def get_km_group(km):
    if km is None:
        return "unknown"
    if km <= 15000:
        return "0-15k"
    elif km <= 50000:
        return "15k-50k"
    elif km <= 100000:
        return "50k-100k"
    elif km <= 200000:
        return "100k-200k"
    elif km <= 300000:
        return "200k-300k"
    elif km <= 400000:
        return "300k-400k"
    else:
        return "400k+"
    
def median(lst):
    lst = sorted(lst)
    n = len(lst)
    if n == 0:
        return 0
    mid = n // 2
    if n % 2 == 0:
        return (lst[mid - 1] + lst[mid]) / 2
    return lst[mid]

def calculate_scores(car_price, car_km, car_year, similar_cars):

    if len(similar_cars) < 2:
        return None

    prices = [x[0] for x in similar_cars]
    kms = [x[1] for x in similar_cars]
    years = [x[2] for x in similar_cars]

    median_price = median(prices)
    avg_km = sum(kms) / len(kms)
    avg_year = sum(years) / len(years)

    price_score = (median_price / car_price) * 50 if car_price else 0
    km_score = (avg_km / car_km) * 50 if car_km else 0
    year_score = (car_year / avg_year) * 50 if car_year else 0

    price_score = max(0, min(price_score, 100))
    km_score = max(0, min(km_score, 100))
    year_score = max(0, min(year_score, 100))

    final_score = (
        price_score * 0.5 +
        km_score * 0.3 +
        year_score * 0.2
    )

    price_diff = car_price - median_price
    price_diff_percent = (price_diff / median_price) * 100 if median_price else 0

    scam = (
        price_diff_percent < -30 and
        car_km < 100000 and
        car_year > 2018
    )

    if final_score >= 90:
        label = "🚨 ULTRA DEAL"
    elif final_score >= 80:
        label = "🔥 TOP DEAL"
    elif final_score >= 65:
        label = "👍 GOOD DEAL"
    elif final_score >= 50:
        label = "🤏 OK"
    else:
        label = "❌ BAD"

    return {
        "median_price": median_price,
        "avg_km": avg_km,
        "avg_year": avg_year,
        "price_score": price_score,
        "km_score": km_score,
        "year_score": year_score,
        "final_score": final_score,
        "price_diff": price_diff,
        "price_diff_percent": price_diff_percent,
        "label": label,
        "scam": scam
    }
    

# =====================================
# ✔ ADDED: URL NORMALIZER
# =====================================
def normalize_url(url):
    try:
        return url.split("?")[0]
    except:
        return url


# =====================================
# GLOBALS
# =====================================

# =====================================
# GLOBALS
# =====================================
running = False
checkboxes = []

MAX_PER_CYCLE = 10

radar_workers = {}
workers_lock = threading.Lock()

seen_global = set()
seen_lock = threading.Lock()

sync_scheduled = False

# =====================================
# LOG
# =====================================
def log(text):
    def write_log():
        try:
            logs.insert(tk.END, str(text) + "\n")
            logs.see(tk.END)
        except tk.TclError:
            pass

    try:
        root.after(0, write_log)
    except (tk.TclError, NameError):
        pass


# =====================================
# SAFE INT
# =====================================
def safe_int(text):
    try:
        if not text:
            return None
        digits = "".join([c for c in str(text) if c.isdigit()])
        return int(digits) if digits else None
    except:
        return None


# =====================================
# LISTINGS EXTRACTOR
# =====================================

def extract_listings(page):
    results = set()

    links = page.locator("a[href]").evaluate_all(
        """elements => elements.map(a => a.href)"""
    )

    for url in links:
        if "polovniautomobili.com/auto-oglasi/" not in url:
            continue

        # Preskoči stranicu pretrage, uzmi samo konkretne oglase
        if "/pretraga" in url:
            continue

        url = normalize_url(url)
        ad_id = extract_id(url)

        if ad_id:
            results.add((url, ad_id))
    print("PAGE URL:", page.url)
    print("TITLE:", page.title())
    print("AUTO LINKS:", page.locator('a[href*="/auto-oglasi/"]').count())
    print("FOUND LISTINGS:", len(results))
    return results

# =====================================
# CAR DATA EXTRACTOR
# =====================================
def extract_car_data(page):

    price = None
    km = None
    year = None

    try:
        page.wait_for_timeout(2000)

        # Pronalaženje cene na PolovniAutomobili
        price_el = page.locator('span[class*="FormattedPrice"]').first

        if price_el.count() > 0:
            price_text = price_el.inner_text(timeout=5000)
            price = safe_int(price_text)

            if price is not None and not (100 <= price <= 100_000_000):
                price = None

        print("PRICE DEBUG:", price)

        km = None

        km_selectors = [
            '[data-testid*="mileage"]',
            '[data-testid*="kilomet"]',
            '[data-testid*="odometer"]'
        ]

        for sel in km_selectors:
            el = page.query_selector(sel)
            if el:
                km = safe_int(el.inner_text())
                if km and 100 <= km <= 1_000_000:
                    break
                else:
                    km = None

        if not km:
            text = page.inner_text("body")

            matches = re.findall(r"(\d{1,3}(?:[.,]\d{3})+)\s?km", text)

            cleaned = []
            for m in matches:
                val = safe_int(m)
                if val and 100 <= val <= 1_000_000:
                    cleaned.append(val)

            if cleaned:
                km = min(cleaned)

        CURRENT_YEAR = datetime.now().year

        year = None

        year_el = page.query_selector('[data-testid*="registration"]')
        if year_el:
            year = safe_int(year_el.inner_text())

        if not year:
            text = page.inner_text("body")

            years = re.findall(r"\b(19\d{2}|20\d{2})\b", text)
            years = [int(y) for y in years if 1995 <= int(y) <= CURRENT_YEAR]

            if years:
                year = years[0]

    except:
        pass

    return price, km, year



def extract_id(url):
    match = re.search(r"/auto-oglasi/(\d+)(?:/|$)", url)
    return match.group(1) if match else None


def is_new(url, ad_id):
    with db_lock:
        cursor.execute(
            "SELECT 1 FROM cars WHERE ad_id = ? OR url = ? LIMIT 1",
            (ad_id, url)
        )
        return cursor.fetchone() is None
# =====================================
# INDEPENDENT RADAR WORKER
# =====================================
def radar_worker(radar_id, name, search_url, stop_event):
    browser = None
    local_queue = []
    baseline_done = False

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            context = browser.new_context(
                viewport={"width": 1366, "height": 768},
                locale="sr-RS"
            )
            page = context.new_page()
            page.set_default_navigation_timeout(30000)

            log(f"🟢 STARTED: {name}")

            while not stop_event.is_set():
                try:
                    log(f"🔄 SCANNING: {name}")

                    try:
                        page.goto(
                            search_url,
                            wait_until="domcontentloaded",
                            timeout=30000
                        )
                    except Exception as e:
                        import traceback

                        error_text = traceback.format_exc()

                        log(f"ERROR [{name}]: {e}")
                        log(error_text)

                        print(f"ERROR IN RADAR: {name}")
                        print(error_text)

                        if stop_event.wait(10):
                            break
                    
                    page.wait_for_timeout(2500)
                    page.mouse.wheel(0, 5000)
                    page.wait_for_timeout(1000)

                    listings = extract_listings(page)

                    log(f"📋 {name}: found {len(listings)} listings")

                    # Prvi prolaz samo pamti postojeće oglase.
                    if not baseline_done:
                        baseline_links = {
                            normalize_url(url)
                            for url, _ in listings
                        }

                        with seen_lock:
                            seen_global.update(baseline_links)

                        baseline_done = True
                        log(
                            f"📊 BASELINE {name}: "
                            f"{len(baseline_links)} existing listings"
                        )

                    else:
                        # Dodaj nove oglase u red ovog radara.
                        queued_urls = {
                            normalize_url(item[0])
                            for item in local_queue
                        }

                        for listing_url, ad_id in listings:
                            clean_url = normalize_url(listing_url)

                            with seen_lock:
                                already_seen = clean_url in seen_global

                            if already_seen or clean_url in queued_urls:
                                continue

                            if not is_new(clean_url, ad_id):
                                continue

                            local_queue.append((clean_url, ad_id))
                            queued_urls.add(clean_url)

                        # Obradi najviše MAX_PER_CYCLE oglasa.
                        batch = local_queue[:MAX_PER_CYCLE]
                        local_queue = local_queue[MAX_PER_CYCLE:]

                        for listing_url, ad_id in batch:
                            if stop_event.is_set():
                                break

                            clean_url = normalize_url(listing_url)

                            # Spreči da dva radara obrade isti oglas
                            # istovremeno.
                            with seen_lock:
                                if clean_url in seen_global:
                                    continue
                                seen_global.add(clean_url)

                            try:
                                if stop_event.wait(
                                    random.uniform(2.5, 5.5)
                                ):
                                    with seen_lock:
                                        seen_global.discard(clean_url)
                                    break

                                page.goto(
                                    clean_url,
                                    wait_until="domcontentloaded",
                                    timeout=30000
                                )

                                page.wait_for_timeout(2000)

                                price, km, year = extract_car_data(page)
                                brand, model = extract_brand_model(clean_url)
                                save_time = datetime.now().isoformat()

                                # Sačuvaj oglas; zaključavanje štiti
                                # zajedničku SQLite konekciju.
                                with db_lock:
                                    cursor.execute("""
                                        INSERT OR IGNORE INTO cars
                                        (brand, model, price, km, year,
                                         url, ad_id, created_at)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                    """, (
                                        brand, model, price, km, year,
                                        clean_url, ad_id, save_time
                                    ))

                                    inserted = cursor.rowcount > 0
                                    conn.commit()

                                if not inserted:
                                    continue

                                similar = get_similar_cars(
                                    brand, model, year
                                )

                                score_data = calculate_scores(
                                    price, km, year, similar
                                )

                                if not isinstance(score_data, dict):
                                    score_data = {}

                                score_value = score_data.get("final_score")
                                score_text = (
                                    f"{score_value:.2f}"
                                    if isinstance(score_value, (int, float))
                                    else "N/A"
                                )

                                median_price = score_data.get("median_price")
                                median_text = (
                                    f"{median_price:.0f}"
                                    if isinstance(median_price, (int, float))
                                    else "N/A"
                                )

                                price_diff = score_data.get("price_diff")
                                price_diff_text = (
                                    f"{price_diff:.0f}"
                                    if isinstance(price_diff, (int, float))
                                    else "N/A"
                                )

                                diff_percent = score_data.get(
                                    "price_diff_percent"
                                )
                                diff_percent_text = (
                                    f"{diff_percent:.1f}%"
                                    if isinstance(diff_percent, (int, float))
                                    else "N/A"
                                )

                                def format_score(value):
                                    return (
                                        f"{value:.0f}"
                                        if isinstance(value, (int, float))
                                        else "N/A"
                                    )

                                label = score_data.get(
                                    "label", "NOT ENOUGH DATA"
                                )
                                scam = bool(score_data.get("scam", False))

                                msg = f"""
🚗 NEW {name} FOUND!

🏷 Brand: {brand}
🚘 Model: {model}

🔗 {clean_url}

💰 Price: {price if price is not None else "N/A"}€
📊 KM: {km if km is not None else "N/A"}
📅 Year: {year if year is not None else "N/A"}

📊 SCORE: {score_text}
🏷 LABEL: {label}
🚨 SCAM: {scam}

📊 Market median: {median_text}€
📉 Difference: {price_diff_text}€ ({diff_percent_text})

🧠 SCORE:
💰 Price: {format_score(score_data.get("price_score"))}
📊 KM: {format_score(score_data.get("km_score"))}
📅 Year: {format_score(score_data.get("year_score"))}

🏆 FINAL SCORE: {score_text}/100 ({label})
"""

                                if scam:
                                    msg += "\n⚠ POSSIBLE SCAM DETECTED"

                                if (
                                    isinstance(score_value, (int, float))
                                    and score_value >= 90
                                ):
                                    send_telegram(
                                        "🚨 ULTRA DEAL DETECTED 🚨"
                                    )

                                log(msg)
                                send_telegram(msg)

                            except Exception as e:
                                # Ako obrada nije uspela, dozvoli
                                # ponovni pokušaj u sledećem ciklusu.
                                with seen_lock:
                                    seen_global.discard(clean_url)

                                if not stop_event.is_set():
                                    log(
                                        f"ERROR processing "
                                        f"{clean_url}: {e}"
                                    )

                    if stop_event.wait(30):
                        break

                except Exception as e:
                    log(f"ERROR [{name}]: {e}")

                    if stop_event.wait(10):
                        break

    except Exception as e:
        log(f"RADAR ERROR [{name}]: {e}")

    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass

        with workers_lock:
            worker = radar_workers.get(radar_id)

            # Ne uklanjaj eventualnog novog radnika za isti ID.
            if worker and worker["event"] is stop_event:
                radar_workers.pop(radar_id, None)

        log(f"🔴 STOPPED: {name}")



# =====================================
# START / STOP / WORKER SYNC
# =====================================
def sync_workers():
    global sync_scheduled

    if not running:
        return

    selected = {
        item["id"]: item
        for item in checkboxes
        if item["var"].get()
    }

    with workers_lock:
        # Zaustavi samo radnike čiji radar više nije čekiran.
        for radar_id, worker in list(radar_workers.items()):
            if radar_id not in selected:
                worker["event"].set()

        # Pokreni radnike za čekirane radare koji još ne rade.
        for radar_id, radar in selected.items():
            if radar_id in radar_workers:
                continue

            stop_event = threading.Event()

            thread = threading.Thread(
                target=radar_worker,
                args=(
                    radar_id,
                    radar["name"],
                    radar["url"],
                    stop_event
                ),
                daemon=True
            )

            radar_workers[radar_id] = {
                "event": stop_event,
                "thread": thread,
                "name": radar["name"]
            }

            thread.start()

    # Održavaj samo jedan ciklus provere checkboxova.
    if not sync_scheduled:
        sync_scheduled = True
        root.after(1000, sync_tick)


def sync_tick():
    global sync_scheduled

    sync_scheduled = False

    if running:
        sync_workers()


def start():
    global running

    if not any(item["var"].get() for item in checkboxes):
        messagebox.showwarning(
            "Auto Radar",
            "Selektuj bar jedan radar."
        )
        return

    if not running:
        running = True

        with seen_lock:
            seen_global.clear()

        log("🚗 RADAR STARTED")
        send_telegram("🚗 Radar STARTED")

    sync_workers()


def stop():
    global running

    running = False

    with workers_lock:
        for worker in radar_workers.values():
            worker["event"].set()

    log("🛑 Zaustavljanje svih radara...")
    send_telegram("🛑 Radar STOPPED")


# =====================================
# ADD / DELETE RADAR
# =====================================
def add_radar():
    name = name_entry.get().strip()
    url = url_entry.get().strip()

    if not name or not url:
        messagebox.showwarning(
            "Auto Radar",
            "Unesi naziv radara i URL pretrage."
        )
        return

    if not url.startswith("https://"):
        messagebox.showwarning(
            "Auto Radar",
            "URL mora počinjati sa https://"
        )
        return

    with db_lock:
        cursor.execute(
            "INSERT INTO radars(name, url) VALUES (?, ?)",
            (name, url)
        )
        conn.commit()

    name_entry.delete(0, tk.END)
    url_entry.delete(0, tk.END)
    refresh()


def delete_selected():
    selected_ids = [
        item["id"]
        for item in checkboxes
        if item["var"].get()
    ]

    if not selected_ids:
        messagebox.showwarning(
            "Auto Radar",
            "Čekiraj radar koji želiš da obrišeš."
        )
        return

    with db_lock:
        for radar_id in selected_ids:
            cursor.execute(
                "DELETE FROM radars WHERE id=?",
                (radar_id,)
            )
        conn.commit()

    refresh()


def refresh():
    previous_selection = {
        item["id"]: item["var"].get()
        for item in checkboxes
    }

    for widget in radar_frame.winfo_children():
        widget.destroy()

    checkboxes.clear()

    with db_lock:
        cursor.execute("SELECT id, name, url FROM radars")
        rows = cursor.fetchall()

    for radar_id, name, url in rows:
        var = tk.BooleanVar(
            value=previous_selection.get(radar_id, False)
        )

        cb = tk.Checkbutton(
            radar_frame,
            text=name,
            variable=var,
            command=sync_workers,
            font=("Segoe UI", 10),
            bg="#0f1115",
            fg="#d0d0d0",
            activebackground="#0f1115",
            activeforeground="#ffffff",
            selectcolor="#1e2430"
        )
        cb.pack(anchor="w")

        checkboxes.append({
            "id": radar_id,
            "name": name,
            "url": url,
            "var": var
        })

    if running:
        sync_workers()

# =====================================
# MODERN GUI - CUSTOMTKINTER
# =====================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG = "#081321"
PANEL = "#0D1B2D"
PANEL_2 = "#102239"
BORDER = "#213956"
TEXT = "#EAF2FF"
MUTED = "#8FA8C8"
BLUE = "#2878F0"
GREEN = "#16B981"
RED = "#E0445E"
AMBER = "#E8A23A"

root = ctk.CTk()
root.title("Auto Radar | Pametno praćenje polovnih automobila")
root.geometry("1450x900")
root.minsize(1120, 720)
root.configure(fg_color=BG)

# Shared state for the new GUI
checkboxes = []
log_filter = "Svi"
log_history = []

# Top header
header = ctk.CTkFrame(root, fg_color=PANEL, corner_radius=0, height=78, border_width=1, border_color=BORDER)
header.pack(fill="x")
header.pack_propagate(False)
brand = ctk.CTkFrame(header, fg_color="transparent")
brand.pack(side="left", padx=22, pady=12)
ctk.CTkLabel(brand, text="🚘  Auto Radar", font=ctk.CTkFont(size=25, weight="bold"), text_color=TEXT).pack(anchor="w")
ctk.CTkLabel(brand, text="Pametno praćenje polovnih automobila", font=ctk.CTkFont(size=12), text_color=MUTED).pack(anchor="w")
header_status = ctk.CTkLabel(header, text="●  SISTEM ZAUSTAVLJEN", text_color=AMBER, font=ctk.CTkFont(size=13, weight="bold"))
header_status.pack(side="right", padx=24)

# Main content area: left navigation + workspace
body = ctk.CTkFrame(root, fg_color="transparent")
body.pack(fill="both", expand=True, padx=14, pady=14)
sidebar = ctk.CTkFrame(body, width=165, fg_color=PANEL, corner_radius=14, border_width=1, border_color=BORDER)
sidebar.pack(side="left", fill="y", padx=(0, 12))
sidebar.pack_propagate(False)
ctk.CTkLabel(sidebar, text="MENI", text_color=MUTED, font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=18, pady=(20, 8))
for nav in ["▦  Dashboard", "◉  Radari", "🚗  Oglasi", "▥  Statistika", "⚙  Podešavanja"]:
    ctk.CTkButton(
        sidebar, text=nav, anchor="w", height=38,
        fg_color=BLUE if nav.startswith("▦") else "transparent",
        hover_color=PANEL_2, text_color=TEXT, corner_radius=8,
        command=lambda page=nav: open_menu_page(page)
    ).pack(fill="x", padx=9, pady=3)
ctk.CTkFrame(sidebar, fg_color=BORDER, height=1).pack(fill="x", padx=12, pady=14)
ctk.CTkLabel(sidebar, text="TELEGRAM", text_color=MUTED, font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=18)
telegram_status = ctk.CTkLabel(
    sidebar,
    text="● Podešavanje potrebno" if not BOT_TOKEN or not CHAT_ID else "● Podešeno",
    text_color=AMBER if not BOT_TOKEN or not CHAT_ID else GREEN,
    font=ctk.CTkFont(size=11),
)
telegram_status.pack(anchor="w", padx=18, pady=(5, 8))
ctk.CTkButton(
    sidebar,
    text="Test Telegram",
    command=test_telegram,
    height=30,
    fg_color=PANEL_2,
    hover_color="#405873",
    text_color=TEXT,
    corner_radius=7,
).pack(fill="x", padx=12, pady=(0, 12))
ctk.CTkLabel(sidebar, text="v2.1 • CustomTkinter", text_color="#607895", font=ctk.CTkFont(size=10)).pack(side="bottom", pady=12)

workspace = ctk.CTkFrame(body, fg_color="transparent")
workspace.pack(side="left", fill="both", expand=True)

# Statistics cards
stats = ctk.CTkFrame(workspace, fg_color="transparent")
stats.pack(fill="x", pady=(0, 12))

def make_stat(parent, title, value, subtitle, color):
    card = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=12, border_width=1, border_color=BORDER)
    card.pack(side="left", fill="x", expand=True, padx=(0, 8))
    ctk.CTkLabel(card, text=title, text_color=MUTED, font=ctk.CTkFont(size=12)).pack(anchor="w", padx=15, pady=(12, 0))
    val = ctk.CTkLabel(card, text=value, text_color=color, font=ctk.CTkFont(size=26, weight="bold"))
    val.pack(anchor="w", padx=15, pady=(2, 0))
    ctk.CTkLabel(card, text=subtitle, text_color=MUTED, font=ctk.CTkFont(size=10)).pack(anchor="w", padx=15, pady=(0, 12))
    return val

stat_total = make_stat(stats, "UKUPNO RADARA", "0", "Evidentirano u bazi", "#69A7FF")
stat_active = make_stat(stats, "AKTIVNI RADARI", "0", "Trenutno skeniraju", GREEN)
stat_new = make_stat(stats, "SAČUVANI OGLASI", "0", "Ukupno u bazi", "#C39BFF")
stat_deals = make_stat(stats, "TOP PONUDE", "0", "Zabeležene TOP / ULTRA poruke", AMBER)

upper = ctk.CTkFrame(workspace, fg_color="transparent")
upper.pack(fill="both", expand=True)

# Add radar form
add_panel = ctk.CTkFrame(upper, fg_color=PANEL, corner_radius=12, border_width=1, border_color=BORDER, width=300)
add_panel.pack(side="left", fill="y", padx=(0, 12))
add_panel.pack_propagate(False)
ctk.CTkLabel(add_panel, text="＋  Dodaj novi radar", text_color=TEXT, font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=16, pady=(16, 12))
ctk.CTkLabel(add_panel, text="Naziv radara", text_color=MUTED).pack(anchor="w", padx=16, pady=(0, 5))
name_entry = ctk.CTkEntry(add_panel, placeholder_text="npr. BMW Serija 3", height=38, border_color=BORDER, fg_color="#091626")
name_entry.pack(fill="x", padx=16, pady=(0, 13))
ctk.CTkLabel(add_panel, text="URL pretrage", text_color=MUTED).pack(anchor="w", padx=16, pady=(0, 5))
url_entry = ctk.CTkEntry(add_panel, placeholder_text="https://www.polovniautomobili.com/...", height=38, border_color=BORDER, fg_color="#091626")
url_entry.pack(fill="x", padx=16, pady=(0, 14))
ctk.CTkButton(add_panel, text="＋  DODAJ RADAR", command=add_radar, height=40, fg_color=BLUE, hover_color="#1B63D1", corner_radius=8).pack(fill="x", padx=16)
ctk.CTkFrame(add_panel, fg_color=BORDER, height=1).pack(fill="x", padx=16, pady=16)
ctk.CTkLabel(add_panel, text="UPRAVLJANJE", text_color=MUTED, font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=16, pady=(0, 8))
ctk.CTkButton(add_panel, text="▶  START", command=start, height=38, fg_color=GREEN, hover_color="#0F9565", corner_radius=8).pack(fill="x", padx=16, pady=4)
ctk.CTkButton(add_panel, text="■  STOP SVE", command=stop, height=38, fg_color=RED, hover_color="#B83249", corner_radius=8).pack(fill="x", padx=16, pady=4)
ctk.CTkButton(add_panel, text="▤  OBRIŠI IZABRANE", command=lambda: delete_selected(), height=38, fg_color="#334760", hover_color="#405873", corner_radius=8).pack(fill="x", padx=16, pady=4)
ctk.CTkLabel(add_panel, text="Možeš dodati ili ukloniti radare\ndok aplikacija radi.", text_color=MUTED, font=ctk.CTkFont(size=11), justify="left").pack(anchor="w", padx=16, pady=12)

# Radar list panel
radar_panel = ctk.CTkFrame(upper, fg_color=PANEL, corner_radius=12, border_width=1, border_color=BORDER)
radar_panel.pack(side="left", fill="both", expand=True)
radar_title_row = ctk.CTkFrame(radar_panel, fg_color="transparent")
radar_title_row.pack(fill="x", padx=15, pady=(13, 8))
ctk.CTkLabel(radar_title_row, text="◉  Moji radari", text_color=TEXT, font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
radar_count_label = ctk.CTkLabel(radar_title_row, text="0 sačuvanih", text_color=MUTED, font=ctk.CTkFont(size=11))
radar_count_label.pack(side="right")
radar_headers = ctk.CTkFrame(radar_panel, fg_color=PANEL_2, corner_radius=6)
radar_headers.pack(fill="x", padx=10, pady=(0, 5))
ctk.CTkLabel(radar_headers, text="Izaberi / Naziv", width=180, anchor="w", text_color=MUTED).pack(side="left", padx=8, pady=8)
ctk.CTkLabel(radar_headers, text="Status", width=90, anchor="w", text_color=MUTED).pack(side="left", padx=4)
ctk.CTkLabel(radar_headers, text="Kontrole", anchor="w", text_color=MUTED).pack(side="left", padx=4)
radar_frame = ctk.CTkScrollableFrame(radar_panel, fg_color="transparent", corner_radius=0)
radar_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

# Bottom: activity log and recently found listings
lower = ctk.CTkFrame(workspace, fg_color="transparent")
lower.pack(fill="both", expand=True, pady=(12, 0))
log_panel = ctk.CTkFrame(lower, fg_color=PANEL, corner_radius=12, border_width=1, border_color=BORDER)
log_panel.pack(side="left", fill="both", expand=True, padx=(0, 12))
log_top = ctk.CTkFrame(log_panel, fg_color="transparent")
log_top.pack(fill="x", padx=14, pady=(12, 5))
ctk.CTkLabel(log_top, text="⌁  Aktivnost sistema", text_color=TEXT, font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")
filter_menu = ctk.CTkOptionMenu(log_top, values=["Svi", "Info", "Upozorenja", "Greške"], command=lambda value: change_log_filter(value), width=125, height=30, fg_color=PANEL_2, button_color=BLUE)
filter_menu.pack(side="right")
logs = ctk.CTkTextbox(log_panel, fg_color="#07111E", text_color="#C9D9EE", corner_radius=8, border_width=1, border_color=BORDER, font=ctk.CTkFont(family="Consolas", size=11), wrap="word")
logs.pack(fill="both", expand=True, padx=12, pady=(4, 12))

cars_panel = ctk.CTkFrame(lower, fg_color=PANEL, corner_radius=12, border_width=1, border_color=BORDER, width=380)
cars_panel.pack(side="left", fill="both")
cars_panel.pack_propagate(False)
cars_title_row = ctk.CTkFrame(cars_panel, fg_color="transparent")
cars_title_row.pack(fill="x", padx=13, pady=(12, 8))
ctk.CTkLabel(cars_title_row, text="🚘  Nedavno pronađeni oglasi", text_color=TEXT, font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
cars_table = ctk.CTkScrollableFrame(cars_panel, fg_color="transparent")
cars_table.pack(fill="both", expand=True, padx=8, pady=(0, 8))

# Override log to support filtering while preserving existing log(text) calls from workers.
def classify_log(message):
    text = str(message).lower()
    if "error" in text or "greška" in text or "failed" in text:
        return "Greške"
    if "warning" in text or "upozorenje" in text or "scam" in text:
        return "Upozorenja"
    return "Info"

def render_logs():
    try:
        logs.configure(state="normal")
        logs.delete("1.0", "end")
        for item in log_history[-500:]:
            if log_filter == "Svi" or classify_log(item[1]) == log_filter:
                logs.insert("end", item[0] + "  " + item[1] + "\n")
        logs.see("end")
        logs.configure(state="disabled")
    except Exception:
        pass

def log(message):
    stamp = datetime.now().strftime("%H:%M:%S")
    log_history.append((stamp, str(message)))
    try:
        root.after(0, render_logs)
    except (tk.TclError, RuntimeError):
        pass

def change_log_filter(value):
    global log_filter
    log_filter = value
    render_logs()

# Override refresh to build modern radar rows and retain checkbox/worker integration.
def refresh():
    previous_selection = {item["id"]: item["var"].get() for item in checkboxes}
    for widget in radar_frame.winfo_children():
        widget.destroy()
    checkboxes.clear()
    with db_lock:
        cursor.execute("SELECT id, name, url FROM radars ORDER BY id DESC")
        rows = cursor.fetchall()
    for radar_id, name, url in rows:
        var = tk.BooleanVar(value=previous_selection.get(radar_id, False))
        row = ctk.CTkFrame(radar_frame, fg_color="#0A1727", corner_radius=7, border_width=1, border_color="#172D46")
        row.pack(fill="x", pady=3)
        cb = ctk.CTkCheckBox(row, text=name, variable=var, command=sync_workers, width=180, checkbox_width=18, checkbox_height=18, text_color=TEXT, fg_color=BLUE, hover_color="#1B63D1")
        cb.pack(side="left", padx=8, pady=10)
        status_text = "SCANNING" if radar_id in radar_workers and not radar_workers[radar_id]["event"].is_set() else "STOPPED"
        status_color = GREEN if status_text == "SCANNING" else MUTED
        status_label = ctk.CTkLabel(row, text=status_text, text_color=status_color, width=90, font=ctk.CTkFont(size=10, weight="bold"))
        status_label.pack(side="left", padx=4)
        ctk.CTkButton(row, text="▶", width=30, height=28, fg_color="#126B4C", hover_color="#0F9565", command=lambda v=var, rid=radar_id: set_and_sync(v, rid, True)).pack(side="left", padx=3, pady=5)
        ctk.CTkButton(row, text="■", width=30, height=28, fg_color="#34465E", hover_color="#526984", command=lambda v=var, rid=radar_id: set_and_sync(v, rid, False)).pack(side="left", padx=3, pady=5)
        ctk.CTkButton(row, text="🗑", width=30, height=28, fg_color="#713044", hover_color=RED, command=lambda rid=radar_id, nm=name: delete_radar_by_id(rid, nm)).pack(side="left", padx=3, pady=5)
        checkboxes.append({"id": radar_id, "name": name, "url": url, "var": var})
        ctk.CTkLabel(row, text=url, text_color="#7893B4", font=ctk.CTkFont(size=10), anchor="w").pack(side="left", fill="x", expand=True, padx=8)
    radar_count_label.configure(text=f"{len(rows)} sačuvanih")
    if running:
        sync_workers()

def set_and_sync(var, radar_id, enabled):
    global running
    var.set(enabled)
    if enabled and not running:
        running = True
        log("🚗 RADAR STARTED")
        send_telegram("🚗 Radar STARTED")
    sync_workers()
    root.after(150, refresh)

# Safe delete: show confirmation, signal active workers, then delete selected saved radars.
def delete_selected():
    selected_ids = [item["id"] for item in checkboxes if item["var"].get()]
    if not selected_ids:
        messagebox.showwarning("Auto Radar", "Prvo čekiraj radar(e) koje želiš da obrišeš.", parent=root)
        return
    dialog = ctk.CTkToplevel(root)
    dialog.title("Potvrda brisanja")
    dialog.geometry("460x285")
    dialog.resizable(False, False)
    dialog.configure(fg_color=BG)
    dialog.transient(root)
    dialog.grab_set()
    ctk.CTkLabel(dialog, text="⚠  Potvrda brisanja", font=ctk.CTkFont(size=20, weight="bold"), text_color=TEXT).pack(anchor="w", padx=22, pady=(22, 12))
    ctk.CTkLabel(dialog, text=f"Želiš da obrišeš {len(selected_ids)} izabran radar(a)?", font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT).pack(anchor="w", padx=22, pady=4)
    ctk.CTkLabel(dialog, text="Aktivni worker-i će dobiti signal za zaustavljanje.\nOglasi koji su već sačuvani ostaće u bazi.", justify="left", wraplength=410, text_color=MUTED).pack(anchor="w", padx=22, pady=(4, 14))
    row = ctk.CTkFrame(dialog, fg_color="transparent")
    row.pack(side="bottom", fill="x", padx=22, pady=18)
    def confirm_delete():
        # Signal workers first so their loops can exit and close their browser contexts.
        with workers_lock:
            for rid in selected_ids:
                worker = radar_workers.get(rid)
                if worker:
                    worker["event"].set()
        with db_lock:
            for rid in selected_ids:
                cursor.execute("DELETE FROM radars WHERE id=?", (rid,))
            conn.commit()
        dialog.destroy()
        log(f"🗑 Obrisano radara: {len(selected_ids)}. Aktivni worker-i su dobili signal za zaustavljanje.")
        refresh()
        update_dashboard()
    ctk.CTkButton(row, text="Otkaži", command=dialog.destroy, fg_color="#263B55", hover_color="#354D6B", width=120).pack(side="left")
    ctk.CTkButton(row, text="Obriši", command=confirm_delete, fg_color=RED, hover_color="#B83249", width=120).pack(side="right")

# Refresh statistics and recent listings without restarting workers.
def update_dashboard():
    try:
        with db_lock:
            cursor.execute("SELECT COUNT(*) FROM radars")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM cars")
            car_count = cursor.fetchone()[0]
            cursor.execute("SELECT price, km, year, brand, model, url FROM cars ORDER BY id DESC LIMIT 8")
            recent = cursor.fetchall()
        active = sum(1 for w in radar_workers.values() if not w["event"].is_set() and w["thread"].is_alive())
        stat_total.configure(text=str(total))
        stat_active.configure(text=str(active))
        stat_new.configure(text=str(car_count))
        stat_deals.configure(text=str(sum(1 for _, message in log_history if "TOP DEAL" in message.upper() or "ULTRA DEAL" in message.upper())))
        header_status.configure(text="●  SISTEM AKTIVAN" if running else "●  SISTEM ZAUSTAVLJEN", text_color=GREEN if running else AMBER)
        for widget in cars_table.winfo_children():
            widget.destroy()
        if not recent:
            ctk.CTkLabel(cars_table, text="Još nema sačuvanih oglasa.", text_color=MUTED).pack(anchor="w", padx=8, pady=10)
        for price, km, year, brand_name, model_name, url in recent:
            item = ctk.CTkFrame(cars_table, fg_color="#0A1727", corner_radius=7)
            item.pack(fill="x", pady=3)
            price_text = f"{price:,} €".replace(",", ".") if price is not None else "Cena N/A"
            details = f"{brand_name or ''} {model_name or ''}  •  {year or '—'}  •  {f'{km:,}'.replace(',', '.') if km is not None else '—'} km"
            ctk.CTkLabel(item, text=details.strip(), text_color=TEXT, anchor="w", font=ctk.CTkFont(size=11)).pack(fill="x", padx=9, pady=(7, 1))
            ctk.CTkLabel(item, text=price_text, text_color=GREEN, anchor="w", font=ctk.CTkFont(size=11, weight="bold")).pack(fill="x", padx=9, pady=(0, 7))
            ctk.CTkButton(item, text="Otvori oglas ↗", width=105, height=24, fg_color=PANEL_2, hover_color="#203A58", command=lambda u=url: open_listing(u)).pack(anchor="e", padx=7, pady=(0, 6))
    except Exception as e:
        log(f"GUI update error: {e}")
    try:
        root.after(3000, update_dashboard)
    except tk.TclError:
        pass

def delete_radar_by_id(radar_id, radar_name):
    """Remove one saved radar and its search URL, after stopping its worker."""
    if not messagebox.askyesno(
        "Obriši radar",
        f"Da li želiš da obrišeš radar '{radar_name}' i njegov sačuvani link?\n\nSačuvani oglasi ostaju u bazi.",
        parent=root,
    ):
        return False
    with workers_lock:
        worker = radar_workers.get(radar_id)
        if worker:
            worker["event"].set()
    with db_lock:
        cursor.execute("DELETE FROM radars WHERE id=?", (radar_id,))
        conn.commit()
    log(f"🗑 Radar '{radar_name}' i njegov link su obrisani.")
    refresh()
    return True


def open_menu_page(page_name):
    """Open a working page for each sidebar menu item."""
    page = page_name.split("  ", 1)[-1].strip()
    if page == "Dashboard":
        # Dashboard is the main window; provide visible confirmation instead of a dead button.
        log("Otvoren Dashboard.")
        return

    win = ctk.CTkToplevel(root)
    win.title(f"Auto Radar | {page}")
    win.geometry("900x620")
    win.minsize(700, 450)
    win.configure(fg_color=BG)
    win.transient(root)

    ctk.CTkLabel(win, text=page, text_color=TEXT, font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", padx=22, pady=(20, 4))
    ctk.CTkLabel(win, text="Auto Radar • pregled i upravljanje", text_color=MUTED).pack(anchor="w", padx=22, pady=(0, 16))
    content = ctk.CTkScrollableFrame(win, fg_color=PANEL, corner_radius=12, border_width=1, border_color=BORDER)
    content.pack(fill="both", expand=True, padx=18, pady=(0, 18))

    if page == "Radari":
        ctk.CTkLabel(content, text="Sačuvani radari i URL linkovi", text_color=TEXT, font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=14, pady=(14, 8))
        with db_lock:
            cursor.execute("SELECT id, name, url FROM radars ORDER BY id DESC")
            radar_rows = cursor.fetchall()
        if not radar_rows:
            ctk.CTkLabel(content, text="Nema sačuvanih radara. Dodaj ih preko forme na Dashboard-u.", text_color=MUTED).pack(anchor="w", padx=14, pady=12)
        for rid, rname, rurl in radar_rows:
            item = ctk.CTkFrame(content, fg_color="#0A1727", corner_radius=8)
            item.pack(fill="x", padx=10, pady=5)
            ctk.CTkLabel(item, text=rname, text_color=TEXT, font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=12, pady=(9, 2))
            ctk.CTkLabel(item, text=rurl, text_color=MUTED, wraplength=680, justify="left").pack(anchor="w", padx=12, pady=(0, 7))
            ctk.CTkButton(item, text="Obriši radar i link", width=160, height=30, fg_color=RED, hover_color="#B83249", command=lambda i=rid, n=rname, w=win: (w.destroy() if delete_radar_by_id(i, n) else None)).pack(anchor="e", padx=12, pady=(0, 9))
        ctk.CTkLabel(content, text="Brisanje uklanja radar i URL iz liste; već sačuvani oglasi ostaju.", text_color=MUTED, wraplength=700).pack(anchor="w", padx=14, pady=12)

    elif page == "Oglasi":
        ctk.CTkLabel(content, text="Oglasi sačuvani u lokalnoj bazi", text_color=TEXT, font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=14, pady=(14, 8))
        with db_lock:
            cursor.execute("SELECT brand, model, price, km, year, url, created_at FROM cars ORDER BY id DESC LIMIT 500")
            car_rows = cursor.fetchall()
        if not car_rows:
            ctk.CTkLabel(content, text="Još nema sačuvanih oglasa.", text_color=MUTED).pack(anchor="w", padx=14, pady=12)
        for brand_name, model_name, price, km, year, url, created_at in car_rows:
            item = ctk.CTkFrame(content, fg_color="#0A1727", corner_radius=8)
            item.pack(fill="x", padx=10, pady=4)
            price_text = f"{price:,} €".replace(",", ".") if price is not None else "Cena nije pronađena"
            details = f"{brand_name or ''} {model_name or ''} • {year or '—'} • {f'{km:,}'.replace(',', '.') if km is not None else '—'} km • {price_text}"
            ctk.CTkLabel(item, text=details, text_color=TEXT, anchor="w").pack(fill="x", padx=10, pady=(8, 2))
            ctk.CTkLabel(item, text=url or "Nema URL-a", text_color=MUTED, wraplength=690, justify="left").pack(anchor="w", padx=10, pady=(0, 4))
            ctk.CTkButton(item, text="Otvori oglas ↗", width=120, height=28, fg_color=PANEL_2, hover_color="#203A58", command=lambda u=url: open_listing(u)).pack(anchor="e", padx=10, pady=(0, 8))

    elif page == "Statistika":
        with db_lock:
            cursor.execute("SELECT COUNT(*) FROM radars")
            radar_total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM cars")
            car_total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM cars WHERE price IS NOT NULL")
            priced_total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM cars WHERE year IS NOT NULL")
            year_total = cursor.fetchone()[0]
        active_total = sum(1 for w in radar_workers.values() if not w["event"].is_set() and w["thread"].is_alive())
        stats_data = [("Sačuvani radari", radar_total), ("Aktivni radari", active_total), ("Sačuvani oglasi", car_total), ("Oglasi sa pronađenom cenom", priced_total), ("Oglasi sa pronađenim godištem", year_total)]
        for label, value in stats_data:
            item = ctk.CTkFrame(content, fg_color="#0A1727", corner_radius=8)
            item.pack(fill="x", padx=12, pady=6)
            ctk.CTkLabel(item, text=label, text_color=MUTED).pack(side="left", padx=14, pady=14)
            ctk.CTkLabel(item, text=str(value), text_color=TEXT, font=ctk.CTkFont(size=20, weight="bold")).pack(side="right", padx=14, pady=8)
        ctk.CTkLabel(content, text="Statistika se računa iz lokalne baze PolovniRadar.db.", text_color=MUTED).pack(anchor="w", padx=14, pady=12)

    elif page == "Podešavanja":
        ctk.CTkLabel(content, text="Telegram obaveštenja", text_color=TEXT, font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=14, pady=(14, 8))
        configured = bool(BOT_TOKEN and CHAT_ID and not BOT_TOKEN.startswith("OVDE_") and not CHAT_ID.startswith("OVDE_"))
        ctk.CTkLabel(content, text="Status: podešeno" if configured else "Status: potrebno je uneti BOT_TOKEN i CHAT_ID u vrhu Python koda", text_color=GREEN if configured else AMBER, wraplength=700, justify="left").pack(anchor="w", padx=14, pady=6)
        ctk.CTkLabel(content, text="BOT_TOKEN i CHAT_ID se unose direktno u kod. Ne šalji ih u čet i ne postavljaj ih javno na GitHub.", text_color=MUTED, wraplength=700, justify="left").pack(anchor="w", padx=14, pady=6)
        ctk.CTkButton(content, text="Test Telegram veze", command=test_telegram, fg_color=BLUE, hover_color="#1B63D1", height=38).pack(anchor="w", padx=14, pady=12)
        ctk.CTkLabel(content, text="Baza podataka: PolovniRadar.db • postojeći oglasi se čuvaju i kada obrišeš radar.", text_color=MUTED, wraplength=700, justify="left").pack(anchor="w", padx=14, pady=6)


def open_listing(url):
    import webbrowser
    if url:
        webbrowser.open(url)

# Keep visible status and stats updated when worker states change.
refresh()
update_dashboard()
log("Auto Radar GUI pokrenut.")
root.protocol("WM_DELETE_WINDOW", lambda: (stop(), root.destroy()))
root.mainloop()
