"""Monthly gas benchmarks from FRED (IMF Primary Commodity Prices, USD/MMBtu)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
SERIES = {
    "henry_hub": "PNGASUSUSDM",   # US natural gas, Henry Hub
    "europe": "PNGASEUUSDM",      # European natural gas (TTF hub)
    "asia_lng": "PNGASJPUSDM",    # Japan LNG import price (delivered, largely oil-indexed contracts)
}


def fetch_fred(series: str, cache: Path) -> pd.Series:
    if not cache.exists():
        # curl rather than urllib: some macOS Python builds ship without CA certificates
        raw = subprocess.run(["curl", "-sL", "--max-time", "60", FRED_URL.format(series=series)],
                             check=True, capture_output=True, text=True).stdout
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(raw)
    df = pd.read_csv(cache, parse_dates=["observation_date"], na_values=["."])
    return df.set_index("observation_date")[series].astype(float).dropna()


def gas_prices(data_dir: Path, start: str = "2010-01-01") -> pd.DataFrame:
    px = pd.DataFrame({k: fetch_fred(v, data_dir / f"{k}_monthly.csv") for k, v in SERIES.items()}).dropna()
    px.index.name = "month"
    return px[start:]
