"""
===============================================================
  COUNTERPARTY EXPOSURE PROFILE — FIXED-FOR-FIXED ASSET SWAP
  Par-par asset swap on Italian BTP, OIS single-curve framework
===============================================================

STRUCTURE (Bank's perspective):
  - Client pays par (N = 100) to the Bank
  - Bank buys bond at dirty price P in the market
  - Upfront to bank: N - P (positive for discount bond)
  - Swap legs (same semi-annual schedule as bond coupons):
      Bank RECEIVES: bond coupon rate c on notional N
      Bank PAYS:     fixed rate K = (r_s + ASW) on notional N
  - Both legs exchange notional N at maturity (these cancel in MtM)
  - ASW is solved so that: (N - P) + swap_MtM_0 = 0
  - swap_MtM_0 = (c - K) * N * A = -(N - P) = P - N

  Since c < K (bank pays more than it receives), the swap MtM is
  always NEGATIVE from the bank's perspective.  The bank compensated
  for this via the upfront (N - P).

  After inception, the exposure profile is one-sided:
    EPE = 0  (bank never has positive exposure on the swap)
    ENE < 0  (bank is always out-of-the-money)

  This correctly reflects that in a par-par ASW, the BANK has no
  counterparty credit risk — it is the CLIENT who bears exposure.

EXPOSURE SIMULATION:
  - 10 observation dates (annual coupon payment dates)
  - Parallel shift to all OIS zero rates: dz ~ N(0, sigma)
  - sigma = 10% (= 0.001, i.e. 10 basis points absolute normal vol)
  - 1500 Monte Carlo paths
  - MtM = PV(received leg) - PV(paid leg)  [excl. upfront, excl. redemption]

REQUIREMENTS:
  pip install QuantLib numpy matplotlib
===============================================================
"""

import QuantLib as ql
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ==============================================================
# [1]  CONFIGURATION — same BTP and OIS curve as Asset_swap_BTP.py
# ==============================================================
COUPON_RATE      = 0.0345
COUPON_FREQUENCY = ql.Semiannual
BOND_MATURITY    = ql.Date(1, ql.February, 2036)
BOND_LAST_COUPON_DATE = ql.Date(1, ql.February, 2026)
BBG_DIRTY_PRICE  = 98.4511
N_PCT            = 100.0

OIS_TENORS = ["1W", "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y"]
OIS_ZEROS  = [0.01931, 0.023711, 0.02448, 0.02475, 0.025132,
              0.02558, 0.0260515, 0.026589, 0.0271, 0.027626, 0.02814]

# Monte Carlo parameters
N_PATHS = 1500
SIGMA   = 0.001   # 10 bps absolute normal vol for parallel shifts
np.random.seed(42)

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
# [3]  HELPER: BUILD OIS CURVE FROM ZERO RATES
# ==============================================================
def build_ois_curve(zeros):
    """Build a ZeroCurve from the OIS pillar rates (continuously compounded)."""
    pillar_dates = [today] + [calendar.advance(today, ql.Period(t)) for t in OIS_TENORS]
    rates = [zeros[0]] + list(zeros)
    curve = ql.ZeroCurve(
        pillar_dates, rates, ois_dc, calendar,
        ql.Linear(), ql.Continuous, ql.Annual,
    )
    curve.enableExtrapolation()
    return curve

# ==============================================================
# [4]  BUILD BOND SCHEDULE AND EXTRACT COUPON DATES
# ==============================================================
schedule = ql.Schedule(
    BOND_LAST_COUPON_DATE, BOND_MATURITY,
    ql.Period(COUPON_FREQUENCY),
    calendar,
    ql.ModifiedFollowing, ql.ModifiedFollowing,
    ql.DateGeneration.Backward, False,
)

all_schedule_dates = list(schedule)

# Coupon payment dates (all dates after the first schedule date)
# Only future ones (after settlement) contribute to the swap
coupon_dates = [d for d in all_schedule_dates[1:] if d > settle]

# Period start dates for year-fraction computation:
# First period starts at BOND_LAST_COUPON_DATE (matching the reference),
# subsequent periods start at the previous coupon date.
all_period_starts = all_schedule_dates[:-1]  # all but last = period start dates
period_starts = []
for s in all_period_starts:
    end_idx = all_schedule_dates.index(s) + 1
    end_d = all_schedule_dates[end_idx]
    if end_d > settle:
        period_starts.append(s)

