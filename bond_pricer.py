"""
Fixed-rate bond pricing using QuantLib.

Constructs a ql.FixedRateBond, attaches a discounting pricing engine,
and exposes clean price, dirty price, yield, duration, and other analytics.
"""

import QuantLib as ql
from dataclasses import dataclass
from typing import Optional, Union


@dataclass
class BondResults:
    """Container for bond valuation results."""

    clean_price: float
    dirty_price: float
    accrued_interest: float
    ytm: float  # yield-to-maturity (compounded at coupon frequency)
    modified_duration: float
    macaulay_duration: float
    convexity: float
    bpv: float  # DV01 — price change for 1 bp parallel shift


def build_fixed_rate_bond(
    face_value: float,
    issue_date: ql.Date,
    maturity_date: ql.Date,
    coupon_rate: float,
    coupon_frequency: int = ql.Annual,
    calendar: ql.Calendar = ql.TARGET(),
    day_count: ql.DayCounter = ql.Thirty360(ql.Thirty360.BondBasis),
    convention: int = ql.ModifiedFollowing,
    settlement_days: int = 2,
    redemption: float = 100.0,
) -> ql.FixedRateBond:
    """Create a QuantLib FixedRateBond object.

    Parameters
    ----------
    face_value : float
        Notional / face amount (typically 100).
    issue_date : ql.Date
        Bond issue date.
    maturity_date : ql.Date
        Bond maturity date.
    coupon_rate : float
        Annual coupon rate (e.g. 0.04 for 4 %).
    coupon_frequency : int
        Coupon payment frequency (default Annual).
    calendar : ql.Calendar
        Payment calendar.
    day_count : ql.DayCounter
        Day-count convention for coupon accrual.
    convention : int
        Business-day convention.
    settlement_days : int
        Number of business days to settlement (T+2 default).
    redemption : float
        Redemption value at maturity (default 100).

    Returns
    -------
    ql.FixedRateBond
    """
    schedule = ql.Schedule(
        issue_date,
        maturity_date,
        ql.Period(coupon_frequency),
        calendar,
        convention,
        convention,
        ql.DateGeneration.Backward,
        False,  # end-of-month
    )

    bond = ql.FixedRateBond(
        settlement_days,
        face_value,
        schedule,
        [coupon_rate],
        day_count,
        convention,
        redemption,
    )
    return bond


def price_bond(
    bond: ql.FixedRateBond,
    discount_curve: ql.YieldTermStructureHandle,
    evaluation_date: Optional[ql.Date] = None,
) -> BondResults:
    """Price a fixed-rate bond given a discount curve.

    Attaches a DiscountingBondEngine and computes analytics.

    Parameters
    ----------
    bond : ql.FixedRateBond
        The bond to price.
    discount_curve : ql.YieldTermStructureHandle
        The discount / projection curve.
    evaluation_date : ql.Date, optional
        If given, the global evaluation date is set to this value.

    Returns
    -------
    BondResults
    """
    if evaluation_date is not None:
        ql.Settings.instance().evaluationDate = evaluation_date

    engine = ql.DiscountingBondEngine(discount_curve)
    bond.setPricingEngine(engine)

    clean = bond.cleanPrice()
    dirty = bond.dirtyPrice()
    accrued = bond.accruedAmount()

    # Yield-to-maturity (using the bond's own day count and frequency)
    compounding = ql.Compounded
    freq = bond.frequency()
    dc = bond.dayCounter()
    bond_price = ql.BondPrice(clean, ql.BondPrice.Clean)
    ytm = bond.bondYield(bond_price, dc, compounding, freq)

    # Risk measures
    mod_dur = ql.BondFunctions.duration(bond, ytm, dc, compounding, freq, ql.Duration.Modified)
    mac_dur = ql.BondFunctions.duration(bond, ytm, dc, compounding, freq, ql.Duration.Macaulay)
    convexity = ql.BondFunctions.convexity(bond, ytm, dc, compounding, freq)
    bpv = ql.BondFunctions.basisPointValue(bond, ytm, dc, compounding, freq)

    return BondResults(
        clean_price=clean,
        dirty_price=dirty,
        accrued_interest=accrued,
        ytm=ytm,
        modified_duration=mod_dur,
        macaulay_duration=mac_dur,
        convexity=convexity,
        bpv=bpv,
    )


