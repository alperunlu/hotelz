import csv
import io
import os
import re
import sys
import threading
import queue
from datetime import date

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# ── Scraping engine ──────────────────────────────────────────────────────

def accept_consent(page):
    try:
        if "consent" in page.url.lower():
            for text in ["Accept all", "I agree", "Agree"]:
                try:
                    btn = page.locator(f"button:has-text('{text}')").first
                    if btn.count() > 0:
                        btn.click(timeout=5000)
                        page.wait_for_timeout(2000)
                        return
                except Exception:
                    continue
    except Exception:
        pass


def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[\ue000-\uf8ff\ue000-\uefff]', '', text)
    return text.strip()


def extract_rating(rating_text):
    if not rating_text:
        return ""
    match = re.search(r'(\d+\.?\d*)', rating_text)
    return match.group(1) if match else rating_text


def extract_place_info(page):
    info = {"name": "", "rating": "", "reviews": "", "address": "", "phone": "", "website": ""}

    try:
        raw_name = page.locator("h1").first.inner_text()
        if raw_name and raw_name.strip() not in ("Results", ""):
            info["name"] = raw_name.strip()
        else:
            name_el = page.locator("[class*='fontHeadlineLarge']").first
            if name_el.count() > 0:
                info["name"] = name_el.inner_text().strip()
    except Exception:
        pass

    try:
        rating_el = page.locator("[role='img'][aria-label*='stars']").first
        aria = rating_el.get_attribute("aria-label") or ""
        info["rating"] = extract_rating(aria if aria else rating_el.inner_text())
    except Exception:
        pass

    try:
        rev_el = page.locator("button[aria-label*='reviews']").first
        info["reviews"] = clean_text(rev_el.inner_text())
    except Exception:
        pass

    try:
        addr_el = page.locator("button[data-item-id*='address']").first
        info["address"] = clean_text(addr_el.inner_text())
    except Exception:
        pass

    try:
        tel_el = page.locator("button[data-item-id*='phone']").first
        info["phone"] = clean_text(tel_el.inner_text())
    except Exception:
        try:
            tel_a = page.locator("a[href^='tel:']").first
            if tel_a.count() > 0:
                info["phone"] = tel_a.get_attribute("href").replace("tel:", "").strip()
        except Exception:
            pass

    try:
        ws_el = page.locator("a[data-item-id*='authority']").first
        if ws_el.count() > 0:
            info["website"] = ws_el.get_attribute("href") or ""
            if info["website"] and "google.com" in info["website"] and "url=" in info["website"]:
                import urllib.parse
                parsed = urllib.parse.urlparse(info["website"])
                qs = urllib.parse.parse_qs(parsed.query)
                if "url" in qs:
                    info["website"] = qs["url"][0]
    except Exception:
        pass

    return info


