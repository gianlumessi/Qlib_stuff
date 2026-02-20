"""
Cross-currency swap pricing using QuantLib.

A cross-currency swap (XCCY swap) exchanges cashflows denominated in two
different currencies.  Unlike a single-currency IRS, XCCY swaps involve
an **exchange of notional** at the start and end of the trade (and sometimes
at intermediate dates).

Three variants are implemented here:

  1. **Fixed-fixed XCCY**: both legs pay a fixed coupon in their respective
     currencies.  Used to lock in a fixed funding cost in a foreign currency.

  2. **Fixed-floating XCCY**: one leg pays a fixed rate, the other pays a
     floating index + spread.  Common when an issuer swaps fixed-rate debt
     in one currency into floating-rate exposure in another.

  3. **Floating-floating XCCY (basis swap)**: both legs pay a floating
     index; one leg includes a spread (the *cross-currency basis*).  This
     is the most liquid interbank XCCY instrument and reveals the market
     price of obtaining funding in one currency vs another.

Pricing approach (manual, from first principles):
  - Each leg is valued in its own currency using its own discount curve.
  - One leg's PV is converted to the other currency using the spot FX rate.
  - The NPV is the difference, from the perspective of one counterparty.
  - The "fair" spread or rate is the value that makes NPV = 0.
"""

import QuantLib as ql
from dataclasses import dataclass, field
from typing import Optional


# =========================================================================
# Result containers
# =========================================================================

@dataclass
class XCCYLegDetail:
    """Cashflow-level detail for one leg of an XCCY swap."""

    currency: str
    dates: list = field(default_factory=list)       # payment date strings
    amounts: list = field(default_factory=list)      # nominal cashflow amounts
    discount_factors: list = field(default_factory=list)
    present_values: list = field(default_factory=list)
    pv_total: float = 0.0


@dataclass
class XCCYSwapResults:
    """Container for cross-currency swap valuation results."""

    swap_type: str              # "Fixed-Fixed", "Fixed-Floating", "Float-Float"
    npv_domestic: float         # NPV in the domestic (first) currency
    npv_foreign: float          # NPV in the foreign (second) currency

    # --- Fair values ---
    fair_value_description: str # what was solved for
    fair_value: float           # the solved quantity (rate or spread)

    # --- Leg PVs in their own currencies ---
    domestic_leg_pv: float
    foreign_leg_pv: float
    foreign_leg_pv_in_domestic: float  # converted at spot FX

    # --- Parameters echoed back ---
    domestic_ccy: str
    foreign_ccy: str
    spot_fx: float              # units of domestic per 1 foreign
    domestic_notional: float
    foreign_notional: float

    # --- Detailed leg breakdowns ---
    domestic_leg_detail: Optional[XCCYLegDetail] = None
    foreign_leg_detail: Optional[XCCYLegDetail] = None


# =========================================================================
# Helper: build a fixed-coupon leg's cashflows
# =========================================================================

def _build_fixed_leg_cashflows(
    notional: float,
    fixed_rate: float,
    effective_date: ql.Date,
    maturity_date: ql.Date,
    frequency: int,
    calendar: ql.Calendar,
    day_count: ql.DayCounter,
    include_notional_exchange: bool = True,
) -> list:
    """Return a list of (date, amount) for a fixed-rate leg.

    Includes notional exchange at start (negative = pay) and end
    (positive = receive) if ``include_notional_exchange`` is True.

    Each coupon amount = notional * rate * day_count_fraction.
    """
    # --- Build the coupon schedule ---
    schedule = ql.Schedule(
        effective_date, maturity_date,
        ql.Period(frequency),
        calendar,
        ql.ModifiedFollowing, ql.ModifiedFollowing,
        ql.DateGeneration.Backward, False,
    )

    cashflows = []

    # Initial notional exchange (pay notional at start)
    if include_notional_exchange:
        cashflows.append((effective_date, -notional))

    # Coupon payments
    for i in range(1, len(schedule)):
        start = schedule[i - 1]
        end = schedule[i]
        # Year fraction for this coupon period
        tau = day_count.yearFraction(start, end)
        coupon = notional * fixed_rate * tau
        cashflows.append((end, coupon))

    # Final notional exchange (receive notional back at maturity)
    if include_notional_exchange:
        cashflows.append((maturity_date, notional))

    return cashflows


