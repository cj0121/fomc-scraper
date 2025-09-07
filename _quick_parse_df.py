import pandas as pd
from dataclasses import asdict
from fomc_scraper.fetch import fetch_html
from fomc_scraper.parse_current import CURRENT_CALENDAR_URL, parse_current_calendar

html = fetch_html(CURRENT_CALENDAR_URL)
entries = parse_current_calendar(html)
df = pd.DataFrame([asdict(e) for e in entries])
print('rows=', len(df))
print('\nPreview:')
print(df.head(10).to_string(index=False))
print('\nCounts by year:')
print(df.groupby('year').size())
print('\nCounts by label head (first word):')
print(df['meeting_label'].str.split().str[0].value_counts().head(10))
