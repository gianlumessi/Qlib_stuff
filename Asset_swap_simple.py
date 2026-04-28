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
from curves import build_zero_curve, build_z_spread_curve, build_euribor_forwarding_curve
from bond_pricer import build_bond_from_settle, price_bond, compute_bond_annuity

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

# EUR vs 6M EURIBOR curve (Bloomberg: YCSW0045) — forwarding curve for the ASW float leg.
# Par swap rates, fixed leg annual 30/360, float leg 6M EURIBOR Act/360.
EURvs6mEURIBOR_TENORS     = ["6M", "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y"]
EURvs6mEURIBOR_PAR_RATES  = [0.02459, 0.026612, 0.02734, 0.027536, 0.027805, 0.02815,
                               0.02854, 0.028989, 0.02943, 0.029874, 0.030316]

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
#      OIS (ESTR) — discounting
#      EURIBOR 6M — forwarding (bootstrapped with OIS discounting)
#      OIS + z-spread — bond pricing
# ==============================================================
ois_handle        = build_zero_curve(today, OIS_TENORS, OIS_ZEROS, calendar)
euribor_handle    = build_euribor_forwarding_curve(
    today, EURvs6mEURIBOR_TENORS, EURvs6mEURIBOR_PAR_RATES, ois_handle
)
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
# [7]  ANNUITY FACTOR A  AND  PAR SWAP RATES
# ==============================================================
annuity, annuity_rows = compute_bond_annuity(bond, ois_handle)
df_T = ois_handle.discount(bond.maturityDate())

# Single-curve par swap rate (OIS only — approximation)
r_s = (1.0 - df_T) / annuity

# Dual-curve par swap rate: EURIBOR 6M forwards discounted at OIS.
# For each coupon period: forward EURIBOR rate × Act/360 tau × OIS DF.
# r_s_dual satisfies: r_s_dual × A_fixed = PV(EURIBOR float leg)
float_dc          = ql.Actual360()
coupon_end_dates  = [row[0] for row in annuity_rows]
period_starts_flt = [bond.startDate()] + coupon_end_dates[:-1]
float_pv = sum(
    euribor_handle.forwardRate(
        s if s > today else today,   # clamp past start dates to today
        e, float_dc, ql.Simple
    ).rate()
    * float_dc.yearFraction(s, e)    # full period tau (consistent with annuity)
    * df_i
    for s, e, (_, _, df_i, _) in zip(period_starts_flt, coupon_end_dates, annuity_rows)
)
r_s_dual = float_pv / annuity

# ==============================================================
# [8]  ASSET SWAP SPREAD — ANALYTIC FORMULA (dual-curve)
#      ASW = (c - r_s_dual) + (N - P) / (N * A)
# ==============================================================
term1 = COUPON_RATE - r_s_dual
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
ibor_index = ql.Euribor6M(euribor_handle)   # forwarding: EURIBOR curve

