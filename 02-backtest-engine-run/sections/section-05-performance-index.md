# Section 05: Performance Index — Per-Contract Bar Index

## Overview

Pre-compute a per-contract bar index so `_next_bar_for_contract` performs an O(log N) binary search instead of an O(N) DataFrame filter on every candidate. With thousands of candidates, the current implementation is the main simulation bottleneck.

**Depends on:** section-01 (logging in engine.py)  
**Parallelizable with:** sections 02, 03, 04 (safe — touches only `_simulate` pre-loop setup and `_next_bar_for_contract`)  
**Blocks:** section-07

---

## File to Modify

`src/essvi_bfly/backtest/engine.py`

---

## Tests First

Add to `tests/test_engine.py`:

```python
class TestBuildContractBarIndex:
    def test_returns_dict_keyed_by_contract_name(self):
        """_build_contract_bar_index returns dict with contract_name keys."""

    def test_values_are_sorted_numpy_arrays(self):
        """Each dict value is a sorted np.ndarray of bar_close timestamps."""

    def test_all_contracts_present(self):
        """Every unique contract_name in the chain has an entry in the index."""

    def test_empty_chain_returns_empty_dict(self):
        """Empty chain DataFrame produces empty dict (no KeyError)."""


class TestNextBarForContract:
    def test_returns_first_bar_after_entry(self):
        """Returns the smallest bar_close strictly > entry_bar for the contract."""

    def test_returns_none_when_no_bar_after_entry(self):
        """Returns None when entry_bar is at or after the last bar."""

    def test_uses_binary_search_not_full_filter(self):
        """Result matches naive filter approach for a sample contract/bar
        when bar_index is provided."""

    def test_performance_10k_lookups(self):
        """10,000 lookups on a 100-contract × 75-bar chain complete in < 0.1s."""
        # Mark: @pytest.mark.slow — skip in CI via pytest -m "not slow"
```

Helpers:
```python
def _synthetic_chain(contracts: list[str], bars_per_contract: int) -> pd.DataFrame:
    """Build a synthetic chain DataFrame with bar_close and contract_name columns."""
```

---

## Implementation

### 1. Add `_build_contract_bar_index`

```python
def _build_contract_bar_index(self, chain: pd.DataFrame) -> dict[str, np.ndarray]:
    """Pre-compute sorted bar_close arrays per contract_name.

    Returns dict mapping contract_name → sorted np.ndarray of bar_close timestamps.
    Used by _next_bar_for_contract for O(log N) lookup via np.searchsorted.
    Called once before the candidate loop in _simulate.

    Note: index is static — do not use with a streaming/appended chain.
    """
```

Implementation:
- Group `chain` by `"contract_name"`.
- For each group: extract `bar_close` values, call `np.unique` (sorts and deduplicates).
- Return the dict.

### 2. Update `_next_bar_for_contract`

Add optional `bar_index` parameter:

```python
def _next_bar_for_contract(
    self,
    chain: pd.DataFrame,
    contract_name: str,
    after_bar: pd.Timestamp,
    bar_index: dict[str, np.ndarray] | None = None,
) -> pd.Timestamp | None:
    """Return the first bar_close strictly after after_bar for contract_name.

    If bar_index provided: O(log N) via np.searchsorted.
    If bar_index is None: legacy O(N) DataFrame filter (backward compat).
    Returns None if contract absent or no bar exists after after_bar.
    """
```

When `bar_index` is provided:
```python
arr = bar_index.get(contract_name)
if arr is None or len(arr) == 0:
    return None
i = np.searchsorted(arr, after_bar, side='right')
if i >= len(arr):
    return None
return pd.Timestamp(arr[i])
```

When `bar_index` is `None`: preserve existing filter path unchanged.

### 3. Wire Index into `_simulate`

Before the candidate loop in `_simulate`, add:
```python
bar_index = self._build_contract_bar_index(chain)
```

Pass to the existing `_next_bar_for_contract` call:
```python
entry_bar = self._next_bar_for_contract(
    chain, candidate.body_contract, candidate.bar_close, bar_index=bar_index
)
```

---

## Correctness Contract

The binary search result must be identical to the naive filter for every `(contract_name, after_bar)` pair. Verified by `test_uses_binary_search_not_full_filter`.

The performance test is a regression guard only — mark `@pytest.mark.slow` and skip in time-sensitive CI.

---

## Acceptance Checklist

- [ ] `_build_contract_bar_index` returns correct dict for a synthetic 3-contract chain — `TestBuildContractBarIndex` tests pass
- [ ] `_next_bar_for_contract` with `bar_index` produces same result as legacy path — `test_uses_binary_search_not_full_filter` passes
- [ ] `_next_bar_for_contract` returns None at end of contract data — test passes
- [ ] `uv run pytest tests/ -v -k "not slow"` exits 0
