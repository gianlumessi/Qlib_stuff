"""
Yield curve bootstrapping utilities using QuantLib.

Provides helpers for building discount curves from deposit rates, futures,
and swap rates — the standard inputs for a money-market / swap curve.

Two sample curves are included for educational examples:
  - EUR curve  (Euribor deposits + EUR IRS)
  - USD curve  (USD LIBOR deposits + USD IRS)
"""

import QuantLib as ql
from typing import Optional


def build_zero_curve(
    evaluation_date: ql.Date,
    tenors: list,
    zero_rates: list,
    calendar: ql.Calendar = ql.TARGET(),
    day_count: ql.DayCounter = ql.Actual365Fixed(),
    compounding: int = ql.Continuous,
    frequency: int = ql.Annual,
) -> ql.RelinkableYieldTermStructureHandle:
    """Build a ZeroCurve from tenor strings and zero rates with linear interpolation.

    Parameters
    ----------
    evaluation_date : ql.Date
    tenors : list[str]
        Pillar tenors, e.g. ["1W","1Y","2Y","5Y","10Y"].
    zero_rates : list[float]
        Zero rates for each tenor.  Today's rate is set equal to the first
        pillar rate (flat short-end extrapolation).
    calendar : ql.Calendar
    day_count : ql.DayCounter
    compounding : int
        Rate compounding (default Continuous).
    frequency : int

    Returns
    -------
    ql.RelinkableYieldTermStructureHandle
    """
    ql.Settings.instance().evaluationDate = evaluation_date

    pillar_dates = [evaluation_date] + [
        calendar.advance(evaluation_date, ql.Period(t)) for t in tenors
    ]
    rates = [zero_rates[0]] + list(zero_rates)

    curve = ql.ZeroCurve(
        pillar_dates, rates, day_count, calendar,
        ql.Linear(), compounding, frequency,
    )
    curve.enableExtrapolation()
    return ql.RelinkableYieldTermStructureHandle(curve)


def build_z_spread_curve(
    ois_handle: ql.RelinkableYieldTermStructureHandle,
    z_spread_bps: float,
    compounding: int = ql.Continuous,
    frequency: int = ql.Annual,
) -> tuple:
    """Wrap an OIS curve with a flat z-spread.

    Returns the curve handle and the mutable ``SimpleQuote`` so callers can
    bump the spread without rebuilding the full curve structure.

    Parameters
    ----------
    ois_handle : ql.RelinkableYieldTermStructureHandle
    z_spread_bps : float
        Z-spread in basis points.
    compounding : int
    frequency : int

    Returns
    -------
    tuple[ql.YieldTermStructureHandle, ql.SimpleQuote]
    """
    z_quote = ql.SimpleQuote(z_spread_bps * 1e-4)
    z_curve = ql.ZeroSpreadedTermStructure(
        ois_handle, ql.QuoteHandle(z_quote), compounding, frequency,
    )
    z_curve.enableExtrapolation()
    return ql.YieldTermStructureHandle(z_curve), z_quote


def build_euribor_forwarding_curve(
    evaluation_date: ql.Date,
    tenors: list,
    par_rates: list,
    ois_discount_handle: ql.RelinkableYieldTermStructureHandle,
    calendar: ql.Calendar = ql.TARGET(),
    fixed_frequency: int = ql.Annual,
    fixed_day_count: ql.DayCounter = ql.Thirty360(ql.Thirty360.BondBasis),
) -> ql.RelinkableYieldTermStructureHandle:
    """Bootstrap a EURIBOR 6M forwarding curve using OIS as the discount curve.

    This is the standard dual-curve bootstrap used by Bloomberg for EUR asset
    swaps: the EURIBOR 6M curve is calibrated to par swap rates (YCSW0045),
    but all present values are computed with OIS (ESTR) discount factors.

    The 6M pillar uses a deposit rate helper; all longer tenors use swap rate
    helpers with the OIS curve passed as the exogenous discounting curve.

    Parameters
    ----------
    evaluation_date : ql.Date
    tenors : list[str]
        Pillar tenors, e.g. ["6M","1Y","2Y",...,"10Y"].
    par_rates : list[float]
        Par swap rates for each tenor.
    ois_discount_handle : ql.RelinkableYieldTermStructureHandle
        OIS curve used for discounting during the bootstrap.
    calendar : ql.Calendar
    fixed_frequency : int
        Fixed-leg payment frequency (default Annual, EUR convention).
    fixed_day_count : ql.DayCounter
        Fixed-leg day count (default 30/360 BondBasis, EUR convention).

    Returns
    -------
    ql.RelinkableYieldTermStructureHandle
    """
    ql.Settings.instance().evaluationDate = evaluation_date

    # Euribor6M with no curve attached — used as the float index template
    # during bootstrapping (the curve being built will be linked in later).
    euribor6m_template = ql.Euribor6M()

    helpers = []
    for tenor, rate in zip(tenors, par_rates):
        period = ql.Period(tenor)
        quote  = ql.QuoteHandle(ql.SimpleQuote(rate))

        if period == ql.Period("6M"):
            # Short end: treat as a 6M EURIBOR deposit (Act/360)
            helpers.append(ql.DepositRateHelper(
                quote, period, 2, calendar,
                ql.ModifiedFollowing, False, ql.Actual360(),
            ))
        else:
            # Longer tenors: par swap rate with OIS exogenous discounting
            helpers.append(ql.SwapRateHelper(
                quote,
                period,
                calendar,
                fixed_frequency,
                ql.ModifiedFollowing,
                fixed_day_count,
                euribor6m_template,
                ql.QuoteHandle(),        # no spread on float leg
                ql.Period("0D"),         # spot-starting
                ois_discount_handle,     # OIS discounting
            ))

    curve = ql.PiecewiseLogCubicDiscount(evaluation_date, helpers, ql.Actual365Fixed())
    curve.enableExtrapolation()
    return ql.RelinkableYieldTermStructureHandle(curve)


