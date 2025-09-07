from __future__ import annotations

import re
import datetime as _dt
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag, NavigableString


CURRENT_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BASE_URL = "https://www.federalreserve.gov"

# Patterns to recognize anchors by href
STATEMENT_HTML_RE = re.compile(r"/newsevents/pressreleases/monetary\d{8}[a-z]?\.htm$", re.I)
IMPL_NOTE_RE = re.compile(r"/newsevents/pressreleases/monetary\d{8}a1\.htm$", re.I)
MINUTES_HTML_RE = re.compile(r"/monetarypolicy/.*minutes.*\d{4}.*\.htm$", re.I)
PRESSCONF_HTML_RE = re.compile(r"/monetarypolicy/fomcpresconf\d{8}\.htm$", re.I)
PRESS_DATE_RE = re.compile(r"monetary(\d{8})", re.I)

# Date parsing helpers
MONTH_RE = re.compile(r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b", re.I)
YEAR_IN_HDR = re.compile(r"(19|20)\d{2}")
YEAR_IN_HREF = re.compile(r"(19|20)\d{2}")

MONTH_TO_NUM = {
	"jan": 1, "january": 1,
	"feb": 2, "february": 2,
	"mar": 3, "march": 3,
	"apr": 4, "april": 4,
	"may": 5,
	"jun": 6, "june": 6,
	"jul": 7, "july": 7,
	"aug": 8, "august": 8,
	"sep": 9, "sept": 9, "september": 9,
	"oct": 10, "october": 10,
	"nov": 11, "november": 11,
	"dec": 12, "december": 12,
}

@dataclass
class CurrentCalendarEntry:
	year: int
	start_date: Optional[str]
	end_date: Optional[str]
	meeting_type: str
	is_cancelled: bool
	has_sep_projections: bool
	statement_url_html: Optional[str]
	minutes_url_html: Optional[str]
	press_conference_url_html: Optional[str]
	source_url: str = CURRENT_CALENDAR_URL


def _normalize_text(text: str) -> str:
	return re.sub(r"\s+", " ", text).strip()


def _nearest_year_heading(tag: Tag) -> Optional[int]:
	for prev in tag.previous_elements:
		if isinstance(prev, Tag) and prev.name in {"h2", "h3", "h4"}:
			text = prev.get_text(" ", strip=True)
			m = YEAR_IN_HDR.search(text)
			if m and ("FOMC Meetings" in text or "FOMC" in text):
				return int(m.group(0))
	for prev in tag.previous_elements:
		if isinstance(prev, Tag) and prev.name in {"h2", "h3", "h4"}:
			text = prev.get_text(" ", strip=True)
			m = YEAR_IN_HDR.search(text)
			if m:
				return int(m.group(0))
	for i, prev in enumerate(tag.previous_elements):
		if i > 400:
			break
		if isinstance(prev, Tag):
			m = YEAR_IN_HDR.search(prev.get_text(" ", strip=True))
			if m:
				return int(m.group(0))
	return None


def _nearest_prev_month_token(tag: Tag) -> Optional[str]:
	for i, prev in enumerate(tag.previous_elements):
		if i > 400:
			break
		if isinstance(prev, Tag):
			text = prev.get_text(" ", strip=True)
			m = MONTH_RE.search(text)
			if m:
				return m.group(0)
	return None


def _ensure_month_prefix(date_prefix: str, container: Tag) -> str:
	if MONTH_RE.search(date_prefix):
		return date_prefix
	if re.search(r"\b\d{1,2}\b", date_prefix):
		month = _nearest_prev_month_token(container)
		if month:
			return f"{month} {date_prefix}".strip()
	return date_prefix


def _container_for(anchor: Tag) -> Tag:
	container = anchor.find_parent(["li", "p", "div"]) or anchor
	for _ in range(6):
		text = container.get_text(" ", strip=True)
		if (MONTH_RE.search(text) and re.search(r"\d", text)) or any(k in text.lower() for k in ["unscheduled", "notation vote", "cancelled", "canceled"]):
			return container
		if container.parent and isinstance(container.parent, Tag):
			container = container.parent
		else:
			break
	return container


def _extract_date_prefix(container: Tag) -> str:
	anchor = None
	for a in container.find_all("a"):
		label = a.get_text(" ", strip=True)
		if re.search(r"\bStatement\b", label, flags=re.I) or re.search(r"\bPress\s+Release\b", label, flags=re.I):
			anchor = a
			break
	full_text = container.get_text(" ", strip=True)
	if anchor is not None:
		accum = []
		for node in container.descendants:
			if node is anchor:
				break
			if isinstance(node, NavigableString):
				accum.append(str(node))
		return _normalize_text(" ".join(accum))
	return _normalize_text(full_text)


def _abs_url(href: Optional[str]) -> Optional[str]:
	if not href:
		return None
	if href.startswith("http://") or href.startswith("https://"):
		return href
	if href.startswith("/"):
		return BASE_URL + href
	return urljoin(CURRENT_CALENDAR_URL, href)


def _collect_links(container: Tag) -> Tuple[dict, bool]:
	links = {
		"statement_url_html": None,
		"minutes_url_html": None,
		"press_conference_url_html": None,
	}
	has_projection = False
	for a in container.find_all("a", href=True):
		href = a["href"].strip()
		abs_href = _abs_url(href)
		atxt = a.get_text(" ", strip=True)
		if STATEMENT_HTML_RE.search(href) and not IMPL_NOTE_RE.search(href):
			links["statement_url_html"] = abs_href
		elif MINUTES_HTML_RE.search(href):
			links["minutes_url_html"] = abs_href
		elif PRESSCONF_HTML_RE.search(href):
			links["press_conference_url_html"] = abs_href
		if re.search(r"Projection", atxt, flags=re.I):
			has_projection = True
	return links, has_projection


def _parse_dates_and_flags(year: int, date_prefix: str, *, has_projection: bool) -> Tuple[Optional[str], Optional[str], str, bool, bool]:
	had_star = "*" in date_prefix
	text = _normalize_text(re.sub(r"\*+", "", date_prefix))
	note = None
	m_note = re.search(r"\(([^)]+)\)", text)
	if m_note:
		note = m_note.group(1).strip()
		text_wo_note = (text[: m_note.start()] + text[m_note.end():]).strip()
	else:
		text_wo_note = text

	mon_pat = r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
	start_date = end_date = None
	m = re.search(fr"\b(?P<m1>{mon_pat})/(?P<m2>{mon_pat})\s+(?P<d1>\d{{1,2}})\s*[-–]\s*(?P<d2>\d{{1,2}})\b", text_wo_note, flags=re.I)
	if m:
		m1 = m.group('m1').lower(); m2 = m.group('m2').lower(); d1 = int(m.group('d1')); d2 = int(m.group('d2'))
		month1 = MONTH_TO_NUM[m1]; month2 = MONTH_TO_NUM[m2]
		end_year = year + (1 if month2 < month1 else 0)
		start_date = f"{year:04d}-{month1:02d}-{d1:02d}"
		end_date = f"{end_year:04d}-{month2:02d}-{d2:02d}"
	else:
		m = re.search(fr"\b(?P<m1>{mon_pat})\s+(?P<d1>\d{{1,2}})\s*[-–]\s*(?P<d2>\d{{1,2}})\b", text_wo_note, flags=re.I)
		if m:
			m1 = m.group('m1').lower(); d1 = int(m.group('d1')); d2 = int(m.group('d2'))
			month = MONTH_TO_NUM[m1]
			start_date = f"{year:04d}-{month:02d}-{d1:02d}"
			end_date = f"{year:04d}-{month:02d}-{d2:02d}"
		else:
			m = re.search(fr"\b(?P<m1>{mon_pat})\s+(?P<d1>\d{{1,2}})\b", text_wo_note, flags=re.I)
			if m:
				m1 = m.group('m1').lower(); d1 = int(m.group('d1'))
				month = MONTH_TO_NUM[m1]
				start_date = f"{year:04d}-{month:02d}-{d1:02d}"
				end_date = start_date

	meeting_type = "Scheduled"
	is_cancelled = False
	if note:
		ln = note.lower()
		if "unscheduled" in ln:
			meeting_type = "Unscheduled"
		if "notation vote" in ln:
			meeting_type = "Notation Vote"
		if "cancelled" in ln or "canceled" in ln:
			is_cancelled = True
	has_sep = bool(had_star or has_projection)
	return start_date, end_date, meeting_type, is_cancelled, has_sep


def _extract_press_date_from_url(url: Optional[str]) -> Optional[_dt.date]:
	if not url:
		return None
	m = PRESS_DATE_RE.search(url)
	if not m:
		return None
	ds = m.group(1)
	try:
		return _dt.date(int(ds[0:4]), int(ds[4:6]), int(ds[6:8]))
	except Exception:
		return None


def _date_from_iso(s: Optional[str]) -> Optional[_dt.date]:
	if not s:
		return None
	y, m, d = s.split("-")
	return _dt.date(int(y), int(m), int(d))


def parse_current_calendar(html: str) -> List[CurrentCalendarEntry]:
	soup = BeautifulSoup(html, "lxml")
	candidate_containers: Set[Tag] = set()
	# Anchor-based collection
	for a in soup.find_all("a", href=True):
		href = a["href"].strip()
		label = a.get_text(" ", strip=True).lower()
		if STATEMENT_HTML_RE.search(href) or MINUTES_HTML_RE.search(href) or PRESSCONF_HTML_RE.search(href) or any(k in label for k in ["statement", "minutes", "press"]):
			candidate_containers.add(_container_for(a))
	# Qualifier-only rows (unscheduled/notation vote/cancelled)
	for node in soup.find_all(["li", "p", "div", "tr"]):
		text = node.get_text(" ", strip=True)
		ltext = text.lower()
		if any(k in ltext for k in ["notation vote", "unscheduled", "cancelled", "canceled"]) and re.search(r"\b\d{1,2}\b", text):
			candidate_containers.add(node)

	records: Dict[Tuple[int, str, str], dict] = {}
	for c in candidate_containers:
		date_prefix = _extract_date_prefix(c)
		date_prefix = _ensure_month_prefix(date_prefix, c)
		if not date_prefix or not MONTH_RE.search(date_prefix):
			continue
		year = _nearest_year_heading(c)
		if not year:
			years = {int(m.group(0)) for a in c.find_all("a", href=True) for m in [YEAR_IN_HREF.search(a["href"])] if m}
			if len(years) == 1:
				year = years.pop()
		if not year:
			continue

		links, has_proj = _collect_links(c)
		start_date, end_date, meeting_type, is_cancelled, has_sep = _parse_dates_and_flags(year, date_prefix, has_projection=has_proj)
		if not start_date:
			continue
		# Always require Statement for Scheduled (non-cancelled) entries
		if meeting_type == "Scheduled" and not is_cancelled and not links["statement_url_html"]:
			continue
		# If Statement exists, ensure its press date equals end_date
		press_dt = _extract_press_date_from_url(links["statement_url_html"]) if links["statement_url_html"] else None
		end_dt = _date_from_iso(end_date)
		if links["statement_url_html"] and press_dt and end_dt and press_dt != end_dt:
			continue

		key = (year, start_date, end_date)
		if key not in records:
			records[key] = {
				"year": year,
				"start_date": start_date,
				"end_date": end_date,
				"meeting_type": meeting_type,
				"is_cancelled": is_cancelled,
				"has_sep_projections": has_sep,
				"statement_url_html": links["statement_url_html"],
				"minutes_url_html": links["minutes_url_html"],
				"press_conference_url_html": links["press_conference_url_html"],
				"source_url": CURRENT_CALENDAR_URL,
			}
		else:
			for k in ["statement_url_html", "minutes_url_html", "press_conference_url_html"]:
				if not records[key][k]:
					records[key][k] = links[k]

	return [CurrentCalendarEntry(**rec) for rec in records.values()]


