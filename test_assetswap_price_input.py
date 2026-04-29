"""
test_assetswap_price_input.py
=====================================================================
Tests what QuantLib's AssetSwap does with the bond price input.

Key question: the constructor takes `bondCleanPrice` — does QuantLib
really treat it as a clean price and add accrued internally?

ANSWER FROM THE C++ SOURCE (ql/instruments/assetswap.cpp, line ~80):

    upfrontDate_ = schedule.startDate();          // = T+2 settle
    Real dirtyPrice = bondCleanPrice_
                    + bond_->accruedAmount(upfrontDate_);   // <-- adds accrued!

    if (parSwap_) {
        Real upfront = (dirtyPrice - 100.0) / 100.0 * notional;
        // upfront cash flow on float leg = (dirty - 100) / 100 * N
    }

So the parameter IS a clean price. QuantLib adds accrued at the
settlement date (= float schedule start) to get dirty, then uses that
dirty price to size the upfront cash flow on the floating leg.

TEST DESIGN:
  Case A — pass the correct clean price              -> reference ASW
  Case B — pass the dirty price labelled as "clean"  -> wrong ASW
  Case C — pass the par value 100 as "clean"         -> shows pure rate effect
  Case D — pass clean-1bp, clean, clean+1bp          -> sensitivity test
=====================================================================
"""

import QuantLib as ql
from curves import build_zero_curve, build_euribor_forwarding_curve

# ── shared market data (same as Asset_swap_simple.py) ──────────────
today    = ql.Date(24, 4, 2026)
calendar = ql.TARGET()
ql.Settings.instance().evaluationDate = today
settle   = calendar.advance(today, ql.Period("2D"))

OIS_TENORS = ["1W","1Y","2Y","3Y","4Y","5Y","6Y","7Y","8Y","9Y","10Y"]
OIS_ZEROS  = [0.01931,0.023711,0.02448,0.02475,0.025132,
              0.02558,0.0260515,0.026589,0.0271,0.027626,0.02814]
EURIBOR_TENORS    = ["6M","1Y","2Y","3Y","4Y","5Y","6Y","7Y","8Y","9Y","10Y"]
EURIBOR_PAR_RATES = [0.02459,0.026612,0.02734,0.027536,0.027805,0.02815,
                     0.02854,0.028989,0.02943,0.029874,0.030316]

ois_handle     = build_zero_curve(today, OIS_TENORS, OIS_ZEROS, calendar)
euribor_handle = build_euribor_forwarding_curve(
    today, EURIBOR_TENORS, EURIBOR_PAR_RATES, ois_handle)

# ── bond ───────────────────────────────────────────────────────────
from bond_pricer import build_bond_from_settle, compute_bond_annuity
bond = build_bond_from_settle(
    settle_date=settle,
    coupon_rate=0.0345,
    maturity_date=ql.Date(1, ql.February, 2036),
    dated_date=ql.Date(1, ql.February, 2026),
    coupon_frequency=ql.Semiannual,
    calendar=calendar,
    day_count=ql.ActualActual(ql.ActualActual.ISMA),
)

# ── pricing engine (OIS discounting) ───────────────────────────────
swap_engine = ql.DiscountingSwapEngine(ois_handle)

# ── ibor index with fixing ──────────────────────────────────────────
ibor_index = ql.Euribor6M(euribor_handle)
fixing_date = ibor_index.fixingDate(settle)
fixing_rate = euribor_handle.forwardRate(
    today, calendar.advance(today, ql.Period("6M")),
    ql.Actual360(), ql.Simple).rate()
if fixing_date <= today:
    ibor_index.addFixing(fixing_date, fixing_rate)

# ── reference prices ───────────────────────────────────────────────
CLEAN_MKT  = 97.632          # Bloomberg clean price
DIRTY_MKT  = 98.4511         # Bloomberg dirty price
ACCRUED    = DIRTY_MKT - CLEAN_MKT   # 0.8191
BBG_ASW    = 72.0            # Bloomberg ASW bps

# Verify QuantLib's own accrued at settle
bond.setPricingEngine(ql.DiscountingBondEngine(ois_handle))
ql_accrued = bond.accruedAmount(settle)

sep = "=" * 72

# ══════════════════════════════════════════════════════════════════
# SECTION 1 — What does the C++ source tell us?
# ══════════════════════════════════════════════════════════════════
print(sep)
print("  C++ SOURCE READING — ql/instruments/assetswap.cpp")
print(sep)
print("""
  Constructor parameter : bondCleanPrice  (clean price)
  Internally computed   : dirtyPrice = bondCleanPrice
                                      + bond->accruedAmount(upfrontDate_)
  upfrontDate_          : float schedule start date (= T+2 settle for spot swap)

  Par-swap upfront CF   : (dirtyPrice - 100) / 100 * notional
  Back-payment CF       : notional  (= 100mm, at maturity)

  fairSpread()          : spread_ - NPV / floatLegBPS * 1bp
                          (with spread_=0 input => -NPV / floatLegBPS * 1bp)

  CONCLUSION: bondCleanPrice IS treated as a clean price.
              QuantLib adds accrued at the settlement date internally.
              Passing dirty price instead of clean will overstate
              the upfront by the accrued amount -> ASW will be wrong.
""")
print(f"  Bloomberg accrued    : {ACCRUED:.4f}%")
print(f"  QuantLib accrued     : {ql_accrued:.4f}%  (at settle={settle})")
print(f"  Difference           : {ql_accrued - ACCRUED:+.4f}%")

