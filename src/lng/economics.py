"""Cargo economics for a US Gulf Coast LNG export cargo.

Pricing follows the standard US LNG tolling / FOB contract (Cheniere-style SPA):

    variable cost   = 1.15 x Henry Hub          (feed gas incl. liquefaction fuel)
    fixed fee       = tolling fee (USD/MMBtu)   (sunk once the contract is signed)

A cargo is worth lifting only if its best delivered netback beats the *variable* cost;
the tolling fee matters for the full-cycle (long-run) decision, not the month-by-month one.
This is exactly why US buyers cancelled cargoes en masse in mid-2020.

Shipping cost per MMBtu delivered for a round trip:
    charter    = day rate x (laden + ballast days)
    fuel       = ballast fuel cost per day x ballast days   (laden leg burns boil-off gas)
    boil-off   = cargo x boil-off rate x laden days, valued at the destination price
    canal      = transit fees on both legs where the route uses Panama
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np


@dataclass(frozen=True)
class Route:
    name: str
    market: str            # price index the cargo sells into: "europe" or "asia_lng"
    distance_nm: float     # one-way, Sabine Pass to discharge port (approximate great-circle sailing)
    canal_fee_usd: float   # round-trip canal tolls (0 if none)
    regas_fee: float       # USD/MMBtu terminal/regas cost borne by the seller to reach the price point


ROUTES = {
    "NW Europe (Rotterdam)": Route("NW Europe (Rotterdam)", "europe", 4_900, 0.0, 0.40),
    "Iberia (Huelva)": Route("Iberia (Huelva)", "europe", 4_500, 0.0, 0.45),
    "Japan via Panama": Route("Japan via Panama", "asia_lng", 9_250, 800_000.0, 0.0),
    "Japan via Cape": Route("Japan via Cape", "asia_lng", 15_800, 0.0, 0.0),
}


@dataclass(frozen=True)
class Assumptions:
    cargo_mmbtu: float = 3_500_000.0     # loaded energy, ~174k m3 carrier
    speed_knots: float = 17.5
    charter_usd_day: float = 75_000.0
    ballast_fuel_usd_day: float = 35_000.0
    boil_off_per_day: float = 0.0010     # 0.10% of cargo per laden day
    hh_multiplier: float = 1.15
    tolling_fee: float = 2.50            # USD/MMBtu, sunk
    port_days: float = 2.0               # loading + discharge time, charged at the charter rate
    routes: dict = field(default_factory=lambda: dict(ROUTES))

    def with_routes(self, **changes) -> "Assumptions":
        return replace(self, routes={**self.routes, **changes})


def voyage_days(route: Route, a: Assumptions) -> tuple[float, float]:
    """(laden days, round-trip days including port time)."""
    one_way = route.distance_nm / (a.speed_knots * 24)
    return one_way, 2 * one_way + a.port_days


def shipping_cost(route: Route, a: Assumptions, dest_price) -> np.ndarray:
    """Shipping + regas cost in USD per *loaded* MMBtu (dest_price: scalar or array)."""
    laden, total = voyage_days(route, a)
    ballast = total - laden - a.port_days
    fixed = a.charter_usd_day * total + a.ballast_fuel_usd_day * ballast + route.canal_fee_usd
    boil_off = a.boil_off_per_day * laden * np.asarray(dest_price, float)
    return fixed / a.cargo_mmbtu + boil_off + route.regas_fee


def netback(route: Route, a: Assumptions, dest_price) -> np.ndarray:
    """FOB value of a cargo sold at the destination price (USD/MMBtu loaded)."""
    return np.asarray(dest_price, float) - shipping_cost(route, a, dest_price)


def netback_table(prices, a: Assumptions, routes: list[str] | None = None):
    """DataFrame of monthly FOB netbacks per route, plus variable and full cost."""
    import pandas as pd
    routes = routes or list(a.routes)
    out = pd.DataFrame(index=prices.index)
    for r in routes:
        rt = a.routes[r]
        out[r] = netback(rt, a, prices[rt.market])
    out["variable_cost"] = a.hh_multiplier * prices["henry_hub"]
    out["full_cost"] = out["variable_cost"] + a.tolling_fee
    return out
