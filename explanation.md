# Fixed Income Pricing with QuantLib — Calculation Guide

This document explains the theory behind every instrument implemented in
this project.  Each section covers the financial intuition, the valuation
formula, and how it maps to the code.

---

## Table of Contents

1. [Yield Curve Construction](#1-yield-curve-construction)
2. [Fixed-Rate Bond Pricing](#2-fixed-rate-bond-pricing)
3. [Par-Par Asset Swap](#3-par-par-asset-swap)
4. [Z-Spread](#4-z-spread)
5. [Interest Rate Swap (IRS)](#5-interest-rate-swap-irs)
6. [Fixed-Fixed Cross-Currency Swap](#6-fixed-fixed-cross-currency-swap)
7. [Fixed-Floating Cross-Currency Swap](#7-fixed-floating-cross-currency-swap)
8. [Floating-Floating Cross-Currency Basis Swap](#8-floating-floating-cross-currency-basis-swap)
9. [Implementation Notes](#9-implementation-notes)
10. [File Structure](#10-file-structure)

---

## 1. Yield Curve Construction

A yield (discount) curve is the foundation for pricing every instrument in
this project.  It provides the time value of money: how much is 1 unit of
currency received at a future date T worth today?

### Instruments used

We bootstrap **two** curves — one per currency:

| Currency | Short End | Long End | File |
|---|---|---|---|
| EUR | Euribor deposits (1M, 3M, 6M) | EUR IRS (1Y–30Y, annual fixed vs Euribor 6M) | `curves.py` |
| USD | USD LIBOR deposits (1M, 3M, 6M) | USD IRS (1Y–30Y, semi-annual fixed vs LIBOR 3M) | `curves.py` |

### Bootstrapping

The curve is built by finding the set of discount factors that **exactly**
reprice each input instrument.  QuantLib uses *piecewise log-cubic
interpolation on discount factors* (`PiecewiseLogCubicDiscount`), which
ensures smooth and well-behaved forward rates.

### Key quantities derived from the curve

| Quantity | Definition | Formula |
|---|---|---|
| **Discount factor** DF(T) | PV today of 1 unit received at T | Read directly from the curve |
| **Zero rate** z(T) | Continuously compounded rate | `DF(T) = exp(-z(T) * T)` |
| **Forward rate** f(T1,T2) | Rate implied today for [T1, T2] | `f = -ln(DF(T2)/DF(T1)) / (T2 - T1)` |

### Convention differences: EUR vs USD

| Convention | EUR | USD |
|---|---|---|
| Fixed leg frequency | Annual | Semi-annual |
| Floating index | Euribor 6M | LIBOR 3M |
| Deposit day count | ACT/360 | ACT/360 |
| Fixed leg day count | 30/360 | 30/360 |
| Calendar | TARGET | US Federal Reserve |


---

## 2. Fixed-Rate Bond Pricing

A fixed-rate bond pays periodic coupons *c* on a face value *N* and
redeems *N* at maturity *T*.

### Dirty (full) price

The dirty price is the present value of all remaining cashflows discounted
at the yield curve:

```
Dirty = sum_i [ c_i * DF(t_i) ]  +  N * DF(T)
```

where `c_i` is the coupon amount on date `t_i` (adjusted for day-count
conventions like 30/360) and `DF(t_i)` is the discount factor from the
evaluation date.

### Clean price

The quoted (clean) price strips out accrued interest:

```
Clean = Dirty - Accrued
```

**Accrued interest** is the pro-rata share of the current coupon that has
elapsed since the last coupon date:

```
Accrued = Coupon_annual * (days_since_last_coupon / days_in_period)
```

(computed using the bond's day-count convention).

### Yield to maturity (YTM)

The YTM *y* is the single internal rate of return that reprices the bond:

```
Dirty = sum_i [ c_i / (1 + y/f)^(f * t_i) ]  +  N / (1 + y/f)^(f * T)
```

where *f* is the compounding frequency (1 = annual).  Solved by
root-finding (Newton-Raphson) in QuantLib.

### Risk measures

| Measure | Formula | Meaning |
|---|---|---|
| **Modified duration** | `D_mod = -(1/P) * dP/dy` | % price change for a 1% yield move |
| **Macaulay duration** | `D_mac = D_mod * (1 + y/f)` | Weighted-average time to cashflows |
| **Convexity** | `C = (1/P) * d²P/dy²` | Curvature — captures the nonlinear price–yield relationship |
| **BPV (DV01)** | `BPV = -D_mod * P / 10,000` | Dollar (euro) price change per 1 basis point yield shift |

### Code: `bond_pricer.py`

- `build_fixed_rate_bond()` constructs a `ql.FixedRateBond`.
- `price_bond()` attaches a `DiscountingBondEngine` and extracts all analytics.
- `price_bond_from_yield()` inverts the yield–price relationship.


---

## 3. Par-Par Asset Swap

### What is it?

A par-par asset swap converts a fixed-rate bond into a synthetic
floating-rate position.  It is a package of (a) the bond and (b) an
interest rate swap, structured so that the bond is exchanged at par.

```
         +------- bond coupons -------->
Investor                                    Swap Dealer
         <--- LIBOR/Euribor + s --------
```

### Structure

**At inception (t = 0):**
- The investor buys the bond at its market dirty price.
- The dealer pays par (100) to the investor.
- **Upfront payment** = `100 - Dirty_market`.
  - Bond at premium (dirty > 100): investor pays the dealer.
  - Bond at discount (dirty < 100): investor receives cash.

**During the life:**
- *Fixed leg*: investor passes the bond's coupons to the dealer.
- *Floating leg*: dealer pays LIBOR + *s* to the investor.

**At maturity:**
- Bond redeems at 100; investor returns this to the dealer.

### Swap value at time 0

At the fair spread, the swap NPV is zero by construction.  The **upfront
payment** `(100 - dirty)` is a real day-0 cash exchange that distinguishes
par-par from a market-value asset swap.

### ASW spread derivation

From the investor's perspective, setting NPV = 0:

```
  (100 - Dirty) + PV(bond cashflows) = PV(LIBOR FRN at par) + s * A
```

Since a par LIBOR FRN is worth 100 at the LIBOR curve, the 100s cancel:

```
  PV(bond cashflows at swap curve) - Dirty_market = s * A
```

Solving:

```
  s = (PV_bond_at_swap_curve - Dirty_market) / (Face * Annuity)
```

| Term | Meaning |
|---|---|
| PV_bond_at_swap_curve | PV of all bond cashflows discounted at the swap curve (= theoretical dirty price with no credit spread) |
| Dirty_market | Observed market dirty price |
| Face | Bond face value (100) |
| Annuity | Floating-leg annuity = `sum(tau_i * DF_i)` over each floating period |

### Two implementations

- **`ql.AssetSwap`**: QuantLib's built-in class; takes clean price, handles internals.
- **Manual replication**: iterates over bond cashflows and floating schedule using discount factors.  Both match to < 0.0001 bps.

### Code: `asset_swap.py`


---

## 4. Z-Spread

The Z-spread is a pure discounting measure: the constant spread *z* added
to every zero rate on the swap curve such that the shifted curve reprices
the bond to its market price:

```
  Dirty_market = sum_i [ c_i * DF(t_i) * exp(-z * t_i) ]
               + N * DF(T) * exp(-z * T)
```

### Z-spread vs ASW spread

| Feature | ASW Spread | Z-Spread |
|---|---|---|
| Structure | Requires a swap (floating leg, annuity) | Pure discount-factor shift |
| Depends on | Floating schedule, day counts, par-par upfront | Only bond cashflow dates |
| Typical use | Trading / relative value | Credit analysis, spread curves |

For bonds near par the two are similar; the gap widens for deep premium/
discount bonds or very long maturities.


---

## 5. Interest Rate Swap (IRS)

### What is it?

An IRS exchanges fixed-rate payments for floating-rate payments in the
**same currency** on the **same notional**.  There is **no exchange of
principal** — only the net interest difference is settled each period.

```
       +--- fixed rate (e.g. 3.00%) --->
Party A                                     Party B
       <--- LIBOR/Euribor + spread -----
```

- **Payer swap**: Party A *pays* fixed, *receives* floating.
- **Receiver swap**: Party A *receives* fixed, *pays* floating.

### Valuation

Each leg is a stream of cashflows discounted at the yield curve.

**Fixed leg PV** (pay side):

```
  PV_fixed = N * R * sum_i [ tau_i * DF(t_i) ]
           = N * R * Annuity_fixed
```

where `R` is the fixed rate and `tau_i` the day-count fraction for period
*i*.

**Floating leg PV** (receive side):

```
  PV_float = N * sum_i [ F_i * tau_i * DF(t_i) ]
```

where `F_i` is the forward rate for period *i*, projected from the curve:

```
  F_i = [ DF(t_{i-1}) / DF(t_i) - 1 ] / tau_i
```

In a single-curve framework, the PV of a floating leg paying flat LIBOR
simplifies to:

```
  PV_float_flat = N * [ DF(t_0) - DF(T) ]
```

(a telescoping sum — the forward payments collapse to the difference
between the first and last discount factors).

### Par (fair) rate

The fair rate is the fixed rate at which the swap has zero NPV:

```
  R_fair = PV_float / (N * Annuity_fixed)
```

### DV01 / BPV

The fixed-leg BPS is the change in the fixed leg's PV for a 1 bp increase
in the fixed rate.  It approximates the swap's interest-rate sensitivity:

```
  BPS_fixed ≈ N * 0.0001 * Annuity_fixed
```

### Code: `swap_pricer.py`

- `build_vanilla_swap()` constructs a `ql.VanillaSwap`.
- `price_irs()` attaches a `DiscountingSwapEngine` and returns NPV, fair
  rate, fair spread, and leg-level BPS.


---

## 6. Fixed-Fixed Cross-Currency Swap

### What is it?

A fixed-fixed XCCY swap exchanges fixed-rate coupons in **two different
currencies**, with **notional exchange at start and maturity**.

```
       +--- EUR fixed coupons -------->
Party A                                     Party B
       <--- USD fixed coupons ---------

  t=0: A pays EUR notional to B, receives USD notional
  t=T: reverse notional exchange
```

### Why it exists

A corporate that has issued USD-denominated bonds but earns EUR revenue can
use a fixed-fixed XCCY swap to convert its USD fixed obligations into EUR
fixed obligations — eliminating FX mismatch.

### Valuation

Each leg is valued in its own currency using its own discount curve:

```
  PV_EUR = -N_EUR * DF_EUR(t_eff) + sum [ EUR_coupon_i * DF_EUR(t_i) ] + N_EUR * DF_EUR(T)
  PV_USD = -N_USD * DF_USD(t_eff) + sum [ USD_coupon_i * DF_USD(t_i) ] + N_USD * DF_USD(T)
```

To compute NPV in a single currency, convert the foreign leg PV using the
**spot FX rate**:

```
  NPV_EUR = PV_USD * (1 / EUR_USD_spot) - PV_EUR
```

(We receive USD, pay EUR; positive NPV means we are in the money.)

### Fair rate

The fair domestic (EUR) fixed rate is the rate that makes NPV = 0:

```
  R_EUR_fair = (PV_USD_in_EUR - PV_EUR_notional_exchanges) / EUR_coupon_annuity
```

### Notional exchange

The notionals are set at inception so that they are equivalent at the
**spot FX rate**:

```
  N_USD = N_EUR * EUR_USD_spot
```

At maturity the same notionals are re-exchanged, regardless of where the
FX rate has moved — this is a key source of FX risk in XCCY swaps.

### Code: `xccy_swap_pricer.py` → `price_fixed_fixed_xccy_swap()`


---

## 7. Fixed-Floating Cross-Currency Swap

### What is it?

One leg pays a fixed rate, the other pays a floating rate + spread, each in
a different currency.  Notional exchange occurs at start and maturity.

```
       +--- EUR fixed coupons -------->
Party A                                     Party B
       <--- USD LIBOR + spread --------
```

### Typical use case

An issuer has fixed-rate EUR debt but wants floating-rate USD exposure (or
vice versa).  This swap achieves both the currency conversion and the
fixed-to-floating conversion in a single instrument.

### Valuation

- **Fixed leg**: valued the same as in a fixed-fixed XCCY swap.
- **Floating leg**: each period's payment is projected using forward rates
  from the USD curve:

```
  Payment_i = N_USD * (F_i + spread) * tau_i
```

where `F_i = [DF_USD(t_{i-1}) / DF_USD(t_i) - 1] / tau_i` is the forward
LIBOR rate for period *i*.

NPV is computed by converting the foreign floating-leg PV to domestic
currency:

```
  NPV_EUR = PV_USD_float * (1 / EUR_USD_spot) - PV_EUR_fixed
```

### Fair rate

Same as fixed-fixed: the domestic fixed rate that zeroes the NPV.

### Code: `xccy_swap_pricer.py` → `price_fixed_floating_xccy_swap()`


---

## 8. Floating-Floating Cross-Currency Basis Swap

### What is it?

Both legs pay a floating rate, each in a different currency, with notional
exchange.  One leg (typically the non-USD leg) includes a **spread** — the
*cross-currency basis*.

```
       +--- EUR Euribor + basis ------>
Party A                                     Party B
       <--- USD LIBOR flat ------------
```

### The cross-currency basis

The basis is the most important output.  It represents the **relative cost
of funding in one currency versus another**.

- **Negative basis** (e.g. -15 bps on the EUR leg): EUR funding is cheap
  relative to USD.  EUR holders "pay" to swap into USD.
- **Positive basis**: EUR funding is expensive; EUR holders are compensated
  for swapping into USD.

The basis reflects supply/demand imbalances in the FX swap market, credit
risk differences between banking systems, and central bank policy.

### Valuation

Both legs are projected using their respective curves:

```
  EUR payment_i = N_EUR * (Euribor_fwd_i + basis) * tau_i
  USD payment_i = N_USD * (LIBOR_fwd_i + 0) * tau_i
```

Each leg also includes the initial and final notional exchanges.

The PV of a floating leg paying its own index flat is approximately zero
(by construction of the bootstrapped curve):

```
  PV(floating flat) ≈ 0
```

Therefore the PV of the spread is approximately:

```
  PV(spread) ≈ N * spread * Annuity_float
```

### Fair basis

The fair basis is the spread on the domestic leg that zeroes the NPV:

```
  basis_fair = (PV_USD_in_EUR - PV_EUR_flat) / (N_EUR * Annuity_EUR)
```

In a stylised single-curve world with no credit or liquidity
frictions, the fair basis is zero.  In reality, the XCCY basis is a
market-observed quantity (typically -10 to -30 bps for EUR/USD) that
reflects real-world funding asymmetries.

### Code: `xccy_swap_pricer.py` → `price_float_float_xccy_swap()`


---

## 9. Implementation Notes

### Single-curve vs multi-curve

This project uses a **single-curve** setup: the same curve is used for both
**discounting** and **forward-rate projection**.  In production systems a
multi-curve framework is standard (OIS discounting + separate IBOR
projection curves), but the single-curve approach is clearer for learning.

### Cross-currency swaps: manual construction

QuantLib does not provide a single high-level class for all XCCY swap
variants.  Instead, we build each leg's cashflows manually:

1. Generate a coupon schedule.
2. For fixed legs: `coupon = notional * rate * day_count_fraction`.
3. For floating legs: project forward rates from the curve,
   `payment = notional * (forward + spread) * day_count_fraction`.
4. Include notional exchanges at start (negative) and end (positive).
5. Discount each leg with its own currency's curve.
6. Convert the foreign-leg PV to the domestic currency at the spot FX rate.

This is transparent and educational; each cashflow is individually visible.

### Conventions summary

| Parameter | EUR | USD |
|---|---|---|
| Spot settlement | T+2 | T+2 |
| Fixed frequency | Annual | Semi-annual |
| Fixed day count | 30/360 | 30/360 |
| Float index | Euribor 6M | LIBOR 3M |
| Float day count | ACT/360 | ACT/360 |
| Calendar | TARGET | US Federal Reserve |


---

## 10. File Structure

| File | Contents |
|---|---|
| `curves.py` | Yield curve bootstrapping — EUR and USD curves from deposits + swaps |
| `bond_pricer.py` | Fixed-rate bond construction, pricing, YTM, duration, convexity |
| `asset_swap.py` | Par-par asset swap (ql.AssetSwap + manual replication), Z-spread |
| `swap_pricer.py` | Interest rate swap (IRS) using ql.VanillaSwap |
| `xccy_swap_pricer.py` | Cross-currency swaps: fixed-fixed, fixed-floating, float-float basis |
| `plots.py` | Matplotlib figures (rate curves, spread vs price, cashflows) |
| `main.py` | End-to-end example demonstrating every instrument |
| `explanation.md` | This file — theory and derivations for all instruments |