def build_discount_curve(
    evaluation_date: ql.Date,
    deposit_helpers: Optional[list] = None,
    swap_helpers: Optional[list] = None,
    day_count: ql.DayCounter = ql.Actual365Fixed(),
) -> ql.YieldTermStructureHandle:
    """Bootstrap a piecewise log-cubic discount curve from rate helpers.

    Parameters
    ----------
    evaluation_date : ql.Date
        The curve's reference date (today).
    deposit_helpers : list[ql.RateHelper], optional
        Short-end deposit rate helpers.
    swap_helpers : list[ql.RateHelper], optional
        Swap rate helpers for the long end.
    day_count : ql.DayCounter
        Day-count convention for the curve (default Actual/365 Fixed).

    Returns
    -------
    ql.YieldTermStructureHandle
        A relinkable handle wrapping the bootstrapped curve.
    """
    ql.Settings.instance().evaluationDate = evaluation_date

    helpers = []
    if deposit_helpers:
        helpers.extend(deposit_helpers)
    if swap_helpers:
        helpers.extend(swap_helpers)

    if not helpers:
        raise ValueError("At least one rate helper is required to build a curve.")

    curve = ql.PiecewiseLogCubicDiscount(evaluation_date, helpers, day_count)
    curve.enableExtrapolation()
    return ql.YieldTermStructureHandle(curve)


def make_deposit_helper(
    rate: float,
    tenor: ql.Period,
    calendar: ql.Calendar = ql.TARGET(),
    day_count: ql.DayCounter = ql.Actual360(),
    convention: int = ql.ModifiedFollowing,
) -> ql.DepositRateHelper:
    """Create a deposit rate helper.

    Parameters
    ----------
    rate : float
        The quoted deposit rate (e.g. 0.035 for 3.5 %).
    tenor : ql.Period
        Deposit maturity, e.g. ql.Period(6, ql.Months).
    calendar : ql.Calendar
        Fixing calendar (default TARGET).
    day_count : ql.DayCounter
        Day-count for the deposit (default ACT/360).
    convention : int
        Business-day convention.

    Returns
    -------
    ql.DepositRateHelper
    """
    return ql.DepositRateHelper(
        ql.QuoteHandle(ql.SimpleQuote(rate)),
        tenor,
        2,  # fixing days
        calendar,
        convention,
        False,
        day_count,
    )


def make_swap_helper(
    rate: float,
    tenor: ql.Period,
    calendar: ql.Calendar = ql.TARGET(),
    fixed_frequency: int = ql.Annual,
    fixed_day_count: ql.DayCounter = ql.Thirty360(ql.Thirty360.BondBasis),
    float_index: Optional[ql.IborIndex] = None,
) -> ql.SwapRateHelper:
    """Create a swap rate helper.

    Parameters
    ----------
    rate : float
        The par swap rate (e.g. 0.03 for 3 %).
    tenor : ql.Period
        Swap maturity, e.g. ql.Period(10, ql.Years).
    calendar : ql.Calendar
        Payment calendar.
    fixed_frequency : int
        Coupon frequency on the fixed leg (default Annual).
    fixed_day_count : ql.DayCounter
        Day-count for the fixed leg (default 30/360 Bond Basis).
    float_index : ql.IborIndex, optional
        Floating-rate index.  If None a 6-month Euribor is used.

    Returns
    -------
    ql.SwapRateHelper
    """
    if float_index is None:
        float_index = ql.Euribor6M()

    return ql.SwapRateHelper(
        ql.QuoteHandle(ql.SimpleQuote(rate)),
        tenor,
        calendar,
        fixed_frequency,
        ql.ModifiedFollowing,
        fixed_day_count,
        float_index,
    )