# =========================================================================
# Helper: build a floating-rate leg's cashflows (projected forwards)
# =========================================================================

def _build_floating_leg_cashflows(
    notional: float,
    spread: float,
    effective_date: ql.Date,
    maturity_date: ql.Date,
    float_index: ql.IborIndex,
    calendar: ql.Calendar,
    discount_curve: ql.YieldTermStructureHandle,
    include_notional_exchange: bool = True,
) -> list:
    """Return a list of (date, amount) for a floating-rate leg.

    Forward rates are projected from the discount curve.  Each payment is:
        notional * (forward_rate + spread) * day_count_fraction

    This is a single-curve approach (projection = discounting curve).
    """
    tenor = float_index.tenor()   # e.g. 6M for Euribor6M, 3M for USDLibor3M
    dc = float_index.dayCounter()

    # --- Build the floating schedule ---
    schedule = ql.Schedule(
        effective_date, maturity_date,
        tenor,
        calendar,
        ql.ModifiedFollowing, ql.ModifiedFollowing,
        ql.DateGeneration.Backward, False,
    )

    cashflows = []

    # Initial notional exchange
    if include_notional_exchange:
        cashflows.append((effective_date, -notional))

    # Floating payments: project forward rates from the curve
    for i in range(1, len(schedule)):
        start = schedule[i - 1]
        end = schedule[i]
        tau = dc.yearFraction(start, end)

        # Forward rate for the period [start, end]
        # Using the discount curve: F = (DF(start)/DF(end) - 1) / tau
        df_start = discount_curve.discount(start)
        df_end = discount_curve.discount(end)
        fwd_rate = (df_start / df_end - 1.0) / tau

        # Payment = notional * (forward + spread) * tau
        payment = notional * (fwd_rate + spread) * tau
        cashflows.append((end, payment))

    # Final notional exchange
    if include_notional_exchange:
        cashflows.append((maturity_date, notional))

    return cashflows


# =========================================================================
# Helper: PV a list of (date, amount) cashflows
# =========================================================================

def _pv_cashflows(
    cashflows: list,
    discount_curve: ql.YieldTermStructureHandle,
    currency_label: str,
) -> XCCYLegDetail:
    """Discount a list of (ql.Date, amount) cashflows and return a detail object."""
    detail = XCCYLegDetail(currency=currency_label)
    total_pv = 0.0

    for date, amount in cashflows:
        df = discount_curve.discount(date)
        pv = amount * df
        total_pv += pv
        detail.dates.append(str(date))
        detail.amounts.append(amount)
        detail.discount_factors.append(df)
        detail.present_values.append(pv)

    detail.pv_total = total_pv
    return detail


# =========================================================================
# 1.  Fixed-Fixed Cross-Currency Swap
# =========================================================================

