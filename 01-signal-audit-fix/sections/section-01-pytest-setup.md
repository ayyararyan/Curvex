# Section 01 — Pytest Setup

## Overview

This section covers the configuration changes needed to add pytest to the project and make the `tests/` directory discoverable. It is a prerequisite for section-04-test-suite. No changes to `src/` are made here.

**Dependency:** None (parallelizable with section-02 and section-03).
**Blocks:** section-04-test-suite.

---

## Preconditions

Before making changes, verify:

1. There is no existing `tests/` directory at the project root. If one exists, note whether it contains an `__init__.py` — that file must not be added in this section.
2. There is no existing `[tool.pytest.ini_options]` section in `pyproject.toml`. If one exists, merge into it rather than adding a duplicate.
3. There is no existing `pytest` entry in any dependency group. If one exists, bump it to `>=8.0` if lower.

---

## Files to Change

**`pyproject.toml`** — two additions:

1. Add `pytest>=8.0` to dev dependencies.
2. Add a `[tool.pytest.ini_options]` section.

**`tests/`** — create the directory (empty, no `__init__.py`).

---

## Change: pyproject.toml

### Dev Dependency Entry

This project uses `uv`. The correct dependency group mechanism depends on the existing `pyproject.toml` structure:

- If the file uses UV's native `[dependency-groups]` (key `dev` under that table), add `pytest>=8.0` there.
- If it uses PEP 508 optional dependencies (`[project.optional-dependencies]` with a `dev` key), add `pytest>=8.0` there.

Inspect the file first to determine which pattern is in use. Do not add both.

The entry to add is:

```
"pytest>=8.0"
```

### pytest.ini_options Section

Add the following section to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

`testpaths = ["tests"]` restricts pytest's collection scope to the `tests/` directory at the project root, preventing it from scanning `src/` or other directories.

`pythonpath = ["src"]` inserts `src/` onto `sys.path` at test collection time. This is what allows test files to write `from essvi_bfly.signal.zscores import ...` without requiring the package to be installed in editable mode. Without this entry, pytest would fail to import the package unless `uv pip install -e .` had been run first.

---

## Change: Create tests/ Directory

Create an empty `tests/` directory at the project root (the same level as `src/` and `pyproject.toml`):

```
<project_root>/
  src/
    essvi_bfly/
      ...
  tests/           ← create this
  pyproject.toml
```

Do **not** create `tests/__init__.py`. Modern pytest (≥ 8.0) discovers test files by walking the directory without requiring an `__init__.py`, and its presence changes import semantics in ways that can break `pythonpath`-based imports.

**Do** create `tests/.gitkeep` so the empty directory is tracked by git and survives a clean checkout or CI environment before section-04 adds test files.

---

## Verification

After making the changes, run:

```
uv run pytest --collect-only
```

Expected output: pytest starts, finds zero tests, and exits with **code 5** ("no tests collected"). Exit code 5 is pytest's standard response for an empty collection; it is not an error. The absence of import errors and the "no tests collected" message confirms:

- `pyproject.toml` syntax is valid.
- `pythonpath = ["src"]` is respected (pytest can resolve `essvi_bfly` if any import is attempted).
- `testpaths = ["tests"]` restricts collection to the empty directory without error.

If `uv run pytest --collect-only` exits with a non-zero code or prints a TOML parse error, check that the `[tool.pytest.ini_options]` section was added with correct TOML syntax (arrays use `["..."]`, not bare strings).

---

## What This Section Does Not Include

- No test code — all test content is in section-04-test-suite.
- No `conftest.py` — not needed for this project.
- No changes to `src/essvi_bfly/` — this section is config-only.
- No changes to `zscores.py` or `candidate_selection.py` — those are section-02 and section-03.
