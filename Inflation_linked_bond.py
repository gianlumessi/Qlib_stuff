"""
===============================================================
  INFLATION-LINKED BOND vs NOMINAL BOND — RATE SENSITIVITIES
===============================================================

This script prices a (real-coupon) inflation-linked bond ("linker")
and an otherwise-identical nominal fixed-rate bond, then compares
their first- and second-order rate sensitivities via bump-and-reprice.

PRICING MODEL (educational, single-currency)
--------------------------------------------
  Nominal ESTR/OIS discount curve  : r_nom(t)  (from OIS zero rates)
  Flat breakeven inflation          : b        (constant)
  Fisher identity (additive approx) : r_real ≈ r_nom - b

  Current published index ratio     : I_now / I_base = CURRENT_CPI / BASE_CPI
  Projected index ratio at t        : (I_now/I_base) * (1 + b)^tau_t

  Linker nominal cashflow at t_i =  real_CF_i * (I_now/I_base) * (1+b)^tau_i
  Linker PV = sum_i [ nominal_CF_i * DF_nom(t_i) ]          (discount on OIS)

  The nominal comparison bond has the SAME maturity, coupon frequency,
  day count and coupon (= the linker's real coupon), priced on the SAME
  OIS curve — it is the pure-rates twin of the linker.

SENSITIVITIES  (bump-and-reprice, +/-1bp central difference, per 100)
---------------------------------------------------------------------
  1. Nominal-rate DV01   : bump OIS curve only (breakeven held).  Both bonds.
  2. Breakeven DV01      : bump flat breakeven only (OIS held).   Linker only;
                           the nominal bond has no breakeven input -> = 0.
  3. Real-rate DV01      : bump OIS curve AND breakeven together (linker) so
                           the nominal discount move and the inflation-
                           projection move combine (see [7] for the exact
                           construction and interpretation).
  4. Convexity           : second-order, from up/down OIS bumps.

For the NOMINAL bond, the analytic yield-based sensitivities
(BondFunctions.basisPointValue / duration(Modified) / convexity) are
also computed and cross-checked against the bump-and-reprice numbers.
The inflation/breakeven and real-rate sensitivities are bump-and-reprice
only, as they are not covered by the standard yield-based BondFunctions.

REQUIREMENTS:  pip install QuantLib
===============================================================
"""

import QuantLib as ql
from bond_pricer import build_fixed_rate_bond

# ==============================================================
# [1]  USER-EDITABLE CONFIGURATION
# ==============================================================
# --- Inflation index levels ---
CURRENT_CPI = 114.0     # <-- current reference CPI (edit me)
BASE_CPI    = 100.0     # index base (bond's reference base CPI)
INDEX_RATIO = CURRENT_CPI / BASE_CPI     # current published index ratio

# --- Flat breakeven inflation assumption ---
BREAKEVEN   = 0.020     # constant breakeven inflation (2.00%)

# --- Bond terms (shared by linker and nominal twin) ---
REAL_COUPON      = 0.015                          # real coupon of the linker
COUPON_FREQUENCY = ql.Semiannual
BOND_MATURITY         = ql.Date(1, ql.February, 2036)
BOND_LAST_COUPON_DATE = ql.Date(1, ql.February, 2026)
FACE             = 100.0
REDEMPTION       = 100.0

# --- Nominal ESTR/OIS zero curve (cont. comp., Act/365F) ---
OIS_TENORS = ["1W", "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y"]
OIS_ZEROS  = [0.01931, 0.023711, 0.02448, 0.02475, 0.025132,
              0.02558, 0.0260515, 0.026589, 0.0271, 0.027626, 0.02814]

BUMP = 1e-4     # 1 basis point

# ==============================================================
# [2]  DATES & CONVENTIONS
# ==============================================================
today    = ql.Date(24, 4, 2026)
calendar = ql.TARGET()
bond_dc  = ql.ActualActual(ql.ActualActual.ISMA)
ois_dc   = ql.Actual365Fixed()
ql.Settings.instance().evaluationDate = today

