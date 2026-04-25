<!-- PROJECT_CONFIG
runtime: python-uv
test_command: uv run pytest
END_PROJECT_CONFIG -->

<!-- SECTION_MANIFEST
section-01-pytest-setup
section-02-zscores-fix
section-03-candidate-comments
section-04-test-suite
END_MANIFEST -->

# Implementation Sections Index

## Dependency Graph

| Section | Depends On | Blocks | Parallelizable |
|---|---|---|---|
| section-01-pytest-setup | — | section-04 | Yes |
| section-02-zscores-fix | — | section-04 | Yes |
| section-03-candidate-comments | — | section-04 | Yes |
| section-04-test-suite | 01, 02, 03 | — | No |

## Execution Order

1. section-01-pytest-setup, section-02-zscores-fix, section-03-candidate-comments (all parallel, no deps)
2. section-04-test-suite (after all three complete)

## Section Summaries

### section-01-pytest-setup

Add `pytest>=8.0` to `pyproject.toml` dev dependencies and add a `[tool.pytest.ini_options]` section with `testpaths = ["tests"]` and `pythonpath = ["src"]`. Create an empty `tests/` directory at the project root. This is a prerequisite for running any tests in section 04.

No code changes to `src/`. No `tests/__init__.py`.

### section-02-zscores-fix

Fix the session-boundary bug in `src/essvi_bfly/signal/zscores.py`, function `add_residual_zscores`. Three sub-changes:

1. **Sort order**: change `sort_values(["contract_name", "bar_close"])` to `sort_values(["contract_name", "session_date", "bar_close"])`.
2. **Rolling window groupby**: change the `.groupby("contract_name")` for the rolling mean/std `.transform(...)` calls to `.groupby(["contract_name", "session_date"])`. Extract the key as a local variable `group_keys = ["contract_name", "session_date"]`.
3. **Persistence counter groupby + reindex guard**: change the `.groupby("contract_name").apply(persistence)` to `.groupby(["contract_name", "session_date"], group_keys=False).apply(persistence).reindex(out.index)`.

No other changes to this file. The `persistence()` helper function and all thresholds/config reads remain unchanged.

### section-03-candidate-comments

Add a 3-line comment block at the top of `select_candidates` in `src/essvi_bfly/signal/candidate_selection.py` documenting:
- The direction mapping: z < 0 → SHORT_BFLY (buy underpriced body); z ≥ 0 → LONG_BFLY (sell overpriced body)
- Consistency with `engine.py._build_actions` (LONG_BFLY entry = BUY wings + SELL body × 2)
- That z = 0 never reaches the direction branch in practice (filtered by `abs(z) < entry_z` upstream)

No code changes. No new imports.

### section-04-test-suite

Create `tests/test_signal.py` with 8 tests. Import from:
- `essvi_bfly.signal.zscores` (persistence, add_residual_zscores)
- `essvi_bfly.signal.candidate_selection` (select_candidates)
- `essvi_bfly.backtest.engine` (BacktestEngine or _build_actions)
- `essvi_bfly.config` (BacktestConfig)

Define a `make_butterfly_chain(body_zscore, body_iv_market, body_iv_essvi, persistence=3)` helper that returns `(chain_df, diagnostics_df, config)` with minimal synthetic data satisfying all filter conditions (quote_ok, converged, enforce_otm_structure_side=False, lot_size=1, contract_multiplier=1, etc.).

Tests (write in this order per TDD plan):
1. `test_build_actions_long_bfly_convention` — LONG_BFLY entry action list is BUY/SELL/SELL/BUY
2. `test_persistence_counter_sign_flip` — Case A: sign flip sequence
3. `test_persistence_counter_leading_nan` — Case B: leading NaN (session warmup pattern)
4. `test_zscore_rolling_within_session` — session 2 bars 0-8 are NaN after fix
5. `test_direction_long_bfly` — positive z → LONG_BFLY candidate
6. `test_direction_short_bfly` — negative z → SHORT_BFLY candidate
7. `test_edge_long_bfly_positive` — LONG_BFLY edge > 0 when iv_market > iv_essvi for body
8. `test_edge_short_bfly_positive` — SHORT_BFLY edge > 0 when iv_market < iv_essvi for body
