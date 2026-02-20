"""
Interest Rate Swap (IRS) pricing using QuantLib.

An IRS exchanges a stream of fixed-rate payments for floating-rate payments
(or vice versa) on the same currency and notional.  There is no exchange of
principal — only the net interest difference changes hands on each payment
date.

Key concepts:
  - **Payer swap**: the party *pays* fixed and *receives* floating.
  - **Receiver swap**: the party *receives* fixed and *pays* floating.
  - **Par (fair) rate**: the fixed rate at which the swap has zero NPV.
  - **DV01 / BPV**: sensitivity of the swap NPV to a 1 bp parallel shift.

This module wraps QuantLib's ``VanillaSwap`` and ``DiscountingSwapEngine``.
"""

import QuantLib as ql
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class IRSResults:
    """Container for interest-rate swap valuation results."""

    # --- Headline numbers ---
    npv: float                  # net present value from the payer's perspective
    fair_rate: float            # par fixed rate (decimal, e.g. 0.03 = 3 %)
    fair_spread: float          # spread over LIBOR that zeroes the swap

    # --- Leg-level detail ---
    fixed_leg_npv: float
    floating_leg_npv: float
    fixed_leg_bps: float        # PV01 of the fixed leg
    floating_leg_bps: float     # PV01 of the floating leg

    # --- Trade parameters (echoed back for clarity) ---
    notional: float
    fixed_rate: float
    maturity_years: int
    swap_type: str              # "Payer" or "Receiver"


# ---------------------------------------------------------------------------
# IRS builder
# ---------------------------------------------------------------------------

def build_vanilla_swap(
    notional: float,
    fixed_rate: float,
    tenor_years: int,
    discount_curve: ql.YieldTermStructureHandle,
    float_index: Optional[ql.IborIndex] = None,
    swap_type: int = ql.VanillaSwap.Payer,
    fixed_frequency: int = ql.Annual,
    fixed_day_count: ql.DayCounter = ql.Thirty360(ql.Thirty360.BondBasis),
    float_spread: float = 0.0,
    calendar: ql.Calendar = ql.TARGET(),
    evaluation_date: Optional[ql.Date] = None,
) -> ql.VanillaSwap:
    """Construct a plain-vanilla IRS.

    Parameters
    ----------
    notional : float
        Swap notional amount (e.g. 10_000_000).
    fixed_rate : float
        Fixed coupon rate (e.g. 0.03 for 3 %).
    tenor_years : int
        Swap maturity in whole years.
    discount_curve : ql.YieldTermStructureHandle
        Curve used for both discounting and projection (single-curve setup).
    float_index : ql.IborIndex, optional
        Floating-rate index.  Defaults to Euribor 6M linked to the curve.
    swap_type : int
        ``ql.VanillaSwap.Payer`` (pay fixed) or ``ql.VanillaSwap.Receiver``
        (receive fixed).
    fixed_frequency : int
        Payment frequency on the fixed leg (default Annual).
    fixed_day_count : ql.DayCounter
        Day count for the fixed leg (default 30/360).
    float_spread : float
        Spread over the floating index (default 0).
    calendar : ql.Calendar
        Payment calendar (default TARGET).
    evaluation_date : ql.Date, optional
        If given, the global evaluation date is set.

    Returns
    -------
    ql.VanillaSwap
    """
    if evaluation_date is not None:
        ql.Settings.instance().evaluationDate = evaluation_date

    eval_date = ql.Settings.instance().evaluationDate

    # --- Floating index (needs to be linked to the curve for projections) ---
    if float_index is None:
        float_index = ql.Euribor6M(discount_curve)

    # --- Effective and maturity dates ---
    # Standard T+2 settlement
    effective_date = calendar.advance(eval_date, ql.Period(2, ql.Days))
    maturity_date = calendar.advance(effective_date, ql.Period(tenor_years, ql.Years))

    # --- Fixed-leg schedule ---
    fixed_schedule = ql.Schedule(
        effective_date,
        maturity_date,
        ql.Period(fixed_frequency),   # e.g. Annual → 1Y
        calendar,
        ql.ModifiedFollowing,
        ql.ModifiedFollowing,
        ql.DateGeneration.Backward,
        False,
    )

    # --- Floating-leg schedule (tenor derived from the index, e.g. 6M) ---
    float_schedule = ql.Schedule(
        effective_date,
        maturity_date,
        float_index.tenor(),          # e.g. 6 Months for Euribor6M
        calendar,
        ql.ModifiedFollowing,
        ql.ModifiedFollowing,
        ql.DateGeneration.Backward,
        False,
    )

    # --- Build the VanillaSwap ---
    swap = ql.VanillaSwap(
        swap_type,
        notional,
        fixed_schedule,
        fixed_rate,
        fixed_day_count,
        float_schedule,
        float_index,
        float_spread,
        float_index.dayCounter(),     # ACT/360 for Euribor
    )

    return swap


# ---------------------------------------------------------------------------
# IRS pricer
# ---------------------------------------------------------------------------

def price_irs(
    notional: float,
    fixed_rate: float,
    tenor_years: int,
    discount_curve: ql.YieldTermStructureHandle,
    float_index: Optional[ql.IborIndex] = None,
    swap_type: int = ql.VanillaSwap.Payer,
    fixed_frequency: int = ql.Annual,
    fixed_day_count: ql.DayCounter = ql.Thirty360(ql.Thirty360.BondBasis),
    float_spread: float = 0.0,
    calendar: ql.Calendar = ql.TARGET(),
    evaluation_date: Optional[ql.Date] = None,
) -> IRSResults:
    """Price a plain-vanilla interest rate swap.

    Builds a ``VanillaSwap``, attaches a ``DiscountingSwapEngine``, and
    extracts valuation results.

    Parameters
    ----------
    (same as ``build_vanilla_swap`` — see above)

    Returns
    -------
    IRSResults
    """
    # --- Build the swap ---
    swap = build_vanilla_swap(
        notional=notional,
        fixed_rate=fixed_rate,
        tenor_years=tenor_years,
        discount_curve=discount_curve,
        float_index=float_index,
        swap_type=swap_type,
        fixed_frequency=fixed_frequency,
        fixed_day_count=fixed_day_count,
        float_spread=float_spread,
        calendar=calendar,
        evaluation_date=evaluation_date,
    )

    # --- Attach the pricing engine ---
    engine = ql.DiscountingSwapEngine(discount_curve)
    swap.setPricingEngine(engine)

    # --- Extract results ---
    npv = swap.NPV()
    fair_rate = swap.fairRate()       # fixed rate that makes NPV = 0
    fair_spread = swap.fairSpread()   # floating spread that makes NPV = 0

    fixed_leg_npv = swap.legNPV(0)    # leg 0 = fixed
    floating_leg_npv = swap.legNPV(1) # leg 1 = floating
    fixed_leg_bps = swap.legBPS(0)    # PV of 1 bp on the fixed leg
    floating_leg_bps = swap.legBPS(1) # PV of 1 bp on the floating leg

    return IRSResults(
        npv=npv,
        fair_rate=fair_rate,
        fair_spread=fair_spread,
        fixed_leg_npv=fixed_leg_npv,
        floating_leg_npv=floating_leg_npv,
        fixed_leg_bps=fixed_leg_bps,
        floating_leg_bps=floating_leg_bps,
        notional=notional,
        fixed_rate=fixed_rate,
        maturity_years=tenor_years,
        swap_type="Payer" if swap_type == ql.VanillaSwap.Payer else "Receiver",
    )