settle = calendar.advance(today, ql.Period("2D"))

# ==============================================================
# [3]  NOMINAL OIS CURVE (bump-able)
# ==============================================================
def build_ois_curve(parallel_bump=0.0):
    """Build the nominal ESTR/OIS zero curve with an optional parallel bump."""
    pillar_dates = [today] + [calendar.advance(today, ql.Period(t)) for t in OIS_TENORS]
    rates = [OIS_ZEROS[0] + parallel_bump] + [z + parallel_bump for z in OIS_ZEROS]
    curve = ql.ZeroCurve(pillar_dates, rates, ois_dc, calendar,
                         ql.Linear(), ql.Continuous, ql.Annual)
    curve.enableExtrapolation()
    return curve

# ==============================================================
# [4]  COUPON SCHEDULE (shared)
# ==============================================================
schedule = ql.Schedule(
    BOND_LAST_COUPON_DATE, BOND_MATURITY,
    ql.Period(COUPON_FREQUENCY), calendar,
    ql.ModifiedFollowing, ql.ModifiedFollowing,
    ql.DateGeneration.Backward, False,
)
all_dates    = list(schedule)
coupon_dates = [d for d in all_dates[1:] if d > settle]
period_starts = []
for s in all_dates[:-1]:
    end_d = all_dates[all_dates.index(s) + 1]
    if end_d > settle:
        period_starts.append(s)

# ==============================================================
# [5]  PRICING FUNCTIONS
#
#      Both pricers share the signature (nominal_bump, breakeven_bump)
#      so a single bump harness drives every sensitivity.  The nominal
#      bond simply ignores breakeven_bump (it has no inflation leg),
#      which makes its breakeven DV01 identically zero.
# ==============================================================
def price_linker(nominal_bump=0.0, breakeven_bump=0.0):
    """Dirty price per 100 face of the inflation-linked bond.

    Real cashflows are grown by the projected index ratio
        (I_now/I_base) * (1 + b)^tau
    and discounted on the (bumped) nominal OIS curve.
    """
    curve = build_ois_curve(nominal_bump)
    b     = BREAKEVEN + breakeven_bump
    df_settle = curve.discount(settle)

    pv = 0.0
    for s, e in zip(period_starts, coupon_dates):
        alpha  = bond_dc.yearFraction(s, e)
        tau    = ois_dc.yearFraction(settle, e)
        growth = INDEX_RATIO * (1.0 + b) ** tau
        cf     = REAL_COUPON * alpha * FACE * growth
        pv    += cf * curve.discount(e) / df_settle
    tau_T    = ois_dc.yearFraction(settle, BOND_MATURITY)
    growth_T = INDEX_RATIO * (1.0 + b) ** tau_T
    pv += REDEMPTION * growth_T * curve.discount(BOND_MATURITY) / df_settle
    return pv

def build_nominal_bond():
    return build_fixed_rate_bond(
        face_value=FACE,
        issue_date=BOND_LAST_COUPON_DATE,
        maturity_date=BOND_MATURITY,
        coupon_rate=REAL_COUPON,
        coupon_frequency=COUPON_FREQUENCY,
        calendar=calendar,
        day_count=bond_dc,
        convention=ql.ModifiedFollowing,
        settlement_days=2,
        redemption=REDEMPTION,
    )

def price_nominal(nominal_bump=0.0, breakeven_bump=0.0):
    """Dirty price per 100 face of the nominal twin.  breakeven_bump is
    accepted for a uniform bump interface but has NO effect (no inflation
    leg) — that is exactly why its breakeven DV01 is zero by construction."""
    curve  = build_ois_curve(nominal_bump)
    handle = ql.YieldTermStructureHandle(curve)
    bond   = build_nominal_bond()
    bond.setPricingEngine(ql.DiscountingBondEngine(handle))
    return bond.dirtyPrice()

