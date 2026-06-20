"""
===============================================================
  COUNTERPARTY EXPOSURE PROFILES — FOUR SWAP STRUCTURES
  Par-par ASW (3 bond prices) + Fix-for-Fix differential swap

  RATE MODEL:  one-factor Hull-White (1F HW) short-rate model,
               fitted to the current ESTR/OIS zero curve.
===============================================================

STRUCTURES 1-3:  Par-par asset swap on BTP 3.45%, differing by
                 bond dirty price (P = 100, 90, 110).

  The bank converts the bond into a synthetic FRN via a swap:
    Bank passes:   bond fixed coupons (c = 3.45%) + principal N
    Bank receives: ESTR floating + ASW spread

  ASW = (c - r_s) + (N - P) / (N * A)
  Swap MtM = N*(1 - DF_fwd(obs,T)) + (ASW - c)*N*A_rem
  Inception MtM = 100 - P.

  NB: the P = 100 (par) scenario IS the plain fix-for-floating
  BTP asset swap (MtM_0 = 0).

STRUCTURE 4:  Fix-for-fix differential swap
    Bank RECEIVES: 3.50% fixed
    Bank PAYS:     3.00% fixed
    MtM = (c_recv - c_pay) * N * A_rem = 0.50% * N * A_rem
    Always positive (bank always ITM).  One-sided exposure.
    Exhibits sawtooth profile: MtM steps down at each semi-annual
    coupon date as the bank receives a net coupon payment.

EXPOSURE SIMULATION (Hull-White 1F):
  - 100 equally spaced observation dates from today to maturity
  - Short rate r(t) simulated forward under the HW process,
    calibrated to the base OIS curve as initial term structure:
      a (mean reversion) = 0.03,  sigma = 0.01
  - At each observation date / path, the path-consistent discount
    factors P(t,T) are rebuilt from r(t) via the HW analytic affine
    bond formula:  P(t,T) = A(t,T) * exp(-B(t,T) * r(t))
  - Swap MtM is the value AT the observation date (remaining
    cashflows discounted to the observation date only).  The MtM
    is NOT discounted back to t=0 — this is an exposure study.
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

N_PATHS  = 1500
N_TENORS = 100
np.random.seed(42)

# Hull-White 1F parameters (fixed)
HW_A     = 0.03    # mean reversion
HW_SIGMA = 0.01    # short-rate volatility

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
ts_handle  = ql.YieldTermStructureHandle(base_curve)

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
# ==============================================================
sep = "=" * 68
print(sep)
print("  COUNTERPARTY EXPOSURE — FOUR SWAP STRUCTURES (Hull-White 1F)")
print(sep)

print(f"\n[1]  COMMON PARAMETERS")
print(f"  Bond coupon c:           {COUPON_RATE*100:.2f}%")
print(f"  OIS par swap rate r_s:   {r_s*100:.4f}%")
print(f"  Annuity A:               {annuity:.6f}")
print(f"  DF(0,T):                 {df_T:.6f}")
print(f"  HW mean reversion a:     {HW_A:.4f}")
print(f"  HW sigma:                {HW_SIGMA:.4f}")

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
# [7]  TENOR GRID — 100 equally spaced from today to maturity
#
#      Dense grid is essential for the fix-for-fix sawtooth:
#      observation dates fall between semi-annual coupon dates,
#      so A_rem steps down visibly at each coupon payment.
# ==============================================================
maturity_serial = BOND_MATURITY.serialNumber()
today_serial = today.serialNumber()

tenor_serial = np.linspace(today_serial, maturity_serial, N_TENORS + 1, dtype=int)
tenor_serial = np.unique(tenor_serial)
tenor_dates = [ql.Date(int(s)) for s in tenor_serial]
tenor_years = np.array([ois_dc.yearFraction(today, d) for d in tenor_dates])

print(f"\n[3]  TENOR GRID")
print(f"  {len(tenor_dates)} observation dates from {today} to {BOND_MATURITY}")
print(f"  First 5: {', '.join(str(d) for d in tenor_dates[:5])}")
print(f"  Last 5:  {', '.join(str(d) for d in tenor_dates[-5:])}")

# ==============================================================
# [8]  PRE-COMPUTE BASE DFs, FORWARD RATES AND COUPON PERIOD DATA
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

# Instantaneous forward rate f(0,t) from the base curve, per observation date.
def inst_fwd(tau):
    if tau <= 0.0:
        tau = 1e-6
    return base_curve.forwardRate(tau, tau, ql.Continuous, ql.Annual, True).rate()

f0_obs = np.array([inst_fwd(t) for t in tenor_years])

# ==============================================================
# [9]  HULL-WHITE MODEL — analytic affine bond reconstruction
#
#      P(t,T) = A(t,T) * exp(-B(t,T) * r(t))
#        B(t,T) = (1 - exp(-a(T-t))) / a
#        A(t,T) = P0(T)/P0(t)
#                 * exp( B(t,T)*f(0,t)
#                        - (sigma^2/(4a))*(1-exp(-2a t))*B(t,T)^2 )
#
#      Reprices the base curve exactly at t=0 (r(0)=f(0,0)).
# ==============================================================
hw_model   = ql.HullWhite(ts_handle, HW_A, HW_SIGMA)        # QuantLib HW model
hw_process = ql.HullWhiteProcess(ts_handle, HW_A, HW_SIGMA) # short-rate process

def hw_discount_bond(tau_t, P0t, f0t, r_t, tau_T, P0T):
    """Path-consistent forward discount factor P(t,T) given short rate r(t).
    r_t may be a scalar or a NumPy array (vectorised over paths)."""
    dtau = tau_T - tau_t
    B = (1.0 - np.exp(-HW_A * dtau)) / HW_A
    A = (P0T / P0t) * np.exp(
        B * f0t - (HW_SIGMA ** 2 / (4.0 * HW_A)) * (1.0 - np.exp(-2.0 * HW_A * tau_t)) * B ** 2
    )
    return A * np.exp(-B * r_t)

# Sanity check: HW model discountBond reprices the base curve at t=0.
chk_T = tenor_years[len(tenor_years) // 2]
chk_model = hw_model.discountBond(0.0, chk_T, hw_process.x0())
chk_curve = base_curve.discount(tenor_dates[len(tenor_years) // 2])
print(f"\n[4]  HULL-WHITE MODEL CHECK")
print(f"  r(0) = f(0,0):           {hw_process.x0():.6f}")
print(f"  P(0,{chk_T:.2f}) model:        {chk_model:.6f}")
print(f"  P(0,{chk_T:.2f}) base curve:   {chk_curve:.6f}")
print(f"  Reprice error:           {abs(chk_model - chk_curve):.2e}")

# ==============================================================
# [10]  SIMULATE THE SHORT RATE FORWARD ON THE TENOR GRID
#
#       r(0) = process.x0() = f(0,0).
#       Euler-exact step under the HW process:
#         E[r_k | r_{k-1}] = r_{k-1} e^{-a dt} + M_k
#         M_k  = process.expectation(t_{k-1}, 0, dt)
#         sd_k = process.stdDeviation(t_{k-1}, 0, dt)
#       Vectorised over all 1500 paths (HW expectation is affine
#       in r_{k-1}, std is independent of r_{k-1}).
# ==============================================================
n_obs   = len(tenor_dates)
r_paths = np.zeros((N_PATHS, n_obs))
r_paths[:, 0] = hw_process.x0()

for k in range(1, n_obs):
    s  = tenor_years[k - 1]
    dt = tenor_years[k] - tenor_years[k - 1]
    M  = hw_process.expectation(s, 0.0, dt)     # alpha(s+dt) - alpha(s) e^{-a dt}
    sd = hw_process.stdDeviation(s, 0.0, dt)    # sigma sqrt((1-e^{-2a dt})/(2a))
    exp_factor = np.exp(-HW_A * dt)
    Z = np.random.normal(0.0, 1.0, size=N_PATHS)
    r_paths[:, k] = M + r_paths[:, k - 1] * exp_factor + sd * Z

print(f"\n[5]  MONTE CARLO SIMULATION (Hull-White 1F)")
print(f"  Paths: {N_PATHS},  a: {HW_A:.4f},  sigma: {HW_SIGMA:.4f},  Tenors: {n_obs}")
print(f"  Short rate at final tenor: mean={r_paths[:,-1].mean():.4f}, "
      f"std={r_paths[:,-1].std():.4f}")

# ==============================================================
# [11]  PRE-COMPUTE A_rem AND DF_fwd_T FOR ALL PATHS AND TENORS
#
#       Path-consistent under each simulated short rate.
#       These are scenario-independent. The only scenario-specific
#       quantity is (ASW - c), which is a scalar.
#
#       ASW scenarios: MtM = N*(1 - DF_fwd_T) + (ASW - c)*N*A_rem
#       Fix-fix:       MtM = (c_recv - c_pay) * N * A_rem
# ==============================================================
arr_A_rem    = np.zeros((N_PATHS, n_obs))
arr_df_fwd_T = np.ones((N_PATHS, n_obs))

t_mat = date_years[mat_serial]
P0_mat = base_dfs[mat_serial]

for t_idx in range(n_obs):
    obs_date = tenor_dates[t_idx]
    obs_serial = obs_date.serialNumber()
    obs_t = tenor_years[t_idx]
    P0_obs = base_dfs[obs_serial]
    f0t = f0_obs[t_idx]
    r_t = r_paths[:, t_idx]

    rem_coupons = [(s_ser, e_ser, alpha) for s_ser, e_ser, alpha in coupon_data
                   if e_ser > obs_serial]
    if not rem_coupons:
        continue

    rem_annuity = np.zeros(N_PATHS)
    for s_ser, e_ser, alpha in rem_coupons:
        P0_e = base_dfs[e_ser]
        t_e = date_years[e_ser]
        df_fwd_e = hw_discount_bond(obs_t, P0_obs, f0t, r_t, t_e, P0_e)
        rem_annuity += alpha * df_fwd_e

    df_fwd_mat = hw_discount_bond(obs_t, P0_obs, f0t, r_t, t_mat, P0_mat)

    arr_A_rem[:, t_idx] = rem_annuity
    arr_df_fwd_T[:, t_idx] = df_fwd_mat

print("  Pre-computation of path-consistent A_rem and DF_fwd_T complete.")

# ==============================================================
# [12]  COMPUTE MtM FOR EACH ASW SCENARIO
# ==============================================================
float_term = N_PCT * (1.0 - arr_df_fwd_T)

mtm_all = {}
for label, P, asw, mtm0 in scenario_data:
    spread_diff = asw - COUPON_RATE
    mtm_all[label] = float_term + spread_diff * N_PCT * arr_A_rem

print("  MtM computed for all three ASW scenarios.")

# ==============================================================
# [13]  FIX-FOR-FIX DIFFERENTIAL SWAP
#
#       MtM = (c_recv - c_pay) * N * A_rem
#       Always positive since c_recv > c_pay.
#       Sawtooth: A_rem steps down at each semi-annual coupon date
#       as the bank receives a net coupon payment of
#       (c_recv - c_pay) * alpha_i * N ≈ 0.25% of notional.
# ==============================================================
coupon_diff_ff = C_RECV - C_PAY
mtm_fixfix     = coupon_diff_ff * N_PCT * arr_A_rem
mtm0_fixfix    = coupon_diff_ff * N_PCT * annuity

mtm_all["Fix-Fix"] = mtm_fixfix

print(f"\n[6]  FIX-FOR-FIX DIFFERENTIAL SWAP")
print(f"  Bank receives:  {C_RECV*100:.2f}% fixed")
print(f"  Bank pays:      {C_PAY*100:.2f}% fixed")
print(f"  Inception MtM:  {mtm0_fixfix:.4f}% of notional (always positive)")

# ==============================================================
# [14]  EXPOSURE METRICS — ALL FOUR STRUCTURES
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

step_print = max(1, n_obs // 10)

for label, P, asw, mtm0 in scenario_data:
    epe, ene, pfe, nfe = metrics[label]
    print(f"\n[7]  {label.upper()}  (P = {P:.0f}, ASW = {asw*10000:.1f} bps, MtM_0 = {mtm0:+.2f})")
    print(f"  {'Tenor':>8}  {'EPE':>8}  {'ENE':>8}  {'PFE 95%':>10}  {'NFE 5%':>10}")
    print(f"  {'-'*50}")
    for i in range(0, n_obs, step_print):
        det = "  <- t=0" if i == 0 else ""
        print(f"  {tenor_years[i]:>7.2f}Y  {epe[i]:>8.4f}  {ene[i]:>8.4f}  "
              f"{pfe[i]:>10.4f}  {nfe[i]:>10.4f}{det}")
    if (n_obs - 1) % step_print != 0:
        i = n_obs - 1
        print(f"  {tenor_years[i]:>7.2f}Y  {epe[i]:>8.4f}  {ene[i]:>8.4f}  "
              f"{pfe[i]:>10.4f}  {nfe[i]:>10.4f}")

epe_ff, ene_ff, pfe_ff, nfe_ff = metrics["Fix-Fix"]
print(f"\n[7]  FIX-FOR-FIX  (recv {C_RECV*100:.2f}%, pay {C_PAY*100:.2f}%, MtM_0 = {mtm0_fixfix:+.2f})")
print(f"  {'Tenor':>8}  {'EPE':>8}  {'ENE':>8}  {'PFE 95%':>10}  {'NFE 5%':>10}")
print(f"  {'-'*50}")
for i in range(0, n_obs, step_print):
    det = "  <- t=0" if i == 0 else ""
    print(f"  {tenor_years[i]:>7.2f}Y  {epe_ff[i]:>8.4f}  {ene_ff[i]:>8.4f}  "
          f"{pfe_ff[i]:>10.4f}  {nfe_ff[i]:>10.4f}{det}")
if (n_obs - 1) % step_print != 0:
    i = n_obs - 1
    print(f"  {tenor_years[i]:>7.2f}Y  {epe_ff[i]:>8.4f}  {ene_ff[i]:>8.4f}  "
          f"{pfe_ff[i]:>10.4f}  {nfe_ff[i]:>10.4f}")
print(f"\n  Always positive: bank receives more than it pays.")

# ==============================================================
# [15]  EPE / ENE DIAGNOSTIC — par ASW scenario
#
#       Under Hull-White the bond prices P(t,T) are log-affine in
#       the Gaussian short rate, so the MtM distribution is
#       skewed (the exp(-B r) reconstruction is convex in r).
# ==============================================================
mtm_par = mtm_all["A (par)"]
mid_idx = n_obs // 2
mtm_mid = mtm_par[:, mid_idx]
skew_mid = float(np.mean(((mtm_mid - mtm_mid.mean()) / mtm_mid.std()) ** 3))
epe_mid, ene_mid = metrics["A (par)"][0][mid_idx], metrics["A (par)"][1][mid_idx]

print(f"\n[8]  EPE / ENE DIAGNOSTIC  (par scenario, t = {tenor_years[mid_idx]:.1f}Y)")
print(f"  EPE:                {epe_mid:>8.4f}")
print(f"  |ENE|:              {abs(ene_mid):>8.4f}")
print(f"  EPE / |ENE|:        {epe_mid / abs(ene_mid):>8.4f}  (1.0 = perfect symmetry)")
print(f"  MtM skewness:       {skew_mid:>8.4f}  (0 = symmetric)")
print(f"  Short rate std:     {r_paths[:, mid_idx].std():>8.4f}  "
      f"({r_paths[:, mid_idx].std()*100:.2f}%)")

# ==============================================================
# [16]  PLOT 0 — OIS ZERO CURVE + SAMPLE SIMULATED HW CURVES
#
#       The base zero curve plus the zero curves implied by a
#       handful of simulated short rates at a 2Y horizon
#       (reconstructed via the HW affine bond formula).
# ==============================================================
fig, ax = plt.subplots(figsize=(10, 6))

curve_tenors_yr = np.array([ois_dc.yearFraction(today, calendar.advance(today, ql.Period(t)))
                            for t in OIS_TENORS])
curve_zeros_pct = np.array(OIS_ZEROS) * 100
ax.plot(curve_tenors_yr, curve_zeros_pct, "k-o", lw=2.5, ms=6,
        label="Base OIS curve (t=0)", zorder=5)

# Sample simulated zero curves observed at a 2Y horizon.
horizon_idx = int(np.argmin(np.abs(tenor_years - 2.0)))
tau_h = tenor_years[horizon_idx]
P0_h = base_dfs[tenor_dates[horizon_idx].serialNumber()]
f0_h = f0_obs[horizon_idx]
fwd_mats = [d for d in tenor_dates if date_years[d.serialNumber()] > tau_h + 0.05]
fwd_tau = np.array([date_years[d.serialNumber()] for d in fwd_mats])
fwd_P0  = np.array([base_dfs[d.serialNumber()] for d in fwd_mats])

rng_sample = np.random.RandomState(7)
sample_paths = rng_sample.choice(N_PATHS, size=5, replace=False)
sample_colors = ["#2196F3", "#90CAF9", "#FFB74D", "#F44336", "#8E24AA"]
for sp, col in zip(sample_paths, sample_colors):
    r_h = r_paths[sp, horizon_idx]
    zeros_h = []
    for tT, P0T in zip(fwd_tau, fwd_P0):
        P_tT = hw_discount_bond(tau_h, P0_h, f0_h, r_h, tT, P0T)
        zeros_h.append(-np.log(P_tT) / (tT - tau_h))
    ax.plot(fwd_tau, np.array(zeros_h) * 100, "--", color=col, lw=1.3,
            label=f"Sim. zero curve @ {tau_h:.1f}Y (path {sp})", zorder=3)

ax.set_xlabel("Tenor (years)", fontsize=12)
ax.set_ylabel("Zero rate (%, continuously compounded)", fontsize=12)
ax.set_title("ESTR/OIS Zero Curve — Base and Hull-White Simulated Curves",
             fontsize=13, fontweight="bold")
ax.legend(fontsize=9)
ax.grid(True, alpha=0.3)
plt.tight_layout()
fig.savefig("plots/ois_curve.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"\n  Plot saved to plots/ois_curve.png")

# ==============================================================
# [17]  FOUR INDIVIDUAL EXPOSURE PLOTS
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

common_sup = (f"{N_PATHS} paths | {N_TENORS} tenors | "
              f"Hull-White 1F (a={HW_A:.2f}, $\\sigma$={HW_SIGMA:.2f})")

for label, P, asw, mtm0 in scenario_data:
    epe, ene, pfe, nfe = metrics[label]
    tag = label.split("(")[1].rstrip(")")
    fname = f"plots/exposure_asw_{tag}.png"
    extra = "  (fix-for-floating BTP asset swap)" if P == 100.0 else ""
    save_exposure_plot(
        fname, tenor_years, mtm_all[label], epe, ene, pfe, nfe,
        f"P = {P:.0f},  ASW = {asw*10000:.0f} bps,  MtM$_0$ = {mtm0:+.1f}{extra}",
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
