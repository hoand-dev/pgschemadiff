# Code Review — pgschemadiff

**Date:** 2026-05-24  
**Reviewer:** Claude (claude-sonnet-4-6)  
**Scope:** `main` branch (init commit `9e831f5`) + all 14 `claude/*` feature branches

---

## Executive Summary

The repository has a **completely broken `main` branch** (app cannot run) and
**14 divergent, un-merged feature branches** — all authored by Claude in prior
sessions. None of the fixes have been consolidated back to `main`. Two
fundamentally incompatible architecture tracks have emerged in parallel:

- **Track A** (`claude/stoic-pascal-LOygS`): Full Clean Architecture rewrite
  (domain/application/infrastructure layers, import-linter, CI, ADRs).
- **Track B** (8 other branches): Minimal prototype fix — move files into
  `src/pgschemadiff/`, add `ConfirmDialog`, optionally add tests.

Merging either track as-is into `main` would be straightforward, but they
cannot both land without a deliberate decision on which architecture to pursue.

---

## P0 — Blockers (app cannot run)

### P0-1 · Package layout mismatch — all imports broken

**File:** every source file on `main`  
**Finding:** All `.py` files import from `pgschemadiff.*` sub-packages
(e.g., `from pgschemadiff.domain.models import Profile`,
`from pgschemadiff.presentation.app import PgSchemaDiffApp`), but no
`src/pgschemadiff/` directory exists on `main`. `pyproject.toml` correctly
declares `packages = ["src/pgschemadiff"]` (hatchling src layout), so the
package would be installed from `src/`, but the source tree doesn't have that
path at all. Running `python -m pgschemadiff` fails immediately with
`ModuleNotFoundError`.

**Fix required:** Move all source files into
`src/pgschemadiff/{domain,infrastructure,presentation}/` matching the import
paths. All Track B branches have done this correctly.

---

### P0-2 · `confirm_dialog.py` missing

**File:** `home.py` line ~12  
**Finding:**
```python
from pgschemadiff.presentation.widgets.confirm_dialog import ConfirmDialog
```
`ConfirmDialog` is imported and used in `action_delete_profile`, but no
`confirm_dialog.py` exists anywhere on `main`. The import raises
`ImportError` at startup.

**Fix required:** Add `ConfirmDialog` (a `ModalScreen[bool]`) before the
delete action can work. All Track B branches implement this.

---

### P0-3 · `profiles.yaml` at wrong path

**File:** `__main__.py` `_default_config_path()`  
**Finding:** `__main__.py` searches for `config/profiles.yaml` first, then
XDG paths. `profiles.yaml` on `main` is at the repository root, so the
default config search never finds it, and every new run starts with zero
profiles.

**Fix required:** Move `profiles.yaml` → `config/profiles.yaml`.

---

## P1 — Critical Bugs

### P1-1 · Delete-by-name desyncs `self._profiles` from `ListView`

**File:** `home.py` `action_delete_profile` (inner `on_confirm` callback)  
**Finding:**
```python
def on_confirm(confirmed: bool | None) -> None:
    if confirmed:
        idx = lv.index or 0
        self._profiles = [p for p in self._profiles if p.name != profile.name]
        lv.remove_items([idx])          # ← removes by integer index
        ...
        new_idx = min(idx, len(self._profiles) - 1)
        lv.index = new_idx
        self._render_detail(self._profiles[new_idx])
```
Three separate issues:
1. `self._profiles` is filtered by `name` (removes all matches), but
   `lv.remove_items([idx])` removes exactly one item by its list index. If
   two profiles share the same name, the model removes both but the ListView
   only removes one — they permanently diverge.
2. `lv.remove_items()` does not exist in the public Textual API. The correct
   approach is to call `.remove()` on the `ListItem` widget directly, or
   `lv.clear()` and repopulate.
3. After filtering `self._profiles`, `new_idx = min(idx, len(self._profiles)-1)`
   computes the post-delete index based on the *new* model length, but then
   passes it to `self._render_detail(self._profiles[new_idx])` — this is
   correct only if `ListView`'s internal index also moved to the same position,
   which is not guaranteed after `lv.remove_items`.

---

### P1-2 · `lv.index or 0` treats index 0 as falsy

**File:** `home.py` `action_delete_profile`  
**Finding:**
```python
idx = lv.index or 0
```
`ListView.index` returns `int | None`. The `or 0` pattern treats `0` as
falsy and substitutes `0` — coincidentally correct here, but the intent is
wrong. The correct guard is:
```python
idx = lv.index if lv.index is not None else 0
```

---

## P2 — Architecture / Maintainability

### P2-1 · `profile_detail.py` is dead duplicated code

**File:** `profile_detail.py`, `home.py`  
**Finding:** `HomeScreen` inlines the entire profile detail rendering inside
`_render_detail()`. `profile_detail.py` defines a standalone `ProfileDetail`
widget with identical rendering logic in `_render()`, but `HomeScreen` never
imports or instantiates `ProfileDetail`. The widget exists in the repository
but is not connected to anything. Any future change to field rendering must be
made in two places.

