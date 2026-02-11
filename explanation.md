# Bond Pricing and Par-Par Asset Swaps — Calculation Guide

This document explains the calculations implemented in this project, step by
step, with the underlying financial intuition.

---

## 1. Yield Curve Construction

We bootstrap a EUR discount curve from two types of market instruments:

| Instrument | Tenors | Day Count | Role |
|---|---|---|---|
| Deposits (Euribor) | 1M, 3M, 6M | ACT/360 | Short end (< 1 year) |
| Interest Rate Swaps | 1Y -- 30Y | 30/360 fixed, ACT/360 float | Long end |

**Method**: Piecewise log-cubic interpolation on discount factors
(`PiecewiseLogCubicDiscount`), which ensures smooth forward rates.

From the bootstrapped curve we can extract:

- **Discount factor** DF(T): the present value today of 1 EUR received at
  time T.
- **Zero rate** z(T): the continuously-compounded rate such that
  DF(T) = exp(-z(T) * T).
- **Forward rate** f(T1, T2): the rate implied today for borrowing between
  T1 and T2: f = -ln(DF(T2)/DF(T1)) / (T2-T1).


## 2. Fixed-Rate Bond Pricing

A fixed-rate bond pays periodic coupons c on face value N and returns N at
maturity T.

### Dirty (full) price

The dirty price is the present value of all remaining cashflows:

```
Dirty = sum_{i} c_i * DF(t_i)  +  N * DF(T)
```

where c_i is the coupon amount on date t_i (adjusted for day-count
conventions) and DF(t_i) is the discount factor to that date.

### Clean price

The clean price strips out accrued interest:

```
Clean = Dirty - Accrued
```

Accrued interest is the pro-rata share of the current coupon period that has
already elapsed.

### Yield to maturity (YTM)

The YTM y is the single discount rate that reprices the bond:

```
Dirty = sum_{i} c_i / (1 + y/f)^{f*t_i}  +  N / (1 + y/f)^{f*T}
```

where f is the compounding frequency (1 for annual).  It is found by
root-finding (Newton-Raphson in QuantLib).

### Risk measures

| Measure | Formula | Interpretation |
|---|---|---|
| **Modified duration** | D_mod = -(1/P) * dP/dy | % price change per 1% yield move |
| **Macaulay duration** | D_mac = D_mod * (1 + y/f) | Weighted-average time to cashflows |
| **Convexity** | C = (1/P) * d^2P/dy^2 | Curvature of the price-yield relationship |
| **BPV (DV01)** | BPV = D_mod * P / 10000 | Absolute price change per 1 bp yield move |


## 3. Par-Par Asset Swap

### What is it?

A par-par asset swap converts a fixed-rate bond into a synthetic
floating-rate position.  The structure:

```
         +-------- bond coupons -------->
Investor                                    Swap Dealer
         <---- LIBOR/Euribor + s --------
```

**At inception (t = 0):**
- The investor buys the bond at its market dirty price.
- The dealer pays the investor par (100).
- The net upfront payment exchanged is:

```
  Upfront = 100 - Dirty_market
```

If the bond trades above par (dirty > 100), the investor pays the
difference to the dealer.  If below par, the investor receives cash.

**During the life:**
- *Fixed leg*: the investor passes through the bond's coupons to the dealer.
- *Floating leg*: the dealer pays LIBOR + s (the **ASW spread**) on a par
  notional to the investor.

**At maturity:**
- The bond redeems at 100; the investor returns this to the dealer.

The net effect: the investor has swapped a fixed-rate bond for a
floating-rate note at par, with credit exposure embedded in the ASW spread.

### The ASW spread

The asset-swap spread *s* is the value that makes the package NPV-neutral
at inception.

### Swap value at time 0

At initiation with the fair spread, the swap NPV is zero by construction.
However, the **upfront payment** (100 - dirty) is a real cash exchange that
distinguishes the par-par structure from a market-value asset swap.

- If the bond trades at a **premium** (dirty > 100): upfront < 0, i.e. the
  investor pays the dealer.