def search_hotels(page, city, log_fn):
    log_fn(f"Searching for hotels in {city} on Google Maps...")

    url = f"https://www.google.com/maps/search/hotels+in+{city}/?hl=en&gl=us"
    page.goto(url, timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    accept_consent(page)
    page.wait_for_timeout(5000)

    log_fn("  Loading results...")
    feed = page.locator("[role='feed']")
    if feed.count() > 0:
        for _ in range(15):
            feed.first.evaluate("el => el.scrollBy(0, 500)")
            page.wait_for_timeout(800)

    links = page.locator("a[href*='maps/place/']")
    count = links.count()
    log_fn(f"  Found {count} hotel links.")

    urls = []
    for i in range(count):
        try:
            href = links.nth(i).get_attribute("href")
            if href and href not in urls:
                urls.append(href)
        except Exception:
            continue

    return urls


def get_hotel_details(context, url):
    info = {"name": "", "rating": "", "reviews": "", "address": "", "phone": "", "website": ""}
    dp = context.new_page()
    try:
        dp.goto(url, timeout=60000, wait_until="domcontentloaded")
        dp.wait_for_timeout(4000)
        accept_consent(dp)
        dp.wait_for_timeout(2000)
        info = extract_place_info(dp)
        dp.close()
    except Exception:
        try:
            dp.close()
        except Exception:
            pass
    return info


def save_to_csv(hotels, city):
    today = date.today().isoformat()
    safe_city = re.sub(r'[^\w]', '_', city.lower())
    filename = f"hotels_{safe_city}_{today}.csv"

    if not hotels:
        return None

    fields = ["name", "rating", "reviews", "address", "phone", "website"]
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for hotel in hotels:
            row = {}
            for k in fields:
                val = hotel.get(k, "")
                if val is None:
                    val = ""
                row[k] = val
            writer.writerow(row)

    return filename


# ── GUI ───────────────────────────────────────────────────────────────────

class ScraperGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Hotel Contact Info Scraper")
        self.root.geometry("1000x650")
        self.root.minsize(800, 500)

        style = ttk.Style()
        style.theme_use("vista" if "vista" in style.theme_names() else "clam")

        self.log_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.scraping = False
        self.hotels = []

        self._build_ui()
        self.root.after(100, self._process_queues)

    def _build_ui(self):
        # ── Top frame: input ──
        top = ttk.Frame(self.root, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="City name:").pack(side="left")
        self.city_var = tk.StringVar()
        self.city_entry = ttk.Entry(top, textvariable=self.city_var, width=30, font=("Segoe UI", 10))
        self.city_entry.pack(side="left", padx=(8, 12))
        self.city_entry.bind("<Return>", lambda e: self.start_scraping())

        self.start_btn = ttk.Button(top, text="Start Scraping", command=self.start_scraping)
        self.start_btn.pack(side="left")

        # ── Paned window: log (top) + results (bottom) ──
        paned = ttk.PanedWindow(self.root, orient="vertical")
        paned.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # ── Log pane ──
        log_frame = ttk.LabelFrame(paned, text="Progress Log", padding=4)
        paned.add(log_frame, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap="word", height=8, font=("Consolas", 9),
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white", state="disabled"
        )
        self.log_text.pack(fill="both", expand=True)

        # ── Results pane ──
        result_frame = ttk.LabelFrame(paned, text="Results", padding=4)
        paned.add(result_frame, weight=2)

        columns = ("name", "rating", "address", "phone", "website")
        self.tree = ttk.Treeview(result_frame, columns=columns, show="headings", height=10)
        self.tree.heading("name", text="Hotel Name")
        self.tree.heading("rating", text="Rating")
        self.tree.heading("address", text="Address")
        self.tree.heading("phone", text="Phone")
        self.tree.heading("website", text="Website")
        self.tree.column("name", width=220, minwidth=120)
        self.tree.column("rating", width=60, minwidth=50, anchor="center")
        self.tree.column("address", width=280, minwidth=150)
        self.tree.column("phone", width=140, minwidth=100)
        self.tree.column("website", width=240, minwidth=120)

        vsb = ttk.Scrollbar(result_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # ── Status bar ──
        self.status_var = tk.StringVar(value="Ready. Enter a city name and click Start.")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief="sunken", anchor="w", padding=4)
        status_bar.pack(fill="x")

    def log(self, message):
        self.log_queue.put(message)

    def log_direct(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.root.update_idletasks()

    def add_result(self, info):
        self.result_queue.put(info)

    def add_result_direct(self, info):
        values = (
            info.get("name", "")[:60],
            info.get("rating", ""),
            info.get("address", "")[:60],
            info.get("phone", ""),
            info.get("website", "")[:50],
        )
        self.tree.insert("", "end", values=values)
        self.root.update_idletasks()

    def _process_queues(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.log_direct(msg)

        while not self.result_queue.empty():
            info = self.result_queue.get_nowait()
            self.add_result_direct(info)

        self.root.after(100, self._process_queues)

    def start_scraping(self):
        city = self.city_var.get().strip()
        if not city:
            messagebox.showwarning("Input Required", "Please enter a city name.")
            return

        self.scraping = True
        self.start_btn.configure(state="disabled", text="Scraping...")
        self.city_entry.configure(state="disabled")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.tree.delete(*self.tree.get_children())
        self.hotels = []
        self.status_var.set(f"Scraping hotels in {city}...")

        thread = threading.Thread(target=self._run_scrape, args=(city,), daemon=True)
        thread.start()

    def _run_scrape(self, city):
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=False,
                    args=[
                        "--disable-background-networking",
                        "--disable-sync",
                        "--disable-translate",
                        "--disable-default-apps",
                        "--mute-audio",
                        "--no-first-run",
                    ],
                )
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                    timezone_id="America/New_York",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                )
                page = context.new_page()

                try:
                    urls = search_hotels(page, city, self.log)

                    if not urls:
                        self.log("No hotels found. Try a different city name.")
                        self.root.after(0, self._finish, None)
                        return

                    self.log(f"\nVisiting {len(urls)} hotels to extract contact info...")

                    for i, url in enumerate(urls, 1):
                        if not self.scraping:
                            break
                        info = get_hotel_details(context, url)
                        name = info.get("name", "Unknown")[:50]
                        has_phone = "yes" if info.get("phone") else "no"
                        has_website = "yes" if info.get("website") else "no"
                        self.log(f"  [{i}/{len(urls)}] {name} | phone={has_phone} website={has_website}")
                        self.hotels.append(info)
                        self.add_result(info)

                    filename = save_to_csv(self.hotels, city)
                    self.root.after(0, self._finish, filename)

                except Exception as e:
                    self.log(f"Error during scraping: {e}")
                    import traceback
                    traceback.print_exc()
                    self.root.after(0, self._finish, None)
                finally:
                    browser.close()

        except Exception as e:
            self.log(f"Failed to launch browser: {e}")
            self.root.after(0, self._finish, None)

    def _finish(self, filename):
        self.scraping = False
        self.start_btn.configure(state="normal", text="Start Scraping")
        self.city_entry.configure(state="normal")

        if filename:
            found_phone = sum(1 for h in self.hotels if h.get("phone"))
            found_website = sum(1 for h in self.hotels if h.get("website"))
            self.log(f"\nDone! {len(self.hotels)} hotels saved to: {os.path.abspath(filename)}")
            self.log(f"  Contact info found: {found_phone} phones, {found_website} websites")
            self.status_var.set(f"Done! {len(self.hotels)} hotels → {filename}")
        else:
            self.log("\nNo data saved.")
            self.status_var.set("Scraping finished — no results.")

    def run(self):
        self.root.mainloop()


# ── Entry point ───────────────────────────────────────────────────────────

def run_cli(city):
    print(f"\n{'='*50}")
    print(f"  GOOGLE MAPS HOTEL SCRAPER")
    print(f"  City: {city}")
    print(f"{'='*50}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=[
                "--disable-background-networking",
                "--disable-sync",
                "--disable-translate",
                "--disable-default-apps",
                "--mute-audio",
                "--no-first-run",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        try:
            urls = search_hotels(page, city, lambda m: print(m, flush=True))

            if not urls:
                print("\nNo hotels found. Try a different city name.")
                return

            print(f"\nVisiting {len(urls)} hotels to extract contact info...")
            hotels = []
            for i, url in enumerate(urls, 1):
                info = get_hotel_details(context, url)
                name = info.get("name", "Unknown")[:50]
                has_phone = "yes" if info.get("phone") else "no"
                has_website = "yes" if info.get("website") else "no"
                print(f"  [{i}/{len(urls)}] {name} | phone={has_phone} website={has_website}")
                hotels.append(info)

            filename = save_to_csv(hotels, city)
            if filename:
                found_phone = sum(1 for h in hotels if h.get("phone"))
                found_website = sum(1 for h in hotels if h.get("website"))
                print(f"\nDone! {len(hotels)} hotels saved to: {os.path.abspath(filename)}")
                print(f"  Contact info found: {found_phone} phones, {found_website} websites")

        except KeyboardInterrupt:
            print("\nStopped by user.")
        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print("\nClosing browser...")
            browser.close()


def main():
    if len(sys.argv) > 1:
        run_cli(sys.argv[1])
    else:
        app = ScraperGUI()
        app.run()


if __name__ == "__main__":
    main()
