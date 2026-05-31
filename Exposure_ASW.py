"""
===============================================================
  COUNTERPARTY EXPOSURE PROFILES — TWO POSITIVE-MtM SWAPS
  OIS single-curve, cumulative random-walk simulation
===============================================================

Two swap structures are compared, both with POSITIVE inception MtM
from the Bank's perspective:

  SWAP 1 — FIX-FLOAT  (Receiver swap, above-par coupon):
    Bank RECEIVES: r_s + 50 bps  (fixed)
    Bank PAYS:     OIS floating
    MtM = R * N * A_rem  -  N * (DF_fwd(obs, s_first) - DF_fwd(obs, T))
    where R = r_s + 0.005  (struck above par → positive inception MtM)
    Two-sided exposure driven by floating leg sensitivity.

  SWAP 2 — FIX-FIX  (Differential swap):
    Bank RECEIVES: 3.50% fixed
    Bank PAYS:     3.00% fixed
    MtM = (c_recv - c_pay) * N * A_rem = 0.50% * N * A_rem
    Always positive (bank always ITM). One-sided exposure.

EXPOSURE SIMULATION:
  - 100 equally spaced observation dates from today to maturity
  - Cumulative normally distributed parallel shifts (random walk):
      shifts[:, 0] = 0
      shifts[:, t] = shifts[:, t-1] + N(0, sigma)
  - sigma = 0.10 (10 pp absolute normal vol per step)
  - 1500 Monte Carlo paths (identical paths for both swaps)
  - Analytical DF shifting: DF_shifted(d) = DF_base(d) * exp(-dz * t_d)
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
N_PCT            = 100.0

OIS_TENORS = ["1W", "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y"]
OIS_ZEROS  = [0.01931, 0.023711, 0.02448, 0.02475, 0.025132,
              0.02558, 0.0260515, 0.026589, 0.0271, 0.027626, 0.02814]

N_PATHS   = 1500
N_TENORS  = 100
SIGMA     = 0.010     # percentage absolute normal vol per step
np.random.seed(42)

# Swap 1 parameters
SPREAD_OVER_PAR = 0.005   # 50 bps above par swap rate

# Swap 2 parameters
C_RECV = 0.035   # Bank receives 3.50%
C_PAY  = 0.030   # Bank pays 3.00%

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
# [3]  BUILD BASE OIS CURVE
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

base_curve = build_ois_curve(OIS_ZEROS)

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
# [5]  COMPUTE ANNUITY AND PAR SWAP RATE
# ==============================================================
annuity = 0.0
for s, e in zip(period_starts, coupon_dates):
    alpha = bond_dc.yearFraction(s, e)
    df    = base_curve.discount(e)
    annuity += alpha * df

df_T = base_curve.discount(BOND_MATURITY)
r_s  = (1.0 - df_T) / annuity

# Swap 1: Bank receives R = r_s + 50 bps
R_SWAP1 = r_s + SPREAD_OVER_PAR

# Inception MtM computations
# Swap 1: MtM = R*N*A - N*(DF(s_first) - DF(T))
#   At inception the floating leg PV = N*(1 - DF(T)) when s_first = settle
#   But we use the first remaining coupon start as s_first.
#   Since we compute from today, DF_fwd(today, s_first) = DF(s_first)/DF(today) = DF(s_first)
df_s_first = base_curve.discount(period_starts[0]) if period_starts[0] > today else 1.0
mtm0_swap1 = R_SWAP1 * N_PCT * annuity - N_PCT * (df_s_first - df_T)

# Swap 2: MtM = (c_recv - c_pay) * N * A_rem
mtm0_swap2 = (C_RECV - C_PAY) * N_PCT * annuity

sep = "=" * 68
print(sep)
print("  COUNTERPARTY EXPOSURE — TWO POSITIVE-MtM SWAPS")
print(sep)

print(f"\n[1]  SWAP PARAMETERS AT INCEPTION")
print(f"  OIS par swap rate r_s:   {r_s*100:.4f}%")
print(f"  Annuity A:               {annuity:.6f}")
print(f"  DF(0,T):                 {df_T:.6f}")
print(f"  DF(0,s_first):           {df_s_first:.6f}")
print(f"\n  SWAP 1 — Fix-Float (Receiver)")
print(f"    Bank receives:         {R_SWAP1*100:.4f}% fixed (r_s + 50 bps)")
print(f"    Bank pays:             OIS floating")
print(f"    Inception MtM:         {mtm0_swap1:.4f}% of notional (positive)")
print(f"\n  SWAP 2 — Fix-Fix (Differential)")
print(f"    Bank receives:         {C_RECV*100:.2f}% fixed")
print(f"    Bank pays:             {C_PAY*100:.2f}% fixed")
print(f"    Inception MtM:         {mtm0_swap2:.4f}% of notional (positive)")

# ==============================================================
# [6]  TENOR GRID — 100 equally spaced from today to maturity
#      t=0 is today (deterministic), rest are simulated
# ==============================================================
maturity_serial = BOND_MATURITY.serialNumber()
today_serial = today.serialNumber()
total_days = maturity_serial - today_serial

tenor_serial = np.linspace(today_serial, maturity_serial, N_TENORS + 1, dtype=int)
tenor_serial = np.unique(tenor_serial)
tenor_dates = [ql.Date(int(s)) for s in tenor_serial]
tenor_years = np.array([ois_dc.yearFraction(today, d) for d in tenor_dates])

print(f"\n[2]  TENOR GRID")
print(f"  {len(tenor_dates)} observation dates from {today} to {BOND_MATURITY}")
print(f"  First 5: {', '.join(str(d) for d in tenor_dates[:5])}")
print(f"  Last 5:  {', '.join(str(d) for d in tenor_dates[-5:])}")
print(f"  tenor_years[0] = {tenor_years[0]:.4f} (deterministic)")
print(f"  tenor_years[-1] = {tenor_years[-1]:.4f}")

# ==============================================================
# [7]  PRE-COMPUTE BASE DISCOUNT FACTORS AND TIME-TO-DATES
#      For analytical shifting: DF_shifted(d) = DF_base(d) * exp(-dz * t_d)
#      This avoids rebuilding QuantLib curves for each path.
# ==============================================================
# All dates we need DFs for: coupon dates + maturity + tenor observation dates
all_relevant_dates = sorted(set(
    coupon_dates + [BOND_MATURITY] + tenor_dates + period_starts
))
# Filter to dates >= today
all_relevant_dates = [d for d in all_relevant_dates if d >= today]

base_dfs = {}
date_years = {}
for d in all_relevant_dates:
    base_dfs[d.serialNumber()] = base_curve.discount(d)
    date_years[d.serialNumber()] = ois_dc.yearFraction(today, d)

# Pre-compute coupon period data
coupon_data = []
for s, e in zip(period_starts, coupon_dates):
    alpha = bond_dc.yearFraction(s, e)
    coupon_data.append((s.serialNumber(), e.serialNumber(), alpha))

mat_serial = BOND_MATURITY.serialNumber()
s_first_serial = period_starts[0].serialNumber() if period_starts[0] >= today else today.serialNumber()

# ==============================================================
# [8]  GENERATE CUMULATIVE RANDOM WALK SHIFTS
#      shifts[:, 0] = 0
#      shifts[:, t] = shifts[:, t-1] + N(0, sigma)
#      Same paths for both swaps.
# ==============================================================
increments = np.random.normal(0.0, SIGMA, size=(N_PATHS, len(tenor_dates)))
increments[:, 0] = 0.0
shifts = np.cumsum(increments, axis=1)

print(f"\n[3]  MONTE CARLO SIMULATION")
print(f"  Paths: {N_PATHS}")
print(f"  Sigma: {SIGMA:.2f} (per step)")
print(f"  Shift type: cumulative random walk")
print(f"  Tenors: {len(tenor_dates)} (t=0 deterministic + {len(tenor_dates)-1} simulated)")
print(f"  Shift stats at final tenor: mean={shifts[:,-1].mean():.4f}, "
      f"std={shifts[:,-1].std():.4f}")

# ==============================================================
# [9]  VECTORIZED EXPOSURE SIMULATION
#
#      For each observation date obs:
#        DF_shifted(d) = DF_base(d) * exp(-dz * t_d)
#        DF_fwd(obs, d) = DF_shifted(d) / DF_shifted(obs)
#                       = [DF_base(d)/DF_base(obs)] * exp(-dz*(t_d - t_obs))
#
#      SWAP 1 (Fix-Float):
#        MtM = R * N * A_rem - N * (DF_fwd(obs, s_first_rem) - DF_fwd(obs, T))
#        where s_first_rem is the start of the first remaining coupon period
#
#      SWAP 2 (Fix-Fix):
#        MtM = (c_recv - c_pay) * N * A_rem
# ==============================================================
mtm_swap1 = np.zeros((N_PATHS, len(tenor_dates)))
mtm_swap2 = np.zeros((N_PATHS, len(tenor_dates)))

coupon_diff_swap2 = C_RECV - C_PAY

for t_idx in range(len(tenor_dates)):
    obs_date = tenor_dates[t_idx]
    obs_serial = obs_date.serialNumber()
    dz = shifts[:, t_idx]  # shape (N_PATHS,)

    obs_df_base = base_dfs[obs_serial]
    obs_t = date_years[obs_serial]

    # Remaining coupon periods after obs_date
    rem_coupons = [(s_ser, e_ser, alpha) for s_ser, e_ser, alpha in coupon_data
                   if e_ser > obs_serial]

    if not rem_coupons:
        continue

    # Compute remaining annuity (vectorized across paths)
    # A_rem = sum_i alpha_i * DF_fwd(obs, e_i)
    # DF_fwd(obs, e_i) = [DF_base(e_i)/DF_base(obs)] * exp(-dz * (t_e_i - t_obs))
    rem_annuity = np.zeros(N_PATHS)
    for s_ser, e_ser, alpha in rem_coupons:
        df_base_e = base_dfs[e_ser]
        t_e = date_years[e_ser]
        df_fwd_e = (df_base_e / obs_df_base) * np.exp(-dz * (t_e - obs_t))
        rem_annuity += alpha * df_fwd_e

    # Swap 2: MtM = (c_recv - c_pay) * N * A_rem
    mtm_swap2[:, t_idx] = coupon_diff_swap2 * N_PCT * rem_annuity

    # Swap 1: MtM = R * N * A_rem - N * (DF_fwd(obs, s_first_rem) - DF_fwd(obs, T))
    # s_first_rem = start of first remaining coupon period
    s_first_rem_serial = rem_coupons[0][0]
    # Clamp s_first_rem to obs_date if it's before obs_date
    if s_first_rem_serial <= obs_serial:
        df_fwd_s_first = np.ones(N_PATHS)
    else:
        df_base_sf = base_dfs[s_first_rem_serial]
        t_sf = date_years[s_first_rem_serial]
        df_fwd_s_first = (df_base_sf / obs_df_base) * np.exp(-dz * (t_sf - obs_t))

    df_base_mat = base_dfs[mat_serial]
    t_mat = date_years[mat_serial]
    df_fwd_mat = (df_base_mat / obs_df_base) * np.exp(-dz * (t_mat - obs_t))

    mtm_swap1[:, t_idx] = R_SWAP1 * N_PCT * rem_annuity \
                           - N_PCT * (df_fwd_s_first - df_fwd_mat)

print("  Simulation complete.")

# ==============================================================
# [10]  EXPOSURE METRICS
# ==============================================================
def compute_exposure_metrics(mtm):
    epe = np.maximum(mtm, 0.0).mean(axis=0)
    ene = np.minimum(mtm, 0.0).mean(axis=0)
    pfe = np.percentile(mtm, 95, axis=0)
    nfe = np.percentile(mtm, 5, axis=0)
    return epe, ene, pfe, nfe

EPE_s1, ENE_s1, PFE_s1, NFE_s1 = compute_exposure_metrics(mtm_swap1)
EPE_s2, ENE_s2, PFE_s2, NFE_s2 = compute_exposure_metrics(mtm_swap2)

print(f"\n[4a] SWAP 1 — FIX-FLOAT EXPOSURE (% of notional, bank perspective)")
# Print a subset (every ~10th point)
step_print = max(1, len(tenor_dates) // 10)
print(f"  {'Tenor':>8}  {'EPE':>8}  {'ENE':>8}  {'PFE 95%':>10}  {'NFE 5%':>10}")
print(f"  {'-'*50}")
for i in range(0, len(tenor_dates), step_print):
    label = "  <- deterministic" if i == 0 else ""
    print(f"  {tenor_years[i]:>7.2f}Y  {EPE_s1[i]:>8.4f}  {ENE_s1[i]:>8.4f}  "
          f"{PFE_s1[i]:>10.4f}  {NFE_s1[i]:>10.4f}{label}")
# Always print last point
if (len(tenor_dates) - 1) % step_print != 0:
    i = len(tenor_dates) - 1
    print(f"  {tenor_years[i]:>7.2f}Y  {EPE_s1[i]:>8.4f}  {ENE_s1[i]:>8.4f}  "
          f"{PFE_s1[i]:>10.4f}  {NFE_s1[i]:>10.4f}")

print(f"\n  Inception MtM = {mtm0_swap1:.4f}%. Two-sided: rate moves create both upside and downside.")

print(f"\n[4b] SWAP 2 — FIX-FIX EXPOSURE (% of notional, bank perspective)")
print(f"  {'Tenor':>8}  {'EPE':>8}  {'ENE':>8}  {'PFE 95%':>10}  {'NFE 5%':>10}")
print(f"  {'-'*50}")
for i in range(0, len(tenor_dates), step_print):
    label = "  <- deterministic" if i == 0 else ""
    print(f"  {tenor_years[i]:>7.2f}Y  {EPE_s2[i]:>8.4f}  {ENE_s2[i]:>8.4f}  "
          f"{PFE_s2[i]:>10.4f}  {NFE_s2[i]:>10.4f}{label}")
if (len(tenor_dates) - 1) % step_print != 0:
    i = len(tenor_dates) - 1
    print(f"  {tenor_years[i]:>7.2f}Y  {EPE_s2[i]:>8.4f}  {ENE_s2[i]:>8.4f}  "
          f"{PFE_s2[i]:>10.4f}  {NFE_s2[i]:>10.4f}")

print(f"\n  Inception MtM = {mtm0_swap2:.4f}%. Always positive: bank receives more than it pays.")

# ==============================================================
# [11]  SIDE-BY-SIDE PLOT
#       Each subplot has its own y-scale (independent axes) so the
#       exposure profiles are visible despite different magnitudes.
#       Y-limits are set from the PFE/NFE envelope with 20% padding.
# ==============================================================
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

def plot_exposure(ax, tenor_yrs, mtm, epe, ene, pfe, nfe, title):
    ymin = min(nfe.min(), ene.min())
    ymax = max(pfe.max(), epe.max())
    pad = 0.2 * max(abs(ymax), abs(ymin), 1.0)
    ylim_lo, ylim_hi = ymin - pad, ymax + pad

    for p in range(mtm.shape[0]):
        ax.plot(tenor_yrs, mtm[p, :], color="grey", alpha=0.05, lw=0.3)
    ax.plot(tenor_yrs, epe, "b-",  lw=2, label="EPE", zorder=5)
    ax.plot(tenor_yrs, ene, "r-",  lw=2, label="ENE", zorder=5)
    ax.plot(tenor_yrs, pfe, "b--", lw=1.5, label="PFE (95%)", zorder=5)
    ax.plot(tenor_yrs, nfe, "r--", lw=1.5, label="NFE (5%)", zorder=5)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylim(ylim_lo, ylim_hi)
    ax.set_xlabel("Time (years)", fontsize=11)
    ax.set_title(title, fontsize=11)
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)

plot_exposure(
    ax1, tenor_years, mtm_swap1, EPE_s1, ENE_s1, PFE_s1, NFE_s1,
    "SWAP 1 — Fix-Float (Receiver)\n"
    f"Bank receives {R_SWAP1*100:.2f}% fixed, pays OIS floating",
)
ax1.set_ylabel("Exposure (% of notional)", fontsize=11)

plot_exposure(
    ax2, tenor_years, mtm_swap2, EPE_s2, ENE_s2, PFE_s2, NFE_s2,
    "SWAP 2 — Fix-Fix (Differential)\n"
    f"Bank receives {C_RECV*100:.2f}%, pays {C_PAY*100:.2f}% fixed",
)

fig.suptitle(
    f"Counterparty Exposure — Positive Inception MtM | "
    f"{N_PATHS} paths | {N_TENORS} tenors | "
    f"$\\sigma$ = {SIGMA:.2f} (cumulative random walk)",
    fontsize=12, fontweight="bold", y=1.02,
)
plt.tight_layout()
plt.savefig("plots/exposure_asw.png", dpi=150, bbox_inches="tight")
print(f"\n  Plot saved to plots/exposure_asw.png")
print(sep)
