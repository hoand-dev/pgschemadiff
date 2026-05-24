# Migration: flat prototype → src/pgschemadiff package

This guide walks through reorganising the current flat-file prototype into the
target `src/pgschemadiff/` package layout described in [`architecture.md`](architecture.md).

Until this migration is done the app **cannot be run** — the Python import paths in
every source file reference `pgschemadiff.presentation.*`, `pgschemadiff.domain.*`, etc.,
which only resolve once the package hierarchy exists.

---

## 1. Create directory structure

```bash
mkdir -p src/pgschemadiff/domain/models
mkdir -p src/pgschemadiff/domain/diff
mkdir -p src/pgschemadiff/domain/migration
mkdir -p src/pgschemadiff/infrastructure/config
mkdir -p src/pgschemadiff/infrastructure/postgres
mkdir -p src/pgschemadiff/presentation/screens
mkdir -p src/pgschemadiff/presentation/widgets
mkdir -p config
```

---

## 2. Add `__init__.py` files

```bash
touch src/pgschemadiff/__init__.py
touch src/pgschemadiff/domain/__init__.py
touch src/pgschemadiff/domain/models/__init__.py
touch src/pgschemadiff/domain/diff/__init__.py
touch src/pgschemadiff/domain/migration/__init__.py
touch src/pgschemadiff/infrastructure/__init__.py
touch src/pgschemadiff/infrastructure/config/__init__.py
touch src/pgschemadiff/infrastructure/postgres/__init__.py
touch src/pgschemadiff/presentation/__init__.py
touch src/pgschemadiff/presentation/screens/__init__.py
touch src/pgschemadiff/presentation/widgets/__init__.py
```

---

## 3. Move source files

| From (root) | To (package) |
|-------------|--------------|
| `__main__.py` | `src/pgschemadiff/__main__.py` |
| `app.py` | `src/pgschemadiff/presentation/app.py` |
| `home.py` | `src/pgschemadiff/presentation/screens/home.py` |
| `profile.py` | `src/pgschemadiff/domain/models/profile.py` |
| `profile_item.py` | `src/pgschemadiff/presentation/widgets/profile_item.py` |
| `profile_detail.py` | `src/pgschemadiff/presentation/widgets/profile_detail.py` |
| `yaml_loader.py` | `src/pgschemadiff/infrastructure/config/yaml_loader.py` |
| `styles.tcss` | `src/pgschemadiff/presentation/styles.tcss` |
| `profiles.yaml` | `config/profiles.yaml` |

Using `git mv` preserves history:

```bash
git mv __main__.py   src/pgschemadiff/__main__.py
git mv app.py        src/pgschemadiff/presentation/app.py
git mv home.py       src/pgschemadiff/presentation/screens/home.py
git mv profile.py    src/pgschemadiff/domain/models/profile.py
git mv profile_item.py    src/pgschemadiff/presentation/widgets/profile_item.py
git mv profile_detail.py  src/pgschemadiff/presentation/widgets/profile_detail.py
git mv yaml_loader.py     src/pgschemadiff/infrastructure/config/yaml_loader.py
git mv styles.tcss   src/pgschemadiff/presentation/styles.tcss
git mv profiles.yaml config/profiles.yaml
```

---

## 4. Fix CSS_PATH in app.py

After moving `styles.tcss` the path reference in `PgSchemaDiffApp` must update:

```python
# src/pgschemadiff/presentation/app.py
class PgSchemaDiffApp(App):
    CSS_PATH = "styles.tcss"   # Textual resolves this relative to the .py file
```

Textual resolves `CSS_PATH` relative to the Python source file, so no change is
needed as long as `styles.tcss` is in the same directory as `app.py`. ✅

---

## 5. Add re-export `__init__.py` for domain models

`home.py`, `yaml_loader.py`, and `profile_item.py` import `Profile` from
`pgschemadiff.domain.models` (no trailing `.profile`). Add a re-export:

```python
# src/pgschemadiff/domain/models/__init__.py
from pgschemadiff.domain.models.profile import ConnectionInfo, Profile

__all__ = ["ConnectionInfo", "Profile"]
```

---

## 6. Create the missing `confirm_dialog.py`

`home.py` imports `ConfirmDialog` from `pgschemadiff.presentation.widgets.confirm_dialog`
but this file does not exist yet. Extract the inline logic:

```python
# src/pgschemadiff/presentation/widgets/confirm_dialog.py
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmDialog(ModalScreen[bool]):
    """Generic yes/no confirmation dialog."""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }
    ConfirmDialog > Vertical {
        width: 60;
        height: auto;
        border: thick $primary;
        padding: 1 2;
    }
    ConfirmDialog Button {
        margin: 1 1 0 0;
    }
    """

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._title, id="dialog-title")
            yield Label(self._body, id="dialog-body")
            yield Button("Delete", id="btn-confirm", variant="error")
            yield Button("Cancel", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-confirm")
```

---

## 7. Verify imports

All imports in the moved files should already be correct (they were written for the
target structure). Double-check by running mypy:

```bash
uv run mypy src/pgschemadiff
```

---

## 8. Run the app

```bash
uv sync
uv run python -m pgschemadiff
# or with explicit config
uv run python -m pgschemadiff --config config/profiles.yaml
```

---

## 9. Update pyproject.toml entry point (if needed)

`pyproject.toml` already declares the correct entry point and package path:

```toml
[project.scripts]
pgschemadiff = "pgschemadiff.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/pgschemadiff"]
```

No changes required. ✅

---

## Checklist

- [ ] Directory structure created
- [ ] `__init__.py` files added
- [ ] Source files moved with `git mv`
- [ ] `src/pgschemadiff/domain/models/__init__.py` re-exports Profile / ConnectionInfo
- [ ] `confirm_dialog.py` created
- [ ] `uv run mypy src/pgschemadiff` passes
- [ ] App runs: `uv run python -m pgschemadiff`
- [ ] Delete confirmation modal works
- [ ] Root flat files removed (after verifying everything works from `src/`)
