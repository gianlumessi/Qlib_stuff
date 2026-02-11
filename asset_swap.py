"""
Par-par asset swap pricing using QuantLib.

A par-par asset swap is structured so that the bond is exchanged at par
(100) regardless of its market price.  The investor:

  1. Buys the bond at its market dirty price.
  2. Pays/receives an up-front amount equal to (dirty price - 100) to make
     the economics "par-par".
  3. Receives the bond's fixed coupons on one leg.
  4. Pays Libor/Euribor + asset-swap spread (ASW spread) on the floating leg.

The ASW spread is the key output: it represents the credit / liquidity
premium the bond trades at relative to the swap curve.

Two implementations are provided:
  - ``price_par_par_asset_swap``   — uses QuantLib's ``AssetSwap`` class.
  - ``replicate_par_par_asset_swap`` — builds the same result from first
    principles using the bond's cashflows and the swap-curve discount
    factors, so the mechanics are fully transparent.
"""

import QuantLib as ql
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class AssetSwapResults:
    """Container for par-par asset swap results (QuantLib AssetSwap)."""

    asset_swap_spread: float   # in basis points
    fair_spread: float         # decimal
    bond_clean_price: float
    bond_dirty_price: float
    npv: float
    fixed_leg_npv: float
    floating_leg_npv: float


@dataclass
class CashflowDetail:
    """One row in the cashflow-by-cashflow breakdown."""

    date: str
    amount: float
    discount_factor: float
    present_value: float


@dataclass
class FloatingPeriodDetail:
    """One row in the floating-annuity breakdown."""

    start: str
    end: str
    year_fraction: float
    discount_factor: float
    contribution: float


@dataclass
class ReplicatedAssetSwapResults:
    """Container for the manual (replicated) asset swap results."""

    asset_swap_spread: float          # in basis points
    fair_spread: float                # decimal
    bond_pv_at_swap_curve: float      # theoretical dirty price at swap curve
    market_dirty_price: float
    floating_annuity: float           # per-unit-notional annuity factor
    bond_cashflows: list = field(default_factory=list)
    floating_periods: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# 1.  QuantLib AssetSwap approach
# ---------------------------------------------------------------------------

def price_par_par_asset_swap(
    bond: ql.FixedRateBond,
    bond_dirty_price: float,
    discount_curve: ql.YieldTermStructureHandle,
    float_index: Optional[ql.IborIndex] = None,
    evaluation_date: Optional[ql.Date] = None,
) -> AssetSwapResults:
    """Price a par-par asset swap for a fixed-rate bond.

    Parameters
    ----------
    bond : ql.FixedRateBond
        The underlying fixed-rate bond.
    bond_dirty_price : float
        The market *dirty* (full) price of the bond (e.g. 103.45).
        Internally converted to clean price for QuantLib's ``AssetSwap``,
        which expects a clean price.
    discount_curve : ql.YieldTermStructureHandle
        Discount / projection curve for the floating leg.
    float_index : ql.IborIndex, optional
        Floating-rate index (default: 6-month Euribor linked to the
        discount curve).
    evaluation_date : ql.Date, optional
        If provided, the global evaluation date is set.

    Returns
    -------
    AssetSwapResults
    """
    if evaluation_date is not None:
        ql.Settings.instance().evaluationDate = evaluation_date

    if float_index is None:
        float_index = ql.Euribor6M(discount_curve)

    # QuantLib's AssetSwap expects the *clean* price.
    bond_clean_price = bond_dirty_price - bond.accruedAmount()

    asset_swap = ql.AssetSwap(
        True,               # pay fixed (investor receives fixed coupons)
        bond,
        bond_clean_price,
        float_index,
        0.0,                # initial spread — we solve for fair spread
        ql.Schedule(),      # empty schedule → derived from the bond
        float_index.dayCounter(),
        True,               # par asset swap
    )

    engine = ql.DiscountingSwapEngine(discount_curve)
    asset_swap.setPricingEngine(engine)

    fair_spread = asset_swap.fairSpread()
    npv = asset_swap.NPV()

    # Retrieve leg NPVs (leg 0 = fixed, leg 1 = floating)
    fixed_leg_npv = asset_swap.legNPV(0)
    floating_leg_npv = asset_swap.legNPV(1)

    return AssetSwapResults(
        asset_swap_spread=fair_spread * 10_000,
        fair_spread=fair_spread,
        bond_clean_price=bond_clean_price,
        bond_dirty_price=bond_dirty_price,
        npv=npv,
        fixed_leg_npv=fixed_leg_npv,
        floating_leg_npv=floating_leg_npv,
    )


# ---------------------------------------------------------------------------
# 2.  Manual replication from first principles
# ---------------------------------------------------------------------------

