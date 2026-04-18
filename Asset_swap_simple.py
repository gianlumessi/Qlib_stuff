"""
===============================================================
  PAR ASSET SWAP PRICING — QUANTLIB IMPLEMENTATION
  Priced from Citigroup's perspective
===============================================================

STRUCTURE:
  - Client pays par (N = 100mm) to Citigroup
  - Citigroup buys bond at dirty price P in the market
  - Citigroup pockets upfront: (N - P)
  - Interest rate swap leg:
      Citi RECEIVES: bond coupons + bond redemption N at maturity
      Citi PAYS    : floating (ESTR flat) + ASW spread + notional N at maturity

PRICING CONDITION  (NPV = 0 from Citi's view):
  (N - P) + B* - N - ASW * N * A = 0

  Solving for ASW:
      ASW = (c - r_s) + (N - P) / (N * A)

  where:
    P    = bond dirty price (discounted at OIS + z-spread)
    B*   = bond cash flows discounted at pure OIS (no z-spread)
    A    = annuity = Σ_i [ alpha_i * DF(0, t_i) ]
    r_s  = par swap rate (same coupon schedule)
    c    = bond coupon rate
    N    = par notional (= 100)

REQUIREMENTS:
  pip install QuantLib
===============================================================
"""

import QuantLib as ql

# ==============================================================
# [1]  USER CONFIGURATION  — edit these two lines
# ==============================================================
COUPON_RATE  = 0.030   # Bond annual coupon rate  (e.g. 0.030 = 3.0%)
Z_SPREAD_BPS = 100     # Z-spread over OIS in basis points (e.g. 100 bps)

# Derived constants — do not edit below
Z_SPREAD  = Z_SPREAD_BPS * 1e-4
NOTIONAL  = 100e6       # 100mm par notional
N_PCT     = 100.0       # par expressed as % of notional

# ==============================================================
# [2]  DATES & CONVENTIONS
# ==============================================================
today    = ql.Date(22, 3, 2026)
ql.Settings.instance().evaluationDate = today

calendar = ql.TARGET()
settle   = calendar.advance(today, ql.Period("2D"))   # T+2 settlement
maturity = calendar.advance(settle, ql.Period("10Y")) # 10Y from settlement

bond_dc  = ql.Thirty360(ql.Thirty360.BondBasis)       # bond day count: 30/360
ois_dc   = ql.Actual365Fixed()                        # OIS curve day count: Act/365

# ==============================================================
# [3]  OIS RISK-FREE CURVE CONSTRUCTION
#
#  Given rates (treated as continuously-compounded zero rates):
#    1W: 0.20%,  1Y: 0.50%,  2Y: 1.00%,  3Y: 1.50%,  4Y: 2.00%
#    5Y: 2.50%,  6Y: 3.00%,  7Y: 3.30%,  8Y: 3.60%,  9Y: 3.90%, 10Y: 4.20%
#
#  In production you would bootstrap this from live OIS swap quotes.
#  Here we use ZeroCurve with linear interpolation for clarity.
# ==============================================================
ois_tenors = ["1W","1Y","2Y","3Y","4Y","5Y","6Y","7Y","8Y","9Y","10Y"]
ois_zeros  = [0.002, 0.005, 0.010, 0.015, 0.020,
              0.025, 0.030, 0.033, 0.036, 0.039, 0.042]

# Build list of pillar dates; prepend today so the curve has a reference date
ois_dates = [today] + [calendar.advance(today, ql.Period(t)) for t in ois_tenors]
ois_zero_rates = [ois_zeros[0]] + ois_zeros   # today rate = 1W rate (short end flat)

# ZeroCurve: first date = reference date, rates are continuously compounded
ois_curve = ql.ZeroCurve(
    ois_dates, ois_zero_rates, ois_dc, calendar,
    ql.Linear(), ql.Continuous, ql.Annual
)
ois_curve.enableExtrapolation()
ois_handle = ql.RelinkableYieldTermStructureHandle(ois_curve)

