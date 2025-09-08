from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple, Set

from bs4 import BeautifulSoup, Tag

from .fetch import fetch_html
from .parse_current import (
	CURRENT_CALENDAR_URL,
	MONTH_TO_NUM,
	MONTH_RE,
	YEAR_IN_HDR,
	CurrentCalendarEntry,
)
import datetime as _dt


HISTORICAL_INDEX_URL = "https://www.federalreserve.gov/monetarypolicy/fomc_historical_year.htm"
BASE_URL = "https://www.federalreserve.gov"

STATEMENT_RE = re.compile(r"statement", re.I)
MINUTES_RE = re.compile(r"minutes", re.I)
PRESS_RE = re.compile(r"press\s*conference|press", re.I)
IMPL_NOTE_RE = re.compile(r"implementation\s*note", re.I)
PROJECTION_RE = re.compile(r"(\bSEP\b|SEP:|summary of economic projections|individual projections)", re.I)


def _abs_url(href: Optional[str]) -> Optional[str]:
	if not href:
		return None
	if href.startswith("http://") or href.startswith("https://"):
		return href
	if href.startswith("/"):
		return BASE_URL + href
	return href


def _collect_links(block: Tag) -> Tuple[Dict[str, Optional[str]], bool]:
	links = {
		"statement_url_html": None,
		"minutes_url_html": None,
		"press_conference_url_html": None,
	}
	has_projection = False
	for a in block.find_all("a", href=True):
		label = a.get_text(" ", strip=True)
		href = _abs_url(a["href"].strip())
		l = label.lower()
		if STATEMENT_RE.search(l):
			links["statement_url_html"] = href
		elif MINUTES_RE.search(l):
			links["minutes_url_html"] = href
		elif PRESS_RE.search(l):
			links["press_conference_url_html"] = href
		if PROJECTION_RE.search(label) or (href and re.search(r"fomcproj", href, flags=re.I)):
			has_projection = True
	return links, has_projection



def _parse_dates_from_text(year: int, text: str) -> Tuple[Optional[str], Optional[str], bool, str]:
	"""Return (start_date, end_date, has_sep, meeting_type).

	meeting_type in {Scheduled, Unscheduled, Notation Vote}.
	"""
	mon_pat = r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
	lraw = re.sub(r"\s+", " ", text).strip().lower()
	clean = re.sub(r"\s+", " ", re.sub(r"\((?:[^)]*)\)", "", text)).strip()
	meeting_type = "Scheduled"
	if "notation vote" in lraw:
		meeting_type = "Notation Vote"
	elif "unscheduled" in lraw:
		meeting_type = "Unscheduled"
	# cross month like Jan/Feb 31-1
	m = re.search(fr"\b(?P<m1>{mon_pat})/(?P<m2>{mon_pat})\s+(?P<d1>\d{{1,2}})\s*[-–]\s*(?P<d2>\d{{1,2}})\*?\b", clean, flags=re.I)
	if m:
		m1 = m.group("m1").lower(); m2 = m.group("m2").lower()
		d1 = int(m.group("d1")); d2 = int(m.group("d2"))
		month1 = MONTH_TO_NUM[m1]; month2 = MONTH_TO_NUM[m2]
		end_year = year + (1 if month2 < month1 else 0)
		start_date = f"{year:04d}-{month1:02d}-{d1:02d}"
		end_date = f"{end_year:04d}-{month2:02d}-{d2:02d}"
		return start_date, end_date, False, meeting_type
	# same month range
	m = re.search(fr"\b(?P<m1>{mon_pat})\s+(?P<d1>\d{{1,2}})\s*[-–]\s*(?P<d2>\d{{1,2}})\*?\b", clean, flags=re.I)
	if m:
		m1 = m.group("m1").lower(); d1 = int(m.group("d1")); d2 = int(m.group("d2"))
		month = MONTH_TO_NUM[m1]
		start_date = f"{year:04d}-{month:02d}-{d1:02d}"
		end_date = f"{year:04d}-{month:02d}-{d2:02d}"
		return start_date, end_date, False, meeting_type
	# single day
	m = re.search(fr"\b(?P<m1>{mon_pat})\s+(?P<d1>\d{{1,2}})\*?\b", clean, flags=re.I)
	if m:
		m1 = m.group("m1").lower(); d1 = int(m.group("d1"))
		month = MONTH_TO_NUM[m1]
		start_date = f"{year:04d}-{month:02d}-{d1:02d}"
		return start_date, start_date, False, meeting_type
	return None, None, False, meeting_type


def _container_for_anchor(anchor: Tag) -> Tag:
	container = anchor.find_parent(["li", "p", "div", "tr"]) or anchor
	for _ in range(6):
		text = container.get_text(" ", strip=True)
		if MONTH_RE.search(text) and re.search(r"\d", text):
			return container
		if container.parent and isinstance(container.parent, Tag):
			container = container.parent
		else:
			break
	return anchor.find_parent(["li", "p", "div", "tr"]) or anchor