# ==============================================================
# [5]  COMPUTE ANNUITY, PAR SWAP RATE, AND ASW AT INCEPTION
#
#      A = Σ alpha_i * DF_OIS(0, t_i)   over all future coupon dates
#      r_s = (1 - DF(T)) / A
#      ASW = (c - r_s) + (N - P) / (N * A)
#      K = r_s + ASW = c + (N - P) / (N * A)
#      Swap MtM at t=0 = (c - K) * N * A = -(N - P) = P - N
# ==============================================================
base_curve = build_ois_curve(OIS_ZEROS)

annuity = 0.0
annuity_details = []
for s, e in zip(period_starts, coupon_dates):
    alpha = bond_dc.yearFraction(s, e)
    df    = base_curve.discount(e)
    annuity += alpha * df
    annuity_details.append((e, alpha, df, alpha * df))

df_T = base_curve.discount(BOND_MATURITY)
r_s  = (1.0 - df_T) / annuity
ASW  = (COUPON_RATE - r_s) + (N_PCT - BBG_DIRTY_PRICE) / (N_PCT * annuity)

# Fixed rate the bank pays
K = r_s + ASW  # equivalently: K = c + (N - P) / (N * A)

# Verify MtM at inception = P - N (the swap starts at negative value for bank)
swap_mtm_0 = (COUPON_RATE - K) * N_PCT * annuity
upfront = BBG_DIRTY_PRICE - N_PCT   # = P - N (negative for discount bond)

print("=" * 68)
print("  FIXED-FOR-FIXED ASSET SWAP — COUNTERPARTY EXPOSURE")
print("=" * 68)

print(f"\n[1]  SWAP PARAMETERS AT INCEPTION")
print(f"  Bond coupon c:           {COUPON_RATE*100:.4f}%")
print(f"  OIS par swap rate r_s:   {r_s*100:.4f}%")
print(f"  ASW spread:              {ASW*10000:.2f} bps")
print(f"  Bank pays K = r_s+ASW:   {K*100:.4f}%")
print(f"  Annuity A:               {annuity:.6f}")
print(f"  DF(0,T):                 {df_T:.6f}")
print(f"  Dirty price P:           {BBG_DIRTY_PRICE:.4f}%")
print(f"  Upfront (P - N):         {upfront:.4f}%")
print(f"  Swap MtM at t=0:         {swap_mtm_0:.4f}%")
print(f"  Check (should be P-N):   {upfront:.4f}% = {swap_mtm_0:.4f}%  "
      f"{'OK' if abs(swap_mtm_0 - upfront) < 0.001 else 'MISMATCH'}")

