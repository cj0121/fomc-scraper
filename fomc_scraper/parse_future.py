from __future__ import annotations

import re
import datetime as _dt
from typing import List, Optional, Tuple, Set

from bs4 import BeautifulSoup, Tag

from .parse_current import (
	CURRENT_CALENDAR_URL,
	MONTH_TO_NUM,
	YEAR_IN_HDR,
	MONTH_RE,
	CurrentCalendarEntry,
)


_DAY_RANGE_ONLY_RE = re.compile(r"^(\d{1,2})\s*[-–]\s*(\d{1,2})\*?$")
_DAY_SINGLE_ONLY_RE = re.compile(r"^(\d{1,2})\*?$")


def _iter_year_sections(soup: BeautifulSoup) -> List[Tuple[int, Tag]]:
	sections: List[Tuple[int, Tag]] = []
	headers: List[Tag] = []
	for h in soup.find_all(["h2", "h3", "h4"]):
		text = h.get_text(" ", strip=True)
		m = YEAR_IN_HDR.search(text)
		if not m:
			continue
		if "FOMC" in text:
			headers.append(h)
	for i, h in enumerate(headers):
		year = int(YEAR_IN_HDR.search(h.get_text(" ", strip=True)).group(0))
		next_h = headers[i + 1] if i + 1 < len(headers) else None
		container = soup.new_tag("div")
		sib = h.next_sibling
		while sib is not None and sib is not next_h:
			if isinstance(sib, Tag):
				container.append(sib)
			sib = sib.next_sibling
		sections.append((year, container))
	return sections


def _parse_with_dom(year: int, section: Tag) -> List[Tuple[str, str, bool]]:
	"""Extract future meetings using the page's DOM structure.
	Looks for rows like: <div class="row fomc-meeting"> with month/date columns.
	"""
	rows: List[Tuple[str, str, bool]] = []
	for row in section.find_all("div", class_=lambda c: c and "fomc-meeting" in c):
		month_col = row.find(class_=lambda c: c and "fomc-meeting__month" in c)
		date_col = row.find(class_=lambda c: c and "fomc-meeting__date" in c)
		if not month_col or not date_col:
			continue
		month_text = month_col.get_text(" ", strip=True)
		date_text = date_col.get_text(" ", strip=True)
		if not month_text or not date_text:
			continue
		# Month may be in a <strong>
		mmon = MONTH_RE.search(month_text)
		if not mmon:
			continue
		month_name = mmon.group(0).lower()
		if month_name not in MONTH_TO_NUM:
			continue
		month_num = MONTH_TO_NUM[month_name]
		# Date part is expected to be like '16-17*' or '28-29' or '9-10*'
		mrange = _DAY_RANGE_ONLY_RE.match(date_text)
		msingle = _DAY_SINGLE_ONLY_RE.match(date_text)
		if mrange:
			d1 = int(mrange.group(1)); d2 = int(mrange.group(2))
			start = f"{year:04d}-{month_num:02d}-{d1:02d}"
			end = f"{year:04d}-{month_num:02d}-{d2:02d}"
			rows.append((start, end, '*' in date_text))
		elif msingle:
			d1 = int(msingle.group(1))
			start = f"{year:04d}-{month_num:02d}-{d1:02d}"
			rows.append((start, start, '*' in date_text))
	return rows


def parse_future_calendar(html: str) -> List[CurrentCalendarEntry]:
	"""Return future Scheduled meetings across all visible years on the page.
	Only end_date >= today are included. Links are None.
	"""
	soup = BeautifulSoup(html, "lxml")
	now = _dt.date.today()
	seen: Set[Tuple[int, str, str]] = set()
	out: List[CurrentCalendarEntry] = []
	for year, section in _iter_year_sections(soup):
		candidates = _parse_with_dom(year, section)
		for start, end, star in candidates:
			try:
				end_dt = _dt.date.fromisoformat(end)
			except Exception:
				continue
			if end_dt < now:
				continue
			key = (year, start, end)
			if key in seen:
				continue
			seen.add(key)
			out.append(
				CurrentCalendarEntry(
					year=year,
					start_date=start,
					end_date=end,
					meeting_type="Scheduled",
					is_cancelled=False,
					has_sep_projections=bool(star),
					statement_url_html=None,
					minutes_url_html=None,
					press_conference_url_html=None,
					source_url=CURRENT_CALENDAR_URL,
				)
			)
	return out