def _augment_with_prev_heading_text(container: Tag) -> str:
	base = container.get_text(" ", strip=True)
	# Look up to a few previous siblings at each ancestor level for a heading-like text
	for level in range(4):
		parent = container
		for _ in range(level):
			if parent and parent.parent and isinstance(parent.parent, Tag):
				parent = parent.parent
			else:
				parent = None
				break
		if not parent:
			continue
		# scan previous siblings
		accum = []
		for sib in list(parent.previous_siblings)[-4:]:
			if isinstance(sib, Tag):
				accum.append(sib.get_text(" ", strip=True))
		prefix = " ".join(reversed(accum)).strip()
		if prefix:
			combo = f"{prefix} {base}".strip()
			if MONTH_RE.search(combo) and re.search(r"\d", combo):
				return combo
	return base


def _parse_year_page(year: int, html: str, *, source_url: str) -> List[CurrentCalendarEntry]:
	soup = BeautifulSoup(html, "lxml")
	results: List[CurrentCalendarEntry] = []
	seen: Set[Tuple[int, str, str]] = set()
	# Pass 1: anchor-scoped containers
	for a in soup.find_all("a", href=True):
		label = a.get_text(" ", strip=True).lower()
		if not (STATEMENT_RE.search(label) or MINUTES_RE.search(label)):
			continue
		container = _container_for_anchor(a)
		text = _augment_with_prev_heading_text(container)
		start_date, end_date, _has_sep, meeting_type = _parse_dates_from_text(year, text)
		if not start_date:
			continue
		links, proj_link = _collect_links(container)
		is_cancelled = "cancelled" in text.lower() or "canceled" in text.lower()
		key = (year, start_date, end_date)
		if key in seen:
			continue
		seen.add(key)
		results.append(
			CurrentCalendarEntry(
				year=year,
				start_date=start_date,
				end_date=end_date,
				meeting_type=meeting_type,
				is_cancelled=is_cancelled,
				has_sep_projections=bool(proj_link),
				statement_url_html=links["statement_url_html"],
				minutes_url_html=links["minutes_url_html"],
				press_conference_url_html=links["press_conference_url_html"],
				source_url=source_url,
			)
		)
	# Pass 2: heading-bounded sections across h1-h6 with 'Meeting'
	HEAD_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
	for hdr in soup.find_all(list(HEAD_TAGS)):
		text = hdr.get_text(" ", strip=True)
		if not text:
			continue
		start_date, end_date, _has_sep, meeting_type = _parse_dates_from_text(year, text)
		if not start_date:
			continue
		links = {
			"statement_url_html": None,
			"minutes_url_html": None,
			"press_conference_url_html": None,
		}
		proj_link = False
		is_cancelled = "cancelled" in text.lower() or "canceled" in text.lower()
		for sib in hdr.next_siblings:
			if isinstance(sib, Tag) and sib.name in HEAD_TAGS:
				break
			if isinstance(sib, Tag):
				for a in sib.find_all("a", href=True):
					label = a.get_text(" ", strip=True)
					href = _abs_url(a["href"].strip())
					l = label.lower()
					if STATEMENT_RE.search(l):
						links["statement_url_html"] = href
					elif MINUTES_RE.search(l):
						links["minutes_url_html"] = href
					elif PRESS_RE.search(l):
						links["press_conference_url_html"] = href
					if PROJECTION_RE.search(label) or (href and re.search(r"fomcproj", href, flags=re.I)):
						proj_link = True
		key = (year, start_date, end_date)
		if key in seen:
			continue
		seen.add(key)
		results.append(
			CurrentCalendarEntry(
				year=year,
				start_date=start_date,
				end_date=end_date,
				meeting_type=meeting_type,
				is_cancelled=is_cancelled,
				has_sep_projections=bool(proj_link),
				statement_url_html=links["statement_url_html"],
				minutes_url_html=links["minutes_url_html"],
				press_conference_url_html=links["press_conference_url_html"],
				source_url=source_url,
			)
		)
	return results


def parse_historical(years: Optional[List[int]] = None) -> List[CurrentCalendarEntry]:
	"""Parse historical FOMC meetings across the requested years.

	If years is None, will parse all years linked from the index page.
	Also attempts to fetch direct year pages like 'fomccalendars{year}.htm' for
	recent years that may not be present on the historical index.
	"""
	index_html = fetch_html(HISTORICAL_INDEX_URL)
	soup = BeautifulSoup(index_html, "lxml")
	links: List[Tuple[int, str]] = []
	for a in soup.find_all("a", href=True):
		text = a.get_text(" ", strip=True)
		m = YEAR_IN_HDR.search(text)
		if not m:
			continue
		y = int(m.group(0))
		if years and y not in years:
			continue
		href = a["href"].strip()
		if not href:
			continue
		if not href.startswith("http"):
			href = BASE_URL + href
		links.append((y, href))
	# Add direct year pages for recent years
	candidate_years: List[int]
	if years is None:
		candidate_years = list(range(2010, _dt.date.today().year + 1))
	else:
		candidate_years = years
	for y in candidate_years:
		links.append((y, f"{BASE_URL}/monetarypolicy/fomccalendars{y}.htm"))

	results: List[CurrentCalendarEntry] = []
	for y, url in sorted(links, key=lambda t: t[0]):
		try:
			html = fetch_html(url)
		except Exception:
			continue
		results.extend(_parse_year_page(y, html, source_url=url))

	return results


