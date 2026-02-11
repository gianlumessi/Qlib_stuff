"""
Plotting utilities for the bond / asset-swap educational project.

Generates three figures:
  1. Interest-rate curves (discount factors, zero rates, forward rates).
  2. ASW spread and Z-spread as a function of the bond dirty price.
  3. Bond cashflow profile with present-value overlay.

All figures are saved to the ``plots/`` directory.
"""

import os
from typing import Optional

import QuantLib as ql
import matplotlib

matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker


PLOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plots")


def _ensure_plot_dir() -> None:
    os.makedirs(PLOT_DIR, exist_ok=True)


# -----------------------------------------------------------------------
# 1.  Interest-rate curves
# -----------------------------------------------------------------------

def plot_rate_curves(
    curve_handle: ql.YieldTermStructureHandle,
    eval_date: ql.Date,
    max_years: int = 30,
    filename: str = "interest_rate_curves.png",
) -> str:
    """Plot discount factors, zero rates, and 1-year forward rates.

    Parameters
    ----------
    curve_handle : ql.YieldTermStructureHandle
    eval_date : ql.Date
    max_years : int
    filename : str

    Returns
    -------
    str
        Absolute path of the saved figure.
    """
    _ensure_plot_dir()

    calendar = ql.TARGET()
    dc = ql.Actual365Fixed()

    # Sample the curve at monthly intervals
    tenors_months = list(range(1, max_years * 12 + 1))
    years = [m / 12 for m in tenors_months]
    dfs, zeros, fwds = [], [], []

    for m in tenors_months:
        d = calendar.advance(eval_date, ql.Period(m, ql.Months))
        dfs.append(curve_handle.discount(d))
        zeros.append(curve_handle.zeroRate(d, dc, ql.Continuous).rate() * 100)

    # 1-year forward rates (sampled at each month for the 1-year rate
    # starting at that point)
    for m in tenors_months:
        d_start = calendar.advance(eval_date, ql.Period(m, ql.Months))
        d_end = calendar.advance(d_start, ql.Period(1, ql.Years))
        fwd = curve_handle.forwardRate(d_start, d_end, dc, ql.Continuous).rate() * 100
        fwds.append(fwd)

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle("EUR Swap Curve", fontsize=14, fontweight="bold", y=1.02)

    # -- Discount factors --
    ax = axes[0]
    ax.plot(years, dfs, color="#1f77b4", linewidth=1.5)
    ax.set_title("Discount Factors")
    ax.set_xlabel("Maturity (years)")
    ax.set_ylabel("DF")
    ax.set_xlim(0, max_years)
    ax.grid(True, alpha=0.3)

    # -- Zero rates --
    ax = axes[1]
    ax.plot(years, zeros, color="#2ca02c", linewidth=1.5)
    ax.set_title("Zero Rates (cont. comp.)")
    ax.set_xlabel("Maturity (years)")
    ax.set_ylabel("Rate (%)")
    ax.set_xlim(0, max_years)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.grid(True, alpha=0.3)

    # -- Forward rates --
    ax = axes[2]
    ax.plot(years, fwds, color="#d62728", linewidth=1.5)
    ax.set_title("1Y Forward Rates (cont. comp.)")
    ax.set_xlabel("Start (years from now)")
    ax.set_ylabel("Rate (%)")
    ax.set_xlim(0, max_years)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    path = os.path.join(PLOT_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# -----------------------------------------------------------------------
# 2.  ASW spread and Z-spread vs dirty price
# -----------------------------------------------------------------------

def plot_spreads_vs_price(
    bond: ql.FixedRateBond,
    base_dirty_price: float,
    accrued: float,
    discount_curve: ql.YieldTermStructureHandle,
    eval_date: ql.Date,
    price_range: float = 5.0,
    n_points: int = 101,
    filename: str = "spread_vs_price.png",
) -> str:
    """Plot ASW spread and Z-spread as a function of the bond dirty price.

    Parameters
    ----------
    bond : ql.FixedRateBond
    base_dirty_price : float
        Central dirty price around which to vary.
    accrued : float
        Accrued interest (for converting dirty → clean for Z-spread).
    discount_curve : ql.YieldTermStructureHandle
    eval_date : ql.Date
    price_range : float
        Half-width of the price range (+/- from base).
    n_points : int
    filename : str

    Returns
    -------
    str
        Absolute path of the saved figure.
    """
    from asset_swap import price_par_par_asset_swap, compute_z_spread

    _ensure_plot_dir()

    lo = base_dirty_price - price_range
    hi = base_dirty_price + price_range
    step = (hi - lo) / (n_points - 1)

    dirty_prices, asw_spreads, z_spreads = [], [], []

    for i in range(n_points):
        px = lo + i * step
        dirty_prices.append(px)

        a = price_par_par_asset_swap(bond, px, discount_curve, evaluation_date=eval_date)
        asw_spreads.append(a.asset_swap_spread)

        clean_for_z = px - accrued
        z = compute_z_spread(bond, clean_for_z, discount_curve)
        z_spreads.append(z)

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.plot(dirty_prices, asw_spreads, color="#1f77b4", linewidth=1.8, label="ASW Spread")
    ax.plot(dirty_prices, z_spreads, color="#d62728", linewidth=1.8, linestyle="--", label="Z-Spread")

    # Mark the base price
    base_asw = asw_spreads[n_points // 2]
    base_z = z_spreads[n_points // 2]
    ax.axvline(base_dirty_price, color="grey", linewidth=0.8, linestyle=":", alpha=0.6)
    ax.plot(base_dirty_price, base_asw, "o", color="#1f77b4", markersize=7)
    ax.plot(base_dirty_price, base_z, "o", color="#d62728", markersize=7)

    ax.set_title("ASW Spread & Z-Spread vs Bond Dirty Price", fontsize=13, fontweight="bold")
    ax.set_xlabel("Bond Dirty Price")
    ax.set_ylabel("Spread (bps)")
    ax.legend(loc="upper right", fontsize=11)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    path = os.path.join(PLOT_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# -----------------------------------------------------------------------
# 3.  Bond cashflow profile
# -----------------------------------------------------------------------

def plot_bond_cashflows(
    bond: ql.FixedRateBond,
    discount_curve: ql.YieldTermStructureHandle,
    eval_date: ql.Date,
    filename: str = "bond_cashflows.png",
) -> str:
    """Bar chart of remaining bond cashflows with a PV overlay.

    Parameters
    ----------
    bond : ql.FixedRateBond
    discount_curve : ql.YieldTermStructureHandle
    eval_date : ql.Date
    filename : str

    Returns
    -------
    str
        Absolute path of the saved figure.
    """
    _ensure_plot_dir()

    settlement = bond.settlementDate()
    dates, amounts, pvs = [], [], []

    for i in range(len(bond.cashflows())):
        cf = bond.cashflows()[i]
        if cf.date() <= settlement:
            continue
        df = discount_curve.discount(cf.date())
        dates.append(cf.date().serialNumber())
        amounts.append(cf.amount())
        pvs.append(cf.amount() * df)

    # Convert serial dates to readable labels
    labels = []
    for d in dates:
        qd = ql.Date(d)
        labels.append(f"{qd.month()}/{qd.year()}")

    x = range(len(labels))
    width = 0.35

    fig, ax = plt.subplots(figsize=(10, 5))
    bars1 = ax.bar([i - width / 2 for i in x], amounts, width, label="Nominal Cashflow",
                   color="#1f77b4", alpha=0.85)
    bars2 = ax.bar([i + width / 2 for i in x], pvs, width, label="Present Value",
                   color="#ff7f0e", alpha=0.85)

    ax.set_title("Bond Cashflow Profile", fontsize=13, fontweight="bold")
    ax.set_xlabel("Payment Date")
    ax.set_ylabel("Amount")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.legend(fontsize=11)
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    path = os.path.join(PLOT_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path
