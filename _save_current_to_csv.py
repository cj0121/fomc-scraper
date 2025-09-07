import pandas as pd
from dataclasses import asdict
from pathlib import Path
from fomc_scraper.fetch import fetch_html
from fomc_scraper.parse_current import CURRENT_CALENDAR_URL, parse_current_calendar

out_path = Path('current_calendar.csv')
html = fetch_html(CURRENT_CALENDAR_URL)
entries = parse_current_calendar(html)
df = pd.DataFrame([asdict(e) for e in entries])
# deterministic column order
cols = [
	'year', 'start_date', 'end_date', 'meeting_type', 'is_cancelled', 'has_sep_projections',
	'statement_url_html', 'minutes_url_html', 'press_conference_url_html', 'source_url'
]
df = df.reindex(columns=cols)
df.to_csv(out_path, index=False)
print(f'saved: {out_path.resolve()}')
print(f'rows: {len(df)}')
print('columns:', list(df.columns))
print('\nhead:')
print(df.head(20).to_string(index=False))