**Fix required:** Either wire `HomeScreen` to use `ProfileDetail`, or delete
`profile_detail.py`.

---

### P2-2 · `ProfileDetail._render` shadows `Widget._render`

**File:** `profile_detail.py` method `_render`  
**Finding:** Textual's `Widget` has an internal `_render(console, renderable,
region)` method. Defining a zero-argument `_render(self)` in a subclass
shadows it with an incompatible signature. mypy will flag this under strict
mode and Textual could call the wrong method if the rendering pipeline changes.

**Fix:** Rename to `_update_display()` or `_refresh_detail()`. Multiple
feature branches (`determined-goodall-KGag4`, `compassionate-hamilton-YFKhv`)
already apply this fix.

---

### P2-3 · No error handling for `ProfileLoader.load()` in `app.py`

**File:** `app.py` `on_mount`  
**Finding:**
```python
def on_mount(self) -> None:
    loader = ProfileLoader(self.config_path)
    profiles = loader.load()
    self.push_screen(HomeScreen(profiles))
```
`ProfileLoader.load()` calls `Profile.model_validate()` on every YAML entry.
A single malformed profile (wrong type, missing field) raises
`pydantic.ValidationError` and crashes the TUI with an unhandled exception —
the user sees a Python traceback in a broken terminal instead of a useful
error message.

**Fix:** Catch `ValidationError` and either skip the invalid profile (with a
notification) or display a startup error screen.

---

### P2-4 · Blocking IO in synchronous `on_mount`

**File:** `app.py`  
**Finding:** YAML config loading is fast for small files, but `on_mount` is
called in the event loop. For parity with planned async DB connection work,
this should be `async def on_mount` using `anyio.Path` or a thread executor.
Not a bug now but sets a bad pattern for future DB integrations.

---

### P2-5 · `on_list_view_selected` and Enter binding conflict

**File:** `home.py`  
**Finding:**
```python
BINDINGS = [
    Binding("enter", "compare", "Compare", show=True, priority=True),
    ...
]

def on_list_view_selected(self, event: ListView.Selected) -> None:
    if isinstance(event.item, ProfileListItem):
        self._start_compare(event.item.profile)
```
With `priority=True`, the Screen's `action_compare` intercepts Enter before
`ListView` processes it — so `on_list_view_selected` should never fire via
keyboard. However, clicking an item with the mouse *does* fire
`on_list_view_selected` without going through the binding. The result is two
code paths to `_start_compare` that will diverge if `action_compare` ever
gains different logic (e.g., validation before comparing). A single path
through `action_compare` is safer.

---

### P2-6 · Branch proliferation without consolidation (process issue)

**Finding:** 14 Claude-authored branches exist. Eight solve the same P0
problem (src layout restructure) independently, each with minor variations.
None has been merged to `main`. The most feature-complete Track B branch is
`claude/compassionate-hamilton-YFKhv` (2026-05-24, includes tests) or
`claude/compassionate-hamilton-f4xvz` (includes `ComparingScreen`). Track A
(`claude/stoic-pascal-LOygS`) is the only branch with a full Clean
Architecture foundation, CI, and the beginning of the diff engine domain
model.

**Recommendation:** Choose one track and consolidate. If the goal is a
working prototype first, merge `claude/compassionate-hamilton-YFKhv` or
`claude/compassionate-hamilton-f4xvz`. If the goal is the production
architecture described in `README.md`, continue from `claude/stoic-pascal-LOygS`.
Delete or close the remaining branches after the decision.

---

## P3 — Design Issues

### P3-1 · `Profile.mode` should be a `Literal` type

**File:** `profile.py` (main) / `src/pgschemadiff/domain/models/profile.py`  
**Finding:**
```python
mode: str = "schema-only"
```
`mode` accepts any string. The domain only supports `"schema-only"`,
`"data-diff"`, and `"full"` (per README). An invalid value from YAML silently
passes validation.

**Fix:**
```python
from typing import Literal
mode: Literal["schema-only", "data-diff", "full"] = "schema-only"
```

---

### P3-2 · `ProfileLoader.save()` performs full-file rewrite

**File:** `yaml_loader.py`  
**Finding:** Saving any edit rewrites the entire `profiles.yaml`. This is
safe for the prototype but means:
- Comments and YAML formatting in the file are destroyed on first save.
- Two concurrent TUI instances (unlikely but possible) would silently
  overwrite each other's writes.

**Note:** Acceptable for current scope; document as a known limitation.

---

## P4 — Security

### P4-1 · `dsn()` embeds plaintext password in DSN string

**File:** `profile.py` `ConnectionInfo.dsn()`  
**Finding:**
```python
def dsn(self) -> str:
    pwd = f":{self.password}" if self.password else ""
    return f"postgresql://{self.user}{pwd}@{self.host}:{self.port}/{self.database}"
