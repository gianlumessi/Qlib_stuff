"""
===============================================================
  COUNTERPARTY EXPOSURE PROFILES — FOUR SWAP STRUCTURES
  Par-par ASW (3 bond prices) + Fix-for-Fix differential swap
===============================================================

STRUCTURES 1-3:  Par-par asset swap on BTP 3.45%, differing by
                 bond dirty price (P = 100, 90, 110).

  The bank converts the bond into a synthetic FRN via a swap:
    Bank passes:   bond fixed coupons (c = 3.45%) + principal N
    Bank receives: ESTR floating + ASW spread

  ASW = (c - r_s) + (N - P) / (N * A)
  Swap MtM = N*(1 - DF_fwd(obs,T)) + (ASW - c)*N*A_rem
  Inception MtM = 100 - P.

STRUCTURE 4:  Fix-for-fix differential swap
    Bank RECEIVES: 3.50% fixed
    Bank PAYS:     3.00% fixed
    MtM = (c_recv - c_pay) * N * A_rem = 0.50% * N * A_rem
    Always positive (bank always ITM).  One-sided exposure.

EXPOSURE SIMULATION:
  - Cumulative parallel ESTR shifts (random walk):
      shifts[:, 0] = 0,  shifts[:, t] = shifts[:, t-1] + N(0, sigma)
  - Analytical DF shifting: DF_shifted(d) = DF_base(d) * exp(-dz * t_d)
  - Same 1500 MC paths reused across all four structures
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

N_PATHS = 1500
SIGMA   = 0.010
np.random.seed(42)

# Three bond price scenarios for the par-par ASW
SCENARIOS = [
    ("A (par)",      100.0),
    ("B (discount)",  90.0),
    ("C (premium)",  110.0),
]

# Fix-for-fix differential swap parameters
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

# ==============================================================
# [6]  ASW SPREAD AND INCEPTION MtM FOR EACH SCENARIO
#
#      ASW = (c - r_s) + (N - P) / (N * A)
#
#      Swap MtM at inception (from bank's perspective):
#        MtM = N*(1 - DF_T) + (ASW - c)*N*A
#            = N*(1 - DF_T) + [-(1 - DF_T)/A + (N - P)/(N*A) - c + c]*N*A  ... nah
#            = N*(1 - DF_T) - r_s*N*A + (N - P)/A * A
#            = N*(1 - DF_T) - N*(1 - DF_T) + (N - P)
#            = N - P = 100 - P
#
#      Check: swap_MtM + P = 100  ✓
# ==============================================================
sep = "=" * 68
print(sep)
print("  COUNTERPARTY EXPOSURE — PAR-PAR ASSET SWAP")
print("  Bond price sensitivity study")
print(sep)

print(f"\n[1]  COMMON PARAMETERS")
print(f"  Bond coupon c:           {COUPON_RATE*100:.2f}%")
print(f"  OIS par swap rate r_s:   {r_s*100:.4f}%")
print(f"  Annuity A:               {annuity:.6f}")
print(f"  DF(0,T):                 {df_T:.6f}")

scenario_data = []
print(f"\n[2]  DAY-1 MtM CHECK  (swap MtM + bond price = 100)")
print(f"  {'Scenario':<16}  {'P':>6}  {'ASW (bps)':>10}  {'MtM':>8}  {'MtM+P':>8}  {'Check':>6}")
print(f"  {'-'*60}")
for label, P in SCENARIOS:
    asw = (COUPON_RATE - r_s) + (N_PCT - P) / (N_PCT * annuity)
    mtm0 = N_PCT * (1.0 - df_T) + (asw - COUPON_RATE) * N_PCT * annuity
    check_val = mtm0 + P
    ok = "OK" if abs(check_val - 100.0) < 0.01 else "FAIL"
    print(f"  {label:<16}  {P:>6.0f}  {asw*10000:>10.2f}  {mtm0:>8.4f}  {check_val:>8.4f}  {ok:>6}")
    scenario_data.append((label, P, asw, mtm0))

# ==============================================================
# [7]  TENOR GRID — t=0 (today) + 10 annual observation dates
# ==============================================================
n_tenors = 10
step = max(1, len(coupon_dates) // n_tenors)
sim_tenor_dates = coupon_dates[step-1::step][:n_tenors]

tenor_dates = [today] + sim_tenor_dates
tenor_years = np.array([ois_dc.yearFraction(today, d) for d in tenor_dates])

print(f"\n[3]  OBSERVATION DATES ({len(tenor_dates)} tenors)")
for i, (d, y) in enumerate(zip(tenor_dates, tenor_years)):
    label = "  <- deterministic (shift = 0)" if y == 0.0 else ""
    print(f"    {i+1:>2}. {d}  ({y:.2f}Y){label}")

# ==============================================================
# [8]  PRE-COMPUTE BASE DFs AND COUPON PERIOD DATA
# ==============================================================
all_relevant_dates = sorted(set(
    coupon_dates + [BOND_MATURITY] + tenor_dates + period_starts
))
all_relevant_dates = [d for d in all_relevant_dates if d >= today]

base_dfs = {}
date_years = {}
for d in all_relevant_dates:
    base_dfs[d.serialNumber()] = base_curve.discount(d)
    date_years[d.serialNumber()] = ois_dc.yearFraction(today, d)

coupon_data = []
for s, e in zip(period_starts, coupon_dates):
    alpha = bond_dc.yearFraction(s, e)
    coupon_data.append((s.serialNumber(), e.serialNumber(), alpha))

mat_serial = BOND_MATURITY.serialNumber()

# ==============================================================
# [9]  GENERATE CUMULATIVE RANDOM WALK SHIFTS
#      shifts[:, 0] = 0
#      shifts[:, t] = shifts[:, t-1] + N(0, sigma)
#      Same paths reused for all three scenarios.
# ==============================================================
increments = np.random.normal(0.0, SIGMA, size=(N_PATHS, len(tenor_dates)))
increments[:, 0] = 0.0
shifts = np.cumsum(increments, axis=1)

print(f"\n[4]  MONTE CARLO SIMULATION")
print(f"  Paths: {N_PATHS},  Sigma: {SIGMA:.4f} per step,  Tenors: {len(tenor_dates)}")
print(f"  Shift stats at final tenor: mean={shifts[:,-1].mean():.4f}, "
      f"std={shifts[:,-1].std():.4f}")

# ==============================================================
# [10]  PRE-COMPUTE A_rem AND DF_fwd_T FOR ALL PATHS AND TENORS
#
#       These are scenario-independent. The only scenario-specific
#       quantity is (ASW - c), which is a scalar.
#
#       MtM(obs) = N*(1 - DF_fwd_T) + (ASW - c)*N*A_rem
# ==============================================================
arr_A_rem   = np.zeros((N_PATHS, len(tenor_dates)))
arr_df_fwd_T = np.ones((N_PATHS, len(tenor_dates)))

for t_idx in range(len(tenor_dates)):
    obs_date = tenor_dates[t_idx]
    obs_serial = obs_date.serialNumber()
    dz = shifts[:, t_idx]

    obs_df_base = base_dfs[obs_serial]
    obs_t = date_years[obs_serial]

    rem_coupons = [(s_ser, e_ser, alpha) for s_ser, e_ser, alpha in coupon_data
                   if e_ser > obs_serial]
    if not rem_coupons:
        continue

    rem_annuity = np.zeros(N_PATHS)
    for s_ser, e_ser, alpha in rem_coupons:
        df_base_e = base_dfs[e_ser]
        t_e = date_years[e_ser]
        df_fwd_e = (df_base_e / obs_df_base) * np.exp(-dz * (t_e - obs_t))
        rem_annuity += alpha * df_fwd_e

    df_base_mat = base_dfs[mat_serial]
    t_mat = date_years[mat_serial]
    df_fwd_mat = (df_base_mat / obs_df_base) * np.exp(-dz * (t_mat - obs_t))

    arr_A_rem[:, t_idx] = rem_annuity
    arr_df_fwd_T[:, t_idx] = df_fwd_mat

print("  Pre-computation of A_rem and DF_fwd_T complete.")

# ==============================================================
# [11]  COMPUTE MtM FOR EACH SCENARIO
#
#       MtM = N*(1 - DF_fwd_T) + (ASW - c)*N*A_rem
# ==============================================================
float_term = N_PCT * (1.0 - arr_df_fwd_T)   # same for all scenarios

mtm_all = {}
for label, P, asw, mtm0 in scenario_data:
    spread_diff = asw - COUPON_RATE    # (ASW - c), negative for all scenarios here
    mtm = float_term + spread_diff * N_PCT * arr_A_rem
    mtm_all[label] = mtm

print("  MtM computed for all three ASW scenarios.")

# ==============================================================
# [12]  FIX-FOR-FIX DIFFERENTIAL SWAP
#
#       MtM = (c_recv - c_pay) * N * A_rem
#       Always positive since c_recv > c_pay.
#       Uses the same pre-computed arr_A_rem (same bond schedule).
# ==============================================================
coupon_diff_ff = C_RECV - C_PAY
mtm_fixfix     = coupon_diff_ff * N_PCT * arr_A_rem
mtm0_fixfix    = coupon_diff_ff * N_PCT * annuity

mtm_all["Fix-Fix"] = mtm_fixfix

print(f"\n[5b] FIX-FOR-FIX DIFFERENTIAL SWAP")
print(f"  Bank receives:  {C_RECV*100:.2f}% fixed")
print(f"  Bank pays:      {C_PAY*100:.2f}% fixed")
print(f"  Inception MtM:  {mtm0_fixfix:.4f}% of notional (always positive)")

# ==============================================================
# [13]  EXPOSURE METRICS — ALL FOUR STRUCTURES
# ==============================================================
def compute_exposure_metrics(mtm):
    epe = np.maximum(mtm, 0.0).mean(axis=0)
    ene = np.minimum(mtm, 0.0).mean(axis=0)
    pfe = np.percentile(mtm, 95, axis=0)
    nfe = np.percentile(mtm, 5, axis=0)
    return epe, ene, pfe, nfe

metrics = {}
for label, P, asw, mtm0 in scenario_data:
    metrics[label] = compute_exposure_metrics(mtm_all[label])
metrics["Fix-Fix"] = compute_exposure_metrics(mtm_fixfix)

step_print = max(1, len(tenor_dates) // 10)

for label, P, asw, mtm0 in scenario_data:
    epe, ene, pfe, nfe = metrics[label]
    print(f"\n[6]  {label.upper()}  (P = {P:.0f}, ASW = {asw*10000:.1f} bps, MtM_0 = {mtm0:+.2f})")
    print(f"  {'Tenor':>8}  {'EPE':>8}  {'ENE':>8}  {'PFE 95%':>10}  {'NFE 5%':>10}")
    print(f"  {'-'*50}")
    for i in range(0, len(tenor_dates), step_print):
        det = "  <- det" if i == 0 else ""
        print(f"  {tenor_years[i]:>7.2f}Y  {epe[i]:>8.4f}  {ene[i]:>8.4f}  "
              f"{pfe[i]:>10.4f}  {nfe[i]:>10.4f}{det}")
    if (len(tenor_dates) - 1) % step_print != 0:
        i = len(tenor_dates) - 1
        print(f"  {tenor_years[i]:>7.2f}Y  {epe[i]:>8.4f}  {ene[i]:>8.4f}  "
              f"{pfe[i]:>10.4f}  {nfe[i]:>10.4f}")

epe_ff, ene_ff, pfe_ff, nfe_ff = metrics["Fix-Fix"]
print(f"\n[6]  FIX-FOR-FIX  (recv {C_RECV*100:.2f}%, pay {C_PAY*100:.2f}%, MtM_0 = {mtm0_fixfix:+.2f})")
print(f"  {'Tenor':>8}  {'EPE':>8}  {'ENE':>8}  {'PFE 95%':>10}  {'NFE 5%':>10}")
print(f"  {'-'*50}")
for i in range(0, len(tenor_dates), step_print):
    det = "  <- det" if i == 0 else ""
    print(f"  {tenor_years[i]:>7.2f}Y  {epe_ff[i]:>8.4f}  {ene_ff[i]:>8.4f}  "
          f"{pfe_ff[i]:>10.4f}  {nfe_ff[i]:>10.4f}{det}")
if (len(tenor_dates) - 1) % step_print != 0:
    i = len(tenor_dates) - 1
    print(f"  {tenor_years[i]:>7.2f}Y  {epe_ff[i]:>8.4f}  {ene_ff[i]:>8.4f}  "
          f"{pfe_ff[i]:>10.4f}  {nfe_ff[i]:>10.4f}")
print(f"\n  Always positive: bank receives more than it pays.")

# ==============================================================
# [14]  FOUR INDIVIDUAL PLOTS — one per structure
# ==============================================================
def save_exposure_plot(filename, tenor_yrs, mtm, epe, ene, pfe, nfe, title, suptitle):
    fig, ax = plt.subplots(figsize=(10, 6))
    for p in range(mtm.shape[0]):
        ax.plot(tenor_yrs, mtm[p, :], color="grey", alpha=0.05, lw=0.3)
    ax.plot(tenor_yrs, epe, "b-",  lw=2, label="EPE", zorder=5)
    ax.plot(tenor_yrs, ene, "r-",  lw=2, label="ENE", zorder=5)
    ax.plot(tenor_yrs, pfe, "b--", lw=1.5, label="PFE (95%)", zorder=5)
    ax.plot(tenor_yrs, nfe, "r--", lw=1.5, label="NFE (5%)", zorder=5)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xlabel("Time (years)", fontsize=12)
    ax.set_ylabel("Swap MtM (% of notional)", fontsize=12)
    ax.set_title(title, fontsize=12)
    ax.legend(loc="best", fontsize=10)
    ax.grid(True, alpha=0.3)
    fig.suptitle(suptitle, fontsize=13, fontweight="bold", y=1.01)
    plt.tight_layout()
    fig.savefig(filename, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Plot saved to {filename}")

common_sup = f"{N_PATHS} paths | $\\sigma$ = {SIGMA:.3f} | cumulative random walk"

for label, P, asw, mtm0 in scenario_data:
    epe, ene, pfe, nfe = metrics[label]
    tag = label.split("(")[1].rstrip(")")
    fname = f"plots/exposure_asw_{tag}.png"
    save_exposure_plot(
        fname, tenor_years, mtm_all[label], epe, ene, pfe, nfe,
        f"P = {P:.0f},  ASW = {asw*10000:.0f} bps,  MtM$_0$ = {mtm0:+.1f}",
        f"Par-Par Asset Swap — {label} | {common_sup}",
    )

epe_ff, ene_ff, pfe_ff, nfe_ff = metrics["Fix-Fix"]
save_exposure_plot(
    "plots/exposure_fixfix.png", tenor_years, mtm_fixfix, epe_ff, ene_ff, pfe_ff, nfe_ff,
    f"Bank receives {C_RECV*100:.2f}% fixed, pays {C_PAY*100:.2f}% fixed\n"
    f"MtM$_0$ = {mtm0_fixfix:+.2f}% — always positive (one-sided)",
    f"Fix-for-Fix Differential Swap | {common_sup}",
)

print(sep)
