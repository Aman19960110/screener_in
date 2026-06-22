# Screener.in client

An authenticated Python client for fetching company ratios, snapshots, and peer
comparisons from Screener.in.

## Setup

```powershell
uv sync
$env:SCREENER_USERNAME = "your-email@example.com"
$env:SCREENER_PASSWORD = "your-password"
```

```python
import os
from screener_scrapper import ScreenerClient

with ScreenerClient(
    os.environ["SCREENER_USERNAME"],
    os.environ["SCREENER_PASSWORD"],
) as client:
    snapshot = client.get_company_snapshot("RELIANCE")
    peers = client.get_peer_comparison("RELIANCE")
    all_tables = client.get_all_tables("RELIANCE")
```

The client raises `AuthenticationError`, `ParseError`, or `ScreenerError` for
actionable failures instead of returning partial responses silently.

## Tests

```powershell
python -m unittest discover -s tests -v
```
