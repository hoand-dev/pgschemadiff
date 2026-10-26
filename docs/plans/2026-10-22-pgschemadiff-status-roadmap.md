# Phân tích trạng thái và roadmap triển khai pgschemadiff

> Đánh giá ngày 2026-10-22 từ source/docs trong checkout local và trạng thái GitHub đọc được. Phân biệt rõ local checkout với remote branch vì local đang trễ một commit. Estimate giả định một backend engineer, QA/reviewer part-time, 4–6 giờ tập trung/ngày; chưa tính thời gian chờ human gate hoặc review ngoài nhóm.

## 1. Tóm tắt điều hành

Dự án đã có nền tảng domain, PostgreSQL introspection, typed deltas, topo-sort và diff dispatcher. Remote branch đã thêm table/index/constraint comparators; bước kế tiếp là ColumnComparator và hoàn thiện M2. Migration generator/applier chưa được triển khai; TUI đã có đủ view mock nhưng chưa nối use case thật.

| Hạng mục | Trạng thái xác minh |
|---|---|
| Local checkout | `claude/progress-check-kspf8m`, HEAD `73412b2` |
| Remote branch | HEAD `30fc278`, commit ngày 2026-06-30; local checkout thiếu commit này. Remote-tracking refs trong local có vẻ stale. |
| Remote branch so với main | Ahead 5, behind 0; main tại `0c745e1`. Chưa có PR mở cho branch; chưa merge vào main. |
| CI gần nhất | Run `28414147822` trên `30fc278`, success. Commit ghi nhận 1.121 unit tests và Ruff, format, mypy strict, import-linter xanh. Không thấy run mới hơn. |
| Local verification | Không tái chạy được: `.venv` thiếu pytest/ruff; `uv run` gặp Access Denied khi thao tác `.venv\.gitignore`. Đây là vấn đề môi trường local, không phải bằng chứng code fail. |
| Working tree | Có untracked `docs/ui-design/pgschemadiff.zip`; giữ nguyên đến khi maintainer quyết định track hay ignore. |

### Hoàn thành

- Clean Architecture: `domain`, `application`, `infrastructure`, `presentation`; import-linter enforce boundaries.
- Domain MVP-A: database, schema, table, column, index, constraint, extension; Pydantic frozen models.
- PostgreSQL pool, `pg_catalog` inspector, type normalizer và `pgsd inspect`.
- Delta foundation, lossless `Delta` union, `DeltaSet`, deterministic `DiffEngine` dispatcher.
- Kahn topological sort với cycle detection và độ phức tạp O(n+m).
- Theo remote commit `30fc278`: TableComparator, IndexComparator, ConstraintComparator; 131 test mới; tổng 1.121 unit tests.
- TUI shell và 7 view tương tác với mock data.

### Đang làm / kế tiếp

- Phase 2 / M2 Diff Engine chưa hoàn tất.
- Remote đã hoàn thành P2-DIFF-02/04/05. **P2-DIFF-03 ColumnComparator** là bước kế tiếp.
- Chưa có use case `compare_schemas` hoặc lệnh `pgsd diff`.
- TUI hiện vẫn dùng `presentation/tui/_mock.py`.

### Còn thiếu

- ColumnComparator; schema/extension comparators chưa có task implementation rõ ràng.
- Rename annotations, ignore rules, edge/property tests và diff CLI.
- Risk classifier, SQL emitters, transaction splitter, multi-file migration writer, applier, `generate`/`apply` CLI, round-trip integration test.
- Nối TUI vào application use cases.
- MVP-B: views, materialized views, functions, procedures, sequences, enums, triggers, RLS policies, composite/domain types.
- Coverage gate, benchmark gates và release workflow.

## 2. Phân tích rủi ro và dependency

### Blocker/rủi ro ưu tiên cao