# ==============================================================
# [6]  TENOR GRID FOR EXPOSURE OBSERVATION
#      10 equally-spaced points across the swap's remaining life
# ==============================================================
n_tenors = 10
step = max(1, len(coupon_dates) // n_tenors)
tenor_dates = coupon_dates[step-1::step][:n_tenors]
tenor_years = [ois_dc.yearFraction(today, d) for d in tenor_dates]

print(f"\n[2]  OBSERVATION DATES ({len(tenor_dates)} tenors)")
for i, (d, y) in enumerate(zip(tenor_dates, tenor_years)):
    print(f"    {i+1:>2}. {d}  ({y:.2f}Y)")

# ==============================================================
# [7]  MONTE CARLO EXPOSURE SIMULATION
#
#      At each observation date t_k:
#        1. Draw parallel shift dz ~ N(0, sigma)
#        2. Shifted curve: z_new = z_base + dz for all pillars
#        3. Compute remaining annuity A_rem(t_k) on shifted curve
#           (only future coupon dates after t_k)
#        4. MtM = (c - K) * N * A_rem
#           (redemption flows cancel on both legs)
#
#      Since c < K, MtM is always negative — bank has no positive
#      exposure.  The magnitude varies with A_rem as rates shift.
# ==============================================================
print(f"\n[3]  MONTE CARLO SIMULATION")
print(f"  Paths: {N_PATHS},  Sigma: {SIGMA*10000:.0f} bps,  Tenors: {len(tenor_dates)}")

shifts = np.random.normal(0.0, SIGMA, size=(N_PATHS, len(tenor_dates)))
mtm_matrix = np.zeros((N_PATHS, len(tenor_dates)))

coupon_diff = COUPON_RATE - K   # fixed negative spread

for t_idx, obs_date in enumerate(tenor_dates):
    # Remaining coupon dates and their period starts (after obs_date)
    rem_coupons = [(s, e) for s, e in zip(period_starts, coupon_dates) if e > obs_date]

    if not rem_coupons:
        continue

    for path in range(N_PATHS):
        dz = shifts[path, t_idx]
        shifted_zeros = [z + dz for z in OIS_ZEROS]
        shifted_curve = build_ois_curve(shifted_zeros)

        # DF from today to obs_date (for forward DF computation)
        df_obs = shifted_curve.discount(obs_date)

        # Remaining annuity as seen from obs_date (forward DFs)
        rem_annuity = 0.0
        for s, e in rem_coupons:
            alpha = bond_dc.yearFraction(s, e)
            df_e  = shifted_curve.discount(e)
            df_fwd = df_e / df_obs   # forward DF from obs to e
            rem_annuity += alpha * df_fwd

        # MtM of remaining swap (redemptions cancel)
        mtm_matrix[path, t_idx] = coupon_diff * N_PCT * rem_annuity

print("  Simulation complete.")

# ==============================================================
# [8]  EXPOSURE METRICS
#
#      EPE  = E[max(MtM, 0)]         expected positive exposure
#      ENE  = E[min(MtM, 0)]         expected negative exposure
#      PFE  = 95th pctl of MtM       potential future exposure
#      NFE  = 5th pctl of MtM        negative future exposure
# ==============================================================
EPE = np.maximum(mtm_matrix, 0.0).mean(axis=0)
ENE = np.minimum(mtm_matrix, 0.0).mean(axis=0)
PFE = np.percentile(mtm_matrix, 95, axis=0)
NFE = np.percentile(mtm_matrix, 5, axis=0)

print(f"\n[4]  EXPOSURE PROFILE (% of notional, bank perspective)")
print(f"  {'Tenor':>8}  {'EPE':>8}  {'ENE':>8}  {'PFE 95%':>10}  {'NFE 5%':>10}")
print(f"  {'-'*50}")
for i, y in enumerate(tenor_years):
    print(f"  {y:>7.2f}Y  {EPE[i]:>8.4f}  {ENE[i]:>8.4f}  {PFE[i]:>10.4f}  {NFE[i]:>10.4f}")

print(f"\n  Note: EPE ~ 0 because c < K (bank always out-of-the-money).")
print(f"  The CLIENT has the counterparty exposure, not the bank.")

# ==============================================================
# [9]  PLOT
# ==============================================================
fig, ax = plt.subplots(figsize=(10, 6))

ax.plot(tenor_years, EPE, "b-o", linewidth=2, markersize=5, label="EPE (mean of positive MtM)")
ax.plot(tenor_years, ENE, "r-o", linewidth=2, markersize=5, label="ENE (mean of negative MtM)")
ax.plot(tenor_years, PFE, "b--s", linewidth=1.5, markersize=4, label="PFE (95th percentile)")
ax.plot(tenor_years, NFE, "r--s", linewidth=1.5, markersize=4, label="NFE (5th percentile)")
ax.axhline(0, color="grey", linewidth=0.8, linestyle="-")

ax.fill_between(tenor_years, 0, EPE, alpha=0.1, color="blue")
ax.fill_between(tenor_years, ENE, 0, alpha=0.1, color="red")

ax.set_xlabel("Time (years)", fontsize=11)
ax.set_ylabel("Exposure (% of notional)", fontsize=11)
ax.set_title(
    "Counterparty Exposure Profile — Fixed-for-Fixed Par-Par Asset Swap\n"
    f"BTP {COUPON_RATE*100:.2f}% | Bank pays {K*100:.2f}% | "
    f"ASW={ASW*10000:.0f}bps | {N_PATHS} paths | $\\sigma$={SIGMA*10000:.0f}bps",
    fontsize=11,
)
ax.legend(loc="lower right", fontsize=10)
ax.grid(True, alpha=0.3)
ax.set_xlim(0, tenor_years[-1] + 0.5)

plt.tight_layout()
plt.savefig("plots/exposure_asw.png", dpi=150)
print(f"\n  Plot saved to plots/exposure_asw.png")
print("=" * 68)
