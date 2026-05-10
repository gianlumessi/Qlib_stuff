"""
===============================================================
  LEVERAGED BOND / ZERO-COUPON NOTE PRICING — QuantLib
  Priced from Bank's perspective
===============================================================

STRUCTURE:
  - Bond face value: FACE_VALUE = 100mm
  - The bank buys FACE_VALUE of BTP at its dirty price.
    Dirty cost = dirty_price_pct * FACE_VALUE / 100
  - The investor pays INVESTOR_PAYMENT upfront (solved for below).
    The investor is buying a zero-coupon note from the bank at a
    discount.  The note face value is FACE_VALUE.  The note redeems
    at FACE_VALUE at maturity.
  - The bank finances the remainder: F = dirty_cost - INVESTOR_PAYMENT
  - The bank borrowed F from its treasury at OIS rate (ESTR) + bank_spread.

SWAP LEGS — all cash flows discounted at the ESTR OIS zero curve:

  Bank receives leg:
    - INVESTOR_PAYMENT on day 1 (DF = 1, enters at face value)
    - Bond coupons: C * FV at each coupon date,  PV = C * FV * A
    - Bond redemption: FV at maturity,           PV = FV * DF(0,T)
    Total PV receives = INVESTOR_PAYMENT + C * FV * A + FV * DF(0,T)

  Bank pays leg:
    - Dirty cost on day 1 (DF = 1)
    - Financing interest at (r_s + s) on F at each coupon date,
      PV = (r_s + s) * F * A.  Using the par condition
      r_s * A + DF(0,T) = 1, the total financing + principal PV
      simplifies to F * (1 + s * A)
    - Note redemption FV to investor at maturity, PV = FV * DF(0,T)
    Total PV pays = dirty_cost + F * (1 + s * A) + FV * DF(0,T)

CLOSED-FORM SOLUTION:
  Setting PV(receives) = PV(pays) and noting FV * DF(0,T) cancels:
    INVESTOR_PAYMENT + C * FV * A = dirty_cost + F * (1 + s * A)
  Substituting F = dirty_cost - INVESTOR_PAYMENT and solving:
    INVESTOR_PAYMENT = dirty_cost - C * FV * A / (2 + s * A)

  Verified numerically with scipy.optimize.brentq.

REQUIREMENTS:
  pip install QuantLib scipy
===============================================================
"""

import QuantLib as ql
from scipy.optimize import brentq
from curves import build_zero_curve, build_z_spread_curve
from bond_pricer import build_bond_from_settle, price_bond, compute_bond_annuity

# ==============================================================
# [1]  CONFIGURATION  — edit these values to match market data
# ==============================================================
### ISIN: IT0005676504, Des: Btp 3.45 01/02/2036, Maturity: 01/Feb/2036
COUPON_RATE      = 0.0345                        # Bond annual coupon rate
COUPON_FREQUENCY = ql.Semiannual                 # Semi-annual BTP coupons
Z_SPREAD_BPS     = 74.4                          # Z-spread over OIS in bps
BOND_MATURITY    = ql.Date(1, ql.February, 2036) # Exact maturity date
BOND_LAST_COUPON_DATE = ql.Date(1, ql.February, 2026)  # Accrual start

FACE_VALUE   = 100e6    # 100mm bond notional
FV_PCT       = 100.0    # face value as % of notional
BANK_SPREAD  = 10e-4    # bank treasury funding spread: 10 bps over OIS

# OIS zero curve  (continuously compounded, Act/365 Fixed)
# BBG Code of ESTR Swap curve: EESWE1
OIS_TENORS = ["1W", "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y"]
OIS_ZEROS  = [0.01931, 0.023711, 0.02448, 0.02475, 0.025132,
              0.02558, 0.0260515, 0.026589, 0.0271, 0.027626, 0.02814]

# ==============================================================
# [2]  DATES & CONVENTIONS
# ==============================================================
today    = ql.Date(24, 4, 2026)
calendar = ql.TARGET()
bond_dc  = ql.ActualActual(ql.ActualActual.ISMA)  # ISMA = ICMA in QuantLib
ql.Settings.instance().evaluationDate = today

settle = calendar.advance(today, ql.Period("2D"))   # T+2 settlement

# ==============================================================
# [3]  BUILD CURVES
#      OIS (ESTR) — discounting for all cash flows
#      OIS + z-spread — used only to derive the BTP dirty price
# ==============================================================
ois_handle        = build_zero_curve(today, OIS_TENORS, OIS_ZEROS, calendar)
z_handle, z_quote = build_z_spread_curve(ois_handle, Z_SPREAD_BPS)

