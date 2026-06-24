# UI Design — pgschemadiff TUI

> Source of truth for the Textual TUI implementation (Phase 4, task **P4-UX-01**).
>
> The original mock was produced in claude.ai/design as an HTML/React prototype.
> The full bundle (theme.css, JSX components, mock data, design chat) is preserved
> at [`docs/ui-design/reference/`](ui-design/reference/) — read those for any
> pixel-level detail not captured here. **This document is the implementation
> contract; the bundle is the visual reference.**

---

## 1. Intent (from the design chat)

The user wanted a **vim-style terminal interface** for `pgschemadiff` with
the **Catppuccin Mocha + Latte** themes (dark / light, toggleable), feeling
like Textual / tmux running inside a real terminal. The schema is a realistic
**multi-tenant SaaS workload** (3 schemas — `public`, `billing`, `analytics`).

Key explicit decisions:

- **TUI is the wrapper; CLI is the core.** They share use cases; the TUI never
  embeds business logic.
- **Catppuccin Mocha** is default; **Latte** toggled via `gT` or `:set bg=latte`.
- **7 screens**, all interactive, with vim navigation.
- **Both side-by-side and tree diff** modes.
- **Decide-for-me on remaining decisions** — be creative.

## 2. Layout (overall app chrome)

```
┌─ terminal titlebar ───────────────────────────────────────────────┐
│ ● ● ●        pgschemadiff — zsh — src→tgt — 164×48      tmux 0:* │
├─ header ──────────────────────────────────────────────────────────┤
│ ◈ pgschemadiff v0.0.0   [NORMAL]   src→tgt pills   branch · :cmd  │
├─ body ────────────────────────────────────────────────────────────┤
│ ┌─ sidebar 320c ──┐ ┌─ tabbar ────────────────────────────────── ─┐│
│ │ SCHEMA EXPLORER │ │ Connection · Overview · Diff · Migration   ││
│ │ / filter        │ │ · Apply · History · Settings    (+4 ~6 -2)  ││
│ │ ☑ changes only  │ ├──────────────────────────────────────────── ─┤
│ │ ◈ public        │ │                                              │
│ │   ▾ tables      │ │           VIEW BODY (per tab)                │
│ │     ▦ tenants ~ │ │                                              │
│ │     ▦ users ~   │ │                                              │
│ │     ...         │ │                                              │
│ └─────────────────┘ └──────────────────────────────────────────────┘
├─ statusbar (vim modeline) ────────────────────────────────────────┤
│ NORMAL  pgschemadiff/overview  tenants  ⚠ 1 conflict  25c utf-8…  │
├─ command bar ─────────────────────────────────────────────────────┤
│ : command │ ? help │ gc go gd gm ga gh gs │ j/k / gT ZZ  · hint   │
└───────────────────────────────────────────────────────────────────┘
```

Container hierarchy in Textual:

```
PgsdApp
└── MainScreen
    ├── Header (custom widget)
    ├── Body (Horizontal)
    │   ├── Sidebar (Vertical, ~36 cells wide)
    │   │   ├── SidebarHeader
    │   │   ├── SidebarSearch (Input)
    │   │   ├── SidebarFilters
    │   │   ├── SchemaTree (Tree)
    │   │   └── SidebarLegend
    │   └── Main (Vertical)
    │       ├── ViewTabs (custom — labelled tabs with chord hints)
    │       └── ContentSwitcher
    │           ├── ConnectionView
    │           ├── OverviewView
    │           ├── DiffView
    │           ├── MigrationView
    │           ├── ApplyView
    │           ├── HistoryView
    │           └── SettingsView
    ├── Statusbar (custom widget)
    └── Cmdbar (custom widget; switches between hint mode and input mode)
```

## 3. Colour tokens

Catppuccin Mocha (dark) and Latte (light) are built into Textual as named
themes (`catppuccin-mocha`, `catppuccin-latte`). `App.theme = "..."` plus a
reactive watcher is sufficient. The reference `theme.css` enumerates every
token we will need; the table below maps them to Textual variable names:

| Semantic | Mocha CSS | Latte CSS | Textual variable |
|---|---|---|---|
| base background | `#1e1e2e` | `#eff1f5` | `$background` |
| panel background | `#181825` | `#e6e9ef` | `$surface` |
| crust / deeper bg | `#11111b` | `#dce0e8` | `$panel` |
| primary accent (mauve) | `#cba6f7` | `#8839ef` | `$primary` |
| secondary (lavender) | `#b4befe` | `#7287fd` | `$secondary` |
| add (green) | `#a6e3a1` | `#40a02b` | `$success` |
| modify (yellow) | `#f9e2af` | `#df8e1d` | `$warning` |
| delete (red) | `#f38ba8` | `#d20f39` | `$error` |
| conflict (peach) | `#fab387` | `#fe640b` | _custom_ `$accent-conflict` |
| source pill (blue) | `#89b4fa` | `#1e66f5` | `$info` |
| target pill (peach) | `#fab387` | `#fe640b` | _custom_ `$accent-target` |
| muted text | `#a6adc8` | `#6c6f85` | `$text-muted` |

