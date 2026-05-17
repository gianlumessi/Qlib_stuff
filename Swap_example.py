"""
===============================================================
  5-YEAR OIS SWAP PRICING — QuantLib
===============================================================

STRUCTURE:
  - 5-year receiver OIS swap (bank receives fixed, pays ESTR)
  - Fixed rate = par swap rate (so NPV = 0 at inception)
  - Then bump the 1Y zero rate down by 1 bp and re-value

STEPS:
  1. Build the OIS zero curve from given pillar rates
  2. Compute the 5Y par swap rate: r_s = (1 - DF(5Y)) / A
  3. Price the swap at par rate → NPV should be 0
  4. Bump the 1Y rate down 1 bp, rebuild curve, reprice
  5. Print the results

REQUIREMENTS:
  pip install QuantLib
===============================================================
"""

import QuantLib as ql

# ==============================================================
# [1]  OIS CURVE DATA
# ==============================================================
# OIS zero curve  (continuously compounded, Act/365 Fixed).
# BBG Code of ESTR Swap curve: EESWE1.
OIS_TENORS = ["1W", "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y"]
OIS_ZEROS  = [0.01931, 0.023711, 0.02448, 0.02475, 0.025132,
              0.02558, 0.0260515, 0.026589, 0.0271, 0.027626, 0.02814]

# ==============================================================
# [2]  DATES & CONVENTIONS
# ==============================================================
today    = ql.Date(24, 4, 2026)
calendar = ql.TARGET()
ql.Settings.instance().evaluationDate = today

settle = calendar.advance(today, ql.Period("2D"))   # T+2 settlement
maturity = calendar.advance(settle, ql.Period("5Y"))

# Swap conventions (EUR OIS standard)
fixed_dc       = ql.Actual360()     # OIS fixed leg: Act/360
fixed_freq     = ql.Annual          # annual fixed payments
float_freq     = ql.Annual          # OIS float leg: annual compounded
ois_dc         = ql.Actual365Fixed() # curve day count

# ==============================================================
# [3]  BUILD OIS CURVE
# ==============================================================
def build_ois_curve(tenors, zeros):
    """Build a ZeroCurve from tenor strings and continuously compounded zero rates."""
    pillar_dates = [today] + [calendar.advance(today, ql.Period(t)) for t in tenors]
    rates = [zeros[0]] + list(zeros)
    curve = ql.ZeroCurve(
        pillar_dates, rates, ois_dc, calendar,
        ql.Linear(), ql.Continuous, ql.Annual,
    )
    curve.enableExtrapolation()
    return curve

ois_curve  = build_ois_curve(OIS_TENORS, OIS_ZEROS)
ois_handle = ql.YieldTermStructureHandle(ois_curve)

# ==============================================================
# [4]  COMPUTE PAR SWAP RATE FROM DISCOUNT FACTORS
#
#      For an OIS swap with annual fixed payments:
#        r_s = (1 - DF(T)) / A
#      where A = Σ alpha_i * DF(t_i)  (annuity of the fixed leg)
#
#      This is the fixed rate that makes the swap NPV = 0.
# ==============================================================
# Build the fixed leg schedule
fixed_schedule = ql.Schedule(
    settle, maturity,
    ql.Period(fixed_freq),
    calendar,
    ql.ModifiedFollowing,
    ql.ModifiedFollowing,
    ql.DateGeneration.Backward,
    False,
)

# Compute annuity from the schedule
schedule_dates = list(fixed_schedule)
annuity = 0.0
print_rows = []

for i in range(1, len(schedule_dates)):
    t_prev = schedule_dates[i - 1]
    t_i    = schedule_dates[i]
    alpha_i = fixed_dc.yearFraction(t_prev, t_i)
    df_i    = ois_curve.discount(t_i)
    contrib = alpha_i * df_i
    annuity += contrib
    print_rows.append((t_i, alpha_i, df_i, contrib))

df_T = ois_curve.discount(maturity)
par_swap_rate = (1.0 - df_T) / annuity

# ==============================================================
# [5]  BUILD & PRICE THE 5Y OIS SWAP AT PAR RATE
#
#      Using ql.MakeOIS to construct the swap with proper
#      conventions.  First query the fair rate, then rebuild
#      with that rate so NPV = 0 exactly.
# ==============================================================
NOTIONAL = 10e6   # 10mm notional

estr_index = ql.Eonia(ois_handle)   # ESTR proxy (same overnight mechanics)

# Build swap at our analytically-derived par rate first to get QL's fair rate
swap_engine = ql.DiscountingSwapEngine(ois_handle)

ois_swap_temp = ql.MakeOIS(
    ql.Period("5Y"), estr_index, par_swap_rate,
    nominal=NOTIONAL, swapType=ql.OvernightIndexedSwap.Receiver,
    pricingEngine=swap_engine,
)
fair_rate_ql = ois_swap_temp.fairRate()