def build_sample_eur_curve(evaluation_date: ql.Date) -> ql.YieldTermStructureHandle:
    """Build a representative EUR discount curve for demo purposes.

    Uses a set of realistic (but illustrative) deposit and swap rates.

    Parameters
    ----------
    evaluation_date : ql.Date
        The valuation date.

    Returns
    -------
    ql.YieldTermStructureHandle
    """
    deposits = [
        make_deposit_helper(0.0380, ql.Period(1, ql.Months)),
        make_deposit_helper(0.0375, ql.Period(3, ql.Months)),
        make_deposit_helper(0.0365, ql.Period(6, ql.Months)),
    ]
    swaps = [
        make_swap_helper(0.0320, ql.Period(1, ql.Years)),
        make_swap_helper(0.0300, ql.Period(2, ql.Years)),
        make_swap_helper(0.0290, ql.Period(3, ql.Years)),
        make_swap_helper(0.0285, ql.Period(5, ql.Years)),
        make_swap_helper(0.0290, ql.Period(7, ql.Years)),
        make_swap_helper(0.0300, ql.Period(10, ql.Years)),
        make_swap_helper(0.0310, ql.Period(15, ql.Years)),
        make_swap_helper(0.0315, ql.Period(20, ql.Years)),
        make_swap_helper(0.0310, ql.Period(30, ql.Years)),
    ]
    return build_discount_curve(evaluation_date, deposits, swaps)


# ---------------------------------------------------------------------------
# USD helpers and sample curve
# ---------------------------------------------------------------------------

def make_usd_deposit_helper(
    rate: float,
    tenor: ql.Period,
    calendar: ql.Calendar = ql.UnitedStates(ql.UnitedStates.FederalReserve),
    day_count: ql.DayCounter = ql.Actual360(),
    convention: int = ql.ModifiedFollowing,
) -> ql.DepositRateHelper:
    """Create a USD deposit rate helper (same mechanics as EUR, different calendar)."""
    return ql.DepositRateHelper(
        ql.QuoteHandle(ql.SimpleQuote(rate)),
        tenor,
        2,  # T+2 settlement
        calendar,
        convention,
        False,
        day_count,
    )


def make_usd_swap_helper(
    rate: float,
    tenor: ql.Period,
    calendar: ql.Calendar = ql.UnitedStates(ql.UnitedStates.FederalReserve),
    fixed_frequency: int = ql.Semiannual,
    fixed_day_count: ql.DayCounter = ql.Thirty360(ql.Thirty360.BondBasis),
    float_index: Optional[ql.IborIndex] = None,
) -> ql.SwapRateHelper:
    """Create a USD swap rate helper.

    USD IRS conventions differ from EUR:
      - Fixed leg pays semiannually (not annually).
      - Floating index is typically USD LIBOR 3M.
    """
    if float_index is None:
        float_index = ql.USDLibor(ql.Period(3, ql.Months))

    return ql.SwapRateHelper(
        ql.QuoteHandle(ql.SimpleQuote(rate)),
        tenor,
        calendar,
        fixed_frequency,
        ql.ModifiedFollowing,
        fixed_day_count,
        float_index,
    )


def build_sample_usd_curve(evaluation_date: ql.Date) -> ql.YieldTermStructureHandle:
    """Build a representative USD discount curve for demo purposes.

    Uses illustrative deposit and swap rates that produce a curve roughly
    50-70 bp above the EUR curve — a stylised representation of the
    EUR/USD rate differential.
    """
    # --- Short end: USD LIBOR deposits ---
    deposits = [
        make_usd_deposit_helper(0.0450, ql.Period(1, ql.Months)),
        make_usd_deposit_helper(0.0440, ql.Period(3, ql.Months)),
        make_usd_deposit_helper(0.0430, ql.Period(6, ql.Months)),
    ]

    # --- Long end: USD IRS (semi-annual fixed vs 3M LIBOR) ---
    swaps = [
        make_usd_swap_helper(0.0400, ql.Period(1, ql.Years)),
        make_usd_swap_helper(0.0380, ql.Period(2, ql.Years)),
        make_usd_swap_helper(0.0365, ql.Period(3, ql.Years)),
        make_usd_swap_helper(0.0355, ql.Period(5, ql.Years)),
        make_usd_swap_helper(0.0360, ql.Period(7, ql.Years)),
        make_usd_swap_helper(0.0370, ql.Period(10, ql.Years)),
        make_usd_swap_helper(0.0380, ql.Period(15, ql.Years)),
        make_usd_swap_helper(0.0385, ql.Period(20, ql.Years)),
        make_usd_swap_helper(0.0380, ql.Period(30, ql.Years)),
    ]
    return build_discount_curve(evaluation_date, deposits, swaps)
