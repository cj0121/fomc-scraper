from __future__ import annotations

import time
from typing import Optional

import requests


DEFAULT_HEADERS = {
	"User-Agent": (
		"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
		"AppleWebKit/537.36 (KHTML, like Gecko) "
		"Chrome/127.0.0.0 Safari/537.36"
	),
	"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
	"Accept-Language": "en-US,en;q=0.9",
}


def fetch_html(url: str, *, timeout: float = 20.0, max_retries: int = 3, backoff: float = 1.5, sleep_between: float = 0.6, headers: Optional[dict] = None) -> str:
	"""Fetch an HTML page with simple retries and polite pacing.

	Parameters
	----------
	url: str
		URL to retrieve.
	timeout: float
		Request timeout in seconds.
	max_retries: int
		Maximum number of retry attempts on transient failures.
	backoff: float
		Exponential backoff multiplier.
	sleep_between: float
		Minimum sleep between successful requests to avoid hammering the host.
	headers: Optional[dict]
		Additional headers to merge with defaults.

	Returns
	-------
	str
		Response text.
	"""
	merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
	last_exc: Optional[Exception] = None
	for attempt in range(max_retries + 1):
		try:
			resp = requests.get(url, headers=merged_headers, timeout=timeout)
			resp.raise_for_status()
			# Polite pause after success
			time.sleep(sleep_between)
			return resp.text
		except Exception as exc:  # noqa: BLE001 - broad for retry
			last_exc = exc
			if attempt == max_retries:
				raise
			# Exponential backoff before next try
			delay = backoff ** attempt
			time.sleep(delay)

	# Should not reach here due to raise on final failure
	assert last_exc is not None
	raise last_exc


