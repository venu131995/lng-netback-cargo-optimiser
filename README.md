# US LNG Netback & Cargo Optimiser

A physical-trading desk tool for **US Gulf Coast LNG**. For every month since US exports began
(March 2016), it answers the questions a trader and an operator ask about each cargo:

- **Where should it go?** Europe or Asia, and via Panama or the Cape of Good Hope.
- **Should it be lifted at all,** or cancelled?
- **How should a whole portfolio** of cargoes be split across limited ships and regas slots?

It also measures how freight rates and the 2023–24 Panama Canal drought changed those answers.

## How the economics work

US LNG is sold FOB under Cheniere-style contracts. The buyer pays **115% of Henry Hub** for each cargo
lifted, plus a fixed **tolling fee** (about USD 2.50/MMBtu) that is owed whether or not the cargo is lifted.

```
FOB netback (route)  = destination price − shipping cost(route) − regas fee
lift the cargo if      best netback  >  1.15 × Henry Hub          (tolling fee is sunk)
```

Shipping cost per MMBtu is built bottom-up for each route:

- **charter:** day rate × (laden days + ballast days + port days);
- **fuel:** fuel on the ballast leg;
- **boil-off:** 0.10% of cargo per laden day, valued at the destination price;
- **canal:** Panama tolls on both legs where the route uses Panama.

| Route (from Sabine Pass) | Distance | Round trip | Shipping cost at USD 10 gas |
|---|---|---|---|
| Iberia (Huelva) | 4,500 nm | 23 days | USD 1.17/MMBtu |
| NW Europe (Rotterdam) | 4,900 nm | 25 days | USD 1.18/MMBtu |
| Japan via Panama | 9,250 nm | 46 days | USD 1.66/MMBtu |
| Japan via Cape | 15,800 nm | 77 days | USD 2.41/MMBtu |

Prices are monthly IMF benchmarks from FRED: Henry Hub, European gas (TTF) and Japan LNG import prices.
Base case: 3.5 million MMBtu cargo, 17.5 knots, USD 75k/day charter.

## Results

All figures come from `results/summary.json`, produced by `scripts/run_lng.py`.

### 1. Destination choice, March 2016 – July 2026 (125 months)

| Best destination | Share of months |
|---|---|
| Japan via Panama | 66% |
| Iberia | 29% |
| **Cancel cargo** | **6%** |

- **2016–2021:** Asia almost always paid more, often by USD 2–5/MMBtu after shipping.
- **2022:** the arbitrage flipped. Europe paid **up to USD 16/MMBtu more** than Asia after Russian pipeline
  gas was cut, and the best destination was Europe in 10 of 12 months.
- **Since 2023:** the spread has been small and switches sign, so cargoes swing between the two markets
  (`fig3_destination_arbitrage.png`).

### 2. The model reproduces the 2020 cargo cancellations

From **February to August 2020** every route's netback fell below 1.15 × Henry Hub. For example, the
Rotterdam netback was USD 0.39/MMBtu in May 2020 against a variable cost of about USD 2. Cancelling avoids
the variable cost, and the tolling fee is lost either way. This matches what happened: buyers reportedly
cancelled well over 100 US cargoes for summer 2020 (`fig2_netbacks_and_cancellations.png`).

### 3. Value of destination flexibility (one cargo a month)

| Contract | Cumulative margin 2016–2026 |
|---|---|
| **Flexible destination, may cancel** | **USD 3.46bn** |
| Fixed: Asia via Panama | USD 3.17bn |
| Fixed: Europe | USD 3.04bn |

Free choice of destination adds **USD 290–420m (9–14%)** over any fixed destination. Most of that came in
2022, when a cargo locked into Asia missed Europe's premium, and in 2016–2021, when Europe paid least
(`fig4_flexibility_value.png`).

### 4. Freight decides the arbitrage

| Charter rate (USD/day) | 40k | 75k | 120k | 200k | 300k |
|---|---|---|---|---|---|
| Months Asia is best | 71% | 66% | 48% | 33% | 14% |
| Months Europe is best | 25% | 29% | 41% | 49% | 57% |
| Months to cancel | 4% | 6% | 11% | 18% | 30% |

Asia trips are about twice as long, so high freight rates (as in late 2022, when spot rates passed
USD 300k/day) push cargoes toward Europe. They also raise the number of cargoes worth cancelling
(`fig5_charter_sensitivity.png`).

### 5. Panama Canal drought, Aug 2023 – Jun 2024

With Panama removed as an option, the best destination changes in **9 of 11 months**. Cargoes either
divert to Europe or take the Cape route. Each affected cargo loses **about USD 0.47/MMBtu, or USD 1.7m**.

### 6. Portfolio optimisation: 10 cargoes a month, 12 ships, last 36 months

Each month is solved as a **mixed-integer linear programme**. Every cargo is assigned to a route or cancelled,
subject to regas-slot limits per route and the fleet's available ship-days. Panama is capped at one slot a
month during the drought.

| Allocation method | Margin, Aug 2023 – Jul 2026 |
|---|---|
| **MILP optimiser** | **USD 9.30bn** |
| Greedy (best route first) | USD 8.36bn |
| Europe only | USD 6.65bn |

- **The MILP earns 11% (USD 0.95bn) more than greedy.** A greedy desk fills the highest-paying route first.
  When ships are scarce, the long Asia trips use up ship-days that could carry two Europe cargoes. The
  optimiser trades margin per cargo against ship-days per cargo.
- **Ship value.** The dual price of the fleet constraint shows when ships are the bottleneck. During the
  drought one extra ship-day was worth **USD 200–420k**, far above charter rates, so chartering more ships
  would have paid. Since mid-2024 the fleet has rarely been binding (`fig6_portfolio_plan.png`).
- **Shortfall.** Over the 36 months, 11 cargoes could not be lifted for lack of ships or slots. None were
  cancelled for economic reasons.

## Figures

| File | Content |
|---|---|
| `fig1_benchmarks.png` | Henry Hub, TTF and Japan LNG prices since 2016 |
| `fig2_netbacks_and_cancellations.png` | Europe and Asia netbacks vs. variable and full cost; cancellation months shaded |
| `fig3_destination_arbitrage.png` | Best destination each month and the Asia–Europe netback spread |
| `fig4_flexibility_value.png` | Cumulative margin, flexible vs. fixed-destination cargo |
| `fig5_charter_sensitivity.png` | Destination mix as charter rates rise |
| `fig6_portfolio_plan.png` | MILP cargo plan by route and shadow value of a ship-day |

## Simplifications

- Monthly benchmark averages, not the forward curves traders actually lock in (TTF/JKM futures).
- Japan LNG import prices are largely oil-indexed and lag spot prices. A spot JKM series would show more
  frequent Asia premia in 2021–22.
- Distances, speeds, costs and the Panama window are representative assumptions, all set in `economics.py`
  and the top of `run_lng.py`. Charter rates are held flat in the backtest, with the sensitivity shown above.
- Regas fees are simplified to one figure per route; canal waiting times and spot-charter availability are
  not modelled.

## Tests (`tests/`, 6 passing)

- Voyage-time and shipping-cost formulas match hand calculations.
- Route costs rank in the right order.
- The MILP matches brute-force enumeration and never does worse than the greedy method.
- Every cargo is cancelled when all routes lose money.
- The ship-day value is positive only when the fleet constraint binds.

## Run

```bash
pip install -r requirements.txt
python -m pytest -q tests     # 6 tests, < 1 s
python scripts/run_lng.py     # ~10 s: downloads FRED data, writes results/ and figures/
```