# ==============================================================
# [4]  BUILD BOND
#      Semi-annual fixed coupon, Act/Act ISMA, T+2 settlement
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
# [5]  PRICE BOND AT OIS + Z-SPREAD  →  dirty price
#      The z-spread represents the BTP's credit/liquidity premium.
#      dirty_cost = dirty_price_pct * FACE_VALUE / 100
# ==============================================================
priced_z       = price_bond(bond, z_handle)
dirty_price_pct = priced_z.dirty_price       # as % of notional
clean_price_pct = priced_z.clean_price
accrued_pct     = priced_z.accrued_interest
ytm             = priced_z.ytm

dirty_cost = dirty_price_pct * FACE_VALUE / 100.0   # absolute amount (e.g. ~98mm)

# ==============================================================
# [6]  B*  — bond cash flows discounted at pure OIS (no z-spread)
#      B* tells us the PV of the BTP at the risk-free rate.
#      The difference (B* - dirty_price) = PV of z-spread.
# ==============================================================
priced_ois = price_bond(bond, ois_handle)
B_star_pct = priced_ois.dirty_price

# ==============================================================
# [7]  ANNUITY FACTOR A  AND  PAR SWAP RATE
#
#      A = Σ_i [ alpha_i * DF_OIS(0, t_i) ]
#      Par swap rate: r_s = (1 - DF(0,T)) / A
#      These are the building blocks for both the financing cost
#      and the closed-form INVESTOR_PAYMENT solution.
# ==============================================================
annuity, annuity_rows = compute_bond_annuity(bond, ois_handle)
df_T = ois_handle.discount(bond.maturityDate())

# Par swap rate from OIS: r_s * A = 1 - DF(T)
r_s = (1.0 - df_T) / annuity

# Time to maturity in years (for implied yield computation)
ois_dc = ql.Actual365Fixed()
T_years = ois_dc.yearFraction(settle, bond.maturityDate())

# ==============================================================
# [8]  CLOSED-FORM INVESTOR PAYMENT
#
#      Setting PV(bank receives) = PV(bank pays):
#        IP + C * FV * A = dirty_cost + F * (1 + s * A)
#      where F = dirty_cost - IP.  Solving for IP:
#        IP + C*FV*A = dirty_cost + (dirty_cost - IP)*(1 + s*A)
#        IP + C*FV*A = dirty_cost + dirty_cost + dirty_cost*s*A - IP - IP*s*A
#        IP + IP + IP*s*A = 2*dirty_cost + dirty_cost*s*A - C*FV*A
#        IP * (2 + s*A) = dirty_cost * (2 + s*A) - C*FV*A
#        IP = dirty_cost - C * FV * A / (2 + s * A)
#
#      In percentage terms (dividing by FACE_VALUE / 100):
#        IP_pct = dirty_pct - C * FV_pct * A / (2 + s * A)
# ==============================================================
s = BANK_SPREAD   # bank funding spread (10 bps)

IP_pct = dirty_price_pct - COUPON_RATE * FV_PCT * annuity / (2.0 + s * annuity)
IP_abs = IP_pct * FACE_VALUE / 100.0   # absolute amount

# Financing amount
F_pct = dirty_price_pct - IP_pct
F_abs = F_pct * FACE_VALUE / 100.0

# ==============================================================
# [9]  NUMERICAL CROSS-CHECK  (scipy.optimize.brentq)
#
#      Define NPV(IP) = PV(receives) - PV(pays) and find IP such
#      that NPV = 0.  This verifies the closed-form algebra.
# ==============================================================
def npv_func(ip_pct):
    """NPV as a function of INVESTOR_PAYMENT (% of notional).
    Returns PV(receives) - PV(pays); zero at break-even."""
    f_pct = dirty_price_pct - ip_pct

    # PV of what the bank receives
    pv_receives = (
        ip_pct                             # upfront from investor (DF=1)
        + COUPON_RATE * FV_PCT * annuity   # bond coupons discounted at OIS
        + FV_PCT * df_T                    # bond redemption at maturity
    )

    # PV of what the bank pays
    pv_pays = (
        dirty_price_pct                    # dirty cost of bond purchase (DF=1)
        + f_pct * (1.0 + s * annuity)     # financing: principal + interest
        + FV_PCT * df_T                    # note redemption to investor
    )

    return pv_receives - pv_pays

IP_numerical = brentq(npv_func, 0.0, FV_PCT)

# ==============================================================
# [10]  NPV VERIFICATION — BANK'S PERSPECTIVE
#
#       Using the closed-form IP, compute each component's PV
#       and verify the total is zero.
# ==============================================================
# --- Bank receives ---
pv_upfront_recv  = IP_pct                              # investor payment (day 1)
pv_coupons_recv  = COUPON_RATE * FV_PCT * annuity      # bond coupons at OIS
pv_redemp_recv   = FV_PCT * df_T                       # bond redemption at maturity
pv_total_recv    = pv_upfront_recv + pv_coupons_recv + pv_redemp_recv

