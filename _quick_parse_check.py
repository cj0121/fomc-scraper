from dataclasses import asdict
import json
from fomc_scraper.fetch import fetch_html
from fomc_scraper.parse_current import CURRENT_CALENDAR_URL, parse_current_calendar

html = fetch_html(CURRENT_CALENDAR_URL)
entries = parse_current_calendar(html)
print(f"entries={len(entries)}")
print(json.dumps([asdict(e) for e in entries[:10]], indent=2))