1. **Checkout local trễ remote một commit.** Local ở `73412b2`; GitHub branch ở `30fc278`. Nếu làm tiếp trên local mà chưa đồng bộ, có thể làm lại P2-DIFF-02/04/05 hoặc tạo conflict.
2. **Execution state không đồng nhất.** `TASK_INDEX.md` còn trạng thái cũ; `AI_STATE.md` còn xếp P2-DIFF-02/04/05 vào queue. `PROJECT_CONTEXT.md`, `ROADMAP.md` và README còn ghi Phase 0/branch cũ. Remote commit mới nhất đã cập nhật `docs/TASKS.md`, nhưng checkout local chưa có commit đó.
3. **Integration CI có thể xanh giả.** `.github/workflows/ci.yml` có fallback `|| (... && exit 0)` trong integration job. Test hỏng có thể bị nuốt. CI còn provision PostgreSQL service trong khi `tests/integration/conftest.py` tự chạy Testcontainers; `PGSD_TEST_DSN` trong workflow không được fixture dùng. Chọn một DB strategy và để test failure fail-closed.
4. **M1 chưa đủ bằng chứng.** `pgsd inspect` đã có, nhưng inspector integration tests (`P1-TEST-02`) chưa hoàn tất; PR #3 đã bị human đóng và project state ghi rõ không tự tạo lại. Benchmark 1.000 objects dưới 2 giây cũng chưa xác nhận. Điều này không bắt buộc chặn phát triển M2, nhưng chặn tuyên bố M1/release-ready.
5. **Thiếu comparator schema/extension.** Engine fetch `SCHEMA`/`EXTENSION`, domain đã có delta tương ứng, nhưng task list không có comparator tasks. M2 có thể trả kết quả không đầy đủ nếu không bổ sung.
6. **Coverage field chưa rõ.** Column model/introspection có identity, generated expression và collation; delta hiện được định nghĩa cho add/drop/type/default/nullability/rename. Schema chỉ có create/drop; extension có version/schema và comment. Cần kiểm kê field-by-field, bổ sung delta/emitter hoặc ghi rõ giới hạn MVP-A; không được im lặng bỏ qua thay đổi.
7. **Kind chưa hỗ trợ trả diff rỗng.** `_fetch_objects_for_kind` trả `{}` cho kind chưa introspect. Đây là tradeoff incremental có chủ ý nhưng có nguy cơ biến “không hỗ trợ” thành “không thay đổi”. Trước khi mở rộng object kinds, cần capability check hoặc diagnostic rõ.

### Rủi ro kiến trúc và vận hành

- `MigrationWriter` hiện thuộc `application/migration/ports.py`, ghi `MigrationPlan` bundle atomically và không overwrite; contract khớp ADR-0008 trước khi viết filesystem adapter.
- ADR-0009 yêu cầu risk theo delta và default chặn `DESTRUCTIVE`/`BLOCKED`; cần quyết định risk nằm trong Delta hay assessment/manifest trước khi thiết kế JSON/CLI.
- Prototype modules còn nằm cạnh TUI hiện tại; Ruff/mypy loại một số module cũ, pytest bỏ `tests/test_screens.py`. Chọn canonical code/test path; không xóa file khi chưa xác nhận còn được dùng.
- Hướng dẫn package cũ đã obsolete; `docs/architecture.md` mô tả cấu trúc hiện tại.
- Coverage được upload nhưng chưa enforce threshold. Inspector đang dùng một connection REPEATABLE READ; giữ cách này đến khi benchmark chứng minh cần multi-connection snapshot theo ADR-0012.
- Remote branch chưa có PR mở và còn 5 commits so với main. Merge là human gate theo `ORCHESTRATOR.md`; không auto-merge.

### Điểm mạnh cần giữ

Frozen domain models, phân tầng rõ, import-linter, mypy strict, lossless delta union, deterministic diff và topo-sort O(n+m). Không cần đại tu kiến trúc; ưu tiên hoàn thiện contracts và use cases.

## 3. Quy ước checklist và estimate

- `[ ]` Chưa làm · `[/]` Đang làm · `[x]` Hoàn thành.
- Cx theo quy ước `docs/TASKS.md`: S <2 giờ; M khoảng nửa ngày; L 1–2 ngày; XL từ 3 ngày.
- P0 = blocker/critical; P1 = ưu tiên cao; P2 = sau core; P3 = nice-to-have.
- P2-DIFF-02/04/05 được đánh dấu hoàn thành theo remote commit/CI, dù local checkout chưa chứa commit đó.
- ID có ghi “task mới đề xuất” chưa tồn tại trong task registry hiện tại.

