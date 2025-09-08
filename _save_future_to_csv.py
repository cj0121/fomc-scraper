import pandas as pd
from dataclasses import asdict
from pathlib import Path

from fomc_scraper.fetch import fetch_html
from fomc_scraper.parse_future import parse_future_calendar, CURRENT_CALENDAR_URL


def main() -> None:
	out_path = Path('future_calendar.csv')
	html = fetch_html(CURRENT_CALENDAR_URL)
	entries = parse_future_calendar(html)
	df = pd.DataFrame([asdict(e) for e in entries])
	cols = [
		'year', 'start_date', 'end_date', 'meeting_type', 'is_cancelled', 'has_sep_projections',
		'statement_url_html', 'minutes_url_html', 'press_conference_url_html', 'source_url'
	]
	if not df.empty:
		df = df.reindex(columns=cols)
	df.to_csv(out_path, index=False)
	print(f'saved: {out_path.resolve()}')
	print(f'rows: {len(df)}')
	if not df.empty:
		print('columns:', list(df.columns))
		print('\nhead:')
		print(df.sort_values(['year', 'start_date']).head(20).to_string(index=False))


if __name__ == '__main__':
	main()


