# Intraday eSSVI Butterfly Statistical Arbitrage Strategy

**Author context**: Aryan Ayyar — Quantitative Research Strategy Document
**Version**: 1.0 | **Frequency**: 1-min / 5-min bars | **Market**: NSE Index Options (Nifty / BankNifty)

***

## 1. Executive Summary

This document specifies a statistical arbitrage strategy that exploits transient mispricings between market-implied volatilities and a model-implied volatility surface calibrated using the **extended SSVI (eSSVI)** parameterization. At each intraday bar, the strategy compares reverse Black–Scholes IVs from market mid-quotes against the calibrated eSSVI surface, standardizes the residuals into z-scores, and deploys **long or short butterfly spreads** at strikes where the mispricing exceeds a statistical threshold.[^1][^2][^3][^4]

The theoretical foundation is the Breeden–Litzenberger identity: a butterfly spread is a direct claim on the local risk-neutral density. If eSSVI defines the fair density \( q^*(K) \) and market prices imply \( q^{mkt}(K) \), any persistent gap \( q^{mkt}(K) - q^*(K) \) is a tradeable convexity mispricing, assuming mean reversion of the surface.[^3]

***

## 2. Strategy Thesis

### 2.1 Core Hypothesis

High-frequency dynamics of the implied volatility surface exhibit **mean-reverting clustering** at the 1–5 minute horizon. Idiosyncratic quote noise, order-flow imbalances, and liquidity-provider inventory shocks cause individual strikes to deviate from the arbitrage-free surface enforced by eSSVI's no-butterfly and no-calendar-spread constraints. These deviations revert — providing a systematic edge to a model-anchored market maker.[^5][^6][^3]

### 2.2 Why eSSVI

- **Arbitrage-free by construction**: eSSVI enforces no-butterfly-arbitrage and no-calendar-spread-arbitrage across the full surface.[^7][^5]
- **Low parameter count**: Three parameters per slice (\( \theta_t, \rho_t, \psi_t \)) make it robust to calibrate on sparse intraday snapshots.[^2]
- **Smooth interpolation**: Provides fair IVs at strikes where market quotes are stale or wide.[^8]

### 2.3 Why Butterflies

A butterfly at strikes \( K_1 < K_2 < K_3 \) with equal spacing \( \Delta K \) has value approximately:

\[
B(K_2) \approx e^{-rT} q(K_2) (\Delta K)^2
\]

This is a **pure bet on local probability mass** at \( K_2 \). The structure is near delta-neutral, low-vega, positive-theta near the body, and has capped risk equal to the net debit/credit — making it capital-efficient for strike-level statistical arbitrage.[^9][^10]

***

## 3. Signal Construction

### 3.1 Data Pipeline (per bar \( t \))

1. **Snapshot**: Pull NSE option chain mid-quotes (bid/ask midpoint) across all liquid strikes and maturities via Kite API.
2. **Filter**: Drop strikes where bid-ask spread exceeds threshold (e.g., > 1.5% of mid) or volume in last N bars is zero.
3. **Compute market IV**: Invert Black–Scholes via Newton–Raphson on mid-quote to get \( \sigma^{mkt}(K, T) \).[^11]
4. **Calibrate eSSVI**: Fit slice-by-slice per expiry with no-arb constraints; use previous bar's parameters as warm-start for speed and numerical stability.[^12][^8]
5. **Extract model IV**: Evaluate \( \sigma^{eSSVI}(K, T) \) at every traded strike.

### 3.2 Residual and Z-Score

For each (K, T) pair:

\[
\varepsilon_t(K, T) = \sigma^{mkt}_t(K, T) - \sigma^{eSSVI}_t(K, T)
\]

\[
z_t(K, T) = \frac{\varepsilon_t(K, T) - \mu^{roll}_\varepsilon(K,T)}{\sigma^{roll}_\varepsilon(K, T)}
\]

where \( \mu^{roll} \) and \( \sigma^{roll} \) are computed over a rolling window of 30–60 bars.

### 3.3 Entry Threshold

A naive 1σ threshold generates excessive false positives under intraday microstructure noise. **Recommended thresholds**:

| Regime | Entry | Exit |
|---|---|---|
| Conservative | \| z \| > 2.0 | \| z \| < 0.5 |
| Moderate | \| z \| > 1.5 | \| z \| < 0.5 |
| Aggressive (scalp) | \| z \| > 1.25 | \| z \| < 0.25 |