# ==============================================================
# [6]  BUMP-AND-REPRICE HELPERS
# ==============================================================
def dv01(price_fn, d_nom=0.0, d_be=0.0):
    """Central-difference price change for a +1bp move of the chosen factor(s).

    The move is (d_nom, d_be) scaled to +/-1bp; returns the signed price
    change per +1bp (negative for a long bond under a rate rise)."""
    up = price_fn(nominal_bump=+d_nom * BUMP, breakeven_bump=+d_be * BUMP)
    dn = price_fn(nominal_bump=-d_nom * BUMP, breakeven_bump=-d_be * BUMP)
    return (up - dn) / 2.0

def convexity_curve(price_fn):
    """Second-order sensitivity to the nominal curve, from up/down 1bp bumps.
    Reported as the standard dimensionless convexity  P''/P  (per unit^2)."""
    p0 = price_fn()
    up = price_fn(nominal_bump=+BUMP)
    dn = price_fn(nominal_bump=-BUMP)
    second = (up - 2.0 * p0 + dn) / (BUMP ** 2)
    return second / p0

# ==============================================================
# [7]  COMPUTE SENSITIVITIES
# ==============================================================
sep = "=" * 70
print(sep)
print("  INFLATION-LINKED BOND vs NOMINAL BOND — RATE SENSITIVITIES")
print(sep)

linker_px  = price_linker()
nominal_px = price_nominal()

print(f"\n[1]  SETUP")
print(f"  Current CPI / Base CPI:      {CURRENT_CPI:.2f} / {BASE_CPI:.2f}")
print(f"  Current index ratio:         {INDEX_RATIO:.4f}")
print(f"  Flat breakeven inflation:    {BREAKEVEN*100:.2f}%")
print(f"  Real coupon (both bonds):    {REAL_COUPON*100:.2f}%")
print(f"  Maturity:                    {BOND_MATURITY}")
print(f"  Linker dirty price:          {linker_px:.4f}")
print(f"  Nominal-bond dirty price:    {nominal_px:.4f}")

# ---- 1. Nominal-rate DV01: bump OIS only (breakeven held) --------------
lnk_nom_dv01 = dv01(price_linker,  d_nom=1.0)
nom_nom_dv01 = dv01(price_nominal, d_nom=1.0)

# ---- 2. Breakeven DV01: bump breakeven only (OIS held) ----------------
lnk_be_dv01 = dv01(price_linker,  d_be=1.0)   # +1bp breakeven
nom_be_dv01 = dv01(price_nominal, d_be=1.0)   # structurally 0.0

# ---- 3. Real-rate DV01 (linker): bump OIS and breakeven TOGETHER -------
#   Construction:  real = nominal - breakeven  (Fisher, additive).
#   We raise the nominal discount curve and the breakeven by +1bp at the
#   same time.  For the linker this super-imposes two offsetting effects:
#     * the nominal-curve rise lowers PV via steeper discounting, while
#     * the breakeven rise lifts the projected (indexed) cashflows.
#   Because the linker's cashflows are inflation-indexed, the nominal-rate
#   effect is largely NETTED by the inflation-projection effect, leaving a
#   small residual — the part of the move that is a genuine *real*-rate
#   change (a joint nominal+breakeven shift holds the real rate roughly
#   constant, so the linker, a real-rate instrument, barely moves).
#   The nominal bond has no inflation leg, so its "together" bump is just
#   its nominal-rate DV01.
lnk_real_dv01 = dv01(price_linker,  d_nom=1.0, d_be=1.0)
nom_real_dv01 = dv01(price_nominal, d_nom=1.0, d_be=1.0)

# ---- 4. Convexity (second-order, OIS up/down) -------------------------
lnk_cvx = convexity_curve(price_linker)
nom_cvx = convexity_curve(price_nominal)

# ==============================================================
# [8]  ANALYTIC CROSS-CHECK FOR THE NOMINAL BOND (BondFunctions)
# ==============================================================
curve  = build_ois_curve()
handle = ql.YieldTermStructureHandle(curve)
nbond  = build_nominal_bond()
nbond.setPricingEngine(ql.DiscountingBondEngine(handle))

