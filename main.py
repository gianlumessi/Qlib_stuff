#!/usr/bin/env python3
"""
Educational example: pricing a fixed-rate bond and its par-par asset swap.

This script demonstrates:
  1. Building a EUR discount curve from deposit + swap rates.
  2. Pricing a fixed-rate government/corporate bond off that curve.
  3. Computing the par-par asset-swap spread (ASW) and Z-spread.

All numbers are illustrative — not live market data.
"""

import QuantLib as ql

from curves import build_sample_eur_curve
from bond_pricer import build_fixed_rate_bond, price_bond, price_bond_from_yield
from asset_swap import price_par_par_asset_swap, asset_swap_spread_from_z_spread


def separator(title: str) -> None:
    width = 60
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


def main() -> None:
    # ------------------------------------------------------------------
    # 1. Global settings
    # ------------------------------------------------------------------
    eval_date = ql.Date(15, ql.January, 2025)
    ql.Settings.instance().evaluationDate = eval_date
    print(f"Evaluation date : {eval_date}")

    # ------------------------------------------------------------------
    # 2. Build discount curve
    # ------------------------------------------------------------------
    separator("EUR Discount Curve")
    curve_handle = build_sample_eur_curve(eval_date)

    pillars = [
        ql.Period(1, ql.Months),
        ql.Period(6, ql.Months),
        ql.Period(1, ql.Years),
        ql.Period(2, ql.Years),
        ql.Period(5, ql.Years),
        ql.Period(10, ql.Years),
        ql.Period(20, ql.Years),
        ql.Period(30, ql.Years),
    ]
    print(f"{'Tenor':<10} {'Discount Factor':>16} {'Zero Rate':>12}")
    print("-" * 40)
    for p in pillars:
        d = ql.TARGET().advance(eval_date, p)
        df = curve_handle.discount(d)
        zr = curve_handle.zeroRate(
            d, ql.Actual365Fixed(), ql.Continuous
        ).rate()
        print(f"{str(p):<10} {df:>16.8f} {zr * 100:>11.4f}%")

    # ------------------------------------------------------------------
    # 3. Define and price a fixed-rate bond
    # ------------------------------------------------------------------
    separator("Fixed-Rate Bond Pricing")

    issue_date = ql.Date(15, ql.March, 2023)
    maturity_date = ql.Date(15, ql.March, 2033)
    coupon_rate = 0.0325  # 3.25 % annual coupon

    bond = build_fixed_rate_bond(
        face_value=100.0,
        issue_date=issue_date,
        maturity_date=maturity_date,
        coupon_rate=coupon_rate,
        coupon_frequency=ql.Annual,
    )

    results = price_bond(bond, curve_handle, eval_date)

    print(f"Bond           : {coupon_rate*100:.2f}% {issue_date} - {maturity_date}")
    print(f"Clean price    : {results.clean_price:>10.4f}")
    print(f"Dirty price    : {results.dirty_price:>10.4f}")
    print(f"Accrued        : {results.accrued_interest:>10.4f}")
    print(f"YTM            : {results.ytm * 100:>10.4f}%")
    print(f"Mod. duration  : {results.modified_duration:>10.4f}")
    print(f"Mac. duration  : {results.macaulay_duration:>10.4f}")
    print(f"Convexity      : {results.convexity:>10.4f}")
    print(f"BPV (DV01)     : {results.bpv:>10.4f}")

    # Price from a target yield
    target_yield = 0.035
    px_from_yield = price_bond_from_yield(bond, target_yield)
    print(f"\nClean price at {target_yield*100:.2f}% yield : {px_from_yield:.4f}")

    # ------------------------------------------------------------------
    # 4. Par-par asset swap
    # ------------------------------------------------------------------
    separator("Par-Par Asset Swap")

    # In practice this would be an observed market price.  We subtract
    # 1.5 points from the model price to simulate a credit/liquidity
    # discount — this makes the ASW spread non-trivial and more realistic.
    market_clean_price = results.clean_price - 1.50

    asw = price_par_par_asset_swap(
        bond=bond,
        bond_clean_price=market_clean_price,
        discount_curve=curve_handle,
        evaluation_date=eval_date,
    )

    print(f"Market clean px : {asw.bond_clean_price:>10.4f}")
    print(f"ASW spread      : {asw.asset_swap_spread:>10.2f} bps")
    print(f"Fair spread     : {asw.fair_spread * 100:>10.4f}%")
    print(f"Swap NPV        : {asw.npv:>10.4f}")
    print(f"Fixed leg NPV   : {asw.fixed_leg_npv:>10.4f}")
    print(f"Float leg NPV   : {asw.floating_leg_npv:>10.4f}")

    # Z-spread for comparison
    z_spread_bps = asset_swap_spread_from_z_spread(bond, market_clean_price, curve_handle)
    print(f"Z-spread        : {z_spread_bps:>10.2f} bps")

    # ------------------------------------------------------------------
    # 5. Sensitivity: ASW spread vs. bond price
    # ------------------------------------------------------------------
    separator("ASW Spread Sensitivity to Bond Price")

    print(f"{'Clean Price':>12} {'ASW Spread (bps)':>18} {'Z-Spread (bps)':>16}")
    print("-" * 48)
    for bump in [-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0]:
        px = market_clean_price + bump
        asw_bump = price_par_par_asset_swap(bond, px, curve_handle, evaluation_date=eval_date)
        z_bump = asset_swap_spread_from_z_spread(bond, px, curve_handle)
        print(f"{px:>12.4f} {asw_bump.asset_swap_spread:>18.2f} {z_bump:>16.2f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