Additionally, require signal persistence: the residual must hold the same sign for **at least 2–3 consecutive bars** to filter tick-level noise.[^3]

***

## 4. Trade Construction

### 4.1 Decision Table

| Z-score | Interpretation | Butterfly Action |
|---|---|---|
| \( z > +1.5 \) | Market IV at K rich vs. eSSVI | **Short butterfly** at K (sell body, buy wings) |
| \( z < -1.5 \) | Market IV at K cheap vs. eSSVI | **Long butterfly** at K (buy body, sell wings) |
| Asymmetric residual (one wing only) | Skew mispricing | **Broken-wing butterfly** — widen wing toward the rich side |
| Residual in near-term only | Term structure mispricing | **Diagonal butterfly** across expiries |

### 4.2 Leg Specification (Long Butterfly Example)

Given a signal at body strike \( K_2 \), with wing spacing \( \Delta K \) (typically 1× to 2× strike grid):

- Buy 1 call at \( K_1 = K_2 - \Delta K \)
- Sell 2 calls at \( K_2 \)
- Buy 1 call at \( K_3 = K_2 + \Delta K \)

Max profit = \( \Delta K - \text{net debit} \). Max loss = net debit. Breakevens at \( K_1 + \text{debit} \) and \( K_3 - \text{debit} \).[^13][^14]

***

## 5. Execution Protocol

### 5.1 Legging Sequence

A 4-leg simultaneous fill is often impossible intraday. Recommended legging order:

1. Fill the **body (2 contracts at \( K_2 \))** first — most liquid leg.
2. Immediately queue both wings as limit orders at the theoretical-fair price derived from eSSVI.
3. If wings do not fill within N seconds, hedge residual delta/vega with futures or an ATM call, then continue working.
4. Cancel and rebuild if fills drift by more than 0.3 vol points from entry assumption.

### 5.2 Liquidity Filters

- Nifty weekly ATM strikes: almost always tradeable.
- OTM strikes beyond 3% of spot: require bid-ask spread check before entering.
- Avoid entering in the final 15 minutes of the session — gamma risk explodes on same-day expiries.

### 5.3 Position Sizing

Cap per-trade risk at **0.25% of NAV** (max loss = net debit). Cap aggregate vega exposure across the open butterfly book at **±2% of NAV per 1 vol-point move**.

***

## 6. Risk Management

### 6.1 Greeks Management

A single butterfly is approximately delta-neutral at inception, but:

- **Delta drift**: monitor portfolio delta every bar; hedge with futures if \| Δ \| exceeds threshold.
- **Gamma at body**: short gamma near \( K_2 \) — avoid if realized vol is trending higher.
- **Theta**: positive — the strategy earns carry, but this is not free money; it is compensation for short-gamma tail risk.
- **Vega**: small net vega per butterfly, but aggregate across strikes can accumulate.[^4]

### 6.2 Portfolio-Level Hedges

- Aggregate delta hedged with Nifty futures.
- Aggregate vega hedged with ATM straddle if total \| ν \| exceeds limit.
- Tail hedge: permanent small long position in far-OTM puts to cap black-swan drawdowns on short-butterfly positions.

### 6.3 Model Risk Controls

