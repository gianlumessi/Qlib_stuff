"""
===============================================================
  COUNTERPARTY EXPOSURE PROFILES — PAR-PAR ASSET SWAP
  Fixed-for-Fixed vs Fixed-for-Floating, OIS single-curve
===============================================================

Two swap structures are compared, both on the same Italian BTP:

  FIXED-FOR-FIXED:
    Bank RECEIVES: bond coupon c (fixed)
    Bank PAYS:     K = r_s + ASW (fixed)
    MtM = (c - K) * N * A_rem
    Always one-sided (bank always OTM) because c < K.

  FIXED-FOR-FLOATING:
    Bank RECEIVES: bond coupon c (fixed)
    Bank PAYS:     OIS forward + ASW (floating)
    MtM = (c - ASW) * N * A_rem - N * (1 - DF_fwd(obs, T))
    Two-sided: rate falls → bank gains (fixed > float);
               rate rises → bank loses (fixed < float).

Both use the same ASW spread in the single-curve OIS framework:
  ASW = (c - r_s) + (N - P) / (N * A)

EXPOSURE SIMULATION:
  - 10 observation dates (annual coupon dates)
  - Parallel shift to all OIS zero rates: dz ~ N(0, sigma)
  - sigma = 10 bps absolute normal vol
  - 1500 Monte Carlo paths (identical shifts for both structures)
  - EPE, ENE, PFE (95th), NFE (5th)

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

coupon_dates = [d for d in all_schedule_dates[1:] if d > settle]

all_period_starts = all_schedule_dates[:-1]
period_starts = []
for s in all_period_starts:
    end_idx = all_schedule_dates.index(s) + 1
    end_d = all_schedule_dates[end_idx]
    if end_d > settle:
        period_starts.append(s)

# ==============================================================
# [5]  COMPUTE ANNUITY, PAR SWAP RATE, AND ASW
#
#      A = Sigma alpha_i * DF(0, t_i)
#      r_s = (1 - DF(T)) / A
#      ASW = (c - r_s) + (N - P) / (N * A)
#      K = r_s + ASW = c + (N - P) / (N * A)
#
#      In the single-curve OIS framework, the ASW spread is the same
#      whether the bank pays fixed (K) or floating (OIS + ASW).
# ==============================================================
base_curve = build_ois_curve(OIS_ZEROS)

annuity = 0.0
for s, e in zip(period_starts, coupon_dates):
    alpha = bond_dc.yearFraction(s, e)
    df    = base_curve.discount(e)
    annuity += alpha * df

df_T = base_curve.discount(BOND_MATURITY)
r_s  = (1.0 - df_T) / annuity
ASW  = (COUPON_RATE - r_s) + (N_PCT - BBG_DIRTY_PRICE) / (N_PCT * annuity)
K    = r_s + ASW

upfront = BBG_DIRTY_PRICE - N_PCT   # P - N (negative for discount bond)

# Verify inception MtM for both structures = P - N
fix_fix_mtm0   = (COUPON_RATE - K) * N_PCT * annuity
fix_float_mtm0 = (COUPON_RATE - ASW) * N_PCT * annuity - N_PCT * (1.0 - df_T)

sep = "=" * 68
print(sep)
print("  COUNTERPARTY EXPOSURE — FIX-FIX vs FIX-FLOAT ASSET SWAP")
print(sep)

print(f"\n[1]  SWAP PARAMETERS AT INCEPTION")
print(f"  Bond coupon c:           {COUPON_RATE*100:.4f}%")
print(f"  OIS par swap rate r_s:   {r_s*100:.4f}%")
print(f"  ASW spread:              {ASW*10000:.2f} bps")
print(f"  Fix-fix: bank pays K:    {K*100:.4f}%")
print(f"  Fix-float: bank pays:    OIS + {ASW*10000:.2f} bps")
print(f"  Annuity A:               {annuity:.6f}")
print(f"  DF(0,T):                 {df_T:.6f}")
print(f"  Dirty price P:           {BBG_DIRTY_PRICE:.4f}%")
print(f"  Upfront (P - N):         {upfront:.4f}%")
print(f"  Fix-fix  MtM at t=0:     {fix_fix_mtm0:.4f}%  (should be {upfront:.4f}%)")
print(f"  Fix-float MtM at t=0:    {fix_float_mtm0:.4f}%  (should be {upfront:.4f}%)")

# ==============================================================
# [6]  TENOR GRID — t=0 (deterministic) + 10 annual coupon dates
# ==============================================================
n_tenors = 10
step = max(1, len(coupon_dates) // n_tenors)
sim_tenor_dates = coupon_dates[step-1::step][:n_tenors]

# Prepend today as the t=0 observation point
tenor_dates = [today] + sim_tenor_dates
tenor_years = [0.0] + [ois_dc.yearFraction(today, d) for d in sim_tenor_dates]

print(f"\n[2]  OBSERVATION DATES ({len(tenor_dates)} tenors)")
for i, (d, y) in enumerate(zip(tenor_dates, tenor_years)):
    label = "  <- deterministic (no shift)" if y == 0.0 else ""
    print(f"    {i+1:>2}. {d}  ({y:.2f}Y){label}")

# ==============================================================
# [7]  GENERATE SHARED MONTE CARLO SHIFTS
#      Same random paths used for both structures so the comparison
#      isolates the structural difference, not sampling noise.
#      Column 0 (t=0) is forced to zero — the inception MtM is a
#      known present value, not a simulated one.
# ==============================================================
shifts = np.random.normal(0.0, SIGMA, size=(N_PATHS, len(tenor_dates)))
shifts[:, 0] = 0.0

print(f"\n[3]  MONTE CARLO SIMULATION")
print(f"  Paths: {N_PATHS},  Sigma: {SIGMA*10000:.0f} bps,  Tenors: {len(tenor_dates)}"
      f" (t=0 deterministic + {len(sim_tenor_dates)} simulated)")

# ==============================================================
# [8]  FIXED-FOR-FIXED EXPOSURE SIMULATION
#
#      MtM = (c - K) * N * A_rem(shifted)
#
#      Since c < K, MtM is always negative regardless of shift.
#      The annuity magnitude changes with rates but the sign cannot.
# ==============================================================
mtm_fixfix = np.zeros((N_PATHS, len(tenor_dates)))
coupon_diff_ff = COUPON_RATE - K

for t_idx, obs_date in enumerate(tenor_dates):
    rem_coupons = [(s, e) for s, e in zip(period_starts, coupon_dates) if e > obs_date]
    if not rem_coupons:
        continue

    for path in range(N_PATHS):
        shifted_curve = build_ois_curve([z + shifts[path, t_idx] for z in OIS_ZEROS])
        df_obs = shifted_curve.discount(obs_date)

        rem_annuity = sum(
            bond_dc.yearFraction(s, e) * shifted_curve.discount(e) / df_obs
            for s, e in rem_coupons
        )
        mtm_fixfix[path, t_idx] = coupon_diff_ff * N_PCT * rem_annuity

print("  Fix-fix simulation complete.")

# ==============================================================
# [9]  FIXED-FOR-FLOATING EXPOSURE SIMULATION
#
#      MtM = (c - ASW) * N * A_rem  -  N * (1 - DF_fwd(obs, T))
#
#      First term:  PV of fixed coupons net of spread, discounted
#      Second term: PV of OIS floating coupons (telescopes to 1-DF)
#
#      When rates FALL:
#        A_rem increases, DF_fwd(T) increases → (1-DF_fwd) shrinks
#        → fixed leg gains value, floating leg pays less → MtM rises
#
#      When rates RISE:
#        A_rem decreases, DF_fwd(T) decreases → (1-DF_fwd) grows
#        → fixed leg loses value, floating leg pays more → MtM falls
#
#      This creates two-sided exposure (classic receiver swap profile).
# ==============================================================
mtm_fixflt = np.zeros((N_PATHS, len(tenor_dates)))
c_minus_asw = COUPON_RATE - ASW

for t_idx, obs_date in enumerate(tenor_dates):
    rem_coupons = [(s, e) for s, e in zip(period_starts, coupon_dates) if e > obs_date]
    if not rem_coupons:
        continue

    for path in range(N_PATHS):
        shifted_curve = build_ois_curve([z + shifts[path, t_idx] for z in OIS_ZEROS])
        df_obs = shifted_curve.discount(obs_date)

        # Remaining annuity (forward DFs from obs_date)
        rem_annuity = sum(
            bond_dc.yearFraction(s, e) * shifted_curve.discount(e) / df_obs
            for s, e in rem_coupons
        )

        # Forward DF from obs_date to maturity
        df_fwd_T = shifted_curve.discount(BOND_MATURITY) / df_obs

        # MtM = PV(fixed received) - PV(floating paid)
        # PV(fixed) = c * N * A_rem
        # PV(float) = N * (1 - DF_fwd_T) + ASW * N * A_rem
        # MtM = (c - ASW) * N * A_rem - N * (1 - DF_fwd_T)
        mtm_fixflt[path, t_idx] = c_minus_asw * N_PCT * rem_annuity \
                                  - N_PCT * (1.0 - df_fwd_T)

print("  Fix-float simulation complete.")

# ==============================================================
# [10]  EXPOSURE METRICS FOR BOTH STRUCTURES
#
#       Column 0 (t=0) has shift=0 for all paths, so EPE/ENE/PFE/NFE
#       at t=0 all collapse to the single deterministic inception MtM.
# ==============================================================
def compute_exposure_metrics(mtm):
    epe = np.maximum(mtm, 0.0).mean(axis=0)
    ene = np.minimum(mtm, 0.0).mean(axis=0)
    pfe = np.percentile(mtm, 95, axis=0)
    nfe = np.percentile(mtm, 5, axis=0)
    return epe, ene, pfe, nfe

EPE_ff, ENE_ff, PFE_ff, NFE_ff = compute_exposure_metrics(mtm_fixfix)
EPE_fl, ENE_fl, PFE_fl, NFE_fl = compute_exposure_metrics(mtm_fixflt)

print(f"\n[4a] FIX-FIX EXPOSURE (% of notional, bank perspective)")
print(f"  {'Tenor':>8}  {'EPE':>8}  {'ENE':>8}  {'PFE 95%':>10}  {'NFE 5%':>10}")
print(f"  {'-'*50}")
for i, y in enumerate(tenor_years):
    print(f"  {y:>7.2f}Y  {EPE_ff[i]:>8.4f}  {ENE_ff[i]:>8.4f}  {PFE_ff[i]:>10.4f}  {NFE_ff[i]:>10.4f}"
          + ("  <- deterministic" if y == 0.0 else ""))

print(f"\n  EPE ~ 0: c < K so bank is always OTM (one-sided exposure).")

print(f"\n[4b] FIX-FLOAT EXPOSURE (% of notional, bank perspective)")
print(f"  {'Tenor':>8}  {'EPE':>8}  {'ENE':>8}  {'PFE 95%':>10}  {'NFE 5%':>10}")
print(f"  {'-'*50}")
for i, y in enumerate(tenor_years):
    print(f"  {y:>7.2f}Y  {EPE_fl[i]:>8.4f}  {ENE_fl[i]:>8.4f}  {PFE_fl[i]:>10.4f}  {NFE_fl[i]:>10.4f}"
          + ("  <- deterministic" if y == 0.0 else ""))

print(f"\n  Two-sided: rates down → EPE > 0 (bank gains on fixed leg).")
print(f"             rates up   → ENE < 0 (floating leg costs more).")

# ==============================================================
# [11]  SIDE-BY-SIDE PLOT
# ==============================================================
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6), sharey=True)

# ---- Left: Fixed-for-Fixed ----
for p in range(N_PATHS):
    ax1.plot(tenor_years, mtm_fixfix[p, :], color="grey", alpha=0.05, lw=0.5)
ax1.plot(tenor_years, EPE_ff, "b-o",  lw=2, ms=5, label="EPE", zorder=5)
ax1.plot(tenor_years, ENE_ff, "r-o",  lw=2, ms=5, label="ENE", zorder=5)
ax1.plot(tenor_years, PFE_ff, "b--s", lw=1.5, ms=4, label="PFE (95%)", zorder=5)
ax1.plot(tenor_years, NFE_ff, "r--s", lw=1.5, ms=4, label="NFE (5%)", zorder=5)
ax1.axhline(0, color="grey", lw=0.8)
ax1.set_xlabel("Time (years)", fontsize=11)
ax1.set_ylabel("Exposure (% of notional)", fontsize=11)
ax1.set_title(
    "Fixed-for-Fixed\n"
    f"Bank receives {COUPON_RATE*100:.2f}%, pays {K*100:.2f}% fixed",
    fontsize=11,
)
ax1.legend(loc="best", fontsize=9)
ax1.grid(True, alpha=0.3)
ax1.set_xlim(0, tenor_years[-1] + 0.5)

# ---- Right: Fixed-for-Floating ----
for p in range(N_PATHS):
    ax2.plot(tenor_years, mtm_fixflt[p, :], color="grey", alpha=0.05, lw=0.5)
ax2.plot(tenor_years, EPE_fl, "b-o",  lw=2, ms=5, label="EPE", zorder=5)
ax2.plot(tenor_years, ENE_fl, "r-o",  lw=2, ms=5, label="ENE", zorder=5)
ax2.plot(tenor_years, PFE_fl, "b--s", lw=1.5, ms=4, label="PFE (95%)", zorder=5)
ax2.plot(tenor_years, NFE_fl, "r--s", lw=1.5, ms=4, label="NFE (5%)", zorder=5)
ax2.axhline(0, color="grey", lw=0.8)
ax2.set_xlabel("Time (years)", fontsize=11)
ax2.set_title(
    "Fixed-for-Floating\n"
    f"Bank receives {COUPON_RATE*100:.2f}% fixed, pays OIS + {ASW*10000:.0f}bps",
    fontsize=11,
)
ax2.legend(loc="best", fontsize=9)
ax2.grid(True, alpha=0.3)
ax2.set_xlim(0, tenor_years[-1] + 0.5)

fig.suptitle(
    f"Counterparty Exposure — Par-Par Asset Swap on BTP | "
    f"{N_PATHS} paths | $\\sigma$ = {SIGMA*10000:.0f} bps",
    fontsize=12, fontweight="bold", y=1.02,
)
plt.tight_layout()
plt.savefig("plots/exposure_asw.png", dpi=150, bbox_inches="tight")
print(f"\n  Plot saved to plots/exposure_asw.png")
print(sep)