## 4. Kế hoạch triển khai theo giai đoạn

### Giai đoạn 0 — Đồng bộ trạng thái và QA gate

**Mục tiêu:** mọi người làm trên cùng revision; task board khớp source; CI không che lỗi.

1. [ ] **OPS-01 — Đồng bộ checkout với remote** — P0 · S · 0,5–1 giờ
   - **Mục đích / I-O:** local `73412b2` + remote `30fc278` → local branch khớp remote.
   - **Files/tác động:** Git refs và working tree; không sửa source, không clean/reset; bảo toàn `docs/ui-design/pgschemadiff.zip`.
   - **Hoàn thành khi:** HEAD khớp remote và trạng thái ZIP được xác nhận rõ.

2. [ ] **OPS-02 — Đồng bộ state/docs** — P1 · S · 2–4 giờ
   - **Mục đích / I-O:** đối chiếu GitHub branch, CI và code → queue thể hiện P2-DIFF-03 là task tiếp theo.
   - **Files:** `AI_STATE.md`, `TASK_INDEX.md`, `docs/TASKS.md`, `docs/PROJECT_CONTEXT.md`, `docs/ROADMAP.md`, README.
   - **Tác động:** giảm dispatch nhầm task đã hoàn tất.
   - **Hoàn thành khi:** branch/HEAD, test count, next task và M1/M2/M3 gates nhất quán giữa các tài liệu.

3. [ ] **QA-01 — Làm integration CI fail-closed, chọn một DB strategy** — P0 · M · 0,5–1 ngày
   - **Mục đích / I-O:** workflow hiện tại + fixture → một cấu hình PostgreSQL có lỗi test thì CI đỏ.
   - **Files:** `.github/workflows/ci.yml`, `tests/integration/conftest.py`, `tests/integration/test_connection.py`.
   - **Hoàn thành khi:** cố ý gây lỗi integration làm job fail; test PG18 thật pass; không còn fallback nuốt lỗi.

4. [ ] **P1-TEST-02 — Inspector integration tests** — P0 cho M1 · L · 1–2 ngày · **cần maintainer quyết định**
   - **Mục đích / I-O:** PostgreSQL 18 có schema mẫu → snapshot `Database` được kiểm chứng với catalog thật.
   - **Files:** `tests/integration/` và fixture/seed helpers; đối chiếu `infrastructure/postgres/inspector.py`, `catalog/*.sql`.
   - **Hoàn thành khi:** test schemas, table/column order, defaults, indexes, constraints/FK, extensions, filters và connection failure.
   - **Lưu ý:** PR #3 đã bị đóng; không mở lại/tạo lại nếu chưa có chỉ đạo.

5. [ ] **P1-BENCH-01 — Benchmark inspect 1.000 objects** — P1 · M · 0,5–1 ngày
   - **Mục đích / I-O:** PostgreSQL fixture có số object cố định → benchmark có thể lặp lại.
   - **Files:** benchmark tests/config, có thể `tests/` và workflow.
   - **Hoàn thành khi:** đạt dưới 2 giây theo `docs/ROADMAP.md`; ghi lại môi trường đo.

### Giai đoạn 1 — Hoàn tất Diff Engine (M2)

**Mục tiêu:** `pgsd diff` phát typed delta đầy đủ MVP-A, deterministic và có thứ tự dependency.

1. [ ] **P2-DIFF-03 — ColumnComparator** — P0 · L · 1–2 ngày · phụ thuộc P2-DIFF-02
   - **Mục đích / I-O:** hai `Table.columns` + domain deltas → add/drop/type/default/nullability/rename deltas.
   - **Files:** `src/pgschemadiff/application/diff/comparators/column.py`, `tests/unit/application/diff/comparators/test_column.py`, tích hợp `comparators/table.py`.
   - **Tác động:** thay delegate giả lập của TableComparator bằng comparison thật.
   - **Hoàn thành khi:** cover add/drop, type, default `None`/value, nullability, rename mapping, stable order và không mutate input.