# ══════════════════════════════════════════════════════════════════
# SECTION 2 — EMPIRICAL TEST: clean vs dirty as input
# ══════════════════════════════════════════════════════════════════
print(f"\n{sep}")
print("  SECTION 2 — EMPIRICAL: effect of passing clean vs dirty price")
print(sep)

def make_asw(price_input, label):
    """Build AssetSwap with given price input and return fairSpread in bps."""
    asw = ql.AssetSwap(
        False, bond, price_input, ibor_index, 0.0,
        ql.Schedule(), ibor_index.dayCounter(), True,
    )
    asw.setPricingEngine(swap_engine)
    spread_bps = asw.fairSpread() * 1e4
    npv        = asw.NPV()
    return spread_bps, npv

cases = [
    (CLEAN_MKT,              "BBG clean price (correct input)"),
    (DIRTY_MKT,              "BBG dirty price  (WRONG — passed as clean)"),
    (100.0,                  "Par = 100        (zero upfront)"),
    (CLEAN_MKT - ACCRUED,    "clean - accrued  (= hypothetical 'no accrued' bond)"),
]

print(f"\n  {'Price input':>12}  {'Label':<42}  {'ASW (bps)':>10}  {'vs BBG':>8}")
print(f"  {'-'*78}")
for price, label in cases:
    asw_bps, npv = make_asw(price, label)
    diff = asw_bps - BBG_ASW
    print(f"  {price:>12.4f}  {label:<42}  {asw_bps:>10.4f}  {diff:>+8.4f}")

# ══════════════════════════════════════════════════════════════════
# SECTION 3 — SENSITIVITY: ±1bp increments around clean price
# ══════════════════════════════════════════════════════════════════
print(f"\n{sep}")
print("  SECTION 3 — SENSITIVITY: ASW vs small price moves (1 bp = 0.01 pts)")
print(sep)
print(f"\n  {'Clean price':>12}  {'ASW (bps)':>12}  {'DASW/DPrice':>14}")
print(f"  {'-'*44}")
prev_asw = None
for delta in [-0.05, -0.04, -0.03, -0.02, -0.01, 0.00,
               0.01,  0.02,  0.03,  0.04,  0.05]:
    p = CLEAN_MKT + delta
    asw_bps, _ = make_asw(p, "")
    dasw = (asw_bps - prev_asw) if prev_asw is not None else float("nan")
    print(f"  {p:>12.4f}  {asw_bps:>12.4f}  {dasw:>+13.4f} bps/pt")
    prev_asw = asw_bps

# ══════════════════════════════════════════════════════════════════
# SECTION 4 — WHAT HAPPENS WITH DIRTY INPUT: decomposition
# ══════════════════════════════════════════════════════════════════
print(f"\n{sep}")
print("  SECTION 4 — WHY dirty input gives wrong ASW: decomposition")
print(sep)

asw_clean_bps, _ = make_asw(CLEAN_MKT, "")
asw_dirty_bps, _ = make_asw(DIRTY_MKT, "")
error_bps = asw_dirty_bps - asw_clean_bps

# Analytical derivation (all quantities in QuantLib "price units", face=100):
#   extra_upfront on float leg  = ql_accrued  (e.g. 0.806, same scale as clean price)
#   ΔNPV_swap = payer[1] * extra_upfront * DF(settle) = -ql_accrued * DF(settle)
#   floatLegBPS ≈ -annuity * 1e-4 * 100   (notional=100, sign from payer[1]=-1)
#   fairSpread_decimal = -NPV / floatLegBPS * 1e-4
#   => Δfairspread_bps = -(ql_accrued * DF(settle) / 100) / (annuity * 1e-4)
df_settle = ois_handle.discount(settle)
annuity_val, _ = compute_bond_annuity(bond, ois_handle)
expected_error_bps = -(ql_accrued * df_settle / 100.0) / (annuity_val * 1e-4)

print(f"""
  When dirty price is passed instead of clean:
    QuantLib internally adds accrued AGAIN => double-counts accrued.
    Extra upfront on float leg = ql_accrued = {ql_accrued:.6f} (price units).
    This reduces swap NPV => fairSpread decreases.

  QL accrued at settle   : {ql_accrued:.6f}%  (price units, not fraction)
  DF(0, settle)          : {df_settle:.6f}
  Annuity A              : {annuity_val:.6f} yrs
  floatLegBPS approx     : {annuity_val * 1e-4 * 100:.6f}  (= A * 1bp * 100)

  Observed error         : {error_bps:+.4f} bps  (dirty ASW - clean ASW)
  Analytical estimate    : {expected_error_bps:+.4f} bps  (-(accrued/100) / (A * 1e-4))
  Residual               : {error_bps - expected_error_bps:+.4f} bps  (from imprecise annuity approx)
""")

print(sep)
print("  SUMMARY")
print(sep)
print(f"""
  [1] QuantLib's AssetSwap ALWAYS interprets the price input as a CLEAN price.
      It adds bond->accruedAmount(settleDate) internally to get dirty price.

  [2] Passing the dirty price as if it were clean double-counts accrued:
      Error = {error_bps:+.2f} bps for this bond (accrued = {ql_accrued:.4f}%).

  [3] The correct input is always the CLEAN price (or forward clean price
      at the swap start date, per the C++ comment in the source).

  [4] Bloomberg ASW = {BBG_ASW:.1f} bps vs QuantLib (clean input) = {asw_clean_bps:.4f} bps
      Difference = {asw_clean_bps - BBG_ASW:+.4f} bps.
""")
print(sep)
