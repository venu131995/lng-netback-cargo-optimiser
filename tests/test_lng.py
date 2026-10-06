import itertools
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lng import ROUTES, Assumptions, greedy_month, netback, plan_month, shipping_cost, voyage_days  # noqa: E402


def test_voyage_arithmetic():
    a = Assumptions()
    laden, total = voyage_days(ROUTES["NW Europe (Rotterdam)"], a)
    assert laden == pytest.approx(4900 / (17.5 * 24))
    assert total == pytest.approx(2 * laden + a.port_days)


def test_shipping_cost_hand_calculation():
    a = Assumptions()
    r = ROUTES["Japan via Panama"]
    laden, total = voyage_days(r, a)
    expected = ((75_000 * total + 35_000 * (total - laden - a.port_days) + 800_000) / 3.5e6
                + 0.001 * laden * 12.0 + 0.0)
    assert shipping_cost(r, a, 12.0) == pytest.approx(expected)
    assert netback(r, a, 12.0) == pytest.approx(12.0 - expected)


def test_longer_routes_cost_more_and_cape_beats_nothing():
    a = Assumptions()
    costs = {k: float(shipping_cost(v, a, 10.0)) for k, v in ROUTES.items()}
    assert costs["Iberia (Huelva)"] < costs["NW Europe (Rotterdam)"] < costs["Japan via Panama"] < costs["Japan via Cape"]


def brute_force(margin, days, cap, supply, fleet):
    routes = list(margin)
    best = 0.0
    for combo in itertools.product(*[range(cap[r] + 1) for r in routes]):
        if sum(combo) <= supply and sum(k * days[r] for k, r in zip(combo, routes)) <= fleet:
            best = max(best, sum(k * margin[r] for k, r in zip(combo, routes)))
    return best


def test_milp_matches_brute_force_and_beats_greedy():
    margin = {"EU": 9e6, "Iberia": 8.5e6, "Asia": 15e6}
    days = {"EU": 26, "Iberia": 24, "Asia": 46}
    cap = {"EU": 4, "Iberia": 3, "Asia": 4}
    plan = plan_month(margin, days, cap, supply=8, fleet_days=230)
    assert plan.margin_usd == pytest.approx(brute_force(margin, days, cap, 8, 230))
    assert plan.margin_usd >= greedy_month(margin, days, cap, 8, 230)
    assert plan.fleet_days_used <= 230
    assert sum(plan.cargoes.values()) + plan.cancelled == 8


def test_cancels_when_every_route_loses_money():
    margin = {"EU": -2e6, "Asia": -1e6}
    plan = plan_month(margin, {"EU": 26, "Asia": 46}, {"EU": 5, "Asia": 5}, supply=6, fleet_days=500)
    assert plan.cancelled == 6 and plan.margin_usd == 0


def test_ship_day_value_positive_only_when_fleet_binds():
    margin = {"EU": 9e6, "Asia": 15e6}
    days = {"EU": 26, "Asia": 46}
    cap = {"EU": 10, "Asia": 10}
    tight = plan_month(margin, days, cap, supply=10, fleet_days=300)
    loose = plan_month(margin, days, cap, supply=10, fleet_days=5000)
    assert tight.ship_day_value > 0
    assert loose.ship_day_value == pytest.approx(0, abs=1e-6)