2. [ ] **P2-DIFF-09 — SchemaComparator** *(task mới đề xuất)* — P0 · M · 0,5–1 ngày · phụ thuộc P2-DIFF-01
   - **Mục đích / I-O:** hai schema snapshots → create/drop deltas; xác định rõ xử lý owner/comment.
   - **Files:** `comparators/schema.py`, tests; nếu hỗ trợ alter thì `domain/delta/schema.py` và tests.
   - **Tác động:** tránh engine fetch schema nhưng không có comparison semantics.
   - **Hoàn thành khi:** test schema chỉ có một phía, schema rỗng/có objects, owner/comment và child objects không emit trùng.

3. [ ] **P2-DIFF-10 — ExtensionComparator** *(task mới đề xuất)* — P0 · M · 0,5–1 ngày · phụ thuộc P2-DIFF-01
   - **Mục đích / I-O:** hai extension snapshots → create/drop/alter version/schema deltas.
   - **Files:** `comparators/extension.py`, tests; cập nhật delta nếu comment thuộc scope.
   - **Hoàn thành khi:** test version/schema thay đổi; comment được hỗ trợ hoặc đánh dấu deferred.

4. [ ] **P2-DIFF-11 — Kiểm kê độ phủ field MVP-A** *(task mới đề xuất)* — P0 · S/M · 2–4 giờ đến 1 ngày
   - **Mục đích / I-O:** fields của Column/Table/Schema/Index/Constraint/Extension → bảng coverage và danh sách gaps.
   - **Files:** domain delta/comparator tests; cập nhật task/docs để chốt supported scope.
   - **Hoàn thành khi:** mọi field được inspect có test; field chưa hỗ trợ không bị coi như “không đổi”.

5. [ ] **P2-DIFF-06 — Rename annotation loader** — P1 · M · khoảng 0,5 ngày · phụ thuộc table + column comparators
   - **Mục đích / I-O:** YAML/TOML mappings → rename map đã validate, tiêu dùng bởi comparators.
   - **Files:** `application/diff/renames.py`, `tests/unit/application/diff/test_renames.py`, điểm integration.
   - **Hoàn thành khi:** cover table/column rename, duplicate/invalid/missing mapping; cập nhật dependency để gồm P2-DIFF-02 và P2-DIFF-03.
   - **Lưu ý:** giữ ADR-0007; không dùng rename heuristic.

6. [ ] **P2-DIFF-07 — Ignore rules** — P1 · M · khoảng 0,5 ngày · phụ thuộc P2-DIFF-01
   - **Mục đích / I-O:** DeltaSet + ignore config → DeltaSet đã lọc.
   - **Files:** `application/diff/ignore.py`, unit tests và use-case wiring.
   - **Hoàn thành khi:** test rule match/non-match, không mutate snapshot, thứ tự output ổn định.

7. [ ] **P2-TEST-01 — Comparator edge tests** — P0 · L · 1–2 ngày · phụ thuộc tất cả comparators
   - **Mục đích / I-O:** corpus MVP-A → regression suite độc lập với test từng task.
   - **Files:** `tests/unit/application/diff/comparators/test_comparators_edge.py`.
   - **Hoàn thành khi:** cover constraint drop+add, nested objects, schema/extension, empty objects, deterministic ordering và không duplicate delta.

8. [ ] **P2-TEST-02 — Hypothesis property tests** — P0 · L · 1–2 ngày · phụ thuộc comparators + topo-sort
   - **Mục đích / I-O:** generated source/target snapshots → kiểm chứng invariants.
   - **Files:** `tests/unit/application/diff/test_diff_properties.py`.
   - **Hoàn thành khi:** `diff(S, S)` rỗng; đảo thứ tự input không đổi output; serialization giữ subtype; `max_examples=500` theo roadmap.

9. [ ] **P2-CLI-01 — `compare_schemas` + `pgsd diff`** — P1 · S/M · 2–4 giờ đến 1 ngày · phụ thuộc comparator, rename/ignore và topo-sort
   - **Mục đích / I-O:** source/target DB + options → ordered `DeltaSet` JSON.
   - **Files:** `application/diff/compare_schemas.py`, `presentation/cli/commands/diff.py`, `presentation/cli/main.py`, CLI tests.
   - **Tác động:** kết nối inspector, registry, filters và topo-sort thành tính năng CLI.
   - **Hoàn thành khi:** JSON parse được/stable; schema filters; connection errors có exit code đúng; log không lộ credentials.
   - **Lưu ý:** README nhắc target snapshot file nhưng task mô tả hai URL; quyết định rõ có thuộc M2 không.