# --- Bank pays ---
pv_dirty_pay     = dirty_price_pct                     # bond purchase (day 1)
pv_financing_pay = (r_s + s) * F_pct * annuity         # financing interest at OIS+s
pv_principal_pay = F_pct * df_T                        # principal repayment at maturity
pv_note_pay      = FV_PCT * df_T                       # note redemption to investor
pv_total_pay     = pv_dirty_pay + pv_financing_pay + pv_principal_pay + pv_note_pay

# Simplified financing PV = F * (1 + s*A) using par swap identity
pv_financing_simplified = F_pct * (1.0 + s * annuity)

npv_check = pv_total_recv - pv_total_pay

# ==============================================================
# [11]  IMPLIED INVESTOR RETURN
#
#       The investor pays IP today and receives FV at maturity.
#       This is a zero-coupon bond with implied yield:
#         y = (FV / IP)^(1/T) - 1    (annually compounded)
# ==============================================================
implied_yield = (FV_PCT / IP_pct) ** (1.0 / T_years) - 1.0

# ==============================================================
# [12]  OUTPUT
# ==============================================================
sep = "=" * 68

print(sep)
print("  LEVERAGED BOND / ZERO-COUPON NOTE — BANK PERSPECTIVE")
print(sep)

print("\n[1]  OIS CURVE ZERO RATES  (continuously compounded, Act/365)")
print(f"  {'Tenor':<8}  {'Zero Rate':>10}")
print(f"  {'-'*20}")
for t, r in zip(OIS_TENORS, OIS_ZEROS):
    print(f"  {t:<8}  {r*100:>9.4f}%")

print(f"\n[2]  BTP BOND  (coupon c = {COUPON_RATE*100:.2f}%,  z-spread = {Z_SPREAD_BPS} bps)")
print(f"  Settlement date:    {settle}")
print(f"  Maturity:           {bond.maturityDate()}")
print(f"  Clean price:        {clean_price_pct:>10.4f}%   (${clean_price_pct/100*FACE_VALUE/1e6:>7.3f}mm)")
print(f"  Accrued interest:   {accrued_pct:>10.4f}%")
print(f"  Dirty price P:      {dirty_price_pct:>10.4f}%   (${dirty_cost/1e6:>7.3f}mm)")
print(f"  YTM (ann, Comp):    {ytm*100:>10.4f}%")

print(f"\n[3]  B*  — bond cash flows discounted at OIS (no z-spread)")
print(f"  B* (OIS value):     {B_star_pct:>10.4f}%   (${B_star_pct/100*FACE_VALUE/1e6:>7.3f}mm)")

print(f"\n[4]  ANNUITY & PAR SWAP RATE")
print(f"  {'Coupon Date':<14}  {'alpha_i':>8}  {'DF(0,ti)':>10}  {'alpha*DF':>10}")
print(f"  {'-'*46}")
for d, a, df, contrib in annuity_rows:
    print(f"  {str(d):<14}  {a:>8.4f}  {df:>10.6f}  {contrib:>10.6f}")
print(f"  {'Annuity A':<14}  {'':>8}  {'':>10}  {annuity:>10.6f}")
print(f"\n  Terminal DF(0,T):   {df_T:.6f}")
print(f"  Par swap rate r_s:  {r_s*100:.4f}%")
print(f"  Time to maturity:   {T_years:.4f} years")

print(f"\n[5]  STRUCTURE PARAMETERS")
print(f"  Face value (FV):            ${FACE_VALUE/1e6:.0f}mm")
print(f"  Bank spread (s):            {BANK_SPREAD*10000:.0f} bps over OIS")
print(f"  Financing rate (r_s + s):   {(r_s + s)*100:.4f}%")
print(f"  Dirty cost of bond:         ${dirty_cost/1e6:.3f}mm")

print(f"\n[6]  CLOSED-FORM INVESTOR PAYMENT")
print(f"  IP = dirty_cost - C * FV * A / (2 + s * A)")
print(f"     = {dirty_price_pct:.4f} - {COUPON_RATE:.4f} * {FV_PCT:.1f} * {annuity:.6f}"
      f" / (2 + {s:.4f} * {annuity:.6f})")
print(f"     = {IP_pct:.4f}%   (${IP_abs/1e6:.3f}mm)")
print(f"  Financing amount F:         {F_pct:.4f}%   (${F_abs/1e6:.3f}mm)")
print(f"  Leverage ratio (FV / IP):   {FV_PCT / IP_pct:.2f}x")

