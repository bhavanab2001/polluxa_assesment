"""
Data extractor — dual-mode: Polluxa API + CSV/JSON fallback.

Handles:
- API mode: HTTP client with Bearer auth, pagination, rate limiting
- CSV mode: Read exported files from a configurable directory
- Rate limiting with configurable delay and retry on 429
- Exponential backoff with jitter for transient failures
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any, Generator

import httpx

from src.config import DataSourceMode, settings
from src.logging_config import get_logger

logger = get_logger("extractor")


class ExtractionError(Exception):
    """Raised when data extraction fails after exhausting retries."""
    pass


class RateLimitError(Exception):
    """Raised when the API returns 429 Too Many Requests."""
    def __init__(self, retry_after: float = 60.0):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s")


class PolluaxAPIClient:
    """
    HTTP client for the Polluxa REST API.

    Features:
    - Bearer token authentication
    - Cursor-based pagination
    - Rate limiting (configurable delay between requests)
    - Exponential backoff with jitter on transient failures
    - Respects HTTP 429 Retry-After headers
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_token: str | None = None,
        request_delay: float | None = None,
        max_retries: int | None = None,
        retry_base_delay: float | None = None,
    ):
        self.base_url = (base_url or settings.polluxa_api_base_url).rstrip("/")
        self.api_token = api_token or settings.polluxa_api_token
        self.request_delay = request_delay or settings.api_request_delay
        self.max_retries = max_retries or settings.api_max_retries
        self.retry_base_delay = retry_base_delay or settings.api_retry_base_delay

        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(30.0),
        )
        self._last_request_time: float = 0.0

    def _rate_limit_wait(self) -> None:
        """Enforce minimum delay between API requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.request_delay:
            sleep_time = self.request_delay - elapsed
            logger.debug("rate_limit_wait", sleep_seconds=round(sleep_time, 2))
            time.sleep(sleep_time)

    def _request_with_retry(
        self, method: str, endpoint: str, **kwargs: Any
    ) -> httpx.Response:
        """
        Make an HTTP request with exponential backoff retry.

        Retries on:
        - HTTP 429 (Too Many Requests) — respects Retry-After header
        - HTTP 500, 502, 503, 504 (server errors)
        - Connection errors / timeouts
        """
        last_exception: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self._rate_limit_wait()

            try:
                response = self._client.request(method, endpoint, **kwargs)
                self._last_request_time = time.time()

                if response.status_code == 429:
                    retry_after = float(
                        response.headers.get("Retry-After", self.retry_base_delay * (2 ** attempt))
                    )
                    logger.warning(
                        "rate_limited",
                        attempt=attempt + 1,
                        retry_after=retry_after,
                        endpoint=endpoint,
                    )
                    if attempt < self.max_retries:
                        time.sleep(retry_after)
                        continue
                    raise RateLimitError(retry_after)

                if response.status_code >= 500:
                    logger.warning(
                        "server_error",
                        status_code=response.status_code,
                        attempt=attempt + 1,
                        endpoint=endpoint,
                    )
                    if attempt < self.max_retries:
                        backoff = self.retry_base_delay * (2 ** attempt)
                        time.sleep(backoff)
                        continue
                    response.raise_for_status()

                response.raise_for_status()
                return response

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exception = exc
                logger.warning(
                    "connection_error",
                    error=str(exc),
                    attempt=attempt + 1,
                    endpoint=endpoint,
                )
                if attempt < self.max_retries:
                    backoff = self.retry_base_delay * (2 ** attempt)
                    time.sleep(backoff)
                    continue

        raise ExtractionError(
            f"Failed after {self.max_retries + 1} attempts: {endpoint}"
        ) from last_exception

    def fetch_paginated(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        page_size: int = 100,
        data_key: str = "data",
        cursor_key: str = "next_cursor",
    ) -> Generator[list[dict[str, Any]], None, None]:
        """
        Fetch all pages of a paginated API endpoint.

        Yields batches (lists) of records. Handles cursor-based
        and offset-based pagination automatically.
        """
        params = dict(params or {})
        params.setdefault("limit", page_size)
        cursor: str | None = None
        page = 0

        while True:
            if cursor:
                params["cursor"] = cursor

            logger.info(
                "fetching_page",
                endpoint=endpoint,
                page=page,
                cursor=cursor,
            )

            response = self._request_with_retry("GET", endpoint, params=params)
            body = response.json()

            records = body.get(data_key, [])
            if not records:
                logger.info("pagination_complete", endpoint=endpoint, total_pages=page)
                break

            yield records
            page += 1

            cursor = body.get(cursor_key)
            if not cursor:
                logger.info("pagination_complete", endpoint=endpoint, total_pages=page)
                break

    def fetch_agents(self, since: str | None = None) -> Generator[list[dict], None, None]:
        """Fetch LinkedIn agents from the Polluxa API."""
        params = {}
        if since:
            params["updated_since"] = since
        yield from self.fetch_paginated("/linkedin/agents", params=params)

    def fetch_leads(self, since: str | None = None) -> Generator[list[dict], None, None]:
        """Fetch outreach leads from the Polluxa API."""
        params = {}
        if since:
            params["updated_since"] = since
        yield from self.fetch_paginated("/leads", params=params)

    def fetch_campaigns(self, since: str | None = None) -> Generator[list[dict], None, None]:
        """Fetch campaigns from the Polluxa API."""
        params = {}
        if since:
            params["updated_since"] = since
        yield from self.fetch_paginated("/campaigns", params=params)

    def fetch_outreach_events(self, since: str | None = None) -> Generator[list[dict], None, None]:
        """Fetch outreach events (invites, accepts, messages, replies)."""
        params = {}
        if since:
            params["since"] = since
        yield from self.fetch_paginated("/outreach/events", params=params)

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()


class CSVExtractor:
    """
    Fallback extractor that reads data from CSV/JSON files.

    Looks for files matching expected naming patterns in the
    configured import directory.
    """

    def __init__(self, import_dir: Path | None = None):
        self.import_dir = import_dir or settings.csv_import_dir
        self.import_dir = Path(self.import_dir)

    def _read_csv(self, filepath: Path) -> list[dict[str, Any]]:
        """Read a CSV file and return list of row dicts."""
        logger.info("reading_csv", filepath=str(filepath))
        records: list[dict[str, Any]] = []
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(dict(row))
        logger.info("csv_read_complete", filepath=str(filepath), row_count=len(records))
        return records

    def _read_json(self, filepath: Path) -> list[dict[str, Any]]:
        """Read a JSON file and return list of records."""
        logger.info("reading_json", filepath=str(filepath))
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict) and "data" in data:
            records = data["data"]
        else:
            records = [data]
        logger.info("json_read_complete", filepath=str(filepath), row_count=len(records))
        return records

    def _find_files(self, pattern: str) -> list[Path]:
        """Find files matching a pattern in the import directory."""
        if not self.import_dir.exists():
            logger.warning("import_dir_not_found", path=str(self.import_dir))
            return []
        files = sorted(self.import_dir.glob(pattern))
        return files

    def _read_entity(self, entity_name: str) -> list[dict[str, Any]]:
        """Read all files for a given entity (CSV or JSON)."""
        all_records: list[dict[str, Any]] = []
        for filepath in self._find_files(f"{entity_name}*.csv"):
            all_records.extend(self._read_csv(filepath))
        for filepath in self._find_files(f"{entity_name}*.json"):
            all_records.extend(self._read_json(filepath))
        return all_records

    def fetch_agents(self) -> list[dict[str, Any]]:
        """Read agent data from CSV/JSON files."""
        return self._read_entity("agents")

    def fetch_leads(self) -> list[dict[str, Any]]:
        """Read lead data from CSV/JSON files."""
        return self._read_entity("leads")

    def fetch_campaigns(self) -> list[dict[str, Any]]:
        """Read campaign data from CSV/JSON files."""
        return self._read_entity("campaigns")

    def fetch_outreach_events(self) -> list[dict[str, Any]]:
        """Read outreach event data from CSV/JSON files."""
        return self._read_entity("events")

    def fetch_message_templates(self) -> list[dict[str, Any]]:
        """Read message template data from CSV/JSON files."""
        return self._read_entity("templates")


def get_extractor() -> PolluaxAPIClient | CSVExtractor:
    """
    Factory function to get the appropriate extractor
    based on the configured data source mode.
    """
    if settings.data_source_mode == DataSourceMode.API:
        logger.info("using_api_extractor", base_url=settings.polluxa_api_base_url)
        return PolluaxAPIClient()
    else:
        logger.info("using_csv_extractor", import_dir=str(settings.csv_import_dir))
        return CSVExtractor()