# ==============================================================
# [4]  BOND CONSTRUCTION
#      Annual fixed coupon, 30/360 BondBasis, Backward stub
# ==============================================================
fixed_schedule = ql.Schedule(
    settle, maturity,
    ql.Period(ql.Annual),
    calendar,
    ql.ModifiedFollowing,
    ql.ModifiedFollowing,
    ql.DateGeneration.Backward,
    False   # no end-of-month convention
)

bond = ql.FixedRateBond(
    2,              # settlement days
    NOTIONAL,
    fixed_schedule,
    [COUPON_RATE],
    bond_dc
)

# ==============================================================
# [5]  PRICE BOND AT OIS + Z-SPREAD  →  dirty price P
#
#  Z-spread = constant parallel shift applied to OIS zero rates.
#  This represents the bond's credit/liquidity premium over the
#  risk-free curve.  A higher z-spread → lower price → discount bond.
# ==============================================================
z_quote  = ql.SimpleQuote(Z_SPREAD)
z_handle = ql.QuoteHandle(z_quote)

# ZeroSpreadedTermStructure: adds flat spread z to OIS curve at each tenor
z_curve  = ql.ZeroSpreadedTermStructure(ois_handle, z_handle, ql.Continuous, ql.Annual)
z_curve.enableExtrapolation()
z_handle_ts = ql.YieldTermStructureHandle(z_curve)

# Set pricing engine to OIS + z-spread → this gives us the bond dirty price P
bond.setPricingEngine(ql.DiscountingBondEngine(z_handle_ts))

P_pct       = bond.dirtyPrice()      # dirty price as % of notional
clean_pct   = bond.cleanPrice()
accrued_pct = bond.accruedAmount() / NOTIONAL * 100.0

# YTM: yield consistent with dirty price P
# Newer QuantLib versions require a BondPrice object instead of a raw float.
# We wrap the clean price in ql.BondPrice(cleanPrice, ql.BondPrice.Clean).
ytm = bond.bondYield(ql.BondPrice(clean_pct, ql.BondPrice.Clean), bond_dc, ql.Compounded, ql.Annual)

# ==============================================================
# [6]  B* — BOND CASH FLOWS DISCOUNTED AT PURE OIS
#
#  B* = Σ_i [ c * alpha_i * N * DF_OIS(0,t_i) ] + N * DF_OIS(0,T)
#
#  This is NOT the same as the market dirty price P.
#    - P  uses the bond's own yield y = OIS + z-spread
#    - B* uses only the OIS curve (no credit spread)
#  So B* > P when z > 0 (discount bond: B* closer to par than P)
#
#  Economic meaning: B* is what Citi hands over in the IRS fixed leg.
#  The difference (B* - P) = PV of z-spread payments, which reflects
#  the credit/liquidity premium the bond carries.
# ==============================================================
bond.setPricingEngine(ql.DiscountingBondEngine(ois_handle))   # OIS only, no z
B_star_pct = bond.dirtyPrice()    # B* as % of notional

# ==============================================================
# [7]  ANNUITY FACTOR A
#
#  A = Σ_i [ alpha_i * DF_OIS(0, t_i) ]
#
#  alpha_i  = 30/360 year fraction of coupon period i (from t_{i-1} to t_i)
#  DF(0,ti) = OIS discount factor to payment date t_i
#
#  A is the PV of receiving 1 unit at each coupon date — it is the
#  common denominator for converting lump sums into per-period spreads.
# ==============================================================
schedule_dates = list(fixed_schedule)
annuity = 0.0
annuity_rows = []

for i in range(1, len(schedule_dates)):
    t_prev  = schedule_dates[i-1]
    t_i     = schedule_dates[i]
    alpha_i = bond_dc.yearFraction(t_prev, t_i)   # period day count fraction
    df_i    = ois_curve.discount(t_i)              # OIS discount factor
    contrib = alpha_i * df_i
    annuity += contrib
    annuity_rows.append((t_i, alpha_i, df_i, contrib))

