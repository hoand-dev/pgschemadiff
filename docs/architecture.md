# Architecture

## Current state — flat prototype

All source files live at the repository root. This layout was chosen for rapid
prototyping but **cannot be installed or imported as a package** because the Python
imports already reference the target package hierarchy (see [Target structure](#target-structure-srcpgschemadiff) below).

```
pgschemadiff/          ← repo root & Python working directory
├── pyproject.toml
├── profiles.yaml      ← sample config (target: config/profiles.yaml)
├── styles.tcss        ← Catppuccin Mocha theme
│
├── __main__.py        ← CLI entry point
├── app.py             ← PgSchemaDiffApp
├── home.py            ← HomeScreen
├── profile.py         ← Domain: Profile, ConnectionInfo
├── profile_item.py    ← Widget: ProfileListItem
├── profile_detail.py  ← Widget (UNUSED — inlined into HomeScreen)
└── yaml_loader.py     ← Infrastructure: ProfileLoader
```

Missing from the prototype (imported but not yet created):

- `confirm_dialog.py` — `ConfirmDialog` widget; logic is currently inline in `home.py`
  via a nested `on_confirm` callback. The import `from pgschemadiff.presentation.widgets.confirm_dialog import ConfirmDialog` will fail until this file is created in the target structure.

---

## Target structure — `src/pgschemadiff/`

The goal is a clean domain-driven layout with three top-level layers: **domain**,
**infrastructure**, and **presentation**.

```
pgschemadiff/                        ← repo root
├── pyproject.toml
├── profiles.yaml                    ← to be moved to config/profiles.yaml
├── config/
│   └── profiles.yaml                ← sample config (XDG-adjacent dev default)
└── src/
    └── pgschemadiff/
        ├── __init__.py
        ├── __main__.py              ← entry point
        │
        ├── domain/
        │   ├── __init__.py
        │   ├── models/
        │   │   ├── __init__.py      ← re-exports Profile, ConnectionInfo
        │   │   └── profile.py
        │   ├── diff/
        │   │   ├── __init__.py
        │   │   └── comparator.py    ← [TODO] schema diff logic
        │   └── migration/
        │       ├── __init__.py
        │       └── generator.py     ← [TODO] SQL migration generator
        │
        ├── infrastructure/
        │   ├── __init__.py
        │   ├── config/
        │   │   ├── __init__.py
        │   │   └── yaml_loader.py
        │   └── postgres/
        │       ├── __init__.py
        │       └── inspector.py     ← [TODO] pg_catalog queries via psycopg
        │
        └── presentation/
            ├── __init__.py
            ├── app.py
            ├── styles.tcss
            ├── screens/
            │   ├── __init__.py
            │   ├── home.py          ← done
            │   ├── comparing.py     ← [TODO] Worker + ProgressBar
            │   ├── diff_explorer.py ← [TODO] Tree widget, 3-column diff
            │   └── sql_preview.py   ← [TODO] RichLog + SQL syntax highlight
            └── widgets/
                ├── __init__.py
                ├── profile_item.py  ← done
                ├── profile_detail.py← unused; logic inlined in HomeScreen
                └── confirm_dialog.py← [TODO] extract from HomeScreen
```

---

## Layer responsibilities

### Domain

Pure Python — no framework dependencies (no Textual, no psycopg, no YAML).

| Module | Responsibility |
|--------|----------------|
| `domain/models/profile.py` | `Profile` and `ConnectionInfo` Pydantic models |
| `domain/diff/comparator.py` | Compare two sets of schema objects, return a diff result |
| `domain/migration/generator.py` | Turn a diff result into a SQL `ALTER`/`CREATE`/`DROP` script |

### Infrastructure

Adapters to the outside world (disk, network, databases).

| Module | Responsibility |
|--------|----------------|
| `infrastructure/config/yaml_loader.py` | Read/write `profiles.yaml` |
| `infrastructure/postgres/inspector.py` | Connect via psycopg, query `pg_catalog` to extract schema objects |

### Presentation

Textual TUI — no business logic, only UI coordination.

| Module | Responsibility |
|--------|----------------|
| `presentation/app.py` | App root, mounts `HomeScreen` |
| `presentation/screens/home.py` | Profile browser with list + detail pane |
| `presentation/screens/comparing.py` | Progress screen while diff runs in a Worker |
| `presentation/screens/diff_explorer.py` | Browse diff results in a tree |
| `presentation/screens/sql_preview.py` | Show generated SQL before export |
| `presentation/widgets/profile_item.py` | List item widget |
| `presentation/widgets/confirm_dialog.py` | Generic yes/no modal |

---

## Data flow (planned)

```
User picks profile (HomeScreen)
    └─→ push ComparingScreen(profile)
            └─→ Worker: infrastructure.postgres.inspector
                    ├── source_schema = Inspector(source).inspect()
                    └── target_schema = Inspector(target).inspect()
            └─→ domain.diff.comparator.compare(source_schema, target_schema)
                    └─→ DiffResult
            └─→ push DiffExplorerScreen(diff_result)
                    └─→ User selects changes
                    └─→ push SqlPreviewScreen(selected_changes)
                            └─→ domain.migration.generator.generate(selected_changes)
                            └─→ User reviews / exports SQL
```

---

## Key design decisions

**Frozen Pydantic models** — `Profile` and `ConnectionInfo` use `model_config = {"frozen": True}`.
This ensures profiles loaded from YAML are never accidentally mutated at runtime;
deletions go through an explicit list rebuild in `HomeScreen.action_delete_profile`.

**No DB connection in domain** — `ConnectionInfo.dsn()` returns a connection string but
never opens a connection. Connection logic belongs exclusively in
`infrastructure/postgres/inspector.py`.

**Inline compose workaround** — Textual ≥ 0.83 can exhibit layout issues when a custom
widget class overrides `compose()` inside a `Vertical`/`Container`. `ProfileDetail`
was written but is unused; its markup is inlined directly into `HomeScreen.compose()`
as a workaround. Re-test with each Textual upgrade.

**psycopg pool** — `psycopg[binary,pool]` is already declared in `pyproject.toml` to
allow `AsyncConnectionPool` in `inspector.py` without a dependency change later.
