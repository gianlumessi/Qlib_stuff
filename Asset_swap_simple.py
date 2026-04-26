"""
===============================================================
  PAR ASSET SWAP PRICING — QuantLib modular implementation
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
from curves import build_zero_curve, build_z_spread_curve
from bond_pricer import build_bond_from_settle, price_bond, compute_bond_annuity

##TODO: Bloomberg uses the EUR vs 6M EURIBOR curve (YCSW0045 Index) to price the floating leg of the asset swap (this is the index of the forwarding, the discounting is still ESTR OIS). Neet to figure out how this works

# ==============================================================
# [1]  CONFIGURATION  — edit these values to match market data
# ==============================================================
### ISIN: IT0005676504, Des: Btp 3.45 01/02/2036, Maturity: 01/Feb/2036
COUPON_RATE      = 0.0345                        # Bond annual coupon rate
COUPON_FREQUENCY = ql.Semiannual                 # Semi-annual BTP coupons
Z_SPREAD_BPS     = 74.4                          # Z-spread over OIS in bps
BOND_MATURITY    = ql.Date(1, ql.February, 2036) # Exact maturity date
BOND_LAST_COUPON_DATE  = ql.Date(1, ql.February, 2026) # Last coupon date (accrual start)

# Bloomberg reference values for sanity check
BBG_CLEAN_PRICE = 97.632
BBG_DIRTY_PRICE = 98.4511
BBG_ASW_BPS     = 72.0

# OIS zero curve  (continuously compounded, Act/365 Fixed).
# See the ECB Data Warehouse (only up to 1Y): https://data.ecb.europa.eu/data/data-categories/financial-markets-and-interest-rates/euro-money-market/compounded-euro-short-term-rates-and-index?layerType=DL
# BBG Code of ESTR Swap 1Y: EESWE1. This is the index used for discounting in Bloomberg
OIS_TENORS = ["1W", "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y"]
OIS_ZEROS  = [0.01931, 0.023711, 0.02448, 0.02475, 0.025132,
              0.02558, 0.0260515, 0.026589, 0.0271, 0.027626, 0.02814]

NOTIONAL = 100e6    # 100mm par notional
N_PCT    = 100.0    # par expressed as % of notional

# ==============================================================
# [2]  DATES & CONVENTIONS
# ==============================================================
today    = ql.Date(24, 4, 2026)
calendar = ql.TARGET()
bond_dc  = ql.ActualActual(ql.ActualActual.ISMA)  # Day count convention. ISMA = ICMA in QuantLib
ql.Settings.instance().evaluationDate = today

settle = calendar.advance(today, ql.Period("2D"))   # T+2 settlement

# ==============================================================
# [3]  BUILD CURVES
# ==============================================================
ois_handle        = build_zero_curve(today, OIS_TENORS, OIS_ZEROS, calendar)
z_handle, z_quote = build_z_spread_curve(ois_handle, Z_SPREAD_BPS)

# ==============================================================
# [4]  BUILD BOND
#      Semi-annual fixed coupon, 30/360 BondBasis, T+2 settlement
#      dated_date = last coupon date so accrued is computed correctly
# ==============================================================
bond = build_bond_from_settle(
    settle_date=settle,
    coupon_rate=COUPON_RATE,
    maturity_date=BOND_MATURITY,
    dated_date=BOND_LAST_COUPON_DATE,
    coupon_frequency=COUPON_FREQUENCY,
    calendar=calendar,
    day_count=bond_dc,
)

# ==============================================================
# [5]  PRICE BOND AT OIS + Z-SPREAD  →  dirty price P
# ==============================================================
priced_z    = price_bond(bond, z_handle)
P_pct       = priced_z.dirty_price
clean_pct   = priced_z.clean_price
accrued_pct = priced_z.accrued_interest
ytm         = priced_z.ytm

# ==============================================================
# [6]  B*  — bond cash flows discounted at pure OIS (no z-spread)
# ==============================================================
priced_ois = price_bond(bond, ois_handle)
B_star_pct = priced_ois.dirty_price

# ==============================================================
# [7]  ANNUITY FACTOR A  AND  PAR SWAP RATE r_s
# ==============================================================
annuity, annuity_rows = compute_bond_annuity(bond, ois_handle)
df_T = ois_handle.discount(bond.maturityDate())
r_s  = (1.0 - df_T) / annuity

# ==============================================================
# [8]  ASSET SWAP SPREAD — ANALYTIC FORMULA
#      ASW = (c - r_s) + (N - P) / (N * A)
# ==============================================================
term1 = COUPON_RATE - r_s
term2 = (N_PCT - P_pct) / (N_PCT * annuity)
ASW   = term1 + term2

# ==============================================================
# [9]  NPV CHECK  (all in % of notional, should sum to 0)
# ==============================================================
npv_upfront  = N_PCT - P_pct
npv_Bstar    = B_star_pct
npv_float    = -N_PCT
npv_asw_pmts = -ASW * N_PCT * annuity
npv_total    = npv_upfront + npv_Bstar + npv_float + npv_asw_pmts

# ==============================================================
# [10]  QUANTLIB AssetSwap — INDEPENDENT CROSS-CHECK
# ==============================================================
ibor_index = ql.Euribor6M(ois_handle)

fixing_rate = ois_handle.forwardRate(
    today, calendar.advance(today, ql.Period("6M")),
    ql.Actual360(), ql.Simple).rate()
# Add fixing for the most recent reset date (T-2 from today)
fixing_date = ibor_index.fixingDate(settle)
if fixing_date <= today:
    ibor_index.addFixing(fixing_date, fixing_rate)

bond.setPricingEngine(ql.DiscountingBondEngine(z_handle))
clean_for_asw = bond.cleanPrice()

swap_engine = ql.DiscountingSwapEngine(ois_handle)

asset_swap = ql.AssetSwap(
    False, bond, clean_for_asw, ibor_index, 0.0,
    ql.Schedule(), ibor_index.dayCounter(), True,
)
asset_swap.setPricingEngine(swap_engine)
asw_ql  = asset_swap.fairSpread()
asw_npv = asset_swap.NPV()

asset_swap_fair = ql.AssetSwap(
    False, bond, clean_for_asw, ibor_index, asw_ql,
    ql.Schedule(), ibor_index.dayCounter(), True,
)
asset_swap_fair.setPricingEngine(swap_engine)
asw_npv_fair = asset_swap_fair.NPV()

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
for t, r in zip(OIS_TENORS, OIS_ZEROS):
    print(f"  {t:<8}  {r*100:>9.2f}%")

print(f"\n[2]  BOND PRICING  (coupon c = {COUPON_RATE*100:.2f}%,  z-spread = {Z_SPREAD_BPS} bps)")
print(f"  Settlement date:    {settle}")
print(f"  Maturity:           {bond.maturityDate()}")
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
print(f"  Term 1  (c - r_s)    =  {term1*10000:>8.2f} bps  <- coupon vs par swap rate")
print(f"  Term 2  (N-P)/(N*A)  =  {term2*10000:>8.2f} bps  <- upfront amortisation")
print(f"  {'-'*42}")
print(f"  ASW  (formula)       =  {ASW*10000:>8.4f} bps")
print(f"  ASW  (QuantLib)      =  {asw_ql*10000:>8.4f} bps")
print(f"  Difference           =  {(ASW - asw_ql)*10000:>8.4f} bps  "
      f"({'ok - small rounding only' if abs(ASW-asw_ql)*10000 < 1 else '!! check schedules'})")

print(f"\n[6]  NPV CHECK — CITI  (all in % of notional, should sum to 0)")
print(f"  Upfront (N - P):         {npv_upfront:>10.4f}%")
print(f"  IRS fixed leg B*:        {npv_Bstar:>10.4f}%   <- Citi receives bond CFs at OIS")
print(f"  IRS float leg (= -N):    {npv_float:>10.4f}%   <- Citi pays ESTR + N; = par")
print(f"  ASW spread payments:     {npv_asw_pmts:>10.4f}%   <- Citi pays spread over life")
print(f"  {'-'*40}")
print(f"  TOTAL NPV:               {npv_total:>10.6f}%  <- should be ~0.000000")
print(f"\n  QuantLib ASW NPV (0 spread):    {asw_npv:>10.2f}   <- should NOT be ~0.00")
print(f"\n  QuantLib ASW NPV (fair spread): {asw_npv_fair:>10.2f}   <- should be ~0.00")
print(f"\n{sep}")

# ==============================================================
# SENSITIVITY: ASW vs Z-SPREAD  (live quote update, no rebuild)
# ==============================================================
print("\n  SENSITIVITY — ASW vs Z-Spread  (coupon c = {:.1f}%)".format(COUPON_RATE*100))
print(f"  {'Z-Spread':>10}  {'Dirty P':>10}  {'ASW (bps)':>12}")
print(f"  {'-'*36}")
for z_bps in [0, 25, 50, 75, 100, 150, 200, 250, 300]:
    z_quote.setValue(z_bps * 1e-4)
    bond.setPricingEngine(ql.DiscountingBondEngine(z_handle))
    p_i   = bond.dirtyPrice()
    t1    = COUPON_RATE - r_s
    t2    = (N_PCT - p_i) / (N_PCT * annuity)
    asw_i = (t1 + t2) * 10000
    print(f"  {z_bps:>8} bps  {p_i:>10.4f}  {asw_i:>10.4f} bps")

z_quote.setValue(Z_SPREAD_BPS * 1e-4)   # restore original z-spread
print(sep)

# ==============================================================
# BLOOMBERG SANITY CHECK
# ==============================================================
print("\n  BLOOMBERG SANITY CHECK  (as of {})".format(today))
print(f"  {'Metric':<22}  {'Computed':>12}  {'Bloomberg':>12}  {'Diff':>10}")
print(f"  {'-'*60}")

diff_clean  = clean_pct  - BBG_CLEAN_PRICE
diff_dirty  = P_pct      - BBG_DIRTY_PRICE
diff_asw_ql = asw_ql * 10000 - BBG_ASW_BPS
diff_asw_f  = ASW    * 10000 - BBG_ASW_BPS

print(f"  {'Clean price (%)':22}  {clean_pct:>12.4f}  {BBG_CLEAN_PRICE:>12.4f}  {diff_clean:>+10.4f}")
print(f"  {'Dirty price (%)':22}  {P_pct:>12.4f}  {BBG_DIRTY_PRICE:>12.4f}  {diff_dirty:>+10.4f}")
print(f"  {'Accrued (%)':22}  {accrued_pct:>12.4f}  {BBG_DIRTY_PRICE-BBG_CLEAN_PRICE:>12.4f}  {accrued_pct-(BBG_DIRTY_PRICE-BBG_CLEAN_PRICE):>+10.4f}")
print(f"  {'ASW - QuantLib (bps)':22}  {asw_ql*10000:>12.4f}  {BBG_ASW_BPS:>12.4f}  {diff_asw_ql:>+10.4f}")
print(f"  {'ASW - formula (bps)':22}  {ASW*10000:>12.4f}  {BBG_ASW_BPS:>12.4f}  {diff_asw_f:>+10.4f}")
print(f"  {'-'*60}")
print(sep)
