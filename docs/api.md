# API Reference

Complete reference for all public classes and methods in pgschemadiff.

---

## Domain Models — `profile.py`

### `ConnectionInfo`

Immutable (frozen) Pydantic model representing a connection to a single PostgreSQL database.

```python
class ConnectionInfo(BaseModel):
    model_config = {"frozen": True}

    host: str
    port: int = 5432
    database: str
    user: str
    password: str = ""
```

**Methods**

| Method | Return | Description |
|--------|--------|-------------|
| `display() -> str` | `"postgres://user@host:port/db"` | URL without password — safe for display |
| `dsn() -> str` | `"postgresql://user:pass@host:port/db"` | Full DSN for psycopg; omits `:password` if empty |

**Example**

```python
from profile import ConnectionInfo

conn = ConnectionInfo(host="localhost", port=5432, database="app_dev", user="henrik")
conn.display()  # "postgres://henrik@localhost:5432/app_dev"
conn.dsn()      # "postgresql://henrik@localhost:5432/app_dev"
```

---

### `Profile`

Immutable (frozen) Pydantic model representing a source → target comparison pair.

```python
class Profile(BaseModel):
    model_config = {"frozen": True}

    name: str
    source: ConnectionInfo
    target: ConnectionInfo
    schemas: list[str] = ["public"]
    ignore_patterns: list[str] = []
    mode: str = "schema-only"
```

**Fields**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | required | Human-readable label shown in the list |
| `source` | `ConnectionInfo` | required | The "before" database to compare from |
| `target` | `ConnectionInfo` | required | The "after" database to compare against |
| `schemas` | `list[str]` | `["public"]` | Schemas to include in the diff |
| `ignore_patterns` | `list[str]` | `[]` | Object name globs to exclude (e.g. `"temp_*"`) |
| `mode` | `str` | `"schema-only"` | Diff mode; currently only `"schema-only"` is planned |

**Methods**

| Method | Return | Description |
|--------|--------|-------------|
| `summary() -> str` | `"src_host / tgt_host"` | One-line summary for the list view |

**Example**

```python
from profile import Profile, ConnectionInfo

profile = Profile(
    name="dev → staging",
    source=ConnectionInfo(host="localhost", database="app_dev", user="dev"),
    target=ConnectionInfo(host="staging.db.local", database="app", user="app"),
    schemas=["public", "billing"],
    ignore_patterns=["temp_*"],
)
profile.summary()  # "localhost / staging.db.local"
```

---

## Infrastructure — `yaml_loader.py`

### `ProfileLoader`

Reads and writes profiles from/to a YAML file. Located (in target structure) at
`infrastructure/config/yaml_loader.py`.

```python
class ProfileLoader:
    def __init__(self, config_path: Path) -> None: ...
    def load(self) -> list[Profile]: ...
    def save(self, profiles: list[Profile]) -> None: ...
```

**Constructor**

| Parameter | Type | Description |
|-----------|------|-------------|
| `config_path` | `Path` | Absolute or relative path to `profiles.yaml` |

**Methods**

#### `load() -> list[Profile]`

Reads the YAML file and returns all profiles. Returns `[]` if the file doesn't exist
or has no `profiles` key. Validates each entry with `Profile.model_validate()`.

```python
from pathlib import Path
from yaml_loader import ProfileLoader

loader = ProfileLoader(Path("profiles.yaml"))
profiles = loader.load()   # list[Profile], empty list if file missing
```

#### `save(profiles: list[Profile]) -> None`

Serialises the profile list back to YAML. Creates parent directories if needed.
Uses `yaml.safe_dump(..., sort_keys=False, allow_unicode=True)`.

```python
loader.save(profiles)   # overwrites config_path with updated data
```

**YAML format**

```yaml
profiles:
  - name: dev → staging
    source:
      host: localhost
      port: 5432
      database: app_dev
      user: henrik
      password: ""
    target:
      host: staging.db.local
      port: 5432
      database: app
      user: app
      password: ""
    schemas: [public, billing, audit]
    ignore_patterns: ["temp_*", "_migrations"]
    mode: schema-only
```

