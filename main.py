#!/usr/bin/env python3
"""
Educational example: pricing a fixed-rate bond and its par-par asset swap.

This script demonstrates:
  1. Building a EUR discount curve from deposit + swap rates.
  2. Pricing a fixed-rate government/corporate bond off that curve.
  3. Computing the par-par asset-swap spread (ASW) two ways:
       a) QuantLib's ``AssetSwap`` class.
       b) Manual replication from first-principles (bond cashflows +
          floating-leg annuity).
  4. Comparing both approaches to verify they match.

All numbers are illustrative — not live market data.
"""

import QuantLib as ql

from curves import build_sample_eur_curve
from bond_pricer import build_fixed_rate_bond, price_bond, price_bond_from_yield
from asset_swap import (
    price_par_par_asset_swap,
    replicate_par_par_asset_swap,
    compute_z_spread,
)


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
    # 4. Par-par asset swap — QuantLib AssetSwap
    # ------------------------------------------------------------------
    separator("Par-Par Asset Swap  (ql.AssetSwap)")

    # In practice this would be an observed market dirty price.  We
    # subtract 1.5 points from the model dirty price to simulate a
    # credit/liquidity discount.
    market_dirty_price = results.dirty_price - 1.50
    market_clean_price = market_dirty_price - results.accrued_interest

    print(f"Market dirty px : {market_dirty_price:>10.4f}")
    print(f"Market clean px : {market_clean_price:>10.4f}")
    print(f"Accrued         : {results.accrued_interest:>10.4f}")

    asw = price_par_par_asset_swap(
        bond=bond,
        bond_dirty_price=market_dirty_price,
        discount_curve=curve_handle,
        evaluation_date=eval_date,
    )

    print(f"ASW spread      : {asw.asset_swap_spread:>10.2f} bps")
    print(f"Fair spread     : {asw.fair_spread * 100:>10.4f}%")
    print(f"Swap NPV        : {asw.npv:>10.4f}")
    print(f"Fixed leg NPV   : {asw.fixed_leg_npv:>10.4f}")
    print(f"Float leg NPV   : {asw.floating_leg_npv:>10.4f}")

    # Z-spread for comparison (takes clean price)
    z_spread_bps = compute_z_spread(bond, market_clean_price, curve_handle)
    print(f"Z-spread        : {z_spread_bps:>10.2f} bps")

    # ------------------------------------------------------------------
    # 5. Par-par asset swap — Manual replication
    # ------------------------------------------------------------------
    separator("Par-Par Asset Swap  (Manual Replication)")

    rep = replicate_par_par_asset_swap(
        bond=bond,
        bond_dirty_price=market_dirty_price,
        discount_curve=curve_handle,
        evaluation_date=eval_date,
    )

    print("Step 1 — Bond cashflows discounted at the swap curve:")
    print(f"  {'Date':<28} {'Amount':>8} {'DF':>12} {'PV':>10}")
    print(f"  {'-'*60}")
    for cf in rep.bond_cashflows:
        print(f"  {cf.date:<28} {cf.amount:>8.4f} {cf.discount_factor:>12.8f} {cf.present_value:>10.4f}")
    print(f"  {'':>28} {'':>8} {'Total PV':>12} {sum(c.present_value for c in rep.bond_cashflows):>10.4f}")
    print(f"\n  Bond PV at settlement (theoretical dirty): {rep.bond_pv_at_swap_curve:.4f}")
    print(f"  Market dirty price:                         {rep.market_dirty_price:.4f}")
    print(f"  Difference (numerator):                     {rep.bond_pv_at_swap_curve - rep.market_dirty_price:.4f}")

    print(f"\nStep 2 — Floating-leg annuity ({len(rep.floating_periods)} periods):")
    print(f"  {'Start':<15} {'End':<15} {'tau':>8} {'DF':>12} {'tau*DF':>10}")
    print(f"  {'-'*62}")
    for fp in rep.floating_periods:
        # Shorten date strings for display
        s = fp.start.split(",")[0] if "," in fp.start else fp.start[:15]
        e = fp.end.split(",")[0] if "," in fp.end else fp.end[:15]
        print(f"  {s:<15} {e:<15} {fp.year_fraction:>8.4f} {fp.discount_factor:>12.8f} {fp.contribution:>10.6f}")
    print(f"  {'':>15} {'':>15} {'':>8} {'Annuity':>12} {rep.floating_annuity:>10.6f}")

    print(f"\nStep 3 — Solve for spread:")
    print(f"  s = (PV_bond - dirty) / (face * annuity)")
    print(f"    = ({rep.bond_pv_at_swap_curve:.4f} - {rep.market_dirty_price:.4f})"
          f" / (100 * {rep.floating_annuity:.6f})")
    print(f"    = {rep.fair_spread:.8f}")
    print(f"    = {rep.asset_swap_spread:.2f} bps")

    # ------------------------------------------------------------------
    # 6. Comparison
    # ------------------------------------------------------------------
    separator("Comparison: ql.AssetSwap vs Manual Replication")

    diff = abs(asw.asset_swap_spread - rep.asset_swap_spread)
    print(f"  {'Method':<30} {'ASW Spread (bps)':>18}")
    print(f"  {'-'*50}")
    print(f"  {'ql.AssetSwap':<30} {asw.asset_swap_spread:>18.4f}")
    print(f"  {'Manual replication':<30} {rep.asset_swap_spread:>18.4f}")
    print(f"  {'Difference':<30} {diff:>18.4f}")
    print(f"  {'Z-spread (reference)':<30} {z_spread_bps:>18.4f}")

    # ------------------------------------------------------------------
    # 7. Sensitivity: ASW spread vs. bond dirty price
    # ------------------------------------------------------------------
    separator("ASW Spread Sensitivity to Bond Dirty Price")

    print(f"{'Dirty Price':>12} {'ASW (ql)':>12} {'ASW (manual)':>14} {'Z-Spread':>12}   (all bps)")
    print("-" * 54)
    for bump in [-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0]:
        px = market_dirty_price + bump
        clean_for_z = px - results.accrued_interest
        a = price_par_par_asset_swap(bond, px, curve_handle, evaluation_date=eval_date)
        r = replicate_par_par_asset_swap(bond, px, curve_handle, evaluation_date=eval_date)
        z = compute_z_spread(bond, clean_for_z, curve_handle)
        print(f"{px:>12.4f} {a.asset_swap_spread:>12.2f} {r.asset_swap_spread:>14.2f} {z:>12.2f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
