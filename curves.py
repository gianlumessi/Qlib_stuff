"""
Yield curve bootstrapping utilities using QuantLib.

Provides helpers for building discount curves from deposit rates, futures,
and swap rates — the standard inputs for a money-market / swap curve.
"""

import QuantLib as ql
from typing import Optional


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