Diff-line accents (`--diff-add-bg`, `--diff-mod-bg`, `--diff-del-bg`) become
Textual CSS classes `.diff-add`, `.diff-mod`, `.diff-del` with appropriate
text & background.

## 4. Vim-style key bindings

| Key chord | Action |
|---|---|
| `g c` | switch to **Connection** view |
| `g o` | switch to **Overview** view |
| `g d` | switch to **Diff** view |
| `g m` | switch to **Migration** view |
| `g a` | switch to **Apply** view |
| `g h` | switch to **History** view |
| `g s` | switch to **Settings** view |
| `g T` | cycle theme (mocha ↔ latte) |
| `:` | enter command palette (focus cmdbar input) |
| `?` | open Help modal |
| `Escape` | leave command mode / dismiss modal / reset chord state |
| `Z Z` | quit |
| `j` / `k` | next / previous item in lists & trees |
| `/` | focus sidebar search |
| `Ctrl+b` | toggle sidebar visibility |
| `space a` | accept change (Diff view) |
| `space s` | skip change (Diff view) |
| `space i` | invoke AI suggestion (Diff / Overview) |

Implementation pattern (Textual lacks first-class vim chords): use a reactive
`_chord` attribute on `PgsdApp`. The `on_key` handler watches for the prefix
(`g`, `Z`, `space`); on the next key it resolves the chord and resets the
flag. Cancel on any other key or after a configurable timeout (~750 ms).

## 5. Command palette (`:` mode)

When the user presses `:`, the cmdbar transforms into an `Input`. Submitted
text is parsed by the same dispatcher the CLI uses — keep one parser, two
front-ends.

Supported initial commands (extend over time):

| Command | Action |
|---|---|
| `:diff [name]` | open Diff view; optional `name` selects an object |
| `:overview` / `:o` | open Overview |
| `:migration` / `:m` | open Migration |
| `:apply [--dry-run]` | open Apply view (and start dry-run worker) |
| `:rollback <run-id>` | open History view with the run preselected |
| `:set bg=mocha\|latte` | switch theme |
| `:set theme=mocha\|latte` | alias of `:set bg=...` |
| `:conn switch <profile>` | swap source/target profile |
| `:help` / `:?` | open Help modal |
| `:q` / `:quit` / `ZZ` | exit |

Unknown commands surface `E492: not an editor command: <cmd>` in the cmdbar
hint area (matches vim convention; matches the prototype).

## 6. Screens

Each section below names the screen, the key it binds to, and the *minimum
viable content* for the first implementation. The reference JSX shows much
richer content — we will add it incrementally as Phase 1-3 data lands.

### 6.1 Connection (`gc`)

- Two side-by-side **connection cards** (source / target) showing label,
  URL host, database, role, SSL mode, latency, table count, size.
- "Compare options" panel: 9 grid fields (include schemas, exclude tables,
  include data, owner roles, storage params, extensions, generated cols,
  comments, case sensitivity).
- Action buttons: `test both` (^t), `save profile` (^s).

### 6.2 Overview (`go`)

- **Stat grid**: 4 cards (added / modified / dropped / conflicts) with big
  numeric value and delta text.
- **Filterable change table**: columns `op`, `schema`, `object`, `risk`, `lock`,
  `est. time`. Rows clickable → jumps to Diff view for that object.
- **AI review panel**: card listing AI suggestions (phased migration,
  archive-before-drop, conflict resolution) — opens AI modal on click.
- **SVG dependency graph**: node-graph rendering (topologically laid out in
  columns/rows, op-coloured cards + curved edges with arrowheads) of FK /
  function call relationships among changed objects. *(Was an ASCII box-drawing
  block in the original mock; the design now uses an SVG node graph.)*

### 6.3 Diff (`gd`)

- **Object header**: type tag, qualified name, breadcrumb, action buttons
  (`accept`, `skip`, `ai`).
- **View mode toggle**: `side-by-side` · `inline` · `tree` (three equal-width
  pills — the design chat called out that they must have the same width).
- **Diff body**:
  - *side-by-side*: two synced panels with the SQL of source and target;
    each line tagged add/del/mod/hunk.
  - *inline*: classic unified diff.
  - *tree*: collapsible AST diff (per-field changes inside columns).
- **Auto-generated rollback** snippet below the diff.
- **Jump chips**: prev/next object navigation.

### 6.4 Migration (`gm`)

- **Generated SQL** pane (syntax-highlighted) with the topo-sorted DDL.
- **Execution plan table**: ordered statements with statement kind, estimated
  duration, lock mode.