fixing_rate = euribor_handle.forwardRate(
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

# ------------------------------------------------------------------
# [10b]  MARKET-PRICE-BASED ASW  — Bloomberg replication
#        Bloomberg computes ASW from the *market* dirty price, not
#        from a model-implied price.  Using BBG_CLEAN_PRICE as input
#        to the QuantLib AssetSwap and BBG_DIRTY_PRICE in the analytic
#        formula should reproduce BBG_ASW_BPS much more closely.
# ------------------------------------------------------------------
asset_swap_mkt = ql.AssetSwap(
    False, bond, BBG_CLEAN_PRICE, ibor_index, 0.0,
    ql.Schedule(), ibor_index.dayCounter(), True,
)
asset_swap_mkt.setPricingEngine(swap_engine)
asw_ql_mkt  = asset_swap_mkt.fairSpread()
asw_npv_mkt = asset_swap_mkt.NPV()

# Analytic formula using Bloomberg market dirty price
term1_mkt = COUPON_RATE - r_s_dual
term2_mkt = (N_PCT - BBG_DIRTY_PRICE) / (N_PCT * annuity)
ASW_mkt   = term1_mkt + term2_mkt

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

print(f"\n[4]  ANNUITY & PAR SWAP RATES")
print(f"  {'Coupon Date':<14}  {'alpha_i':>8}  {'DF(0,ti)':>10}  {'alpha*DF':>10}")
print(f"  {'-'*46}")
for d, a, df, contrib in annuity_rows:
    print(f"  {str(d):<14}  {a:>8.4f}  {df:>10.6f}  {contrib:>10.6f}")
print(f"  {'Annuity A':<14}  {'':>8}  {'':>10}  {annuity:>10.6f}")
print(f"\n  Terminal DF(0,T):            {df_T:.6f}")
print(f"  Par swap rate r_s (OIS):     {r_s*100:.4f}%  <- single-curve approx")
print(f"  Par swap rate r_s (dual):    {r_s_dual*100:.4f}%  <- EURIBOR fwds, OIS discount")
print(f"  Bond coupon c:               {COUPON_RATE*100:.4f}%")
print(f"  c - r_s (OIS):               {(COUPON_RATE-r_s)*10000:.2f} bps")
print(f"  c - r_s (dual):              {(COUPON_RATE-r_s_dual)*10000:.2f} bps")

print(f"\n[5]  ASSET SWAP SPREAD  (dual-curve: EURIBOR fwds + OIS discount)")
print(f"  --- MODEL price (OIS + z-spread = {Z_SPREAD_BPS} bps) ---")
print(f"  Term 1  (c - r_s_dual) =  {term1*10000:>8.2f} bps  <- coupon vs dual-curve par rate")
print(f"  Term 2  (N-P)/(N*A)   =  {term2*10000:>8.2f} bps  <- upfront amortisation  [P={P_pct:.4f}%]")
print(f"  {'-'*50}")
print(f"  ASW  (formula)        =  {ASW*10000:>8.4f} bps")
print(f"  ASW  (QuantLib)       =  {asw_ql*10000:>8.4f} bps")
print(f"  Difference            =  {(ASW - asw_ql)*10000:>8.4f} bps  "
      f"({'ok - small rounding only' if abs(ASW-asw_ql)*10000 < 1 else '!! check schedules'})")
print(f"")
print(f"  --- MARKET price (Bloomberg input: clean={BBG_CLEAN_PRICE}, dirty={BBG_DIRTY_PRICE}) ---")
print(f"  Term 1  (c - r_s_dual) =  {term1_mkt*10000:>8.2f} bps  (same as above)")
print(f"  Term 2  (N-P_mkt)/(N*A)=  {term2_mkt*10000:>8.2f} bps  <- upfront  [P={BBG_DIRTY_PRICE:.4f}%]")
print(f"  {'-'*50}")
print(f"  ASW  (formula/mkt)    =  {ASW_mkt*10000:>8.4f} bps")
print(f"  ASW  (QuantLib/mkt)   =  {asw_ql_mkt*10000:>8.4f} bps")
print(f"  Difference            =  {(ASW_mkt - asw_ql_mkt)*10000:>8.4f} bps  "
      f"({'ok - small rounding only' if abs(ASW_mkt-asw_ql_mkt)*10000 < 1 else '!! check schedules'})")

print(f"\n[6]  NPV CHECK — CITI  (all in % of notional, should sum to 0)")
print(f"  Upfront (N - P):         {npv_upfront:>10.4f}%")
print(f"  IRS fixed leg B*:        {npv_Bstar:>10.4f}%   <- Citi receives bond CFs at OIS")
print(f"  IRS float leg (= -N):    {npv_float:>10.4f}%   <- Citi pays ESTR + N; = par")
print(f"  ASW spread payments:     {npv_asw_pmts:>10.4f}%   <- Citi pays spread over life")
print(f"  {'-'*40}")
print(f"  TOTAL NPV:               {npv_total:>10.6f}%  <- should be ~0.000000")
print(f"\n  QuantLib ASW NPV (0 spread):    {asw_npv:>10.2f}   <- should NOT be ~0.00")
print(f"\n  QuantLib ASW NPV (fair spread): {asw_npv_fair:>10.2f}   <- should be ~0.00")
print(f"\n  QuantLib ASW NPV (mkt / 0 spr): {asw_npv_mkt:>10.2f}   <- market-price version")
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
    t1    = COUPON_RATE - r_s_dual
    t2    = (N_PCT - p_i) / (N_PCT * annuity)
    asw_i = (t1 + t2) * 10000
    print(f"  {z_bps:>8} bps  {p_i:>10.4f}  {asw_i:>10.4f} bps")

z_quote.setValue(Z_SPREAD_BPS * 1e-4)   # restore original z-spread
print(sep)

# ==============================================================
# BLOOMBERG SANITY CHECK
# ==============================================================
print("\n  BLOOMBERG SANITY CHECK  (as of {})".format(today))

diff_clean      = clean_pct       - BBG_CLEAN_PRICE
diff_dirty      = P_pct           - BBG_DIRTY_PRICE
diff_asw_ql     = asw_ql     * 10000 - BBG_ASW_BPS
diff_asw_f      = ASW        * 10000 - BBG_ASW_BPS
diff_asw_ql_mkt = asw_ql_mkt * 10000 - BBG_ASW_BPS
diff_asw_f_mkt  = ASW_mkt    * 10000 - BBG_ASW_BPS

print(f"  {'Metric':<28}  {'Computed':>12}  {'Bloomberg':>12}  {'Diff':>10}")
print(f"  {'-'*66}")
print(f"  {'Clean price (%) [model]':28}  {clean_pct:>12.4f}  {BBG_CLEAN_PRICE:>12.4f}  {diff_clean:>+10.4f}")
print(f"  {'Dirty price (%) [model]':28}  {P_pct:>12.4f}  {BBG_DIRTY_PRICE:>12.4f}  {diff_dirty:>+10.4f}")
print(f"  {'Accrued (%)':28}  {accrued_pct:>12.4f}  {BBG_DIRTY_PRICE-BBG_CLEAN_PRICE:>12.4f}  {accrued_pct-(BBG_DIRTY_PRICE-BBG_CLEAN_PRICE):>+10.4f}")
print(f"  {'-'*66}")
print(f"  {'ASW QL - model price (bps)':28}  {asw_ql*10000:>12.4f}  {BBG_ASW_BPS:>12.4f}  {diff_asw_ql:>+10.4f}")
print(f"  {'ASW formula - model (bps)':28}  {ASW*10000:>12.4f}  {BBG_ASW_BPS:>12.4f}  {diff_asw_f:>+10.4f}")
print(f"  {'-'*66}")
print(f"  {'ASW QL - mkt price (bps)':28}  {asw_ql_mkt*10000:>12.4f}  {BBG_ASW_BPS:>12.4f}  {diff_asw_ql_mkt:>+10.4f}")
print(f"  {'ASW formula - mkt (bps)':28}  {ASW_mkt*10000:>12.4f}  {BBG_ASW_BPS:>12.4f}  {diff_asw_f_mkt:>+10.4f}")
print(f"  {'-'*66}")
bbg_ok = abs(diff_asw_ql_mkt) < 3.0
print(f"  Bloomberg replication (mkt price): {'PASS (<3 bps)' if bbg_ok else 'FAIL (>3 bps)'}")
print(sep)