def price_fixed_fixed_xccy_swap(
    domestic_notional: float,
    foreign_notional: float,
    domestic_fixed_rate: float,
    foreign_fixed_rate: float,
    tenor_years: int,
    domestic_curve: ql.YieldTermStructureHandle,
    foreign_curve: ql.YieldTermStructureHandle,
    spot_fx: float,
    domestic_ccy: str = "EUR",
    foreign_ccy: str = "USD",
    domestic_frequency: int = ql.Annual,
    foreign_frequency: int = ql.Semiannual,
    domestic_dc: ql.DayCounter = ql.Thirty360(ql.Thirty360.BondBasis),
    foreign_dc: ql.DayCounter = ql.Thirty360(ql.Thirty360.BondBasis),
    domestic_calendar: ql.Calendar = ql.TARGET(),
    foreign_calendar: ql.Calendar = ql.UnitedStates(ql.UnitedStates.FederalReserve),
    evaluation_date: Optional[ql.Date] = None,
) -> XCCYSwapResults:
    """Price a fixed-fixed cross-currency swap.

    The domestic-leg payer pays a fixed rate in the domestic currency and
    receives a fixed rate in the foreign currency.  Notionals are exchanged
    at start and maturity.

    Parameters
    ----------
    domestic_notional : float
        Notional in the domestic currency (e.g. 10_000_000 EUR).
    foreign_notional : float
        Notional in the foreign currency.  Typically set so that
        ``foreign_notional = domestic_notional * spot_fx``.
    domestic_fixed_rate : float
        Fixed rate on the domestic leg (e.g. 0.03 for 3 %).
    foreign_fixed_rate : float
        Fixed rate on the foreign leg (e.g. 0.04 for 4 %).
    tenor_years : int
        Swap maturity in whole years.
    domestic_curve : ql.YieldTermStructureHandle
        Discount curve for the domestic currency.
    foreign_curve : ql.YieldTermStructureHandle
        Discount curve for the foreign currency.
    spot_fx : float
        Spot FX rate expressed as domestic per 1 foreign
        (e.g. 1.10 EUR per 1 USD means spot_fx = 1.10).
    domestic_ccy, foreign_ccy : str
        Currency labels for display.
    domestic_frequency, foreign_frequency : int
        Coupon frequencies.
    domestic_dc, foreign_dc : ql.DayCounter
        Day-count conventions.
    domestic_calendar, foreign_calendar : ql.Calendar
        Payment calendars.
    evaluation_date : ql.Date, optional

    Returns
    -------
    XCCYSwapResults
    """
    if evaluation_date is not None:
        ql.Settings.instance().evaluationDate = evaluation_date
    eval_date = ql.Settings.instance().evaluationDate

    # --- Dates ---
    effective = domestic_calendar.advance(eval_date, ql.Period(2, ql.Days))
    maturity = domestic_calendar.advance(effective, ql.Period(tenor_years, ql.Years))

    # --- Build cashflows for each leg ---
    #
    # Convention: from our perspective, we PAY the domestic leg and
    # RECEIVE the foreign leg.
    #
    # Domestic leg cashflows (we pay): coupons out + notional exchange
    dom_cfs = _build_fixed_leg_cashflows(
        domestic_notional, domestic_fixed_rate,
        effective, maturity, domestic_frequency,
        domestic_calendar, domestic_dc,
    )
    # Foreign leg cashflows (we receive): coupons in + notional exchange
    for_cfs = _build_fixed_leg_cashflows(
        foreign_notional, foreign_fixed_rate,
        effective, maturity, foreign_frequency,
        foreign_calendar, foreign_dc,
    )

    # --- Discount each leg in its own currency ---
    dom_detail = _pv_cashflows(dom_cfs, domestic_curve, domestic_ccy)
    for_detail = _pv_cashflows(for_cfs, foreign_curve, foreign_ccy)

    # --- Convert foreign PV to domestic using spot FX ---
    # spot_fx = domestic per 1 foreign  →  foreign_pv * spot_fx = domestic
    for_pv_in_dom = for_detail.pv_total * spot_fx

    # --- NPV from our perspective: receive foreign − pay domestic ---
    npv_dom = for_pv_in_dom - dom_detail.pv_total
    npv_for = npv_dom / spot_fx  # same NPV expressed in foreign currency

    # --- Fair domestic fixed rate ---
    # Solve: PV_foreign_in_dom = PV_domestic  at fair rate
    # PV_domestic is linear in the domestic fixed rate, so we can
    # recompute with rate = 0 to get the intercept and slope.
    dom_cfs_zero = _build_fixed_leg_cashflows(
        domestic_notional, 0.0,
        effective, maturity, domestic_frequency,
        domestic_calendar, domestic_dc,
    )
    dom_detail_zero = _pv_cashflows(dom_cfs_zero, domestic_curve, domestic_ccy)
    # PV at rate=0 is just the notional exchange PV
    # PV at rate=r is PV_zero + r * annuity (where annuity = d(PV)/d(rate))
    annuity = (dom_detail.pv_total - dom_detail_zero.pv_total) / domestic_fixed_rate
    if abs(annuity) > 1e-10:
        fair_dom_rate = (for_pv_in_dom - dom_detail_zero.pv_total) / annuity
    else:
        fair_dom_rate = 0.0

    return XCCYSwapResults(
        swap_type="Fixed-Fixed",
        npv_domestic=npv_dom,
        npv_foreign=npv_for,
        fair_value_description=f"Fair {domestic_ccy} fixed rate",
        fair_value=fair_dom_rate,
        domestic_leg_pv=dom_detail.pv_total,
        foreign_leg_pv=for_detail.pv_total,
        foreign_leg_pv_in_domestic=for_pv_in_dom,
        domestic_ccy=domestic_ccy,
        foreign_ccy=foreign_ccy,
        spot_fx=spot_fx,
        domestic_notional=domestic_notional,
        foreign_notional=foreign_notional,
        domestic_leg_detail=dom_detail,
        foreign_leg_detail=for_detail,
    )