- **Lock estimate table**: AccessShareLock / RowExclusiveLock / AccessExclusiveLock
  counts per object.
- **Tabs** for forward (`up.sql`) vs. rollback (`down.sql`).
- Action: `apply` (ga) primary button → Apply view.

### 6.5 Apply (`ga`)

- **Pre-flight checklist**: connection ping, lock budget, replica lag, free
  space, advisory locks.
- **Step-by-step progress** with animated indicators (running / done / failed).
- **Live log stream** (`tail -f`-style) — append-only `Log` widget.
- Stop / pause / continue actions.
- Final summary on completion: success / rollback offered.

### 6.6 History (`gh`)

- Reverse-chronological list of past runs with status chips: applied,
  rolled-back, failed, dry, pending.
- Selecting a row reveals a **timeline** with statements applied, durations,
  errors.
- Action: `rollback <run-id>`.

### 6.7 Settings (`gs`)

- **Appearance** group: theme, font scale.
- **Keymap** group: vim leader, custom chords.
- **Diff & migration** group: default mode, lock-timeout, max-risk gate.
- **AI / telemetry** group: enable/disable, redaction rules.
- **Live `config.toml` preview** panel that re-renders as settings change.

## 7. Modals

- **HelpModal** (`?`): 4 grouped tables — Navigation, Views, Actions,
  Commands. Closes on `Escape` or clicking `[esc]`.
- **AIModal**: opens from Overview / Diff / Migration "ai" actions, shows
  the suggestion title, body, and confirmation buttons (`accept`, `dismiss`).
- **ConfirmApplyModal**: shown before destructive runs; lists the deltas with
  `DESTRUCTIVE` or `BLOCKED` risk and requires explicit `--max-risk` consent.

## 8. Mock data while backend lags

Until Phase 1-3 land, the views are wired to a single
`presentation/tui/_mock.py` module that exposes the same shape the future
application use cases will return (`Database`, `DeltaSet`, `Migration`,
`HistoryEntry`). The mock data is a subset of the design's
`reference/data.js`. Replacing the mock with real calls is a single import
swap per view. **Do not** add mock data anywhere outside `_mock.py`.

## 9. CLI ↔ TUI integration

- `pgsd` (no args) launches the TUI.
- `pgsd tui` is an explicit alias.
- Every CLI sub-command (`inspect`, `diff`, `generate`, `apply`) has a
  corresponding TUI screen; the command palette wraps the same parser the
  CLI uses (single source of truth, lives in `application/`).

## 10. Implementation tasks (Phase 4)

| Status | Task ID | Title |
|---|---|---|
| [x] | P4-UX-01 | Import this document & reference bundle |
| [x] | P4-TUI-01 | App shell — chrome, theme switching, vim chord dispatcher, command palette, help modal |
| [x] | P4-TUI-02 | ConnectionView — source/target cards, compare options, saved profiles |
| [x] | P4-TUI-03 | OverviewView — stat grid, clickable change table, AI review, dep graph |
| [x] | P4-TUI-04 | DiffView with all 3 modes (side / inline / tree) + jump chips + rollback |
| [x] | P4-TUI-05 | MigrationView — forward/rollback script, exec plan, lock estimates |
| [x] | P4-TUI-06 | ApplyView with progress worker + live log stream |
| [x] | P4-TUI-07 | HistoryView — run list + detail + timeline |
| [x] | P4-TUI-08 | SettingsView with live config.toml preview |

All seven views are implemented against `presentation/tui/_mock.py` (§8).
They render the full design and are fully interactive (clickable change rows,
diff jump chips, mode toggles, the apply worker, etc.) but are **not yet wired
to real `application/` use cases** — that swap lands incrementally as Phase 1-3
data arrives. The mock import in each view is the single seam to replace.

## 11. Pitfalls / decisions worth knowing

- **Textual's `Tabs` widget** doesn't render the keybinding hint chips
  (`gc`, `go`, …) natively. Use a custom widget composed of `Label`s plus the
  built-in `ContentSwitcher`.
- **Chord bindings**: implement manually on `on_key`. Textual's
  `Binding(key="g,c", ...)` is for *simultaneous* presses, not sequential.
- **Theme reactivity**: setting `App.theme = "catppuccin-latte"` triggers a
  full repaint automatically — no manual refresh needed.
- **Sidebar scrolling** must use `Tree.cursor_line` for vim `j/k` to feel
  right; the default arrow-key scroll is fine but doesn't honour our chord
  state.
- **Snapshot tests**: `pytest-textual-snapshot` is the standard. We'll add it
  in Phase 4 (not Phase 0 baseline) to keep MVP-A dependencies lean.
- The mock terminal "chrome" (traffic lights + tmux indicator) shown in the
  prototype is **just decoration** — the user is already inside a real
  terminal when they run `pgsd`, so we do not render it. We keep the spirit
  (titlebar text) but drop the dots.