# ==============================================================
# [8]  PAR SWAP RATE r_s
#
#  r_s is defined so that a par fixed-for-floating IRS at this rate
#  has NPV = 0:
#      r_s * N * A + N * DF(0,T)  =  N    (fixed leg = float leg = par)
#  =>  r_s = (1 - DF(0,T)) / A
#
#  This is the "fair" fixed rate on the same schedule as the bond coupon.
# ==============================================================
df_T = ois_curve.discount(maturity)     # terminal OIS discount factor
r_s  = (1.0 - df_T) / annuity          # par swap rate

# ==============================================================
# [9]  ASSET SWAP SPREAD — ANALYTIC FORMULA
#
#  Substituting into NPV = 0:
#      (N - P) + B* - N - ASW * N * A = 0
#
#  B* = (c - r_s)*N*A + N    [substituting par swap rate identity]
#
#  Substituting B* and solving for ASW:
#      ASW = (c - r_s) + (N - P) / (N * A)
#              ↑ Term 1              ↑ Term 2
#
#  Term 1: coupon vs par swap rate difference
#    If c < r_s → bond pays below-market coupon → ASW is penalised (↓)
#    If c > r_s → bond pays above-market coupon → ASW is enhanced (↑)
#
#  Term 2: pull-to-par amortisation
#    Citi pocketed (N-P) upfront.  This is spread back over the life
#    via a reduction (if N>P, discount bond) or increase (if N<P, premium)
#    in the ASW.  Dividing by (N*A) converts the lump sum to a per-period spread.
# ==============================================================
# Restore z-spread engine to get the correct dirty price P
bond.setPricingEngine(ql.DiscountingBondEngine(z_handle_ts))
P_pct = bond.dirtyPrice()    # re-fetch after engine change

term1 = COUPON_RATE - r_s                       # coupon vs swap rate (rate)
term2 = (N_PCT - P_pct) / (N_PCT * annuity)     # pull-to-par (rate)
ASW   = term1 + term2                            # total ASW (rate)

# ==============================================================
# [10]  NPV CHECK — CITI'S PERSPECTIVE
#
#  All quantities in % of notional.
#  Sum should be identically 0 by construction of the ASW formula.
#
#  Component breakdown:
#    + Upfront : Citi paid P for bond but received N from client → keeps (N-P)
#    + B*      : Citi receives bond cash flows in IRS; valued at OIS = B*
#    - Float   : Citi pays ESTR flat + N at maturity; this equals par = N
#    - ASW pmts: Citi pays the ASW spread over the annuity; PV = ASW * N * A
# ==============================================================
npv_upfront  = N_PCT - P_pct             # + upfront windfall
npv_Bstar    = B_star_pct               # + IRS fixed leg (bond CFs at OIS)
npv_float    = -N_PCT                   # - floating leg = -par by construction
npv_asw_pmts = -ASW * N_PCT * annuity   # - PV of ASW spread payments
npv_total    = npv_upfront + npv_Bstar + npv_float + npv_asw_pmts

# ==============================================================
# [11]  QUANTLIB AssetSwap — INDEPENDENT CROSS-CHECK
#
#  QuantLib's built-in AssetSwap class provides a cross-check.
#  We use Euribor6M backed by the OIS curve as a proxy for the
#  floating index (in practice: SOFR or ESTR overnight index).
#  payBondCoupon=False → Citi RECEIVES bond coupons (our setup).
#  parAssetSwap=True   → floating notional = par (not dirty price).
# ==============================================================
ibor_index = ql.Euribor6M(ois_handle)    # OIS-backed float index