# Rebuild the swap at QuantLib's fair rate so NPV = 0 exactly
ois_swap = ql.MakeOIS(
    ql.Period("5Y"), estr_index, fair_rate_ql,
    nominal=NOTIONAL, swapType=ql.OvernightIndexedSwap.Receiver,
    pricingEngine=swap_engine,
)

npv_base       = ois_swap.NPV()
fixed_leg_npv  = ois_swap.legNPV(0)
float_leg_npv  = ois_swap.legNPV(1)

# ==============================================================
# [6]  BUMP 1Y RATE DOWN BY 1 BP AND REPRICE
#
#      Shift the 1Y zero rate from 2.3711% to 2.3611%
#      (i.e. -1 bp = -0.0001).  Rebuild the curve and reprice.
#      This gives a sense of the swap's sensitivity to the 1Y point.
# ==============================================================
OIS_ZEROS_BUMPED = list(OIS_ZEROS)
OIS_ZEROS_BUMPED[1] -= 0.0001   # 1Y rate down 1 bp

ois_curve_bumped  = build_ois_curve(OIS_TENORS, OIS_ZEROS_BUMPED)
ois_handle_bumped = ql.YieldTermStructureHandle(ois_curve_bumped)

estr_index_bumped = ql.Eonia(ois_handle_bumped)

# Rebuild swap with same fixed rate (fair_rate_ql) but on the bumped curve
swap_engine_bumped = ql.DiscountingSwapEngine(ois_handle_bumped)

ois_swap_bumped = ql.MakeOIS(
    ql.Period("5Y"), estr_index_bumped, fair_rate_ql,
    nominal=NOTIONAL, swapType=ql.OvernightIndexedSwap.Receiver,
    pricingEngine=swap_engine_bumped,
)

npv_bumped      = ois_swap_bumped.NPV()
fair_rate_bumped = ois_swap_bumped.fairRate()

# Change in NPV for -1 bp move in 1Y rate
delta_npv = npv_bumped - npv_base

# ==============================================================
# [7]  OUTPUT
# ==============================================================
sep = "=" * 62

print(sep)
print("  5-YEAR OIS SWAP — ESTR")
print(sep)

print(f"\n[1]  OIS CURVE  (continuously compounded, Act/365)")
print(f"  {'Tenor':<8}  {'Zero Rate':>10}  {'Bumped':>10}")
print(f"  {'-'*32}")
for t, r, rb in zip(OIS_TENORS, OIS_ZEROS, OIS_ZEROS_BUMPED):
    flag = "  <-- -1bp" if r != rb else ""
    print(f"  {t:<8}  {r*100:>9.4f}%  {rb*100:>9.4f}%{flag}")

print(f"\n[2]  SWAP PARAMETERS")
print(f"  Settlement:         {settle}")
print(f"  Maturity:           {maturity}")
print(f"  Notional:           ${NOTIONAL/1e6:.0f}mm")
print(f"  Direction:          Bank receives fixed")
print(f"  Fixed day count:    Act/360")
print(f"  Fixed frequency:    Annual")

print(f"\n[3]  ANNUITY & PAR SWAP RATE")
print(f"  {'Payment Date':<16}  {'alpha_i':>8}  {'DF(0,ti)':>10}  {'alpha*DF':>10}")
print(f"  {'-'*48}")
for d, a, df, contrib in print_rows:
    print(f"  {str(d):<16}  {a:>8.6f}  {df:>10.6f}  {contrib:>10.6f}")
print(f"  {'Annuity A':<16}  {'':>8}  {'':>10}  {annuity:>10.6f}")
print(f"\n  DF(0, 5Y):          {df_T:.6f}")
print(f"  Par swap rate:      {par_swap_rate*100:.4f}%  = (1 - DF(T)) / A")
print(f"  QuantLib fair rate: {fair_rate_ql*100:.4f}%")

print(f"\n[4]  SWAP VALUATION AT PAR RATE  (should be ~0)")
print(f"  Fixed leg NPV:      ${fixed_leg_npv:>14,.2f}")
print(f"  Float leg NPV:      ${float_leg_npv:>14,.2f}")
print(f"  Swap NPV:           ${npv_base:>14,.2f}  <- should be ~0")

print(f"\n[5]  AFTER 1Y RATE BUMPED DOWN 1 BP")
print(f"  New 1Y rate:        {OIS_ZEROS_BUMPED[1]*100:.4f}%  (was {OIS_ZEROS[1]*100:.4f}%)")
print(f"  New fair rate:      {fair_rate_bumped*100:.4f}%  (was {fair_rate_ql*100:.4f}%)")
print(f"  Swap NPV (bumped):  ${npv_bumped:>14,.2f}")
print(f"  Delta NPV:          ${delta_npv:>14,.2f}  (= bumped - base)")
print(f"  DV01 (1Y point):    ${abs(delta_npv):>14,.2f}  per 1 bp")

print(f"\n{sep}")