- Reject signals if eSSVI calibration residual RMSE exceeds 0.5 vol points (surface fit is poor — don't trust residuals).
- Reject signals in the first 15 minutes of the session (IV surface is still resetting).
- Circuit-breaker: halt new entries if realized 5-min vol exceeds 3× its 20-day average (regime break).

### 6.4 Stop Rules

- **Time stop**: close if not reverted within 20 bars (1-min) or 8 bars (5-min).
- **Vol stop**: close if residual widens to \| z \| > 3.5 (either model is wrong or regime shift).
- **Hard P&L stop**: close leg-by-leg at −80% of max loss.

***

## 7. Calibration Mechanics

### 7.1 eSSVI Per-Slice Calibration

For each expiry \( T \), minimize:

\[
\min_{\theta_T, \rho_T, \psi_T} \sum_K w(K) \left( \sigma^{mkt}(K, T) - \sigma^{eSSVI}(K, T; \theta_T, \rho_T, \psi_T) \right)^2
\]

subject to SSVI no-arb constraints:

- \( \theta_T > 0 \), \( \rho_T \in (-1, 1) \)
- \( \psi_T (1 + \| \rho_T \|) \leq 4 \) (no-butterfly per slice)
- \( \theta_T \) non-decreasing across T (no-calendar)[^5][^7]

Weight \( w(K) \) by inverse bid-ask spread and by proximity to ATM (Gaussian kernel).

### 7.2 Warm-Start and Stability

At bar \( t \), initialize optimizer with \( (\theta_{T,t-1}, \rho_{T,t-1}, \psi_{T,t-1}) \). This cuts calibration time by 5–10× and prevents parameter jumps that would generate false signals. If Newton fails to converge in < 20 iterations, fall back to Levenberg–Marquardt; if that also fails, skip the slice for this bar.[^12]

### 7.3 Reverse Black–Scholes

Use Newton–Raphson with Brent's method as fallback. Seed initial guess at ATM with Brenner–Subrahmanyam approximation; for OTM, seed at previous-bar IV. Cap iterations at 50; reject strikes where solver fails.[^15][^11]

***

## 8. Backtest Framework

### 8.1 Data Requirements

- **Minimum**: 6 months of tick-level NSE options data across at least two expiries.
- **Preferred**: 2 years including a stressed regime (e.g., March 2020, October 2024).

### 8.2 Metrics to Report

| Metric | Target |
|---|---|
| Sharpe (net of costs) | > 1.5 |
| Max drawdown | < 8% NAV |
| Win rate per trade | > 55% |
| Avg holding period | 5–20 bars |
| Turnover | Moderate (cost-sensitive) |
| Capacity | Test with progressively larger notionals |

### 8.3 Realistic Cost Model

Each butterfly incurs 4 legs × (½ spread + brokerage + STT + exchange fees). On NSE Nifty weekly options, this totals roughly 0.4–0.8 vol points round-trip per butterfly — edge must clear this hurdle.

### 8.4 Walk-Forward Validation

Re-calibrate entry thresholds and rolling-window lengths on rolling 3-month in-sample windows; validate on 1-month out-of-sample. Avoid curve-fit of threshold to a single regime.

***

## 9. Implementation Architecture

### 9.1 System Components

- **Feed handler**: Kite WebSocket → tick normalization → 1-min/5-min bar aggregation.
- **IV engine**: Cython/Numba Newton–Raphson inverter; target < 5 ms per full chain.
- **Calibrator**: eSSVI slice fitter with warm-start; target < 50 ms per full surface.
- **Signal engine**: rolling residual stats per (K, T); z-score computation.
- **OMS**: leg sequencer, order working logic, residual-delta hedger.
- **Risk monitor**: real-time Greeks aggregation, circuit breakers.

### 9.2 Performance Budget (per 1-min bar)

| Stage | Budget |
|---|---|
| Data intake | 100 ms |
| Reverse-BS all strikes | 50 ms |
| eSSVI calibration (all expiries) | 200 ms |
| Signal generation | 20 ms |
| Order routing | 100 ms |
| **Total** | **~500 ms** |

This leaves ample slack within a 60-second bar.

***

## 10. Known Pitfalls

- **Microstructure noise masquerading as signal**: Wide spreads on OTM strikes inflate apparent mispricings. Always enforce spread filters.
- **Stale quotes**: Some NSE strikes can go 30+ seconds between quote updates. Use quote-age cutoff.
- **Pin risk near expiry**: Short-gamma butterflies are deadly in final hour of expiry — avoid the body on expiry-day ATMs.
- **Model misspecification**: eSSVI cannot capture every regime. Track surface RMSE as a live quality gate.
- **Regime breaks**: Strategy is implicitly short vol-of-vol. Tail hedge is non-negotiable.[^16]

***

## 11. Roadmap and Extensions

- **Phase 1**: Paper-trade on Nifty weekly at 5-min frequency for 4 weeks.
- **Phase 2**: Live micro-deployment (0.1% NAV per trade) for 4 weeks; compare realized vs. backtest.
- **Phase 3**: Scale to full sizing; extend to BankNifty and FinNifty.
- **Phase 4**: Research extensions — replace z-score with a Hawkes-process mean-reversion estimator; incorporate order-flow imbalance as a conditional signal; explore SABR vs. eSSVI ensemble for surface smoothing.[^17][^3]

***

## 12. Theoretical Appendix

### 12.1 Breeden–Litzenberger Linkage

The undiscounted European call price is \( C(K) = \mathbb{E}^Q[(S_T - K)^+] \). Differentiating twice:

\[
\frac{\partial^2 C}{\partial K^2} = q(K)
\]

A butterfly at \( (K - \Delta K, K, K + \Delta K) \) is the finite-difference approximation to \( q(K) (\Delta K)^2 \). The strategy thus trades \( q^{mkt}(K) - q^{eSSVI}(K) \) directly.

### 12.2 No-Butterfly Constraint in eSSVI

A slice is butterfly-arbitrage-free if Gatheral's density condition \( g(k) \geq 0 \) holds for all log-moneyness \( k \); eSSVI's parameter region guarantees this. This means the model never generates spurious convexity signals by itself — all signals arise from market-vs-model residuals.[^7][^5]

---

## References

1. [[2304.02106] eSSVI Surface Calibration - arXiv](https://arxiv.org/abs/2304.02106) - In this work I test two calibration algorithms for the eSSVI volatility surface. The two algorithms ...

2. [eSSVI Surface Calibration](http://www.arxiv.org/abs/2304.02106) - In this work I test two calibration algorithms for the eSSVI volatility surface. The two algorithms ...

3. [[PDF] High-frequency dynamics of the implied volatility surface - arXiv](https://arxiv.org/pdf/2012.10875.pdf) - Abstract. We present a Hawkes modeling of the volatility surface's high-frequency dynamics and show ...

4. [Constructing trading strategies using volatility smile/surface : r/quant](https://www.reddit.com/r/quant/comments/1mglgk7/constructing_trading_strategies_using_volatility/) - If you're a vol trader, the volatility surface is basically your “stock price”. So, essentially, wha...

5. [White Papers](https://www.zeliade.com/whitepapers/) - WHITE PAPERS : Backtesting Expected Shortfall In this work we study four test statistics used to bac...

6. [ssrn-2971502 | PDF | Volatility (Finance)](https://www.scribd.com/document/934362384/ssrn-2971502) - This document presents an extension of the SSVI volatility surface model, introducing a maturity-dep...

7. [A Note about Characterization of Calendar Spread Arbitrage in eSSVI Surfaces](https://www.scirp.org/journal/paperinformation?paperid=128666) - This paper provides a little correction to a proposition about calendar spread arbitrage in eSSVI vo...

8. [[PDF] Robust calibration and arbitrage-free interpola- tion of SSVI slices](https://www.zeliade.com/wp-content/uploads/whitepapers/zwp-008-RobustNoArbSSVI.pdf)

9. [Butterfly Options Strategy: Beginner's Guide - TradingBlock](https://www.tradingblock.com/strategies/butterfly) - A long butterfly is a short volatility trade. It benefits if implied volatility (IV) falls after you...

10. [Butterfly Spread: What It Is, With Types Explained & Example](https://www.investopedia.com/terms/b/butterflyspread.asp) - Butterfly spreads are options strategies that involve using four options contracts with three differ...

11. [Reversing Black-Scholes: Extracting Implied Volatility with Algorithms](https://www.linkedin.com/posts/neuralakarshit_newtonraphson-method-for-iv-computation-activity-7364047251385532416-7_vY) - *A slight mispricing you can exploit for a small, consistent gain. *A behavioral pattern you've noti...

12. [Fixed-point iterative algorithm for SVI model ☆](https://www.sciencedirect.com/science/article/abs/pii/S1544612325006385) - The stochastic volatility inspired (SVI) model is widely used to fit the implied variance smile. Cur...

13. [Option Butterfly](https://www.cmegroup.com/education/courses/option-strategies/option-butterfly) - Look at the butterfly options strategy, how to trade it, the benefits and a comparison to the stradd...

14. [Butterfly Strategy - Examples, Types & How to Use It? | IndiaBonds](https://www.indiabonds.com/bonduni/blogs/what-is-butterfly-strategy/) - In trading terms, “counting butterflies” is best done before entering (to map payoff, break evens, a...

15. [Reverse Engineering The Black Scholes Formula for Volatility - Reddit](https://www.reddit.com/r/options/comments/6ea9gs/reverse_engineering_the_black_scholes_formula_for/) - I have tried to reverse the BS Formula solving for implied volatility given everything else, but hav...

16. [My method on making money trading mispriced options with AI](https://www.reddit.com/r/options/comments/1o7prtk/my_method_on_making_money_trading_mispriced/) - My method on making money trading mispriced options with AI

17. [Butterfly Spread Options Trading Strategy In Python - QuantInsti Blog](https://blog.quantinsti.com/butterfly-spread-options-trading-strategy-python/) - Butterfly Options Strategy is a combination of Bull Spread and Bear Spread, a Neutral Trading Strate...