clean = nbond.cleanPrice()
freq  = nbond.frequency()
ytm   = nbond.bondYield(ql.BondPrice(clean, ql.BondPrice.Clean),
                        bond_dc, ql.Compounded, freq)

# BondFunctions analytic (yield-based) sensitivities, per 100 face.
bf_bpv     = ql.BondFunctions.basisPointValue(nbond, ytm, bond_dc, ql.Compounded, freq)
bf_moddur  = ql.BondFunctions.duration(nbond, ytm, bond_dc, ql.Compounded, freq,
                                       ql.Duration.Modified)
bf_convex  = ql.BondFunctions.convexity(nbond, ytm, bond_dc, ql.Compounded, freq)

print(f"\n[2]  NOMINAL BOND — ANALYTIC vs BUMP-AND-REPRICE CROSS-CHECK")
print(f"  Yield to maturity:                 {ytm*100:.4f}%")
print(f"  BondFunctions BPV (per 1bp):       {bf_bpv:+.5f}")
print(f"  Bump-reprice nominal-rate DV01:    {nom_nom_dv01:+.5f}")
print(f"  Difference:                        {abs(bf_bpv - nom_nom_dv01):.2e}")
print(f"  BondFunctions modified duration:   {bf_moddur:.4f}")
print(f"  Implied duration from bump DV01:   {-nom_nom_dv01/nominal_px/BUMP:.4f}")
print(f"  BondFunctions convexity:           {bf_convex:.4f}")
print(f"  Bump-reprice convexity:            {nom_cvx:.4f}")
print(f"  (Small gaps: BondFunctions is yield-based & flat; the bump")
print(f"   shifts the whole term-structure — expected to differ slightly.)")

# ==============================================================
# [9]  COMPARISON TABLE
# ==============================================================
print(f"\n[3]  SENSITIVITY COMPARISON  (per 100 notional, +1bp moves)")
print(f"  {'Sensitivity':<34}{'Linker':>14}{'Nominal bond':>16}")
print(f"  {'-'*64}")
cvx_label = "Convexity (curve, P″/P)"
print(f"  {'Nominal-rate DV01 (OIS bump)':<34}{lnk_nom_dv01:>14.5f}{nom_nom_dv01:>16.5f}")
print(f"  {'Breakeven / inflation DV01':<34}{lnk_be_dv01:>14.5f}{nom_be_dv01:>16.5f}")
print(f"  {'Real-rate DV01 (OIS+BE joint)':<34}{lnk_real_dv01:>14.5f}{nom_real_dv01:>16.5f}")
print(f"  {cvx_label:<34}{lnk_cvx:>14.4f}{nom_cvx:>16.4f}")
print(f"  {'-'*64}")
print(f"  DV01 sign convention: price change for a +1bp rise "
      f"(negative = price falls).")
print(f"  Note: under additive Fisher (real = nominal - breakeven, breakeven")
print(f"  held), the linker's OIS-bump DV01 already IS a real-rate move — the")
print(f"  linker's genuine real-rate risk is large.  The 'OIS+BE joint' column")
print(f"  instead holds the real rate ~constant, so it nets to ~0 for the linker.")

# ==============================================================
# [10]  ONE-LINE SUMMARY
# ==============================================================
print(f"\n[4]  SUMMARY")
print(f"  The linker splits its rate exposure between the discount curve and the")
print(f"  inflation/breakeven leg: a joint nominal+breakeven (constant-real) move")
print(f"  shifts it only {lnk_real_dv01:+.5f}/100 vs the nominal bond's "
      f"{nom_real_dv01:+.5f}/100 —")
print(f"  i.e. the linker's NET nominal-rate DV01 is far lower than the nominal")
print(f"  bond's because part of its exposure sits in the breakeven leg (its raw")
print(f"  OIS DV01 of {lnk_nom_dv01:+.5f} is offset by a breakeven DV01 of "
      f"{lnk_be_dv01:+.5f}).")
print(sep)