**M2 hoàn tất khi:** mọi kind được cam kết cho MVP-A có comparator; CLI phát typed JSON; property tests pass; dependency ordering được kiểm chứng. Topo-sort đã có nhưng chưa được nối vào use case/CLI.

### Giai đoạn 2 — Migration generator và apply (M3)

**Mục tiêu:** generate migration có risk classification, transaction units và round-trip integration trên PG18.

1. [ ] **P3-RISK-01 — Risk classifier** — P0 · M · khoảng 0,5 ngày
   - **Input → Output:** delta/ngữ cảnh → SAFE/WARNING/DANGEROUS/DESTRUCTIVE/BLOCKED cùng lý do.
   - **Files/tác động:** `application/sql_emit/risk.py`, unit tests; chốt risk nằm trong Delta hay assessment/manifest.
   - **Hoàn thành khi:** canonical corpus theo ADR-0009 pass; mặc định chặn destructive/blocked.

2. [ ] **P3-SQL-01 — Emitter dispatcher** — P0 · M · khoảng 0,5 ngày
   - **Input → Output:** ordered deltas → statements và transaction metadata.
   - **Files:** `application/sql_emit/emitter.py`, tests.
   - **Hoàn thành khi:** mọi delta được hỗ trợ dispatch; unsupported delta báo lỗi rõ, không im lặng bỏ qua.

3. [ ] **P3-SQL-02 — Table emitter** — P0 · L · 1–2 ngày
   - **Input → Output:** table create/drop/attributes → PostgreSQL DDL.
   - **Files:** `application/sql_emit/table_emitter.py`, snapshot tests.
   - **Hoàn thành khi:** cover partition/owner/tablespace/comment theo scope; identifiers quote đúng; child DDL không emit trùng.

4. [ ] **P3-SQL-03 — Column emitter** — P0 · L · 1–2 ngày
   - **Input → Output:** column add/drop/type/default/nullability/rename → `ALTER TABLE` SQL.
   - **Files:** `application/sql_emit/column_emitter.py`, snapshot tests.
   - **Hoàn thành khi:** default/nullability transitions đúng; destructive drop có risk gate; metadata đúng theo scope đã chốt.

5. [ ] **P3-SQL-04 — Index emitter** — P0 · M · khoảng 0,5 ngày
   - **Input → Output:** create/drop/replace index → SQL và non-transactional metadata.
   - **Files:** `application/sql_emit/index_emitter.py`, tests.
   - **Hoàn thành khi:** `CONCURRENTLY` không chạy trong transaction; cover method/include/predicate/unique.

6. [ ] **P3-SQL-05 — Constraint emitter** — P0 · M · khoảng 0,5 ngày
   - **Input → Output:** add/drop constraint → DDL và transaction units.
   - **Files:** `application/sql_emit/constraint_emitter.py`, tests.
   - **Hoàn thành khi:** PK/unique/check/FK/exclusion được cover; NOT VALID/VALIDATE theo scope đã duyệt.

7. [ ] **P3-TX-01 — Transaction unit splitter** — P0 · M · khoảng 0,5 ngày · phụ thuộc risk/index emitter
   - **Input → Output:** SQL statements + metadata → ordered transactional/non-transactional units.
   - **Files:** `application/sql_emit/`, tests.
   - **Hoàn thành khi:** statements không tương thích transaction được tách đúng; thứ tự dependency giữ nguyên.

8. [ ] **P3-OUT-01 — Multi-file migration writer** — P0 · M/L · 1–2 ngày
   - **Input → Output:** migration plan → `up.sql`, `down.sql`, `manifest.json`, `deltas.json`, `README.md`.
   - **Files:** điều chỉnh `domain/ports.py`, writer trong `infrastructure/fs/`, tests.
   - **Tác động:** đáp ứng ADR-0008 và sửa port hiện chỉ nhận một SQL string.
   - **Hoàn thành khi:** manifest/version/transaction units khớp SQL; lỗi ghi không để bundle dở dang; rollback nêu rõ phần irreversible.

