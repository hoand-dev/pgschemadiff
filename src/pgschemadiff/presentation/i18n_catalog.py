"""English and Vietnamese CLI message templates."""

EN: dict[str, str] = {
    "cli.error.connection_failed": "Error: Database connection failed.",
    "cli.error.schema_inspection_failed": "Error: Schema inspection failed.",
    "cli.error.schema_comparison_failed": "Error: Schema comparison failed.",
    "cli.error.schema_diff_failed": "Error: Schema diff failed.",
    "cli.error.migration_apply_failed": "Error: Migration apply failed.",
    "diff.error.invalid_renames": "Error: Invalid renames file: {error}",
    "diff.error.risk_gate": "Risk gate failed: {count} change(s) exceed max-risk={level}.",
    "diff.progress.inspect_source": "Inspecting source",
    "diff.progress.inspect_target": "Inspecting target",
    "diff.progress.compare": "Comparing",
    "generate.error.blocked_max_risk": (
        "Error: --max-risk blocked is not allowed; BLOCKED changes are never generated."
    ),
    "generate.error.output_directory": "Error: --out must be an existing directory.",
    "generate.error.risk_gate": "{detail}",
    "generate.error.migration": "Error: Migration generation failed: {error}",
    "generate.error.migration_failed": "Error: Migration generation failed.",
    "generate.error.bundle_write": "Error: Migration bundle writing failed.",
    "generate.no_changes": "No schema changes.",
    "generate.progress.migration": "Generating migration",
    "generate.progress.bundle": "Writing bundle",
    "generate.success.summary": (
        "Generated migration: deltas={count} max-risk={max_risk} units={units} "
        "(safe={safe} warning={warning} dangerous={dangerous} destructive={destructive})"
    ),
    "report.error.bundle_read": "Error: Could not read migration bundle.",
    "report.error.bundle_invalid": "Error: Invalid migration bundle: {error}",
    "report.error.output_exists": "Error: --out file already exists.",
    "report.error.output_parent": "Error: --out parent must be an existing directory.",
    "report.error.write": "Error: Could not write HTML report.",
    "apply.error.bundle_read": "Error: Could not read migration bundle.",
    "apply.error.bundle_invalid": "Error: Invalid migration bundle: {error}",
    "apply.error.blocked_bundle": "Migration bundle contains a BLOCKED unit and cannot be applied.",
    "apply.error.destructive_requires_yes": (
        "Destructive migration requires --yes when stdin is non-interactive."
    ),
    "apply.confirm.destructive": "This migration contains destructive changes. Continue?",
    "apply.error.cancelled": "Apply cancelled; earlier units remain applied.",
    "apply.error.destructive_not_approved": "Destructive migration was not approved.",
    "apply.error.failure": "{message}",
    "apply.error.timeout_invalid": "Error: Invalid value for {option}.",
    "apply.error.timeout_maximum": "Error: {option} must not exceed 24 hours.",
    "apply.error.failure_metadata": (
        " Unit {unit}/{unit_count} (index {unit_index}), "
        "statement {statement}/{statement_count} (index {statement_index}), "
        "delta={delta_id}, lines {lines}, error={error_class}, SQLSTATE={sqlstate}."
    ),
    "apply.error.invalid_index_warning": (
        " PostgreSQL may have left an INVALID index; manually inspect and clean it up before retry."
    ),
    "apply.note.dry_run_limit": "Dry-run does not prove permissions or future execution success.",
    "apply.warning.dry_run_destructive": (
        "Warning: bundle contains destructive-risk units; dry-run executes no migration SQL."
    ),
    "apply.error.source_mismatch": (
        "Error: {detail}. Re-run generate against this database, or pass "
        "--skip-source-check after review."
    ),
    "apply.warning.source_check_skipped": (
        "Warning: Source schema check skipped by --skip-source-check."
    ),
    "apply.warning.legacy_source_missing": (
        "Bundle has no source fingerprint (format 1); the database state cannot be verified."
    ),
    "apply.source_check": "Source state check: {status}.",
    "apply.source_check.skipped_override": "Source state check: skipped (--skip-source-check).",
    "apply.source_check.match": "match",
    "apply.source_check.skipped_legacy": "skipped_legacy",
    "apply.source_check.skipped_resume": "skipped_resume",
    "apply.source_check.skipped_applied": "skipped_applied",
    "apply.outcome.migration": (
        "{outcome} migration: units-applied={applied}/{total} bundle={bundle_id}"
    ),
    "apply.outcome.applied": "Applied",
    "apply.outcome.resumed": "Resumed",
    "apply.outcome.verified": "Verified: database now matches the desired schema.",
    "apply.warning.verification_mismatch": (
        "Warning: database does not match the desired schema after apply; run diff to inspect."
    ),
}
VI: dict[str, str] = {
    "cli.error.connection_failed": "Lỗi: Không kết nối được cơ sở dữ liệu.",
    "cli.error.schema_inspection_failed": "Lỗi: Không đọc được schema.",
    "cli.error.schema_comparison_failed": "Lỗi: Không thể so sánh schema.",
    "cli.error.schema_diff_failed": "Lỗi: Không thể tạo bản so sánh schema.",
    "cli.error.migration_apply_failed": "Lỗi: Không thể áp dụng migration.",
    "diff.error.invalid_renames": "Lỗi: Tệp renames không hợp lệ: {error}",
    "diff.error.risk_gate": (
        "Lỗi: Kiểm tra rủi ro không đạt: {count} thay đổi vượt quá max-risk={level}."
    ),
    "diff.progress.inspect_source": "Đang đọc schema nguồn",
    "diff.progress.inspect_target": "Đang đọc schema đích",
    "diff.progress.compare": "Đang so sánh",
    "generate.error.blocked_max_risk": (
        "Lỗi: Không cho phép --max-risk blocked; "
        "thay đổi BLOCKED không bao giờ được đưa vào migration."
    ),
    "generate.error.output_directory": "Lỗi: --out phải là thư mục đã tồn tại.",
    "generate.error.risk_gate": "Lỗi: {detail}",
    "generate.error.migration": "Lỗi: Không thể tạo migration: {error}",
    "generate.error.migration_failed": "Lỗi: Không thể tạo migration.",
    "generate.error.bundle_write": "Lỗi: Không thể ghi migration bundle.",
    "generate.no_changes": "Không có thay đổi schema.",
    "generate.progress.migration": "Đang tạo migration",
    "generate.progress.bundle": "Đang ghi bundle",
    "generate.success.summary": (
        "Đã tạo migration: deltas={count} max-risk={max_risk} units={units} "
        "(safe={safe} warning={warning} dangerous={dangerous} destructive={destructive})"
    ),
    "report.error.bundle_read": "Lỗi: Không đọc được migration bundle.",
    "report.error.bundle_invalid": "Lỗi: Migration bundle không hợp lệ: {error}",
    "report.error.output_exists": "Lỗi: Tệp --out đã tồn tại.",
    "report.error.output_parent": "Lỗi: Thư mục cha của --out phải tồn tại.",
    "report.error.write": "Lỗi: Không thể ghi báo cáo HTML.",
    "apply.error.bundle_read": "Lỗi: Không đọc được migration bundle.",
    "apply.error.bundle_invalid": "Lỗi: Migration bundle không hợp lệ: {error}",
    "apply.error.blocked_bundle": ("Lỗi: Migration bundle có unit BLOCKED nên không thể áp dụng."),
    "apply.error.destructive_requires_yes": (
        "Migration có thay đổi phá hủy dữ liệu cần --yes khi stdin không tương tác."
    ),
    "apply.confirm.destructive": "Migration này có thay đổi phá hủy dữ liệu. Tiếp tục?",
    "apply.error.cancelled": "Đã hủy apply; các unit đã chạy xong trước đó vẫn được giữ nguyên.",
    "apply.error.destructive_not_approved": (
        "Lỗi: Migration có thay đổi phá hủy dữ liệu chưa được phê duyệt."
    ),
    "apply.error.failure": "Lỗi: {message}",
    "apply.error.timeout_invalid": "Lỗi: Giá trị của {option} không hợp lệ.",
    "apply.error.timeout_maximum": "Lỗi: {option} không được vượt quá 24 giờ.",
    "apply.error.failure_metadata": (
        " Unit {unit}/{unit_count} (chỉ số {unit_index}), "
        "câu lệnh {statement}/{statement_count} (chỉ số {statement_index}), "
        "delta={delta_id}, dòng {lines}, lỗi={error_class}, SQLSTATE={sqlstate}."
    ),
    "apply.error.invalid_index_warning": (
        " PostgreSQL có thể đã để lại INVALID index; hãy kiểm tra và dọn dẹp thủ công "
        "trước khi thử lại."
    ),
    "apply.note.dry_run_limit": (
        "Dry-run không xác nhận quyền hạn và không bảo đảm lần chạy thật sẽ thành công."
    ),
    "apply.warning.dry_run_destructive": (
        "Cảnh báo: bundle có unit mang rủi ro destructive; "
        "dry-run không thực thi SQL migration nào."
    ),
    "apply.error.source_mismatch": (
        "Lỗi: {detail}. Chạy lại generate với cơ sở dữ liệu này hoặc truyền "
        "--skip-source-check sau khi rà soát."
    ),
    "apply.warning.source_check_skipped": (
        "Cảnh báo: Đã bỏ qua kiểm tra schema nguồn theo --skip-source-check."
    ),
    "apply.warning.legacy_source_missing": (
        "Bundle không có source fingerprint (format 1); "
        "không thể xác minh trạng thái cơ sở dữ liệu."
    ),
    "apply.source_check": "Kiểm tra trạng thái nguồn: {status}.",
    "apply.source_check.skipped_override": (
        "Kiểm tra trạng thái nguồn: đã bỏ qua (--skip-source-check)."
    ),
    "apply.source_check.match": "khớp",
    "apply.source_check.skipped_legacy": "đã bỏ qua (bundle format 1)",
    "apply.source_check.skipped_resume": "đã bỏ qua (tiếp tục lần apply trước)",
    "apply.source_check.skipped_applied": "đã bỏ qua (đã áp dụng)",
    "apply.outcome.migration": (
        "{outcome} migration: units-applied={applied}/{total} bundle={bundle_id}"
    ),
    "apply.outcome.applied": "Đã áp dụng",
    "apply.outcome.resumed": "Đã tiếp tục",
    "apply.outcome.verified": "Đã xác minh: cơ sở dữ liệu hiện khớp với schema mong muốn.",
    "apply.warning.verification_mismatch": (
        "Cảnh báo: cơ sở dữ liệu không khớp schema mong muốn sau khi áp dụng; "
        "chạy diff để kiểm tra."
    ),
}