# =========================================================================
# 2.  Fixed-Floating Cross-Currency Swap
# =========================================================================

def price_fixed_floating_xccy_swap(
    domestic_notional: float,
    foreign_notional: float,
    domestic_fixed_rate: float,
    foreign_float_spread: float,
    tenor_years: int,
    domestic_curve: ql.YieldTermStructureHandle,
    foreign_curve: ql.YieldTermStructureHandle,
    spot_fx: float,
    foreign_float_index: Optional[ql.IborIndex] = None,
    domestic_ccy: str = "EUR",
    foreign_ccy: str = "USD",
    domestic_frequency: int = ql.Annual,
    domestic_dc: ql.DayCounter = ql.Thirty360(ql.Thirty360.BondBasis),
    domestic_calendar: ql.Calendar = ql.TARGET(),
    foreign_calendar: ql.Calendar = ql.UnitedStates(ql.UnitedStates.FederalReserve),
    evaluation_date: Optional[ql.Date] = None,
) -> XCCYSwapResults:
    """Price a fixed-floating cross-currency swap.

    We PAY a domestic fixed rate and RECEIVE foreign floating + spread.

    Parameters
    ----------
    domestic_notional : float
    foreign_notional : float
    domestic_fixed_rate : float
        Fixed coupon on the domestic leg.
    foreign_float_spread : float
        Spread over the foreign floating index (e.g. 0.001 = 10 bps).
    tenor_years : int
    domestic_curve, foreign_curve : ql.YieldTermStructureHandle
    spot_fx : float
    foreign_float_index : ql.IborIndex, optional
        Defaults to USD LIBOR 3M linked to the foreign curve.
    """
    if evaluation_date is not None:
        ql.Settings.instance().evaluationDate = evaluation_date
    eval_date = ql.Settings.instance().evaluationDate

    if foreign_float_index is None:
        foreign_float_index = ql.USDLibor(ql.Period(3, ql.Months), foreign_curve)

    effective = domestic_calendar.advance(eval_date, ql.Period(2, ql.Days))
    maturity = domestic_calendar.advance(effective, ql.Period(tenor_years, ql.Years))

    # --- Domestic leg: fixed coupons ---
    dom_cfs = _build_fixed_leg_cashflows(
        domestic_notional, domestic_fixed_rate,
        effective, maturity, domestic_frequency,
        domestic_calendar, domestic_dc,
    )

    # --- Foreign leg: floating + spread ---
    for_cfs = _build_floating_leg_cashflows(
        foreign_notional, foreign_float_spread,
        effective, maturity,
        foreign_float_index, foreign_calendar,
        foreign_curve,
    )

    # --- PV each leg ---
    dom_detail = _pv_cashflows(dom_cfs, domestic_curve, domestic_ccy)
    for_detail = _pv_cashflows(for_cfs, foreign_curve, foreign_ccy)

    for_pv_in_dom = for_detail.pv_total * spot_fx
    npv_dom = for_pv_in_dom - dom_detail.pv_total
    npv_for = npv_dom / spot_fx

    # --- Fair domestic fixed rate ---
    dom_cfs_zero = _build_fixed_leg_cashflows(
        domestic_notional, 0.0,
        effective, maturity, domestic_frequency,
        domestic_calendar, domestic_dc,
    )
    dom_detail_zero = _pv_cashflows(dom_cfs_zero, domestic_curve, domestic_ccy)
    annuity = (dom_detail.pv_total - dom_detail_zero.pv_total) / domestic_fixed_rate
    if abs(annuity) > 1e-10:
        fair_dom_rate = (for_pv_in_dom - dom_detail_zero.pv_total) / annuity
    else:
        fair_dom_rate = 0.0

    return XCCYSwapResults(
        swap_type="Fixed-Floating",
        npv_domestic=npv_dom,
        npv_foreign=npv_for,
        fair_value_description=f"Fair {domestic_ccy} fixed rate",
        fair_value=fair_dom_rate,
        domestic_leg_pv=dom_detail.pv_total,
        foreign_leg_pv=for_detail.pv_total,
        foreign_leg_pv_in_domestic=for_pv_in_dom,
        domestic_ccy=domestic_ccy,
        foreign_ccy=foreign_ccy,
        spot_fx=spot_fx,
        domestic_notional=domestic_notional,
        foreign_notional=foreign_notional,
        domestic_leg_detail=dom_detail,
        foreign_leg_detail=for_detail,
    )