def build_bond_from_settle(
    settle_date: ql.Date,
    coupon_rate: float,
    tenor: Optional[str] = None,
    maturity_date: Optional[ql.Date] = None,
    dated_date: Optional[ql.Date] = None,
    face_value: float = 100.0,
    calendar: ql.Calendar = ql.TARGET(),
    coupon_frequency: int = ql.Annual,
    day_count: ql.DayCounter = ql.Thirty360(ql.Thirty360.BondBasis),
    convention: int = ql.ModifiedFollowing,
    settlement_days: int = 2,
) -> ql.FixedRateBond:
    """Build a FixedRateBond with configurable schedule start and maturity.

    Exactly one of ``tenor`` or ``maturity_date`` must be supplied.

    For **new issues** leave ``dated_date`` unset — the coupon schedule starts
    on ``settle_date`` and accrued interest is zero at inception.

    For **seasoned bonds** set ``dated_date`` to the last coupon payment date
    (= start of the current coupon period).  QuantLib will then correctly
    accrue interest from that date to the settlement date.

    Parameters
    ----------
    settle_date : ql.Date
        Trade settlement date (used as schedule start when ``dated_date``
        is not provided).
    coupon_rate : float
        Annual coupon rate (e.g. 0.0345 for 3.45 %).
    tenor : str, optional
        Bond tenor string, e.g. "10Y".  Used when no exact maturity is known.
    maturity_date : ql.Date, optional
        Exact maturity date.  Takes priority over ``tenor``.
    dated_date : ql.Date, optional
        Start of the coupon schedule (= last coupon date for seasoned bonds).
        Defaults to ``settle_date`` when not provided.
    face_value : float
    calendar : ql.Calendar
    coupon_frequency : int
        Coupon frequency, e.g. ``ql.Annual`` or ``ql.Semiannual``.
    day_count : ql.DayCounter
    convention : int
    settlement_days : int

    Returns
    -------
    ql.FixedRateBond
    """
    if maturity_date is None and tenor is None:
        raise ValueError("Provide either 'maturity_date' or 'tenor'.")
    if maturity_date is None:
        maturity_date = calendar.advance(settle_date, ql.Period(tenor))
    schedule_start = dated_date if dated_date is not None else settle_date
    return build_fixed_rate_bond(
        face_value=face_value,
        issue_date=schedule_start,
        maturity_date=maturity_date,
        coupon_rate=coupon_rate,
        coupon_frequency=coupon_frequency,
        calendar=calendar,
        day_count=day_count,
        convention=convention,
        settlement_days=settlement_days,
    )


def compute_bond_annuity(
    bond: ql.FixedRateBond,
    discount_handle: Union[ql.YieldTermStructureHandle, ql.RelinkableYieldTermStructureHandle],
    day_count: Optional[ql.DayCounter] = None,
) -> tuple:
    """Compute the fixed-leg annuity A = sum(alpha_i * DF(t_i)).

    Parameters
    ----------
    bond : ql.FixedRateBond
    discount_handle : ql.YieldTermStructureHandle
    day_count : ql.DayCounter, optional
        Defaults to the bond's own day count.

    Returns
    -------
    tuple[float, list[tuple]]
        ``(annuity, rows)`` where each row = ``(date, alpha_i, df_i, contrib)``.
    """
    dc = day_count or bond.dayCounter()

    # QuantLib's Python SWIG bindings return all cashflows as the base CashFlow
    # type, making isinstance(cf, ql.FixedRateCoupon) always False.  Filter
    # coupons by excluding the final redemption (which equals the face value).
    face = bond.notional()
    coupon_dates = [cf.date() for cf in bond.cashflows() if cf.amount() < face]

    # Period boundaries: bond start date + consecutive coupon payment dates.
    period_starts = [bond.startDate()] + coupon_dates[:-1]

    annuity = 0.0
    rows = []
    for start, end in zip(period_starts, coupon_dates):
        alpha_i = dc.yearFraction(start, end)
        df_i    = discount_handle.discount(end)
        contrib = alpha_i * df_i
        annuity += contrib
        rows.append((end, alpha_i, df_i, contrib))
    return annuity, rows


def price_bond_from_yield(
    bond: ql.FixedRateBond,
    target_yield: float,
    day_count: Optional[ql.DayCounter] = None,
    compounding: int = ql.Compounded,
    frequency: Optional[int] = None,
) -> float:
    """Return the clean price of a bond for a given yield.

    Parameters
    ----------
    bond : ql.FixedRateBond
        The bond.
    target_yield : float
        Desired yield (e.g. 0.035 for 3.5 %).
    day_count : ql.DayCounter, optional
        Day-count for yield calculation.  Defaults to the bond's day count.
    compounding : int
        Compounding convention (default Compounded).
    frequency : int, optional
        Compounding frequency.  Defaults to the bond's coupon frequency.

    Returns
    -------
    float
        Clean price corresponding to the target yield.
    """
    dc = day_count or bond.dayCounter()
    freq = frequency or bond.frequency()
    return ql.BondFunctions.cleanPrice(bond, target_yield, dc, compounding, freq)
