# Auto Radar

A Python desktop application for monitoring used-car search listings, storing discovered ads in a local SQLite database, and sending Telegram notifications.

## Features

- Desktop GUI built with CustomTkinter
- Add, start, stop, and delete multiple search radars
- Scrape search-result pages with Playwright (Chromium, headless mode)
- Extract listing details such as price, mileage, year, brand/model, and URL when available
- Store radar configurations and discovered listings in SQLite
- Send Telegram notifications and test the Telegram connection
- Dashboard with activity logs, recent listings, and basic statistics

> **Note:** This project is a personal/portfolio project. Website markup can change, so extraction may need maintenance. Use the target website responsibly and follow its terms and applicable rules.

## Tech stack

- Python
- CustomTkinter / Tkinter
- Playwright
- SQLite
- Requests
- Telegram Bot API

## Requirements

- Python 3.10 or newer recommended
- Windows is the primary target environment
- Internet connection
- A Telegram bot and chat ID if you want notifications

## Setup

1. Clone or download this repository.
2. Install the Python dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Install the Playwright Chromium browser:

   ```bash
   python -m playwright install chromium
   ```

4. Open `auto_radar.py` and set the Telegram configuration near the top:

   ```python
   BOT_TOKEN = "OVDE_UNESI_NOVI_TELEGRAM_BOT_TOKEN"
   CHAT_ID = "OVDE_UNESI_TELEGRAM_CHAT_ID"
   ```

   Replace the placeholder values **on your own computer only**. Never commit a real bot token or other credentials to GitHub.

5. Run the application:

   ```bash
   python auto_radar.py
   ```

6. Open **Podešavanja** in the app and use **Test Telegram veze** to test notifications.

## Local data

The app creates `PolovniRadar.db` locally to store radar settings and discovered listings. This database is intentionally excluded from version control.

## Current limitations

- Listing extraction depends on the website's current HTML structure.
- Some fields may be unavailable for individual listings.
- The app is currently delivered as a single Python file; splitting it into modules and adding automated tests would be useful next improvements.

## Suggested next improvements

- Move configuration into environment variables or a local, ignored configuration file
- Add automated tests for URL pagination and listing-field parsing
- Add structured logging and clearer per-radar scan status
- Separate the GUI, scraper, database, and Telegram integration into modules
- Add screenshots and a short demo GIF

## License

No license has been added yet. If you want others to reuse or modify this project, choose a license before publishing.
