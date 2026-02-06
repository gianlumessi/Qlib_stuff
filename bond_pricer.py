"""
Fixed-rate bond pricing using QuantLib.

Constructs a ql.FixedRateBond, attaches a discounting pricing engine,
and exposes clean price, dirty price, yield, duration, and other analytics.
"""

import QuantLib as ql
from dataclasses import dataclass
from typing import Optional


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