9. [ ] **P3-APPLY-01 — PostgreSQL applier** — P0 · M · khoảng 0,5 ngày
   - **Input → Output:** bundle + DB → mỗi transaction unit được apply hoặc trả lỗi/trạng thái.
   - **Files:** `infrastructure/postgres/applier.py`, unit/integration tests.
   - **Hoàn thành khi:** transactional unit rollback khi lỗi; non-tx unit chạy riêng; lock timeout; manifest validation; partial apply/resume được quyết định rõ.

10. [ ] **P3-CLI-01 — `pgsd generate` và `pgsd apply`** — P0 · M · 0,5–1 ngày
    - **Input → Output:** URLs/options/output path → bundle hoặc apply result.
    - **Files:** CLI command modules, `presentation/cli/main.py`, tests.
    - **Hoàn thành khi:** max-risk gate, exit codes, path errors, destructive confirmation đúng; log không lộ credentials.

11. [ ] **P3-TEST-02 — Emitter snapshot tests** — P0 · M · khoảng 0,5 ngày
    - **Input → Output:** canonical deltas → SQL snapshots.
    - **Files:** `tests/unit/application/sql_emit/`.
    - **Hoàn thành khi:** quote, DDL order, transaction semantics và rollback annotations được cố định bằng test.

12. [ ] **P3-TEST-01 — Core round-trip integration** — P0 · L · 1–2 ngày · phụ thuộc applier
    - **Input → Output:** source/target schema → diff, emit, apply, inspect; kết quả bằng target.
    - **Files:** `tests/integration/`, PG18 fixtures.
    - **Hoàn thành khi:** `apply(emit(diff(∅, S))) → inspect() == S`, gồm non-transactional DDL và failure paths.

**M3 hoàn tất khi:** risk corpus, emitter snapshots, multi-file validation, CLI generate/apply và PG18 round-trip đều pass.

### Giai đoạn 3 — Nối TUI với use case thật

**Mục tiêu:** giữ UI hiện có; thay mock bằng application flows. Mọi business logic đi qua `application/`.

| Checklist / task | Estimate, dependency | Input → Output; files, tác động và kiểm tra hoàn thành |
|---|---|---|
| [ ] **P4-TUI-02 ConnectionView** | M · 0,5 ngày; inspector | Profiles/connection → source/target snapshots; `views/connection.py`; kiểm tra lỗi kết nối, cancel, không lộ secret. |
| [ ] **P4-TUI-03 OverviewView** | M · 0,5 ngày; M2 | Snapshots → diff summary; `views/overview.py`; số lượng khớp CLI. |
| [ ] **P4-TUI-04 DiffView** | L · 1–2 ngày; M2 | DeltaSet → side/inline/tree modes; `views/diff.py`; selection/filter đúng object, đổi mode không mất state. |
| [ ] **P4-TUI-05 MigrationView** | M · 0,5 ngày; M3 | Delta selection → migration preview; `views/migration.py`; SQL/risk lấy từ use case. |
| [ ] **P4-TUI-06 ApplyView** | L · 1–2 ngày; applier | Bundle → progress/log/result; `views/apply.py`; worker không block UI, lỗi/hủy rõ ràng. |
| [ ] **P4-TUI-07 HistoryView** | M · 0,5 ngày; manifest store | Migration store → history/detail; `views/history.py`; manifest lỗi/thiếu được xử lý. |
| [ ] **P4-TUI-08 SettingsView** | M · 0,5 ngày; config | Config → validated live preview; `views/settings.py`; kiểm tra trước khi lưu. |

**Lưu ý:** shell và views hiện đã hoạt động với `presentation/tui/_mock.py`; không viết lại giao diện.

### Giai đoạn 4 — Mở rộng MVP-B

**Chỉ bắt đầu sau M3 round-trip xanh.** Mỗi object type phải hoàn thiện chuỗi catalog query → model → delta/comparator → emitter/risk → tests.