# =========================================================================
# 3.  Floating-Floating Cross-Currency Swap (Basis Swap)
# =========================================================================

def price_float_float_xccy_swap(
    domestic_notional: float,
    foreign_notional: float,
    domestic_float_spread: float,
    foreign_float_spread: float,
    tenor_years: int,
    domestic_curve: ql.YieldTermStructureHandle,
    foreign_curve: ql.YieldTermStructureHandle,
    spot_fx: float,
    domestic_float_index: Optional[ql.IborIndex] = None,
    foreign_float_index: Optional[ql.IborIndex] = None,
    domestic_ccy: str = "EUR",
    foreign_ccy: str = "USD",
    domestic_calendar: ql.Calendar = ql.TARGET(),
    foreign_calendar: ql.Calendar = ql.UnitedStates(ql.UnitedStates.FederalReserve),
    evaluation_date: Optional[ql.Date] = None,
) -> XCCYSwapResults:
    """Price a floating-floating cross-currency basis swap.

    We PAY domestic floating + spread and RECEIVE foreign floating + spread.

    In the interbank market, the convention is typically:
      - Pay EUR LIBOR + basis spread
      - Receive USD LIBOR flat
    The *basis spread* reveals the relative cost of funding in EUR vs USD.

    Parameters
    ----------
    domestic_notional : float
    foreign_notional : float
    domestic_float_spread : float
        Spread on the domestic floating leg (the "basis", e.g. -0.002 = -20 bps).
    foreign_float_spread : float
        Spread on the foreign floating leg (usually 0 for the reference leg).
    tenor_years : int
    domestic_curve, foreign_curve : ql.YieldTermStructureHandle
    spot_fx : float
    domestic_float_index, foreign_float_index : ql.IborIndex, optional
    """
    if evaluation_date is not None:
        ql.Settings.instance().evaluationDate = evaluation_date
    eval_date = ql.Settings.instance().evaluationDate

    if domestic_float_index is None:
        domestic_float_index = ql.Euribor6M(domestic_curve)
    if foreign_float_index is None:
        foreign_float_index = ql.USDLibor(ql.Period(3, ql.Months), foreign_curve)

    effective = domestic_calendar.advance(eval_date, ql.Period(2, ql.Days))
    maturity = domestic_calendar.advance(effective, ql.Period(tenor_years, ql.Years))

    # --- Domestic leg: floating + spread ---
    dom_cfs = _build_floating_leg_cashflows(
        domestic_notional, domestic_float_spread,
        effective, maturity,
        domestic_float_index, domestic_calendar,
        domestic_curve,
    )

    # --- Foreign leg: floating + spread ---
    for_cfs = _build_floating_leg_cashflows(
        foreign_notional, foreign_float_spread,
        effective, maturity,
        foreign_float_index, foreign_calendar,
        foreign_curve,
    )

    # --- PV each leg ---
    dom_detail = _pv_cashflows(dom_cfs, domestic_curve, domestic_ccy)
    for_detail = _pv_cashflows(for_cfs, foreign_curve, foreign_ccy)

    for_pv_in_dom = for_detail.pv_total * spot_fx
    npv_dom = for_pv_in_dom - dom_detail.pv_total
    npv_for = npv_dom / spot_fx

    # --- Fair domestic basis spread ---
    # Re-price the domestic leg with spread=0 to get the "flat" PV,
    # then solve for the spread that makes NPV = 0.
    dom_cfs_flat = _build_floating_leg_cashflows(
        domestic_notional, 0.0,
        effective, maturity,
        domestic_float_index, domestic_calendar,
        domestic_curve,
    )
    dom_detail_flat = _pv_cashflows(dom_cfs_flat, domestic_curve, domestic_ccy)

    # PV(dom, spread=s) ≈ PV(dom, spread=0) + s * annuity
    # where annuity = notional * sum(tau_i * DF_i) for the floating schedule.
    # We can extract it from the difference:
    if abs(domestic_float_spread) > 1e-12:
        annuity_approx = (dom_detail.pv_total - dom_detail_flat.pv_total) / domestic_float_spread
    else:
        # If spread is zero, compute the annuity directly
        schedule = ql.Schedule(
            effective, maturity, domestic_float_index.tenor(),
            domestic_calendar, ql.ModifiedFollowing, ql.ModifiedFollowing,
            ql.DateGeneration.Backward, False,
        )
        dc = domestic_float_index.dayCounter()
        annuity_approx = 0.0
        for i in range(1, len(schedule)):
            tau = dc.yearFraction(schedule[i-1], schedule[i])
            annuity_approx += domestic_notional * tau * domestic_curve.discount(schedule[i])
        # This is in terms of PV at eval_date, consistent with our leg PVs

    if abs(annuity_approx) > 1e-10:
        fair_basis = (for_pv_in_dom - dom_detail_flat.pv_total) / annuity_approx
    else:
        fair_basis = 0.0

    return XCCYSwapResults(
        swap_type="Floating-Floating (Basis)",
        npv_domestic=npv_dom,
        npv_foreign=npv_for,
        fair_value_description=f"Fair {domestic_ccy} basis spread",
        fair_value=fair_basis,
        domestic_leg_pv=dom_detail.pv_total,
        foreign_leg_pv=for_detail.pv_total,
        foreign_leg_pv_in_domestic=for_pv_in_dom,
        domestic_ccy=domestic_ccy,
        foreign_ccy=foreign_ccy,
        spot_fx=spot_fx,
        domestic_notional=domestic_notional,
        foreign_notional=foreign_notional,
        domestic_leg_detail=dom_detail,
        foreign_leg_detail=for_detail,
    )