def replicate_par_par_asset_swap(
    bond: ql.FixedRateBond,
    bond_dirty_price: float,
    discount_curve: ql.YieldTermStructureHandle,
    float_index: Optional[ql.IborIndex] = None,
    evaluation_date: Optional[ql.Date] = None,
) -> ReplicatedAssetSwapResults:
    """Replicate the par-par ASW spread from first principles.

    Instead of relying on ``ql.AssetSwap``, this function prices the bond
    and the floating leg separately and derives the spread algebraically.

    **Derivation**

    In a par-par asset swap the investor buys the bond at its market dirty
    price and enters a swap where:

    - *Fixed leg*: bond coupons + redemption are passed to the dealer.
    - *Floating leg*: dealer pays LIBOR + *s* on par notional.
    - *Upfront*: dealer pays par (100) to investor; investor pays the dirty
      price.  Net upfront to the investor = ``100 - dirty_price``.

    Setting NPV = 0 from the investor's perspective:

        (100 - dirty) + PV(bond cashflows) = PV(LIBOR-flat FRN) + s * A

    A par LIBOR FRN is worth 100, so PV(LIBOR-flat FRN) = 100 and the
    par terms cancel:

        PV(bond cashflows) - dirty = s * A

    where *A* = floating-leg annuity = ``notional * sum(tau_i * DF_i)``.

    Solving:

        **s = (PV_bond_at_swap_curve - dirty_price) / (face * annuity)**

    Parameters
    ----------
    bond : ql.FixedRateBond
        The underlying fixed-rate bond.
    bond_dirty_price : float
        The market dirty price.
    discount_curve : ql.YieldTermStructureHandle
        Swap / discount curve.
    float_index : ql.IborIndex, optional
        Floating-rate index (default: 6-month Euribor).
    evaluation_date : ql.Date, optional
        Valuation date override.

    Returns
    -------
    ReplicatedAssetSwapResults
        Includes a cashflow-by-cashflow breakdown for transparency.
    """
    if evaluation_date is not None:
        ql.Settings.instance().evaluationDate = evaluation_date

    if float_index is None:
        float_index = ql.Euribor6M(discount_curve)

    settlement = bond.settlementDate()
    maturity = bond.maturityDate()
    face = bond.notional()
    df_settle = discount_curve.discount(settlement)

    # ----- Step 1: PV of remaining bond cashflows at the swap curve --------
    bond_pv_eval = 0.0          # PV as of the evaluation date
    cf_details: list[CashflowDetail] = []

    for i in range(len(bond.cashflows())):
        cf = bond.cashflows()[i]
        if cf.date() <= settlement:
            continue
        df = discount_curve.discount(cf.date())
        pv = cf.amount() * df
        bond_pv_eval += pv
        cf_details.append(CashflowDetail(
            date=str(cf.date()),
            amount=cf.amount(),
            discount_factor=df,
            present_value=pv,
        ))

    # Express at settlement date (consistent with dirty-price convention)
    bond_pv_settle = bond_pv_eval / df_settle

    # ----- Step 2: Floating-leg annuity ------------------------------------
    # Build a 6-month schedule from settlement to bond maturity.
    calendar = ql.TARGET()
    float_schedule = ql.Schedule(
        settlement,
        maturity,
        ql.Period(6, ql.Months),
        calendar,
        ql.ModifiedFollowing,
        ql.ModifiedFollowing,
        ql.DateGeneration.Backward,
        False,
    )

    float_dc = float_index.dayCounter()
    annuity = 0.0               # per-unit-notional
    fp_details: list[FloatingPeriodDetail] = []

    for i in range(1, len(float_schedule)):
        start = float_schedule[i - 1]
        end = float_schedule[i]
        tau = float_dc.yearFraction(start, end)
        df_end = discount_curve.discount(end) / df_settle   # DF from settle
        contrib = tau * df_end
        annuity += contrib
        fp_details.append(FloatingPeriodDetail(
            start=str(start),
            end=str(end),
            year_fraction=tau,
            discount_factor=df_end,
            contribution=contrib,
        ))

    # ----- Step 3: Solve for the spread ------------------------------------
    #   s = (PV_bond_at_settle - dirty_price) / (face * annuity)
    spread = (bond_pv_settle - bond_dirty_price) / (face * annuity)

    return ReplicatedAssetSwapResults(
        asset_swap_spread=spread * 10_000,
        fair_spread=spread,
        bond_pv_at_swap_curve=bond_pv_settle,
        market_dirty_price=bond_dirty_price,
        floating_annuity=annuity,
        bond_cashflows=cf_details,
        floating_periods=fp_details,
    )


# ---------------------------------------------------------------------------
# 3.  Z-spread (for comparison)
# ---------------------------------------------------------------------------

def compute_z_spread(
    bond: ql.FixedRateBond,
    bond_clean_price: float,
    discount_curve: ql.YieldTermStructureHandle,
) -> float:
    """Compute the Z-spread for reference / comparison.

    The Z-spread is the constant spread added to the zero curve that
    reprices the bond to its market price.  It differs from the ASW
    spread because the ASW spread is computed on a swap structure with
    par exchange, while the Z-spread is a pure discounting measure.

    Parameters
    ----------
    bond : ql.FixedRateBond
        The fixed-rate bond.
    bond_clean_price : float
        Market clean price.
    discount_curve : ql.YieldTermStructureHandle
        The reference discount curve.

    Returns
    -------
    float
        Z-spread in basis points.
    """
    dc = bond.dayCounter()
    compounding = ql.Compounded
    freq = bond.frequency()

    bond_price = ql.BondPrice(bond_clean_price, ql.BondPrice.Clean)
    z_spread = ql.BondFunctions.zSpread(
        bond,
        bond_price,
        discount_curve.currentLink(),
        dc,
        compounding,
        freq,
    )
    return z_spread * 10_000  # bps