| Checklist / task | Ước lượng | Input → Output; files/tác động; điều kiện hoàn thành |
|---|---|---|
| [ ] **P3-MVPB-01 Views** | M · ~0,5 ngày | View definitions → model/delta/SQL; catalog query, dependency order, diff và round-trip pass. |
| [ ] **P3-MVPB-02 Materialized views** | M · ~0,5 ngày | Definitions/options → model + create/drop/refresh semantics; kiểm tra index và dependency. |
| [ ] **P3-MVPB-03 Functions** | L · 1–2 ngày | Routine signature/body → model/comparator/emitter; test overload, args/defaults, language, quoting, dependency. |
| [ ] **P3-MVPB-04 Procedures** | M · ~0,5 ngày | Procedure signature/body → migration; test overload và metadata riêng. |
| [ ] **P3-MVPB-05 Sequences** | M · ~0,5 ngày | Sequence parameters/ownership → create/alter/drop; test increment, bounds, owned-by. |
| [ ] **P3-MVPB-06 Enums** | M · ~0,5 ngày | Labels/order → delta/SQL; test ADD VALUE BEFORE/AFTER; removal phải BLOCKED nếu không an toàn. |
| [ ] **P3-MVPB-07 Triggers** | L · 1–2 ngày | Trigger definition → model/delta/SQL; test dependency vào function/table và ordering. |
| [ ] **P3-MVPB-08 RLS policies** | M · ~0,5 ngày | Roles/commands/expressions → DDL; test quoting, enable/force RLS, policy diff. |
| [ ] **P3-MVPB-09 Composite types** | M · ~0,5 ngày | Attributes/order → model/delta/emitter; test add/drop/alter và dependency. |
| [ ] **P3-MVPB-10 Domain types** | M · ~0,5 ngày | Base type/default/constraints → DDL; test constraints và thay đổi không chuyển đổi an toàn. |

### Giai đoạn 5 — Production readiness

| Checklist / task | Estimate, dependency | Input → Output; files/tác động; điều kiện hoàn thành |
|---|---|---|
| [ ] **P0-CI-03 Coverage gate** | S · <2 giờ; sau baseline | Coverage → threshold 85% line/80% branch; `pyproject.toml`/workflow; không bật gate trước khi biết headroom. |
| [ ] **P5-CLI-01 Full CLI UX** | M · ~0,5 ngày; M3 | Risk/progress/options → UX hoàn chỉnh; `presentation/cli`; test `--max-risk`, output ổn định, lỗi hữu ích. |
| [ ] **P5-REPORT-01 HTML report** | L · 1–2 ngày; M3 | DeltaSet/manifest → report; escape output, offline render, nội dung khớp CLI. |
| [ ] **P5-I18N-01 EN/VI** | M · ~0,5 ngày | Message keys → catalog EN/VI; test fallback và không hard-code message ngoài scope. |
| [ ] **P5-PKG-01 Build/release** | M · ~0,5 ngày; M3 | Source → wheel/sdist/release workflow; `uv build`, test catalog resources và `pgsd` entry point. |
| [x] **P5-BENCH-01 10k benchmark** | M · ~0,5 ngày; M3 | Fixture 10k objects → inspect/diff/generate benchmark; mục tiêu dưới 10 giây, profile trước khi optimize. |
| [ ] **P5-DOCS-01 User guide/cookbook** | L · 1–2 ngày; hành vi ổn định | Implemented behavior → CLI guide, safe migration và rollback limitations; ví dụ phải chạy được. |
| [ ] **OPS-03 Branch protection** | S · human action | Branch policy → linear history/review/checks bắt buộc; xác nhận GitHub settings, không auto-merge. |

## 5. Refactor, technical debt, performance và tests

### Refactor đề xuất

1. Đồng bộ `AI_STATE.md`, `TASK_INDEX.md`, `docs/TASKS.md`, `docs/PROJECT_CONTEXT.md`, `docs/ROADMAP.md`; thống nhất task catalog và execution queue theo `ORCHESTRATOR.md`.
2. Đánh dấu hướng dẫn package cũ obsolete; tham chiếu `docs/architecture.md` làm tài liệu hiện hành.
3. Rà soát prototype modules trong `src/pgschemadiff/presentation/app.py`, `presentation/screens/`, `presentation/widgets/`, `domain/models/`, `infrastructure/config/`; quyết định giữ làm reference, thay thế hay xóa sau khi xác minh.
4. Rà soát pytest ignore/exclusion trong `pyproject.toml`, nhất là `tests/test_screens.py` và module bị loại khỏi Ruff/mypy. Không xóa test trước khi biết behavior nào đang được cover.

