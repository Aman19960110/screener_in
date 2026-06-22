"""Small authenticated client for company data on screener.in."""

from __future__ import annotations

import re
from io import StringIO
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests
from bs4 import BeautifulSoup


class ScreenerError(RuntimeError):
    """Base exception raised by this module."""


class AuthenticationError(ScreenerError):
    """Raised when authentication fails."""


class ParseError(ScreenerError):
    """Raised when Screener returns an unexpected page shape."""


class ScreenerClient:
    """Authenticated client for a subset of Screener's website endpoints.

    ``session`` is injectable to make the client straightforward to test. The
    client can also be used as a context manager so its connections are closed.
    """

    BASE_URL = "https://www.screener.in"
    DEFAULT_TIMEOUT = 20.0

    def __init__(
        self,
        username: str,
        password: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
    ) -> None:
        if not username or not password:
            raise ValueError("username and password are required")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/149.0.0.0 Safari/537.36"
                )
            }
        )
        self.login(username, password)

    def __enter__(self) -> ScreenerClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Send a request with consistent timeout and HTTP error handling."""
        kwargs.setdefault("timeout", self.timeout)
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ScreenerError(f"{method.upper()} {url} failed: {exc}") from exc
        return response

    @staticmethod
    def _symbol_path(symbol: str) -> str:
        symbol = symbol.strip()
        if not symbol:
            raise ValueError("symbol must not be empty")
        return quote(symbol, safe="-.&")

    def login(self, username: str, password: str) -> None:
        login_url = f"{self.BASE_URL}/login/"
        page = self._request("GET", login_url)
        soup = BeautifulSoup(page.text, "html.parser")
        token_tag = soup.select_one('input[name="csrfmiddlewaretoken"]')
        if token_tag is None or not token_tag.get("value"):
            raise ParseError("Login page did not contain a CSRF token")

        response = self._request(
            "POST",
            login_url,
            data={
                "username": username,
                "password": password,
                "csrfmiddlewaretoken": token_tag["value"],
            },
            headers={"Referer": login_url},
            allow_redirects=True,
        )
        if response.url.rstrip("/").endswith("/login"):
            raise AuthenticationError("Login failed; check the supplied credentials")

    def _csrf_headers(self, referer: str) -> dict[str, str]:
        token = self.session.cookies.get("csrftoken")
        if not token:
            raise AuthenticationError("The session has no CSRF cookie")
        return {
            "Referer": referer,
            "Origin": self.BASE_URL,
            "X-CSRFToken": token,
            "X-Requested-With": "XMLHttpRequest",
        }

    def search_company(self, query: str) -> str:
        if not query.strip():
            raise ValueError("query must not be empty")
        response = self._request(
            "GET", f"{self.BASE_URL}/search/", params={"q": query.strip()}
        )
        return response.url

    def get_company_id(self, symbol: str) -> int:
        response = self._request("GET", self.get_company_url(symbol))
        match = re.search(r"/api/company/(\d+)/", response.text)
        if match is None:
            raise ParseError(f"Unable to find company_id for {symbol!r}")
        return int(match.group(1))

    def get_warehouse_id(self, symbol: str, consolidated: bool = True) -> int:
        path = self._symbol_path(symbol)
        suffix = "/consolidated/" if consolidated else "/"
        response = self._request("GET", f"{self.BASE_URL}/company/{path}{suffix}")
        match = re.search(r'data-warehouse-id=["\'](\d+)["\']', response.text)
        if match is None:
            raise ParseError(f"Unable to find warehouse_id for {symbol!r}")
        return int(match.group(1))

    def get_company_url(self, symbol: str) -> str:
        return f"{self.BASE_URL}/company/{self._symbol_path(symbol)}/"

    def get_quick_ratios(self, symbol: str, ratio_name: str) -> dict[str, str]:
        if not ratio_name.strip():
            raise ValueError("ratio_name must not be empty")
        path = self._symbol_path(symbol)
        warehouse_id = self.get_warehouse_id(symbol)
        referer = f"{self.BASE_URL}/company/{path}/consolidated/"
        response = self._request(
            "POST",
            f"{self.BASE_URL}/api/company/{warehouse_id}/quick_ratios/",
            headers=self._csrf_headers(referer),
            data={"ratio_name": ratio_name.strip()},
        )
        return self._parse_quick_ratios(response.text)

    @staticmethod
    def _parse_quick_ratios(html: str) -> dict[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        result: dict[str, str] = {}
        for item in soup.select('li[data-source="quick-ratio"]'):
            name_tag = item.select_one(".name")
            value_tag = item.select_one(".value")
            if name_tag and value_tag:
                result[name_tag.get_text(" ", strip=True)] = value_tag.get_text(
                    " ", strip=True
                )
        return result

    def get_ratio(self, symbol: str, ratio_name: str) -> str | None:
        return self.get_quick_ratios(symbol, ratio_name).get(ratio_name.strip())

    def show_cookies(self) -> dict[str, str]:
        return self.session.cookies.get_dict()

    def _company_page(self, symbol: str) -> requests.Response:
        path = self._symbol_path(symbol)
        return self._request(
            "GET", f"{self.BASE_URL}/company/{path}/consolidated/"
        )

    def get_top_ratios(self, symbol: str) -> dict[str, str]:
        response = self._company_page(symbol)
        soup = BeautifulSoup(response.text, "html.parser")
        top_ratios = soup.find("ul", id="top-ratios")
        if top_ratios is None:
            raise ParseError("top-ratios section not found")

        data: dict[str, str] = {}
        for item in top_ratios.find_all("li", recursive=False):
            name_tag = item.select_one(".name")
            value_tag = item.select_one(".value")
            if name_tag and value_tag:
                data[name_tag.get_text(" ", strip=True)] = value_tag.get_text(
                    " ", strip=True
                )
        return data

    @staticmethod
    def _tables_from_html(html: str) -> list[pd.DataFrame]:
        # pandas 3 treats a bare HTML string as a path. StringIO is required.
        try:
            return pd.read_html(StringIO(html))
        except ValueError:
            return []
        except ImportError:
            # Keep basic extraction usable if pandas' optional lxml parser is
            # unavailable in the active interpreter.
            tables: list[pd.DataFrame] = []
            soup = BeautifulSoup(html, "html.parser")
            for table in soup.find_all("table"):
                rows = [
                    [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                    for row in table.find_all("tr")
                ]
                rows = [row for row in rows if row]
                if not rows:
                    continue
                width = max(map(len, rows))
                normalized = [row + [None] * (width - len(row)) for row in rows]
                has_header = bool(table.find("tr") and table.find("tr").find("th"))
                if has_header and len(normalized) > 1:
                    frame = pd.DataFrame(normalized[1:], columns=normalized[0])
                else:
                    frame = pd.DataFrame(normalized)
                for column in frame.columns:
                    try:
                        frame[column] = pd.to_numeric(frame[column])
                    except (TypeError, ValueError):
                        pass
                tables.append(frame)
            return tables

    def get_company_snapshot(self, symbol: str) -> dict[str, Any]:
        response = self._company_page(symbol)
        soup = BeautifulSoup(response.text, "html.parser")
        data: dict[str, Any] = {}

        top_ratios = soup.find("ul", id="top-ratios")
        if top_ratios:
            for item in top_ratios.find_all("li", recursive=False):
                name_tag = item.select_one(".name")
                value_tag = item.select_one(".value")
                if name_tag and value_tag:
                    data[name_tag.get_text(" ", strip=True)] = value_tag.get_text(
                        " ", strip=True
                    )

        for table in self._tables_from_html(response.text):
            if table.empty or len(table.columns) < 2:
                continue
            metric_col = table.columns[0]
            for _, row in table.iterrows():
                metric = str(row[metric_col]).strip()
                if not metric or metric.lower() == "nan":
                    continue
                values = row.iloc[1:].dropna()
                if not values.empty:
                    data[metric] = values.iloc[-1]
        return data

    def get_all_tables(self, symbol: str) -> list[pd.DataFrame]:
        """Return every table on a company's consolidated page.

        Tables are returned in the same order in which they appear on the page.
        An empty list is returned when the page contains no HTML tables.
        """
        response = self._company_page(symbol)
        return self._tables_from_html(response.text)

    def get_peer_comparison(self, symbol: str) -> pd.DataFrame:
        warehouse_id = self.get_warehouse_id(symbol)
        path = self._symbol_path(symbol)
        response = self._request(
            "GET",
            f"{self.BASE_URL}/api/company/{warehouse_id}/peers/",
            headers={
                "Referer": f"{self.BASE_URL}/company/{path}/consolidated/",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        soup = BeautifulSoup(response.text, "html.parser")
        peer_ids = [
            row["data-row-company-id"]
            for row in soup.select("tr[data-row-company-id]")
        ]
        tables = self._tables_from_html(response.text)
        if not tables:
            raise ParseError("No peer table found")

        result = tables[0]
        if len(result) == len(peer_ids):
            result = result.copy()
            result["peer_company_id"] = peer_ids
        return result
