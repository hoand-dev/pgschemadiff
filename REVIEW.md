# Code Review — `init` commit (9e831f5)

Reviewed: 2026-05-24  
Scope: all files in the `init` commit

---

## P0 — Critical (app cannot run)

### 1. Package structure does not exist

`pyproject.toml` declares:
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/pgschemadiff"]
```

There is no `src/pgschemadiff/` directory. All source files (`app.py`, `home.py`, `yaml_loader.py`, etc.) are committed flat at the repo root. The README documents the intended layered layout (`src/pgschemadiff/domain/`, `infrastructure/`, `presentation/`) but that layout was never created.

**Impact:** `pip install -e .` or `uv sync` installs nothing. Every import in every file fails with `ModuleNotFoundError`.

**Fix:** Create the directory tree described in README and move files into it, or change `pyproject.toml` to point at the root package.

---

### 2. All inter-module imports reference non-existent packages

Every file uses package-relative imports that assume the intended `src/` layout:

| File | Import | Problem |
|------|--------|---------|
| `__main__.py:9` | `from pgschemadiff.presentation.app import PgSchemaDiffApp` | no such package |
| `app.py:9` | `from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader` | no such package |
| `app.py:10` | `from pgschemadiff.presentation.screens.home import HomeScreen` | no such package |
| `home.py:11` | `from pgschemadiff.domain.models import Profile` | no such package |
| `home.py:12` | `from pgschemadiff.presentation.widgets.confirm_dialog import ConfirmDialog` | no such package |
| `home.py:13` | `from pgschemadiff.presentation.widgets.profile_item import ProfileListItem` | no such package |
| `profile_detail.py:9` | `from pgschemadiff.domain.models import Profile` | no such package |
| `profile_item.py:9` | `from pgschemadiff.domain.models import Profile` | no such package |
| `yaml_loader.py:9` | `from pgschemadiff.domain.models import Profile` | no such package |

Also, there are no `__init__.py` files anywhere, so even if the directories existed, `domain.models` would not expose `Profile` as `from pgschemadiff.domain.models import Profile` without a `models/__init__.py` re-exporting it.

---

### 3. `confirm_dialog.py` is missing entirely

`home.py:12` imports:
```python
from pgschemadiff.presentation.widgets.confirm_dialog import ConfirmDialog
```

`confirm_dialog.py` does not exist anywhere in the repository. `action_delete_profile` (home.py:122–150) calls `self.app.push_screen(ConfirmDialog(...))` — this code path crashes with `ImportError` on startup before the app even launches.

---

### 4. `profiles.yaml` is at repo root but config resolver never finds it

`__main__.py:23` looks for the config at `./config/profiles.yaml` (the local dev path). The sample `profiles.yaml` was committed to the repo root, not to `config/profiles.yaml`. Running the app from the repo root will silently start with zero profiles unless `$PGSCHEMADIFF_CONFIG` is set.

---

## P1 — Hidden bugs

### 5. Delete-by-name can silently corrupt list state

`home.py:133`:
```python
self._profiles = [p for p in self._profiles if p.name != profile.name]
lv.remove_items([idx])
```

`Profile.name` is not unique (no uniqueness constraint on the model or at load time). If two profiles share a name, `_profiles` loses both but `lv` only removes one DOM item. After this, `self._profiles[new_idx]` retrieves a different profile than what the highlighted list item shows — silent data corruption.

**Fix:** Key deletions by object identity (`p is not profile`) or enforce unique names at load time.

---

### 6. `lv.index` and `_profiles` indices can diverge

`home.py:136–139`:
```python
new_idx = min(idx, len(self._profiles) - 1)
lv.index = new_idx
self._render_detail(self._profiles[new_idx])
```

`lv.index` is set *after* `lv.remove_items([idx])`. If Textual asynchronously shifts focus during `remove_items`, `lv.index` may already have changed by the time `new_idx` is set. The subsequent `self._render_detail(self._profiles[new_idx])` could then display the wrong profile. This is a race between the ListView's internal state update and the manual index assignment.

---

## P2 — Maintainability / code duplication

### 7. `profile_detail.py` is dead code that fully duplicates `home.py`

The README itself says `profile_detail.py` is "(unused — đã inline vào HomeScreen)". The 67-line `ProfileDetail.compose()` + `_render()` is a word-for-word copy of the inline detail pane in `HomeScreen`. Any rendering change now requires updating two files.

**Options:** Either delete `profile_detail.py` and commit to the inlined approach, or restore `ProfileDetail` as the canonical widget and have `HomeScreen` use it.

---

### 8. `_render_detail` (home.py) and `ProfileDetail._render` (profile_detail.py) are identical

Line-for-line duplicates:

- `home.py:64–91` — `HomeScreen._render_detail()`
- `profile_detail.py:39–67` — `ProfileDetail._render()`

Both do the same Rich-markup string building for source/target/schemas/ignore/mode. A one-character bug fix in one is silently missed in the other.

---

## P3 — Design / validation gaps

### 9. `Profile.mode` has no type constraint

```python
mode: str = "schema-only"
```

`mode` should be `Literal["schema-only", "data-only", "full"]` (or an `Enum`). Currently any string is accepted silently; a typo at YAML level passes Pydantic validation and will only fail when something downstream tries to act on the mode value.

---

### 10. No error handling in `ProfileLoader.load()`

`yaml_loader.py:29`:
```python
return [Profile.model_validate(p) for p in data["profiles"]]
```

A malformed entry raises `pydantic.ValidationError` and crashes the app before the TUI starts. The user sees a raw Python traceback instead of a friendly message. A try/except per profile with a warning (or skip) would be more resilient.

---

## P4 — Security notes

### 11. DSN string contains plaintext password

`profile.py:28–29`:
```python
def dsn(self) -> str:
    pwd = f":{self.password}" if self.password else ""
    return f"postgresql://{self.user}{pwd}@{self.host}:{self.port}/{self.database}"
