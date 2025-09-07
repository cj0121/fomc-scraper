"""FOMC scraper package.

Focus: parsing current and historical FOMC calendars from the Federal Reserve.

Public surface here stays minimal while we iterate on parsers first.
"""

from .parse_current import parse_current_calendar

__all__ = [
	"parse_current_calendar",
]


