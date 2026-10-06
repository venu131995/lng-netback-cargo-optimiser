"""Monthly cargo allocation for a US LNG portfolio as a mixed-integer linear program.

Each month the portfolio has `supply` cargoes. Each cargo can go to any route or be cancelled
(the variable cost is avoided; the tolling fee is sunk either way). Constraints:

    sum_r x[r] + cancel = supply                     (every cargo is either lifted or cancelled)
    x[r] <= capacity[r]                               (regas slots / buyer appetite per route)
    sum_r x[r] * round_trip_days[r] <= fleet_days     (shipping capacity of the chartered fleet)

Objective: maximise sum_r x[r] * cargo * (netback[r] - variable_cost).
The LP relaxation's dual on the fleet constraint is the marginal value of one more ship-day.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp


@dataclass
class MonthPlan:
    cargoes: dict          # route -> number of cargoes
    cancelled: float
    margin_usd: float
    fleet_days_used: float
    ship_day_value: float  # dual of the fleet constraint from the LP relaxation (USD per ship-day)


def plan_month(margin_per_cargo: dict, round_trip_days: dict, capacity: dict, supply: int,
               fleet_days: float) -> MonthPlan:
    routes = list(margin_per_cargo)
    n = len(routes)
    c = -np.array([margin_per_cargo[r] for r in routes] + [0.0])          # last variable = cancel
    A_supply = np.ones((1, n + 1))
    A_fleet = np.array([[round_trip_days[r] for r in routes] + [0.0]])
    ub = np.array([capacity[r] for r in routes] + [supply], float)
    cons = [LinearConstraint(A_supply, supply, supply), LinearConstraint(A_fleet, -np.inf, fleet_days)]
    res = milp(c, constraints=cons, integrality=np.ones(n + 1), bounds=Bounds(np.zeros(n + 1), ub))
    if not res.success:
        raise RuntimeError(res.message)
    x = np.round(res.x).astype(int)
    lp = linprog(c, A_ub=A_fleet, b_ub=[fleet_days], A_eq=A_supply, b_eq=[supply],
                 bounds=list(zip(np.zeros(n + 1), ub)), method="highs")
    dual = -lp.ineqlin.marginals[0] if lp.success else float("nan")
    return MonthPlan(cargoes={r: int(v) for r, v in zip(routes, x[:-1])}, cancelled=int(x[-1]),
                     margin_usd=float(-res.fun), fleet_days_used=float(A_fleet[0] @ x),
                     ship_day_value=float(dual))


def greedy_month(margin_per_cargo: dict, round_trip_days: dict, capacity: dict, supply: int,
                 fleet_days: float) -> float:
    """Benchmark: send cargoes to the highest-margin route first, ignoring ship-day efficiency."""
    left, days, total = supply, fleet_days, 0.0
    for r in sorted(margin_per_cargo, key=margin_per_cargo.get, reverse=True):
        if margin_per_cargo[r] <= 0:
            break
        k = min(capacity[r], left, int(days // round_trip_days[r]))
        total += k * margin_per_cargo[r]
        left -= k
        days -= k * round_trip_days[r]
    return total