- If the bond trades at a **discount** (dirty < 100): upfront > 0, i.e. the
  investor receives cash.

This upfront compensates for the difference between the bond's market value
and par, so that the ongoing floating payments can be referenced to a par
notional.

### Derivation

From the investor's perspective, setting NPV = 0:

```
  (100 - Dirty) + PV(bond cashflows) = PV(LIBOR FRN at par) + s * A
```

A LIBOR FRN at par is worth 100 when discounted at the same LIBOR curve, so
PV(LIBOR FRN at par) = 100.  The 100s cancel:

```
  PV(bond cashflows) - Dirty = s * A
```

Solving:

```
  s = (PV_bond_at_swap_curve - Dirty_market) / (Face * Annuity)
```

where:

- **PV_bond_at_swap_curve** = sum of all bond cashflows (coupons +
  redemption) discounted at the swap curve.  This is the *theoretical*
  dirty price if the bond had no credit spread.
- **Dirty_market** = the observed market dirty price.
- **Face** = notional (100).
- **Annuity** = floating-leg annuity factor = sum(tau_i * DF_i) for each
  floating period [t_{i-1}, t_i], where tau_i is the day-count fraction
  and DF_i is the discount factor from settlement to t_i.

### Numerical example

For our 3.25% bond with market dirty price 103.449:

```
  PV_bond_at_swap_curve  = 104.949   (theoretical dirty, no credit spread)
  Dirty_market           = 103.449   (market dirty, includes credit discount)
  Upfront                = 100 - 103.449 = -3.449  (investor pays dealer)
  Numerator              = 104.949 - 103.449 = 1.500
  Floating annuity       = 7.327
  ASW spread             = 1.500 / (100 * 7.327) = 0.002047 = 20.47 bps
```


## 4. Z-Spread (for comparison)

The Z-spread is the constant spread *z* added to every zero rate on the
swap curve such that discounting the bond's cashflows at the shifted curve
reproduces the market price:

```
  Dirty_market = sum_{i} c_i * DF(t_i) * exp(-z * t_i)  +  N * DF(T) * exp(-z * T)
```

The Z-spread is a pure discounting measure and does not involve any swap
structure.  It will generally differ slightly from the ASW spread because:

- The ASW spread is defined relative to a floating-leg annuity (which
  depends on the floating schedule and day counts).
- The Z-spread applies a uniform shift to continuous zero rates.

For bonds close to par, the two spreads are similar.  The difference grows
for bonds trading far from par or with long maturities.


## 5. Implementation: Two Approaches

### Approach A: `ql.AssetSwap` (QuantLib built-in)

QuantLib's `AssetSwap` class constructs the full swap structure internally:
- Fixed leg = bond's cashflows (coupons + redemption).
- Floating leg = LIBOR + spread + upfront cashflow.
- Engine: `DiscountingSwapEngine`.
- Output: `fairSpread()` gives the par-par ASW spread.

Note: `ql.AssetSwap` takes the **clean** price as input; we convert from
dirty by subtracting accrued interest.

### Approach B: Manual replication (first principles)

We compute the same spread without `ql.AssetSwap` by:

1. **Pricing the bond at the swap curve**: iterate over
   `bond.cashflows()`, discount each at `curve.discount(date)`,
   sum to get PV at evaluation date, then express at settlement date.

2. **Computing the floating annuity**: build a 6-month schedule from
   settlement to maturity; for each period compute
   `tau * DF(end) / DF(settlement)`.

3. **Solving**: `s = (PV_bond - dirty) / (face * annuity)`.

Both approaches produce identical results (verified to < 0.0001 bps).


## 6. File Structure

| File | Contents |
|---|---|
| `curves.py` | Yield curve bootstrapping (deposits + swaps) |
| `bond_pricer.py` | Fixed-rate bond construction, pricing, analytics |
| `asset_swap.py` | Par-par ASW (ql.AssetSwap + manual replication), Z-spread |
| `plots.py` | Matplotlib figures (curves, spreads, cashflows) |
| `main.py` | End-to-end example tying everything together |
| `explanation.md` | This file |