# Add a past fixing for the Euribor6M index.
# QuantLib requires historical fixings for any reset date on or before today.
# The first floating period's reset date (March 20, 2026) is before our eval date,
# so we supply a fixing.  We use the forward rate from today (the curve's reference
# date) to avoid a "negative time" error from querying before the curve start.
fixing_rate = ois_curve.forwardRate(
    today, calendar.advance(today, ql.Period("6M")),
    ql.Actual360(), ql.Simple).rate()
ibor_index.addFixing(ql.Date(20, 3, 2026), fixing_rate)

bond.setPricingEngine(ql.DiscountingBondEngine(z_handle_ts))
clean_for_asw = bond.cleanPrice()

asset_swap = ql.AssetSwap(
    False,                          # payBondCoupon=False: Citi receives bond coupons
    bond,
    clean_for_asw,                  # clean price input (QL uses dirty internally)
    ibor_index,
    0.0,                            # initial spread guess (solver finds fairSpread)
    ql.Schedule(),                  # empty → default float schedule from ibor index
    ibor_index.dayCounter(),
    True                            # parAssetSwap=True: this is a par asset swap
)
swap_engine = ql.DiscountingSwapEngine(ois_handle)
asset_swap.setPricingEngine(swap_engine)

asw_ql  = asset_swap.fairSpread()   # QuantLib solved ASW
asw_npv = asset_swap.NPV()          # should NOT be since you are not pricing with the fair ASW (fairSpread)

## Reprice using the fair ASW
asset_swap_fairSpread = ql.AssetSwap(
    False,                          # payBondCoupon=False: Citi receives bond coupons
    bond,
    clean_for_asw,                  # clean price input (QL uses dirty internally)
    ibor_index,
    asw_ql,                            # fairSpread
    ql.Schedule(),                  # empty → default float schedule from ibor index
    ibor_index.dayCounter(),
    True                            # parAssetSwap=True: this is a par asset swap
)
asset_swap_fairSpread.setPricingEngine(swap_engine)
asw_npv_fairSpread = asset_swap_fairSpread.NPV()          # should be ~0

# ==============================================================
# OUTPUT
# ==============================================================
sep = "=" * 62

print(sep)
print("  PAR ASSET SWAP — CITIGROUP PERSPECTIVE")
print(sep)

print("\n[1]  OIS CURVE ZERO RATES  (continuously compounded, Act/365)")
print(f"  {'Tenor':<8}  {'Zero Rate':>10}")
print(f"  {'-'*20}")
for t, r in zip(ois_tenors, ois_zeros):
    print(f"  {t:<8}  {r*100:>9.2f}%")

print(f"\n[2]  BOND PRICING  (coupon c = {COUPON_RATE*100:.1f}%,  z-spread = {Z_SPREAD_BPS} bps)")
print(f"  Settlement date:    {settle}")
print(f"  Maturity:           {maturity}")
print(f"  Clean price:        {clean_pct:>10.4f}%   (${clean_pct/100*NOTIONAL/1e6:>7.3f}mm)")
print(f"  Accrued interest:   {accrued_pct:>10.4f}%")
print(f"  Dirty price P:      {P_pct:>10.4f}%   (${P_pct/100*NOTIONAL/1e6:>7.3f}mm)")
print(f"  YTM (ann, Comp):    {ytm*100:>10.4f}%")
print(f"  Upfront (N - P):    {N_PCT - P_pct:>10.4f}%   (${(N_PCT-P_pct)/100*NOTIONAL/1e6:>7.3f}mm)")

print(f"\n[3]  B*  — bond cash flows at OIS (no z-spread)")
print(f"  B* (OIS value):     {B_star_pct:>10.4f}%   (${B_star_pct/100*NOTIONAL/1e6:>7.3f}mm)")
print(f"  B* - N:             {B_star_pct-N_PCT:>10.4f}%   ({('premium' if B_star_pct>N_PCT else 'discount')} vs par)")
print(f"  B* - P:             {B_star_pct-P_pct:>10.4f}%   (= PV of z-spread cash flows)")

