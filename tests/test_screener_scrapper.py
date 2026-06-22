import unittest
from unittest.mock import Mock

import requests

from screener_scrapper import ParseError, ScreenerClient, ScreenerError


class ScreenerClientTests(unittest.TestCase):
    def make_client(self) -> ScreenerClient:
        client = object.__new__(ScreenerClient)
        client.timeout = 3.0
        client.session = Mock(spec=requests.Session)
        return client

    def test_quick_ratio_parser(self) -> None:
        html = """
        <ul>
          <li data-source="quick-ratio">
            <span class="name">Return on equity</span>
            <span class="value">18.2 %</span>
          </li>
        </ul>
        """
        self.assertEqual(
            ScreenerClient._parse_quick_ratios(html),
            {"Return on equity": "18.2 %"},
        )

    def test_literal_html_is_parsed_as_html_not_a_filename(self) -> None:
        tables = ScreenerClient._tables_from_html(
            "<table><tr><th>Metric</th><th>2026</th></tr>"
            "<tr><td>Sales</td><td>100</td></tr></table>"
        )
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].iloc[0, 1], 100)

    def test_snapshot_uses_latest_nonempty_table_value(self) -> None:
        client = self.make_client()
        response = Mock()
        response.text = """
        <ul id="top-ratios"><li><span class="name">Market Cap</span>
        <span class="nowrap value">1,000 Cr.</span></li></ul>
        <table><tr><th>Metric</th><th>2025</th><th>2026</th></tr>
        <tr><td>Sales</td><td>90</td><td>100</td></tr>
        <tr><td>Profit</td><td>10</td><td></td></tr></table>
        """
        client._company_page = Mock(return_value=response)

        snapshot = client.get_company_snapshot("TEST")

        self.assertEqual(snapshot["Market Cap"], "1,000 Cr.")
        self.assertEqual(snapshot["Sales"], 100)
        self.assertEqual(snapshot["Profit"], 10)

    def test_get_all_tables_returns_tables_in_page_order(self) -> None:
        client = self.make_client()
        response = Mock()
        response.text = """
        <table><tr><th>Metric</th><th>Value</th></tr>
        <tr><td>Sales</td><td>100</td></tr></table>
        <table><tr><th>Metric</th><th>Value</th></tr>
        <tr><td>Profit</td><td>20</td></tr></table>
        """
        client._company_page = Mock(return_value=response)

        tables = client.get_all_tables("TEST")

        self.assertEqual(len(tables), 2)
        self.assertEqual(tables[0].iloc[0, 0], "Sales")
        self.assertEqual(tables[1].iloc[0, 0], "Profit")
        client._company_page.assert_called_once_with("TEST")

    def test_warehouse_id_accepts_single_quoted_attribute(self) -> None:
        client = self.make_client()
        response = Mock()
        response.text = "<div data-warehouse-id='6598251'></div>"
        client._request = Mock(return_value=response)
        self.assertEqual(client.get_warehouse_id("RELIANCE"), 6598251)

    def test_missing_warehouse_id_raises_parse_error(self) -> None:
        client = self.make_client()
        response = Mock()
        response.text = "<html></html>"
        client._request = Mock(return_value=response)
        with self.assertRaises(ParseError):
            client.get_warehouse_id("UNKNOWN")

    def test_request_wraps_network_errors_and_sets_timeout(self) -> None:
        client = self.make_client()
        client.session.request.side_effect = requests.Timeout("too slow")
        with self.assertRaises(ScreenerError):
            client._request("GET", "https://example.test")
        client.session.request.assert_called_once_with(
            "GET", "https://example.test", timeout=3.0
        )

    def test_empty_symbol_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ScreenerClient._symbol_path("  ")


if __name__ == "__main__":
    unittest.main()
