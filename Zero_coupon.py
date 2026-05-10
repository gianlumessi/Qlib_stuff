'''
Write a QuantLib Python script to price a leveraged bond structure. Use the same Italian BTP, value date and curves in Asset_swap_simple.py

Use also the naming convention used in Asset_swap_price.py

STRUCTURE:
- Bond face value: FACE_VALUE = 100mm
- The bank buys FACE_VALUE of BTP at its dirty price.
  Dirty cost = dirty_price_pct * FACE_VALUE / 100
- The investor pays INVESTOR_PAYMENT upfront (initial guess 20mm).
  The investor is buying a zero coupon note from the bank at a discount.
  The note face value is FACE_VALUE. The note redeems at FACE_VALUE at maturity.
- The bank finances the remainder: F = dirty_cost - INVESTOR_PAYMENT
- The bank borrowed F from its treasury at OIS rate (ESTR) + bank_spread.
  Set bank_spread = 10 bps.

SWAP LEGS — discount all cash flows using the ESTR OIS zero curve:

  Bank receives leg:
    - INVESTOR_PAYMENT on day 1 (DF = 1, enters at face value)
    - Bond coupons: coupon_rate * FACE_VALUE at each coupon date, PV = C * FV * A
    - Bond redemption: FACE_VALUE at maturity, PV = FV * DF(0,T)
    - Total PV receives = INVESTOR_PAYMENT + C * FV * A + FV * DF(0,T)

  Bank pays leg:
    - Dirty cost on day 1 (DF = 1, enters at face value)
    - Financing interest at (OIS_par_rate + bank_spread) on F at each coupon date,
      PV = (r_s + s) * F * A. This simplifies using the par condition
      r_s * A + DF(0,T) = 1 to give total financing PV = F * (1 + s * A)
    - Principal repayment F at maturity is already included in F * (1 + s * A) above
    - Note redemption FACE_VALUE to investor at maturity, PV = FV * DF(0,T)
    - Total PV pays = dirty_cost + F * (1 + s * A) + FV * DF(0,T)

CASH FLOW TABLE (for output):

  Bank Pays                                    PV
  Dirty bond cost (day 1)                      dirty_cost
  Financing interest (OIS + s) * F * A         (r_s + s) * F * A
  Principal repayment F * DF(0,T)              F * DF(0,T)
  Note redemption FV * DF(0,T)                 FV * DF(0,T)
  Total                                        dirty_cost + F*(1 + s*A) + FV*DF(0,T)

  Bank Receives                                PV
  Upfront INVESTOR_PAYMENT (day 1)             INVESTOR_PAYMENT
  Bond coupons C * FV * A                      C * FV * A
  Bond redemption FV * DF(0,T)                 FV * DF(0,T)
  Total                                        INVESTOR_PAYMENT + C*FV*A + FV*DF(0,T)

OPTIMIZATION:
  Solve for INVESTOR_PAYMENT such that PV(bank receives) = PV(bank pays).
  FV * DF(0,T) cancels from both sides, giving:
    INVESTOR_PAYMENT + C * FV * A = dirty_cost + F * (1 + s * A)
  Substituting F = dirty_cost - INVESTOR_PAYMENT and solving:
    INVESTOR_PAYMENT = dirty_cost - C * FV * A / (2 + s * A)
  Use this as the closed-form solution.
  Verify numerically with scipy.optimize.brentq as a cross-check.
  
BTP BOND SETUP: See the Asset_swap_simple.py script

OUTPUT:
  Print:
  1. BTP dirty price, clean price, accrued, YTM
  2. Dirty cost of bond purchase (dirty_price_pct * FACE_VALUE / 100)
  3. Bank financing amount
  4. B* (PV of bond cash flows at OIS), annuity A, DF(0,T)
  5. Closed-form INVESTOR_PAYMENT
  6. Numerical INVESTOR_PAYMENT from scipy solver (cross-check)
  7. NPV check: PV(receives) - PV(pays) should be 0
  8. Implied investor return: (FACE_VALUE / INVESTOR_PAYMENT)^(1/T) - 1
     This is the zero-coupon yield the investor earns on their 20mm investment

SENSITIVITY TABLE:
  Show INVESTOR_PAYMENT and investor implied yield for z-spreads from 0 to 300 bps in 50 bps steps.

CODE STYLE:
  - Numbered block comments matching the asset swap script style e.g. [1] OIS CURVE, [2] BOND, etc.
  - All configurable parameters at the top
  - Explain each formula in comments before computing it
  - No external dependencies beyond QuantLib and scipy
'''