```

The `dsn()` return value, if ever logged or included in an exception message, leaks the password. `display()` correctly redacts it. Ensure `dsn()` output is never written to logs, tracebacks, or error notifications. Consider using a `SecretStr` field for `password` and constructing the DSN in a way that psycopg accepts keyword arguments rather than a DSN URL.

---

## P5 — Minor / style

### 12. Dead CSS selectors in `styles.tcss`

`.field-label`, `.field-value`, `.field-value-muted` (styles.tcss:97–106) are defined but never applied. The rendering uses inline Rich markup (`[#6c7086]…[/]`) inside single `Static` widgets rather than separate label/value DOM nodes. These selectors are unreachable and will never match anything.

---

## Summary table

| # | Severity | Category | File | Short description |
|---|----------|----------|------|-------------------|
| 1 | P0 | Structure | `pyproject.toml` | `src/pgschemadiff/` package doesn't exist |
| 2 | P0 | Structure | all `.py` files | All inter-module imports reference missing packages |
| 3 | P0 | Missing file | `home.py:12` | `confirm_dialog.py` not committed — ImportError on startup |
| 4 | P0 | Config | `__main__.py:23` | Sample `profiles.yaml` not at expected `config/` path |
| 5 | P1 | Bug | `home.py:133` | Delete-by-name removes all duplicate-named profiles from model |
| 6 | P1 | Bug | `home.py:136` | ListView index / `_profiles` index can diverge after delete |
| 7 | P2 | Duplication | `profile_detail.py` | Entire file is dead — logic inlined in `HomeScreen` |
| 8 | P2 | Duplication | `home.py`, `profile_detail.py` | `_render_detail` / `_render` are identical |
| 9 | P3 | Validation | `profile.py:42` | `mode` field accepts any string — should be `Literal` |
| 10 | P3 | Error handling | `yaml_loader.py:29` | No per-profile error handling — bad YAML crashes app |
| 11 | P4 | Security | `profile.py:28` | `dsn()` returns plaintext password in URL |
| 12 | P5 | Style | `styles.tcss:97` | Dead CSS selectors never matched by any widget |
