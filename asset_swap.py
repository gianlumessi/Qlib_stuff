"""
Par-par asset swap pricing using QuantLib.

A par-par asset swap is structured so that the bond is exchanged at par
(100) regardless of its market price.  The investor:

  1. Buys the bond at its dirty market price.
  2. Pays/receives an up-front amount equal to (dirty price − 100) to make
     the economics "par-par".
  3. Receives the bond's fixed coupons on one leg.
  4. Pays Libor/Euribor + asset-swap spread (ASW spread) on the floating leg.

The ASW spread is the key output: it represents the credit / liquidity
premium the bond trades at relative to the swap curve.

QuantLib exposes the `AssetSwap` instrument directly, which we use here.
"""

import QuantLib as ql
from dataclasses import dataclass
from typing import Optional


@dataclass
class AssetSwapResults:
    """Container for par-par asset swap results."""

    asset_swap_spread: float   # in basis points
    fair_spread: float         # QuantLib fair-spread (decimal)
    bond_clean_price: float
    bond_dirty_price: float
    npv: float                 # NPV of the swap at the given spread
    fixed_leg_npv: float
    floating_leg_npv: float


def price_par_par_asset_swap(
    bond: ql.FixedRateBond,
    bond_clean_price: float,
    discount_curve: ql.YieldTermStructureHandle,
    float_index: Optional[ql.IborIndex] = None,
    evaluation_date: Optional[ql.Date] = None,
) -> AssetSwapResults:
    """Price a par-par asset swap for a fixed-rate bond.

    Parameters
    ----------
    bond : ql.FixedRateBond
        The underlying fixed-rate bond.
    bond_clean_price : float
        The market clean price of the bond (e.g. 102.50).
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

    # par_asset_swap = True  →  par-par structure
    # spread = 0.0           →  we'll solve for the fair spread
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

    # Bond dirty price (for reporting)
    bond_engine = ql.DiscountingBondEngine(discount_curve)
    bond.setPricingEngine(bond_engine)
    bond_dirty = bond.dirtyPrice()

    return AssetSwapResults(
        asset_swap_spread=fair_spread * 10_000,  # convert to bps
        fair_spread=fair_spread,
        bond_clean_price=bond_clean_price,
        bond_dirty_price=bond_dirty,
        npv=npv,
        fixed_leg_npv=fixed_leg_npv,
        floating_leg_npv=floating_leg_npv,
    )


def asset_swap_spread_from_z_spread(
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