---

## Presentation — `app.py`

### `PgSchemaDiffApp`

Top-level Textual application. Loads profiles on mount and pushes `HomeScreen`.

```python
class PgSchemaDiffApp(App):
    CSS_PATH = "styles.tcss"
    TITLE = "pgschemadiff"

    def __init__(self, config_path: Path) -> None: ...
    def on_mount(self) -> None: ...
```

| Attribute | Value |
|-----------|-------|
| `CSS_PATH` | `"styles.tcss"` (Catppuccin Mocha theme) |
| `TITLE` | `"pgschemadiff"` |

**Constructor**

| Parameter | Type | Description |
|-----------|------|-------------|
| `config_path` | `Path` | Passed to `ProfileLoader`; resolved by `__main__` |

**Lifecycle**

1. `on_mount` → `ProfileLoader(config_path).load()` → `push_screen(HomeScreen(profiles))`

---

## Presentation — `home.py`

### `HomeScreen`

Main screen: two-pane layout (profile list on the left, detail panel on the right).

```python
class HomeScreen(Screen):
    BINDINGS = [...]

    def __init__(self, profiles: list[Profile]) -> None: ...
```

**BINDINGS**

| Key | Action | Wired |
|-----|--------|-------|
| `n` | `action_new_profile` | ❌ shows notification only |
| `e` | `action_edit_profile` | ❌ shows notification only |
| `d` | `action_delete_profile` | ✅ full modal confirm + list update |
| `enter` | `action_compare` | ⚠️ shows notification only |
| `?` | `action_help` | ✅ shows key-bindings notification |
| `q` | `action_quit` | ✅ built-in |

**Key internal methods**

| Method | Description |
|--------|-------------|
| `_render_detail(profile)` | Updates the right-hand detail pane for the given profile (or clears it if `None`) |
| `_start_compare(profile)` | Stub — shows a `notify()` toast; will push `ComparingScreen` when implemented |
| `action_delete_profile()` | Pushes `ConfirmDialog`, then removes the profile from list and in-memory state on confirm |

**Widget tree (compose)**

```
HomeScreen
└── Header
└── Horizontal#home-container
    ├── Vertical#profile-list-pane
    │   ├── Static#profile-list-title
    │   └── ListView#profile-list
    │       └── ProfileListItem × N
    └── Vertical#detail-pane
        ├── Static#detail-title
        ├── Static#field-source  .field-row
        ├── Static#field-target  .field-row
        ├── Static#field-schemas .field-row
        ├── Static#field-ignore  .field-row
        ├── Static#field-mode    .field-row
        └── Horizontal#detail-actions
            ├── Button#btn-compare  .-primary
            ├── Button#btn-edit
            └── Button#btn-test
└── Footer
```

---

## Presentation — `profile_item.py`

### `ProfileListItem`

A `ListItem` subclass that holds a reference to a `Profile` and renders its name
and summary in two lines.

```python
class ProfileListItem(ListItem):
    def __init__(self, profile: Profile) -> None: ...
    profile: Profile   # attached Profile object, accessible on selection
```

**Rendered output**

```
▸ dev → staging
  localhost / staging.db.local
```

---

## Entry point — `__main__.py`

### `main()`

CLI entry point. Resolves config path (see priority order below), then runs the app.

```
python -m pgschemadiff [--config PATH]
pgschemadiff [--config PATH]              # after `uv sync` / pip install
```

**CLI arguments**

| Argument | Alias | Description |
|----------|-------|-------------|
| `--config PATH` | `-c PATH` | Explicit path to `profiles.yaml` |

**Config path resolution order**

1. `--config` / `-c` CLI argument
2. `$PGSCHEMADIFF_CONFIG` environment variable
3. `./config/profiles.yaml` (local dev directory layout)
4. `$XDG_CONFIG_HOME/pgschemadiff/profiles.yaml`
5. `~/.config/pgschemadiff/profiles.yaml`
