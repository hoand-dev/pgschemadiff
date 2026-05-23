# pgschemadiff — Home screen prototype

Prototype màn hình Home cho công cụ PostgreSQL schema diff & migration. Đây là bước đầu trong roadmap kiến trúc — chỉ có Home screen, các màn hình khác (Comparing / Diff explorer / SQL preview) chưa được implement.

## Cấu trúc

```
pgschemadiff/
├── pyproject.toml                       uv project, target Python 3.13
├── config/
│   └── profiles.yaml                    4 profile mẫu để demo
└── src/pgschemadiff/
    ├── __main__.py                      entry: python -m pgschemadiff
    ├── domain/models/
    │   └── profile.py                   Profile, ConnectionInfo (Pydantic frozen)
    ├── infrastructure/config/
    │   └── yaml_loader.py               load/save YAML
    └── presentation/
        ├── app.py                       Textual App
        ├── styles.tcss                  Catppuccin Mocha theme
        ├── screens/
        │   └── home.py                  HomeScreen — màn hình chính
        └── widgets/
            ├── profile_item.py          ListItem 2 dòng cho ListView
            ├── profile_detail.py        (unused — đã inline vào HomeScreen)
            └── confirm_dialog.py        Modal confirm dialog
```

## Chạy thử

Trên Ubuntu 26.04 với Python 3.13:

```bash
# Cài uv nếu chưa có
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync deps + chạy
cd pgschemadiff_proto
uv sync
uv run python -m pgschemadiff
```

Hoặc dùng pip:

```bash
pip install textual pydantic pyyaml
PYTHONPATH=src python -m pgschemadiff
```

## Key bindings

| Phím | Hành động |
|---|---|
| `↑ ↓` | Navigate profile list (detail panel update real-time) |
| `enter` | Compare (hiện tại chỉ show notification) |
| `n` | New profile (chưa wired) |
| `e` | Edit profile (chưa wired) |
| `d` | Delete profile (mở modal confirm — đã wired) |
| `?` | Help notification |
| `q` | Quit |

## Những gì đã hoạt động (verified bằng Textual Pilot)

- App khởi động, load 4 profile từ YAML
- Navigate ↑↓ trong list, detail panel update real-time
- Bấm `d` mở modal `ConfirmDialog`, bấm `Delete` thật sự xóa khỏi list
- Bấm `esc` hoặc `Cancel` đóng modal về lại home
- Footer hiển thị key bindings tự động từ `BINDINGS`

## Bước tiếp theo trong roadmap

1. `screens/comparing.py` — màn hình loading với Worker async + ProgressBar
2. `screens/diff_explorer.py` — Tree widget cho diff, 3 cột
3. `screens/sql_preview.py` — RichLog với syntax highlight SQL
4. `infrastructure/postgres/inspector.py` — query pg_catalog thật
5. `domain/diff/comparator.py` — diff logic
6. `domain/migration/generator.py` — sinh SQL migration

## Lưu ý kỹ thuật

- Textual 8.2.7 có bug khi extend `Vertical`/`Container` với compose phức tạp — workaround là inline compose vào Screen thay vì tạo widget class riêng. Ghi nhớ điều này khi build các màn hình sau.
- `psycopg[binary,pool]` đã được liệt kê trong `pyproject.toml` nhưng chưa dùng vì màn hình này chưa kết nối DB. Sẽ active khi implement `screens/comparing.py`.
