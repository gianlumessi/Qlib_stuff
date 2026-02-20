#!/usr/bin/env python3
"""
Educational example: pricing fixed-income instruments with QuantLib.

Instruments covered:
  1. Fixed-rate bond
  2. Par-par asset swap (QuantLib built-in + manual replication)
  3. Interest rate swap (IRS)
  4. Fixed-fixed cross-currency swap
  5. Fixed-floating cross-currency swap
  6. Floating-floating cross-currency basis swap

All numbers are illustrative — not live market data.
"""

import QuantLib as ql

from curves import build_sample_eur_curve, build_sample_usd_curve
from bond_pricer import build_fixed_rate_bond, price_bond, price_bond_from_yield
from asset_swap import (
    price_par_par_asset_swap,
    replicate_par_par_asset_swap,
    compute_z_spread,
)
from swap_pricer import price_irs
from xccy_swap_pricer import (
    price_fixed_fixed_xccy_swap,
    price_fixed_floating_xccy_swap,
    price_float_float_xccy_swap,
)
from plots import plot_rate_curves, plot_spreads_vs_price, plot_bond_cashflows


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

    print(f"Upfront (t=0)   : {asw.upfront:>10.4f}  (investor {'receives' if asw.upfront >= 0 else 'pays'} {abs(asw.upfront):.4f})")
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

    print(f"\nStep 3 — Upfront payment (swap value at t=0):")
    print(f"  Upfront = 100 - Dirty = 100 - {rep.market_dirty_price:.4f} = {rep.upfront:.4f}")
    print(f"  (Investor {'receives' if rep.upfront >= 0 else 'pays'} {abs(rep.upfront):.4f} at inception)")

    print(f"\nStep 4 — Solve for spread:")
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

    # ==================================================================
    #  INTEREST RATE SWAP
    # ==================================================================
    separator("Interest Rate Swap (EUR, 10Y Payer)")

    # Price a 10-year EUR payer swap (pay 3.00 % fixed, receive Euribor 6M)
    irs = price_irs(
        notional=10_000_000,
        fixed_rate=0.0300,        # 3.00 % — the par rate for 10Y is also ~3 %
        tenor_years=10,
        discount_curve=curve_handle,
        evaluation_date=eval_date,
    )

    print(f"Swap type       : {irs.swap_type}")
    print(f"Notional        : {irs.notional:>14,.0f} EUR")
    print(f"Fixed rate      : {irs.fixed_rate * 100:>14.4f}%")
    print(f"Maturity        : {irs.maturity_years}Y")
    print(f"NPV             : {irs.npv:>14,.2f} EUR")
    print(f"Fair rate       : {irs.fair_rate * 100:>14.4f}%")
    print(f"Fair spread     : {irs.fair_spread * 10000:>14.2f} bps")
    print(f"Fixed leg NPV   : {irs.fixed_leg_npv:>14,.2f}")
    print(f"Float leg NPV   : {irs.floating_leg_npv:>14,.2f}")
    print(f"Fixed leg BPS   : {irs.fixed_leg_bps:>14,.2f}")
    print(f"Float leg BPS   : {irs.floating_leg_bps:>14,.2f}")

    # Show a range of fixed rates around the fair rate
    print(f"\n  {'Fixed Rate':>12} {'NPV (EUR)':>16}")
    print(f"  {'-'*30}")
    for bump_bps in [-50, -25, -10, 0, 10, 25, 50]:
        r = irs.fair_rate + bump_bps / 10000
        irs_bump = price_irs(
            10_000_000, r, 10, curve_handle, evaluation_date=eval_date,
        )
        print(f"  {r*100:>11.4f}% {irs_bump.npv:>16,.2f}")

    # ==================================================================
    #  BUILD USD CURVE (needed for cross-currency swaps)
    # ==================================================================
    separator("USD Discount Curve")
    usd_curve = build_sample_usd_curve(eval_date)

    pillars_usd = [
        ql.Period(6, ql.Months),
        ql.Period(2, ql.Years),
        ql.Period(5, ql.Years),
        ql.Period(10, ql.Years),
        ql.Period(30, ql.Years),
    ]
    cal_usd = ql.UnitedStates(ql.UnitedStates.FederalReserve)
    print(f"{'Tenor':<10} {'DF':>16} {'Zero Rate':>12}")
    print("-" * 40)
    for p in pillars_usd:
        d = cal_usd.advance(eval_date, p)
        df = usd_curve.discount(d)
        zr = usd_curve.zeroRate(d, ql.Actual365Fixed(), ql.Continuous).rate()
        print(f"{str(p):<10} {df:>16.8f} {zr * 100:>11.4f}%")

    # ==================================================================
    #  CROSS-CURRENCY SWAP PARAMETERS
    # ==================================================================
    # Spot FX: EUR/USD = 1.10 (1 EUR = 1.10 USD)
    # We express spot_fx as "domestic (EUR) per 1 foreign (USD)":
    #   spot_fx = 1 / 1.10 ≈ 0.9091 EUR per 1 USD
    # But it is more natural to think in EUR/USD = 1.10 and set notionals:
    #   EUR notional = 10,000,000
    #   USD notional = 10,000,000 * 1.10 = 11,000,000
    #   spot_fx (EUR per 1 USD) = 1 / 1.10
    eur_usd_spot = 1.10             # 1 EUR = 1.10 USD
    spot_fx_eur_per_usd = 1.0 / eur_usd_spot   # EUR per 1 USD
    eur_notional = 10_000_000
    usd_notional = eur_notional * eur_usd_spot  # 11,000,000 USD

    # ==================================================================
    #  FIXED-FIXED CROSS-CURRENCY SWAP
    # ==================================================================
    separator("Fixed-Fixed Cross-Currency Swap (EUR/USD, 5Y)")

    ff_xccy = price_fixed_fixed_xccy_swap(
        domestic_notional=eur_notional,
        foreign_notional=usd_notional,
        domestic_fixed_rate=0.0285,   # 2.85 % EUR fixed
        foreign_fixed_rate=0.0355,    # 3.55 % USD fixed
        tenor_years=5,
        domestic_curve=curve_handle,
        foreign_curve=usd_curve,
        spot_fx=spot_fx_eur_per_usd,
        evaluation_date=eval_date,
    )

    print(f"Swap type            : {ff_xccy.swap_type}")
    print(f"EUR notional         : {ff_xccy.domestic_notional:>16,.0f}")
    print(f"USD notional         : {ff_xccy.foreign_notional:>16,.0f}")
    print(f"Spot FX (EUR/USD)    : {eur_usd_spot:.4f}")
    print(f"EUR fixed rate       : 2.85%")
    print(f"USD fixed rate       : 3.55%")
    print(f"EUR leg PV           : {ff_xccy.domestic_leg_pv:>16,.2f} EUR")
    print(f"USD leg PV           : {ff_xccy.foreign_leg_pv:>16,.2f} USD")
    print(f"USD leg PV (in EUR)  : {ff_xccy.foreign_leg_pv_in_domestic:>16,.2f} EUR")
    print(f"NPV (EUR)            : {ff_xccy.npv_domestic:>16,.2f} EUR")
    print(f"{ff_xccy.fair_value_description:<21}: {ff_xccy.fair_value * 100:>14.4f}%")

    # ==================================================================
    #  FIXED-FLOATING CROSS-CURRENCY SWAP
    # ==================================================================
    separator("Fixed-Floating Cross-Currency Swap (EUR/USD, 5Y)")

    # Pay EUR 2.85 % fixed, receive USD LIBOR 3M + 10 bps
    ffl_xccy = price_fixed_floating_xccy_swap(
        domestic_notional=eur_notional,
        foreign_notional=usd_notional,
        domestic_fixed_rate=0.0285,
        foreign_float_spread=0.0010,   # +10 bps over USD LIBOR
        tenor_years=5,
        domestic_curve=curve_handle,
        foreign_curve=usd_curve,
        spot_fx=spot_fx_eur_per_usd,
        evaluation_date=eval_date,
    )

    print(f"Swap type            : {ffl_xccy.swap_type}")
    print(f"EUR fixed rate       : 2.85%")
    print(f"USD float spread     : +10 bps over LIBOR 3M")
    print(f"EUR leg PV           : {ffl_xccy.domestic_leg_pv:>16,.2f} EUR")
    print(f"USD leg PV           : {ffl_xccy.foreign_leg_pv:>16,.2f} USD")
    print(f"USD leg PV (in EUR)  : {ffl_xccy.foreign_leg_pv_in_domestic:>16,.2f} EUR")
    print(f"NPV (EUR)            : {ffl_xccy.npv_domestic:>16,.2f} EUR")
    print(f"{ffl_xccy.fair_value_description:<21}: {ffl_xccy.fair_value * 100:>14.4f}%")

    # ==================================================================
    #  FLOATING-FLOATING CROSS-CURRENCY BASIS SWAP
    # ==================================================================
    separator("Float-Float XCCY Basis Swap (EUR/USD, 5Y)")

    # Pay EUR Euribor 6M + basis, receive USD LIBOR 3M flat
    # The basis is the "price" of EUR vs USD funding.
    basis_bps = -15  # -15 bps is a typical EUR/USD basis
    ffloat_xccy = price_float_float_xccy_swap(
        domestic_notional=eur_notional,
        foreign_notional=usd_notional,
        domestic_float_spread=basis_bps / 10000,  # -15 bps on EUR leg
        foreign_float_spread=0.0,                  # flat on USD leg
        tenor_years=5,
        domestic_curve=curve_handle,
        foreign_curve=usd_curve,
        spot_fx=spot_fx_eur_per_usd,
        evaluation_date=eval_date,
    )

    print(f"Swap type            : {ffloat_xccy.swap_type}")
    print(f"EUR float spread     : {basis_bps:+d} bps over Euribor 6M")
    print(f"USD float spread     : flat (LIBOR 3M)")
    print(f"EUR leg PV           : {ffloat_xccy.domestic_leg_pv:>16,.2f} EUR")
    print(f"USD leg PV           : {ffloat_xccy.foreign_leg_pv:>16,.2f} USD")
    print(f"USD leg PV (in EUR)  : {ffloat_xccy.foreign_leg_pv_in_domestic:>16,.2f} EUR")
    print(f"NPV (EUR)            : {ffloat_xccy.npv_domestic:>16,.2f} EUR")
    print(f"{ffloat_xccy.fair_value_description:<21}: {ffloat_xccy.fair_value * 10000:>14.2f} bps")

    # ------------------------------------------------------------------
    # Generate plots
    # ------------------------------------------------------------------
    separator("Generating Plots")

    p1 = plot_rate_curves(curve_handle, eval_date)
    print(f"  [1] Interest-rate curves  -> {p1}")

    p2 = plot_spreads_vs_price(
        bond, market_dirty_price, results.accrued_interest,
        curve_handle, eval_date,
    )
    print(f"  [2] Spread vs price       -> {p2}")

    p3 = plot_bond_cashflows(bond, curve_handle, eval_date)
    print(f"  [3] Bond cashflow profile -> {p3}")

    print("\nDone.")


if __name__ == "__main__":
    main()