```
The full DSN including password appears in the return value. If this string is
ever logged, printed in a traceback, included in a notification, or passed to
`structlog` at debug level, the password is exposed. `display()` correctly
masks the password; `dsn()` should be treated as a sensitive value and never
passed to any logging infrastructure.

**Recommendation:** Add a `__repr__` override to `ConnectionInfo` that
returns a masked form, and document that `dsn()` is security-sensitive.

---

### P4-2 · ConfirmDialog markup injection via profile name

**Affects:** All Track B branches that implement `ConfirmDialog`  
**Finding:** In `action_delete_profile`:
```python
ConfirmDialog(
    body=f"This will permanently delete '{profile.name}'.\n..."
)
```
If `profile.name` contains Textual markup characters (e.g., `[b]hack[/b]`),
they are rendered as markup, causing unintended formatting or a markup parse
error. For `ConfirmDialog` bodies, profile names should be escaped or rendered
as plain text using `Text.from_markup` escaping.

---

## P5 — Minor / Polish

### P5-1 · Dead CSS selectors in `styles.tcss`

**File:** `styles.tcss`  
**Finding:** The stylesheet contains selectors for widget IDs and classes that
reference widgets that do not exist on `main` (e.g., selectors for
`ProfileDetail`, `ConfirmDialog`, `#comparing-screen`). These are harmless but
add noise.

---

### P5-2 · `app.py` CSS path won't resolve after src layout migration

**File:** `app.py` `CSS_PATH = "styles.tcss"`  
**Finding:** Textual resolves `CSS_PATH` relative to the file that declares it.
On `main`, `app.py` is at the root and `styles.tcss` is also at the root —
this works. After moving `app.py` to `src/pgschemadiff/presentation/app.py`,
`CSS_PATH = "styles.tcss"` will look for `src/pgschemadiff/presentation/styles.tcss`.
The `YFKhv` branch handles this correctly by moving `styles.tcss` into the
`presentation/` package. Other branches (`determined-goodall-QTpaP`) miss this
and the CSS will silently fail to load.

---

## Branch Status Summary

| Branch | Date | Content | Status |
|---|---|---|---|
| `main` | 2026-05-23 | Original prototype (flat layout) | **Unrunnable — P0 blockers** |
| `claude/stoic-pascal-LOygS` | 2026-05-23 | Full Clean Architecture rewrite, P1-DOM-01 domain types | Ready for review; incompatible with Track B |
| `claude/compassionate-hamilton-YFKhv` | 2026-05-24 | src layout + confirm_dialog + tests (10 passing) | Best Track B candidate |
| `claude/compassionate-hamilton-f4xvz` | 2026-05-24 | src layout + ComparingScreen stub | Adds ComparingScreen but no tests |
| `claude/determined-goodall-KGag4` | 2026-05-23 | src layout + CI workflow | Has CI but different style fixes |
| `claude/compassionate-hamilton-dzdr7` | 2026-05-24 | src layout + domain/infra/presentation hierarchy | Solid structure, 10 tests |
| `claude/compassionate-hamilton-e0pY9` | 2026-05-23 | src layout + 17 tests + ConfirmDialog escape binding | Most tests |
| `claude/compassionate-hamilton-zw8jl` | 2026-05-23 | src layout + ComparingScreen | Older version of f4xvz |
| `claude/determined-goodall-QTpaP` | 2026-05-24 | src layout, no tests, CSS path issue | Incomplete |
| `claude/fervent-thompson-dyTEq` | 2026-05-24 | Review findings doc only | Planning artifact |
| `claude/pensive-lamport-f8gXT` | 2026-05-24 | TASK_INDEX.md only | Planning artifact |
| `claude/nice-brahmagupta-nkwW5` | 2026-05-23 | TASK_INDEX.md only | Planning artifact |
| `claude/determined-goodall-4R9qN` | 2026-05-24 | TASK_INDEX.md only | Planning artifact |
| `claude/elegant-albattani-0MjWg` | 2026-05-24 | AI_STATE.md + TASK_INDEX.md | Planning artifact |
| `claude/elegant-albattani-SuEow` | 2026-05-24 | AI_STATE.md + TASK_INDEX.md | Planning artifact |
| `claude/elegant-albattani-yN6AK` | 2026-05-24 | AI_STATE.md + TASK_INDEX.md | Planning artifact |

---

## Recommended Next Actions (Priority Order)

1. **Decide on architecture track** — Pick Track A (Clean Architecture, `stoic-pascal`) or Track B (prototype fix). This unblocks everything else.
2. **Merge the chosen branch to `main`** — The P0 blockers are all fixed on any Track B branch.
3. **Fix P1-1** — Rewrite delete logic using `item.remove()` on the `ListItem` widget directly to eliminate ListView/model divergence.
4. **Fix P2-1** — Delete `profile_detail.py` or wire it into `HomeScreen`.
5. **Fix P3-1** — Add `Literal` type to `Profile.mode`.
6. **Add startup error handling** (P2-3) before any DB connection work begins.
7. **Clean up planning branches** — Delete the 6 branches that contain only `TASK_INDEX.md` / `AI_STATE.md` docs.