print(f"\n[7]  NUMERICAL CROSS-CHECK  (scipy.optimize.brentq)")
print(f"  IP (numerical):    {IP_numerical:.4f}%")
print(f"  IP (closed-form):  {IP_pct:.4f}%")
print(f"  Difference:        {abs(IP_pct - IP_numerical):.10f}%  <- should be ~0")

print(f"\n[8]  CASH FLOW TABLE — BANK'S PERSPECTIVE  (all in % of notional)")
print(f"")
print(f"  {'Bank Receives':<45}  {'PV':>10}")
print(f"  {'-'*57}")
print(f"  {'Upfront investor payment (day 1)':<45}  {pv_upfront_recv:>10.4f}")
print(f"  {'Bond coupons C * FV * A':<45}  {pv_coupons_recv:>10.4f}")
print(f"  {'Bond redemption FV * DF(0,T)':<45}  {pv_redemp_recv:>10.4f}")
print(f"  {'-'*57}")
print(f"  {'TOTAL PV RECEIVES':<45}  {pv_total_recv:>10.4f}")
print(f"")
print(f"  {'Bank Pays':<45}  {'PV':>10}")
print(f"  {'-'*57}")
print(f"  {'Dirty bond cost (day 1)':<45}  {pv_dirty_pay:>10.4f}")
print(f"  {'Financing interest (r_s + s) * F * A':<45}  {pv_financing_pay:>10.4f}")
print(f"  {'Principal repayment F * DF(0,T)':<45}  {pv_principal_pay:>10.4f}")
print(f"  {'Note redemption FV * DF(0,T)':<45}  {pv_note_pay:>10.4f}")
print(f"  {'-'*57}")
print(f"  {'TOTAL PV PAYS':<45}  {pv_total_pay:>10.4f}")
print(f"  {'(simplified: dirty + F*(1+s*A) + FV*DF)':<45}  "
      f"{pv_dirty_pay + pv_financing_simplified + pv_note_pay:>10.4f}")
print(f"")
print(f"  {'NPV = PV(receives) - PV(pays)':<45}  {npv_check:>10.6f}%  <- should be ~0")

print(f"\n[9]  IMPLIED INVESTOR RETURN")
print(f"  Investor pays:     {IP_pct:.4f}%   (${IP_abs/1e6:.3f}mm)")
print(f"  Investor receives: {FV_PCT:.4f}%   (${FACE_VALUE/1e6:.0f}mm)  at maturity")
print(f"  Zero-coupon yield: {implied_yield*100:.4f}%  annually compounded")
print(f"  Formula: y = (FV / IP)^(1/T) - 1 = ({FV_PCT:.2f} / {IP_pct:.4f})^(1/{T_years:.2f}) - 1")

# ==============================================================
# [13]  SENSITIVITY TABLE — INVESTOR PAYMENT & YIELD vs Z-SPREAD
#
#       As the z-spread increases, the BTP dirty price falls →
#       dirty_cost falls → IP decreases → investor buys cheaper →
#       implied yield rises (more credit risk = more return).
# ==============================================================
print(f"\n{sep}")
print(f"  SENSITIVITY — Investor Payment & Yield vs Z-Spread")
print(f"  (coupon c = {COUPON_RATE*100:.2f}%, bank spread s = {BANK_SPREAD*10000:.0f} bps)")
print(f"  {'Z-Spread':>10}  {'Dirty P (%)':>12}  {'IP (%)':>10}  {'IP ($mm)':>10}  {'Yield (%)':>10}  {'Leverage':>10}")
print(f"  {'-'*68}")

for z_bps in [0, 50, 100, 150, 200, 250, 300]:
    # Bump the z-spread quote (live relinking, no curve rebuild)
    z_quote.setValue(z_bps * 1e-4)
    bond.setPricingEngine(ql.DiscountingBondEngine(z_handle))
    p_i = bond.dirtyPrice()

    # Closed-form IP for this dirty price
    ip_i = p_i - COUPON_RATE * FV_PCT * annuity / (2.0 + s * annuity)
    ip_abs_i = ip_i * FACE_VALUE / 100.0
    y_i = (FV_PCT / ip_i) ** (1.0 / T_years) - 1.0
    lev_i = FV_PCT / ip_i

    print(f"  {z_bps:>8} bps  {p_i:>12.4f}  {ip_i:>10.4f}  {ip_abs_i/1e6:>9.3f}  {y_i*100:>10.4f}  {lev_i:>9.2f}x")

# Restore original z-spread
z_quote.setValue(Z_SPREAD_BPS * 1e-4)

print(f"  {'-'*68}")
print(f"  Higher z-spread -> lower BTP price -> cheaper note -> higher investor yield")
print(sep)
