"""US LNG netbacks 2010-2026, destination choice, cargo cancellations, Panama scenario, portfolio MILP."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lng import Assumptions, greedy_month, netback_table, plan_month, shipping_cost, voyage_days  # noqa: E402
from lng.data import gas_prices  # noqa: E402

FIG, RES = ROOT / "figures", ROOT / "results"
PANAMA_DISRUPTION = ("2023-08-01", "2024-06-01")   # drought-related transit restrictions (approximate window)
SUPPLY, FLEET = 10, 12                              # cargoes per month, chartered vessels
START = "2016-03-01"                                # first US Gulf Coast export cargo: Feb 2016
CAPACITY = {"NW Europe (Rotterdam)": 4, "Iberia (Huelva)": 3, "Japan via Panama": 3, "Japan via Cape": 4}
plt.rcParams.update({"figure.dpi": 130, "axes.grid": True, "grid.alpha": 0.3, "axes.spines.top": False,
                     "axes.spines.right": False, "font.size": 9})


def main() -> None:
    FIG.mkdir(exist_ok=True); RES.mkdir(exist_ok=True)
    px = gas_prices(ROOT / "data", start=START)
    a = Assumptions()
    routes = list(a.routes)
    nb = netback_table(px, a)
    best_route = nb[routes].idxmax(axis=1)
    best_nb = nb[routes].max(axis=1)
    lift = best_nb > nb["variable_cost"]
    decision = best_route.where(lift, "Cancel cargo")
    margin = (best_nb - nb["variable_cost"]).clip(lower=0)            # USD/MMBtu, flexible cargo
    days = {r: voyage_days(a.routes[r], a)[1] for r in routes}

    # ------------------------------------------------------------------ flexibility value
    fixed_eu = (nb["NW Europe (Rotterdam)"] - nb["variable_cost"]).clip(lower=0)
    fixed_asia = (nb["Japan via Panama"] - nb["variable_cost"]).clip(lower=0)
    no_cancel_eu = nb["NW Europe (Rotterdam)"] - nb["variable_cost"]
    per_cargo = lambda s: float(s.sum() * a.cargo_mmbtu / 1e6)  # noqa: E731  USD m over the period, one cargo/month
    yearly = pd.DataFrame({"flexible": margin, "fixed_europe": fixed_eu, "fixed_asia_panama": fixed_asia}) \
        .groupby(px.index.year).sum() * a.cargo_mmbtu / 1e6
    dest_by_year = pd.crosstab(px.index.year, decision)

    # ------------------------------------------------------------------ Panama disruption
    pan = slice(*PANAMA_DISRUPTION)
    no_panama = [r for r in routes if r != "Japan via Panama"]
    dec_no_pan = nb.loc[pan, no_panama].idxmax(axis=1).where(nb.loc[pan, no_panama].max(axis=1) > nb.loc[pan, "variable_cost"], "Cancel cargo")
    loss_pan = (nb.loc[pan, routes].max(axis=1) - nb.loc[pan, no_panama].max(axis=1)).clip(lower=0)

    # ------------------------------------------------------------------ charter sensitivity
    sens = []
    for rate in [40_000, 75_000, 120_000, 200_000, 300_000]:
        t = netback_table(px, replace(a, charter_usd_day=rate))
        b = t[routes].idxmax(axis=1).where(t[routes].max(axis=1) > t["variable_cost"], "Cancel cargo")
        sens.append({"charter_usd_day": rate, "share_asia": round(float(b.str.startswith("Japan").mean()), 3),
                     "share_europe": round(float(b.isin(["NW Europe (Rotterdam)", "Iberia (Huelva)"]).mean()), 3),
                     "share_cancel": round(float((b == "Cancel cargo").mean()), 3),
                     "spread_asia_minus_eu_usd": round(float((t["Japan via Panama"] - t["NW Europe (Rotterdam)"]).mean()), 3)})

    # ------------------------------------------------------------------ portfolio MILP, last 36 months
    plans = []
    for m in px.index[-36:]:
        cap = dict(CAPACITY)
        if pd.Timestamp(PANAMA_DISRUPTION[0]) <= m <= pd.Timestamp(PANAMA_DISRUPTION[1]):
            cap["Japan via Panama"] = 1                                   # restricted transit slots
        mpc = {r: float((nb.at[m, r] - nb.at[m, "variable_cost"]) * a.cargo_mmbtu) for r in routes}
        p = plan_month(mpc, days, cap, SUPPLY, FLEET * 30.4)
        eu_only = min(SUPPLY, CAPACITY["NW Europe (Rotterdam)"] + CAPACITY["Iberia (Huelva)"])
        naive_eu = sum(max(mpc[r], 0) * min(CAPACITY[r], SUPPLY) for r in ["NW Europe (Rotterdam)", "Iberia (Huelva)"]) if eu_only else 0
        economic = p.cancelled if max(mpc.values()) <= 0 else 0
        plans.append({"month": m, **p.cargoes, "cancelled": p.cancelled, "cancel_economic": economic,
                      "unlifted_no_ship_or_slot": p.cancelled - economic, "margin_usd_m": p.margin_usd / 1e6,
                      "greedy_usd_m": greedy_month(mpc, days, cap, SUPPLY, FLEET * 30.4) / 1e6,
                      "europe_only_usd_m": naive_eu / 1e6, "fleet_days_used": p.fleet_days_used,
                      "ship_day_value_usd": p.ship_day_value})
    plans = pd.DataFrame(plans).set_index("month")
    plans.to_csv(RES / "portfolio_plan_36m.csv", float_format="%.3f")
    nb.assign(decision=decision, margin=margin).to_csv(RES / "monthly_netbacks.csv", float_format="%.3f")

    cancel_months = [d.strftime("%Y-%m") for d in decision.index[decision == "Cancel cargo"]]
    out = {
        "data": {"source": "FRED / IMF: PNGASUSUSDM, PNGASEUUSDM, PNGASJPUSDM", "first": str(px.index[0].date()),
                 "last": str(px.index[-1].date()), "months": int(len(px))},
        "assumptions": {k: v for k, v in asdict(a).items() if k != "routes"},
        "routes": {r: {"distance_nm": a.routes[r].distance_nm, "round_trip_days": round(days[r], 1),
                       "shipping_usd_mmbtu_at_10": round(float(shipping_cost(a.routes[r], a, 10.0)), 3)}
                   for r in routes},
        "destination_share": decision.value_counts(normalize=True).round(3).to_dict(),
        "destination_counts_by_year": {int(y): {k: int(v) for k, v in row.items() if v} for y, row in dest_by_year.iterrows()},
        "cancel_months": cancel_months,
        "flexibility_value_usd_m_one_cargo_per_month": {
            "flexible_with_cancellation": round(per_cargo(margin), 1),
            "fixed_europe_with_cancellation": round(per_cargo(fixed_eu), 1),
            "fixed_asia_panama_with_cancellation": round(per_cargo(fixed_asia), 1),
            "fixed_europe_no_cancellation": round(per_cargo(no_cancel_eu), 1)},
        "yearly_margin_usd_m": yearly.round(2).to_dict(orient="index"),
        "panama_disruption": {"window": list(PANAMA_DISRUPTION),
                              "months_destination_changes": int((decision.loc[pan] != dec_no_pan).sum()),
                              "avg_netback_loss_usd_mmbtu": round(float(loss_pan.mean()), 3),
                              "loss_per_cargo_usd_m_avg": round(float(loss_pan.mean() * a.cargo_mmbtu / 1e6), 2)},
        "charter_sensitivity": sens,
        "portfolio_36m": {"window": [str(plans.index[0].date()), str(plans.index[-1].date())],
                          "supply_cargoes_per_month": SUPPLY, "fleet_vessels": FLEET, "capacity": CAPACITY,
                          "milp_margin_usd_m": round(float(plans["margin_usd_m"].sum()), 1),
                          "greedy_margin_usd_m": round(float(plans["greedy_usd_m"].sum()), 1),
                          "europe_only_margin_usd_m": round(float(plans["europe_only_usd_m"].sum()), 1),
                          "milp_uplift_vs_greedy_pct": round(100 * (plans["margin_usd_m"].sum() / plans["greedy_usd_m"].sum() - 1), 2),
                          "avg_ship_day_value_usd": round(float(plans["ship_day_value_usd"].mean()), 0),
                          "value_of_one_more_vessel_usd_m_per_year": round(float(plans["ship_day_value_usd"].mean() * 365 / 1e6), 2),
                          "cargoes_by_route": {r: int(plans[r].sum()) for r in routes},
                          "cancelled_economic": int(plans["cancel_economic"].sum()),
                          "unlifted_no_ship_or_slot": int(plans["unlifted_no_ship_or_slot"].sum()),
                          "months_fleet_binding": int((plans["ship_day_value_usd"] > 1).sum()),
                          "breakeven_charter_for_extra_vessel_usd_day_median": round(float(plans["ship_day_value_usd"].median()), 0)},
    }
    (RES / "summary.json").write_text(json.dumps(out, indent=2, default=str))

    # ------------------------------------------------------------------ figures
    fig, ax = plt.subplots(figsize=(8, 3.4))
    for c, lab in [("henry_hub", "Henry Hub (US)"), ("europe", "Europe (TTF)"), ("asia_lng", "Japan LNG (delivered)")]:
        ax.plot(px.index, px[c], lw=1.2, label=lab)
    ax.set_ylabel("USD/MMBtu"); ax.legend(); ax.set_title("Monthly gas benchmarks (IMF via FRED)")
    fig.tight_layout(); fig.savefig(FIG / "fig1_benchmarks.png"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 3.8))
    ax.plot(nb.index, nb["NW Europe (Rotterdam)"], lw=1.1, label="FOB netback: NW Europe")
    ax.plot(nb.index, nb["Japan via Panama"], lw=1.1, label="FOB netback: Japan via Panama")
    ax.plot(nb.index, nb["variable_cost"], color="k", lw=1.1, ls="--", label="Variable cost 1.15 x HH")
    ax.plot(nb.index, nb["full_cost"], color="0.5", lw=1, ls=":", label="Full cost incl. tolling fee")
    for d in decision.index[decision == "Cancel cargo"]:
        ax.axvspan(d, d + pd.offsets.MonthEnd(1), color="tab:red", alpha=0.25, lw=0)
    ax.set_ylabel("USD/MMBtu"); ax.set_ylim(-2, min(45, float(nb[routes].max().max()) + 2)); ax.legend(loc="upper left", fontsize=7)
    ax.set_title("US LNG netbacks vs cost (red = model says cancel the cargo)")
    fig.tight_layout(); fig.savefig(FIG / "fig2_netbacks_and_cancellations.png"); plt.close(fig)

    fig, ax = plt.subplots(2, 1, figsize=(8, 4.4), sharex=True, gridspec_kw={"height_ratios": [1, 2]})
    cmap = {"NW Europe (Rotterdam)": "tab:blue", "Iberia (Huelva)": "tab:cyan", "Japan via Panama": "tab:orange",
            "Japan via Cape": "tab:brown", "Cancel cargo": "tab:red"}
    for k, col in cmap.items():
        idx = decision.index[decision == k]
        if len(idx):
            ax[0].bar(idx, np.ones(len(idx)), width=31, color=col, label=k)
    ax[0].set_yticks([]); ax[0].legend(ncol=4, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.04))
    ax[0].set_title("Best single-cargo destination each month")
    spread = nb["Japan via Panama"] - nb["NW Europe (Rotterdam)"]
    ax[1].fill_between(spread.index, spread, 0, where=spread > 0, color="tab:orange", alpha=0.5, label="Asia pays more")
    ax[1].fill_between(spread.index, spread, 0, where=spread <= 0, color="tab:blue", alpha=0.5, label="Europe pays more")
    ax[1].axhline(0, color="k", lw=0.6); ax[1].set_ylabel("Asia - Europe netback\n(USD/MMBtu)"); ax[1].legend(loc="lower left", fontsize=7)
    fig.tight_layout(h_pad=2.5); fig.savefig(FIG / "fig3_destination_arbitrage.png"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 3.4))
    cum = pd.DataFrame({"Flexible destination (+ cancellation)": margin, "Fixed: Europe": fixed_eu,
                        "Fixed: Asia via Panama": fixed_asia}).cumsum() * a.cargo_mmbtu / 1e6
    cum.plot(ax=ax, lw=1.4)
    ax.set_ylabel("Cumulative margin, one cargo/month (USD m)"); ax.set_title("Value of destination flexibility"); ax.legend(fontsize=7)
    fig.tight_layout(); fig.savefig(FIG / "fig4_flexibility_value.png"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 3.4))
    rates = [s["charter_usd_day"] / 1e3 for s in sens]
    ax.stackplot(rates, [s["share_asia"] for s in sens], [s["share_europe"] for s in sens], [s["share_cancel"] for s in sens],
                 labels=["Asia", "Europe", "Cancel"], colors=["tab:orange", "tab:blue", "tab:red"], alpha=0.7)
    ax.set_xlabel("LNG carrier charter rate (USD k/day)"); ax.set_ylabel("Share of months since 2016"); ax.legend(loc="upper right")
    ax.set_title("Freight decides the arbitrage")
    fig.tight_layout(); fig.savefig(FIG / "fig5_charter_sensitivity.png"); plt.close(fig)

    fig, ax = plt.subplots(2, 1, figsize=(8, 5), sharex=True)
    plans[routes + ["cancelled"]].plot.bar(stacked=True, ax=ax[0], width=0.85,
                                           color=[cmap[r] for r in routes] + ["tab:red"], legend=False)
    ax[0].set_ylabel("Cargoes"); ax[0].set_ylim(0, SUPPLY * 1.35)
    ax[0].legend(routes + ["Unlifted (no ship/slot)"], ncol=3, fontsize=6.5, loc="upper center")
    ax[0].set_title(f"MILP cargo plan: {SUPPLY} cargoes/month, {FLEET} vessels (Panama capped during drought)")
    ax[1].bar(range(len(plans)), plans["ship_day_value_usd"] / 1e3, color="tab:green")
    ax[1].set_ylabel("Shadow value of a\nship-day (USD k)")
    ax[1].set_xticks(range(0, len(plans), 3), [d.strftime("%Y-%m") for d in plans.index[::3]], rotation=45)
    fig.tight_layout(); fig.savefig(FIG / "fig6_portfolio_plan.png"); plt.close(fig)

    print(json.dumps({k: out[k] for k in ["destination_share", "cancel_months", "flexibility_value_usd_m_one_cargo_per_month",
                                          "panama_disruption", "charter_sensitivity", "portfolio_36m", "routes"]}, indent=1, default=str))


if __name__ == "__main__":
    main()