print(f"\n[4]  ANNUITY & PAR SWAP RATE")
print(f"  {'Coupon Date':<14}  {'alpha_i':>8}  {'DF(0,ti)':>10}  {'alpha*DF':>10}")
print(f"  {'-'*46}")
for d, a, df, contrib in annuity_rows:
    print(f"  {str(d):<14}  {a:>8.4f}  {df:>10.6f}  {contrib:>10.6f}")
print(f"  {'Annuity A':<14}  {'':>8}  {'':>10}  {annuity:>10.6f}")
print(f"\n  Terminal DF(0,T):   {df_T:.6f}")
print(f"  Par swap rate r_s:  {r_s*100:.4f}%")
print(f"  Bond coupon c:      {COUPON_RATE*100:.4f}%")
print(f"  c - r_s:            {(COUPON_RATE-r_s)*10000:.2f} bps  "
      f"({'bond pays above' if COUPON_RATE>r_s else 'bond pays below'} par swap rate)")

print(f"\n[5]  ASSET SWAP SPREAD")
print(f"  Term 1  (c - r_s)    =  {term1*10000:>8.2f} bps  ← coupon vs par swap rate")
print(f"  Term 2  (N-P)/(N*A)  =  {term2*10000:>8.2f} bps  ← upfront amortisation")
print(f"  {'─'*42}")
print(f"  ASW  (formula)       =  {ASW*10000:>8.4f} bps")
print(f"  ASW  (QuantLib)      =  {asw_ql*10000:>8.4f} bps")
print(f"  Difference           =  {(ASW - asw_ql)*10000:>8.4f} bps  "
      f"({'✓ small rounding only' if abs(ASW-asw_ql)*10000 < 1 else '⚠ check schedules'})")

print(f"\n[6]  NPV CHECK — CITI  (all in % of notional, should sum to 0)")
print(f"  Upfront (N - P):         {npv_upfront:>10.4f}%")
print(f"  IRS fixed leg B*:        {npv_Bstar:>10.4f}%   ← Citi receives bond CFs at OIS")
print(f"  IRS float leg (= -N):    {npv_float:>10.4f}%   ← Citi pays ESTR + N; = par")
print(f"  ASW spread payments:     {npv_asw_pmts:>10.4f}%   ← Citi pays spread over life")
print(f"  {'─'*40}")
print(f"  TOTAL NPV:               {npv_total:>10.6f}%  ← should be ~0.000000")
print(f"\n  QuantLib AssetSwap NPV priced with 0 ASW:  {asw_npv:>10.2f}   ← should NOT be ~0.00")
print(f"\n  QuantLib AssetSwap NPV priced with fair ASW:  {asw_npv_fairSpread:>10.2f}   ← should be ~0.00")
print(f"\n{sep}")

# ==============================================================
# SENSITIVITY: SHOW HOW ASW CHANGES WITH Z-SPREAD
# ==============================================================
print("\n  SENSITIVITY — ASW vs Z-Spread  (coupon c = {:.1f}%)".format(COUPON_RATE*100))
print(f"  {'Z-Spread':>10}  {'Dirty P':>10}  {'ASW (bps)':>12}")
print(f"  {'-'*36}")
for z_bps in [0, 25, 50, 75, 100, 150, 200, 250, 300]:
    z_quote.setValue(z_bps * 1e-4)    # update the SimpleQuote (live relinking)
    bond.setPricingEngine(ql.DiscountingBondEngine(z_handle_ts))
    p_i    = bond.dirtyPrice()
    t1     = COUPON_RATE - r_s
    t2     = (N_PCT - p_i) / (N_PCT * annuity)
    asw_i  = (t1 + t2) * 10000
    print(f"  {z_bps:>8} bps  {p_i:>10.4f}  {asw_i:>10.4f} bps")

z_quote.setValue(Z_SPREAD)   # restore original z-spread
print(sep)