### Tối ưu hiệu năng

- Giữ inspector một connection REPEATABLE READ như ADR-0012 đến khi benchmark chỉ ra vấn đề; không triển khai `pg_export_snapshot` sớm.
- Đo M1 1.000 objects và P5 10.000 objects; profile riêng inspect/diff/emit.
- Giữ topo-sort O(n+m). Chỉ thêm cache/index hoặc nhiều connection sau khi profile chỉ ra bottleneck.

### Chuẩn hóa convention

- Giữ Ruff, mypy strict, import-linter và CI gate.
- Chia task theo `ORCHESTRATOR.md`: khoảng ≤3 files và một done-condition/task; khai báo dependency và owner.
- Loại object kind chưa hỗ trợ phải phát diagnostic rõ; không coi empty diff là thành công mặc định.
- Sửa dependency rename loader để có cả table và column comparator.
- Không thêm dependency nếu thư viện hiện có đáp ứng; mọi thay đổi dependency phải cập nhật `uv.lock`.

### Test cần bổ sung

- Inspector integration với PG18: catalog mapping thật, filter, permission/error cases.
- Comparator edge/property tests; idempotence, determinism, serialization và ordering.
- CLI JSON/exit-code/filter/error/redaction tests.
- SQL snapshots cho quoting, risk gate, transaction units, DDL order.
- PG18 round-trip generate/apply/inspect, gồm non-transactional statements.
- TUI tests với use case thật/fake ports: worker, cancel, failure, không chỉ mock state.

## 6. Thứ tự triển khai và milestones

### Thứ tự tối ưu

1. Đồng bộ local lên `30fc278`, giữ nguyên ZIP; cập nhật state/docs.
2. Sửa integration CI fail-closed; xin quyết định P1-TEST-02 và chạy M1 benchmark.
3. Làm P2-DIFF-03; có thể làm schema/extension comparators song song vì modules độc lập.
4. Chốt field coverage; làm rename/ignore, edge/property tests.
5. Nối comparator registry, filters và topo-sort vào `compare_schemas`/`pgsd diff`; đóng M2.
6. Chốt risk contract và `MigrationWriter`; làm emitters, transaction splitter, writer, applier.
7. Chạy round-trip PG18; đóng M3.
8. Nối TUI mock views vào use cases thật; không viết lại shell.
9. Chỉ sau M3 mới mở rộng MVP-B; cuối cùng harden/release.

### Roadmap theo tuần

| Tuần | Milestone |
|---|---|
| 0 | Đồng bộ checkout/state, sửa integration CI; quyết định P1-TEST-02. |
| 1–2 | Column + schema/extension comparators, coverage audit, rename/ignore, property tests, `pgsd diff`; hoàn thành M2. |
| 3–5 | Risk model, SQL emitters, transaction units, writer/applier, round-trip; hoàn thành M3. |
| 6–7 | Nối connection/overview/diff/migration/apply/history TUI vào use case MVP-A. |
| 8–12 | MVP-B object types theo dependency; mỗi nhóm có catalog/model/diff/emit/test. |
| 13–15 | Coverage gate, benchmarks, full CLI, docs, package/release hardening. |

**Ước lượng tổng:** 6–8 tuần cho MVP-A backend + TUI dùng được; 13–16 tuần cho MVP-B và production readiness với một kỹ sư chính. Human gate, review và CI có thể kéo dài lịch.

### Blocker chính

- Local checkout thiếu commit mới nhất của remote.
- Branch còn 5 commits so với main, chưa có PR mở.
- P1-TEST-02 cần quyết định maintainer vì PR trước đã đóng.
- Integration CI hiện có thể che lỗi.
- M2 còn ColumnComparator, schema/extension comparators, tests và CLI.
- State/docs mâu thuẫn làm execution queue không đáng tin.

**Hành động tiếp theo:** đồng bộ local mà không đụng ZIP; reconcile state files; sau đó triển khai P2-DIFF-03 và bổ sung schema/extension comparator tasks trước khi tuyên bố M2 hoàn tất.
