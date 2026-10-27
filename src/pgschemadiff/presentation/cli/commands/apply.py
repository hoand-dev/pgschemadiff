"""``pgsd apply`` command implementation."""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, NoReturn

import psycopg
import psycopg_pool
import typer
from rich.text import Text

from pgschemadiff.application.diff.fingerprint import schema_fingerprint
from pgschemadiff.application.migration.apply import (
    ApplyEvent,
    ApplyResult,
    StatementFinished,
    StatementStarted,
    UnitFailed,
    UnitFinished,
    UnitStarted,
    apply_migration,
)
from pgschemadiff.application.migration.bundle import ValidatedBundle, load_bundle
from pgschemadiff.application.migration.guard import (
    GuardResult,
    SourceStateMismatchError,
    verify_source_state,
)
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.infrastructure.fs.bundle_reader import FilesystemBundleReader
from pgschemadiff.infrastructure.postgres.applier import open_executor
from pgschemadiff.presentation import composition
from pgschemadiff.presentation.cli import output
from pgschemadiff.presentation.composition import check_connectivity
from pgschemadiff.presentation.i18n import t
from pgschemadiff.presentation.timeouts import parse_timeout
from pgschemadiff.shared.errors import ApplyMigrationError, MigrationError, RiskGateError

if TYPE_CHECKING:
    from pathlib import Path


def _exit(message: str, code: int) -> NoReturn:
    output.error(message, code)


def _timeout_error_message(error: ValueError) -> str:
    message = str(error)
    invalid_prefix = "Error: Invalid value for "
    if message.startswith(invalid_prefix) and message.endswith("."):
        option = message.removeprefix(invalid_prefix).removesuffix(".")
        return t("apply.error.timeout_invalid", option=option)

    maximum_prefix = "Error: "
    maximum_suffix = " must not exceed 24 hours."
    if message.startswith(maximum_prefix) and message.endswith(maximum_suffix):
        option = message.removeprefix(maximum_prefix).removesuffix(maximum_suffix)
        return t("apply.error.timeout_maximum", option=option)

    return t("apply.error.failure", message=message)


def _requires_destructive_approval(bundle: ValidatedBundle) -> bool:
    return any(unit.max_risk in {RiskLevel.DESTRUCTIVE, RiskLevel.BLOCKED} for unit in bundle.units)


async def _apply(
    bundle: ValidatedBundle,
    db_url: str,
    *,
    lock_timeout_ms: int,
    statement_timeout_ms: int,
    approve_destructive: bool,
) -> ApplyResult:
    async with open_executor(
        db_url,
        lock_timeout_ms=lock_timeout_ms,
        statement_timeout_ms=statement_timeout_ms,
    ) as executor:
        return await apply_migration(
            bundle,
            executor,
            approve_destructive=approve_destructive,
            on_event=_print_event,
        )


async def _verify_source(bundle: ValidatedBundle, db_url: str) -> GuardResult:
    schemas = list(bundle.inspected_schemas) if bundle.inspected_schemas is not None else None
    async with composition.open_inspector(db_url, schemas=schemas) as inspector:
        history = composition.create_history_reader(db_url)
        return await verify_source_state(bundle, inspector, history)


async def _verify_target(bundle: ValidatedBundle, db_url: str) -> bool:
    schemas = list(bundle.inspected_schemas) if bundle.inspected_schemas is not None else None
    async with composition.open_inspector(db_url, schemas=schemas) as inspector:
        database = await inspector.inspect()
    return schema_fingerprint(database) == bundle.target_fingerprint


def _read_bundle(bundle_dir: Path) -> ValidatedBundle:
    try:
        manifest_bytes, up_sql_bytes = FilesystemBundleReader().read(bundle_dir)
    except OSError:
        _exit(t("apply.error.bundle_read"), 1)

    try:
        return load_bundle(manifest_bytes, up_sql_bytes)
    except MigrationError as error:
        _exit(t("apply.error.bundle_invalid", error=error), 2)


def _confirm_risk(bundle: ValidatedBundle, *, dry_run: bool, yes: bool) -> tuple[bool, bool]:
    if any(unit.max_risk is RiskLevel.BLOCKED for unit in bundle.units):
        _exit(t("apply.error.blocked_bundle"), 2)

    destructive = _requires_destructive_approval(bundle)
    approved = yes
    if destructive and not dry_run and not yes:
        if not sys.stdin.isatty():
            _exit(t("apply.error.destructive_requires_yes"), 2)
        try:
            approved = typer.confirm(t("apply.confirm.destructive"))
        except (KeyboardInterrupt, asyncio.CancelledError):
            _exit(t("apply.error.cancelled"), 3)
        if not approved:
            _exit(t("apply.error.destructive_not_approved"), 2)
    return destructive, approved


def _print_event(event: ApplyEvent) -> None:
    if isinstance(event, UnitStarted):
        line = f"unit {event.unit_index + 1}/{event.unit_count} started"
    elif isinstance(event, UnitFinished):
        line = f"unit {event.unit_index + 1}/{event.unit_count} finished"
    elif isinstance(event, StatementStarted):
        line = (
            f"unit {event.unit_index + 1}/{event.unit_count} "
            f"statement {event.statement_index + 1}/{event.statement_count} started "
            f"delta={event.delta_id} lines {event.line_range[0]}-{event.line_range[1]}"
        )
    elif isinstance(event, StatementFinished):
        line = (
            f"unit {event.unit_index + 1}/{event.unit_count} "
            f"statement {event.statement_index + 1}/{event.statement_count} finished "
            f"delta={event.delta_id} lines {event.line_range[0]}-{event.line_range[1]}"
        )
    elif isinstance(event, UnitFailed):
        sqlstate = event.sqlstate or "unknown"
        line = (
            f"unit {event.unit_index + 1}/{event.unit_count} "
            f"statement {event.statement_index + 1}/{event.statement_count} failed "
            f"delta={event.delta_id} lines {event.line_range[0]}-{event.line_range[1]} "
            f"error={event.error_class} SQLSTATE={sqlstate}"
        )
    else:
        return
    if isinstance(event, UnitFailed):
        console = output.stderr_console()
        console.print(Text(line, style="red") if console.is_terminal else line)
    else:
        typer.echo(line, err=True)


def _print_apply_failure(error: ApplyMigrationError, bundle: ValidatedBundle) -> None:
    message = str(error)
    result = error.result
    if isinstance(result, ApplyResult) and result.failed_unit_index is not None:
        unit_index = result.failed_unit_index
        unit = bundle.units[unit_index] if 0 <= unit_index < len(bundle.units) else None
        statement_count = len(unit.statements) if unit is not None else "?"
        statement_index = result.failed_statement_index
        statement_position = statement_index + 1 if statement_index is not None else "?"
        line_range = result.line_range
        lines = f"{line_range[0]}-{line_range[1]}" if line_range is not None else "unknown"
        message += t(
            "apply.error.failure_metadata",
            unit=unit_index + 1,
            unit_count=result.unit_count,
            unit_index=unit_index,
            statement=statement_position,
            statement_count=statement_count,
            statement_index=statement_index,
            delta_id=result.delta_id,
            lines=lines,
            error_class=result.error_class,
            sqlstate=result.sqlstate or "unknown",
        )
        if result.manual_inspection_required:
            message += t("apply.error.invalid_index_warning")
    _exit(t("apply.error.failure", message=message), 3)


def _print_dry_run(bundle: ValidatedBundle) -> None:
    for unit in bundle.units:
        mode = "transactional" if unit.transactional else "non-transactional"
        delta_ids = ",".join(unit.delta_ids) or "none"
        typer.echo(
            f"unit {unit.index + 1}/{len(bundle.units)}: {mode}; "
            f"risk={unit.max_risk.value}; statements={len(unit.statements)}; "
            f"deltas={delta_ids}; lines={unit.start_line}-{unit.end_line}"
        )
    typer.echo(t("apply.note.dry_run_limit"))


def _dry_run(bundle: ValidatedBundle, db_url: str, *, destructive: bool) -> None:
    if destructive:
        typer.echo(
            t("apply.warning.dry_run_destructive"),
            err=True,
        )
    try:
        asyncio.run(check_connectivity(db_url))
    except (psycopg.Error, psycopg_pool.PoolTimeout):
        _exit(t("cli.error.connection_failed"), 1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        _exit(t("apply.error.cancelled"), 3)
    except Exception:
        _exit(t("cli.error.migration_apply_failed"), 3)
    _print_dry_run(bundle)


def _real_apply(
    bundle: ValidatedBundle,
    db_url: str,
    *,
    lock_timeout_ms: int,
    statement_timeout_ms: int,
    approve_destructive: bool,
) -> None:
    try:
        result = asyncio.run(
            _apply(
                bundle,
                db_url,
                lock_timeout_ms=lock_timeout_ms,
                statement_timeout_ms=statement_timeout_ms,
                approve_destructive=approve_destructive,
            )
        )
    except (psycopg.Error, psycopg_pool.PoolTimeout):
        _exit(t("cli.error.connection_failed"), 1)
    except RiskGateError as error:
        _exit(t("apply.error.failure", message=str(error)), 2)
    except ApplyMigrationError as error:
        _print_apply_failure(error, bundle)
    except (KeyboardInterrupt, asyncio.CancelledError):
        _exit(t("apply.error.cancelled"), 3)
    except Exception:
        _exit(t("cli.error.migration_apply_failed"), 3)

    typer.echo(
        t(
            "apply.outcome.migration",
            outcome=t("apply.outcome.resumed" if result.resumed else "apply.outcome.applied"),
            applied=result.applied_unit_count,
            total=result.unit_count,
            bundle_id=result.bundle_id,
        )
    )
    if not result.resumed and bundle.format_version == 2:
        try:
            verified = asyncio.run(_verify_target(bundle, db_url))
        except Exception:
            verified = False
        if verified:
            typer.echo(t("apply.outcome.verified"))
        else:
            typer.echo(
                t("apply.warning.verification_mismatch"),
                err=True,
            )


def _apply_cmd(
    bundle_dir: Path,
    db_url: str,
    *,
    lock_timeout: str = "5s",
    statement_timeout: str = "0",
    dry_run: bool = False,
    yes: bool = False,
    skip_source_check: bool = False,
) -> None:
    """Apply a validated migration bundle to PostgreSQL with risk confirmation."""
    try:
        lock_timeout_ms = parse_timeout(lock_timeout, "--lock-timeout")
        statement_timeout_ms = parse_timeout(statement_timeout, "--statement-timeout")
    except ValueError as error:
        _exit(_timeout_error_message(error), 2)

    bundle = _read_bundle(bundle_dir)
    if any(unit.max_risk is RiskLevel.BLOCKED for unit in bundle.units):
        _exit(t("apply.error.blocked_bundle"), 2)

    guard_result: GuardResult | None = None
    if skip_source_check:
        typer.echo(t("apply.warning.source_check_skipped"), err=True)
    if bundle.format_version == 1:
        guard_result = GuardResult.SKIPPED_LEGACY
        typer.echo(
            t("apply.warning.legacy_source_missing"),
            err=True,
        )
    elif not skip_source_check:
        try:
            guard_result = asyncio.run(_verify_source(bundle, db_url))
        except SourceStateMismatchError as error:
            detail = str(error).removesuffix(".")
            _exit(
                t("apply.error.source_mismatch", detail=detail),
                2,
            )
        except (psycopg.Error, psycopg_pool.PoolTimeout):
            _exit(t("cli.error.connection_failed"), 1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            _exit(t("apply.error.cancelled"), 3)
        except Exception:
            _exit(t("cli.error.schema_inspection_failed"), 1)

    destructive, approve_destructive = _confirm_risk(bundle, dry_run=dry_run, yes=yes)
    if dry_run:
        if skip_source_check:
            typer.echo(t("apply.source_check.skipped_override"))
        else:
            assert guard_result is not None
            typer.echo(
                t(
                    "apply.source_check",
                    status=t(f"apply.source_check.{guard_result.value}"),
                )
            )
        _dry_run(bundle, db_url, destructive=destructive)
        return
    _real_apply(
        bundle,
        db_url,
        lock_timeout_ms=lock_timeout_ms,
        statement_timeout_ms=statement_timeout_ms,
        approve_destructive=approve_destructive,
    )


def apply_cmd(
    bundle_dir: Path,
    db_url: str,
    *,
    lock_timeout: str = "5s",
    statement_timeout: str = "0",
    dry_run: bool = False,
    yes: bool = False,
    skip_source_check: bool = False,
) -> None:
    """Run ``pgsd apply`` with a redacted fallback for unexpected failures."""
    try:
        _apply_cmd(
            bundle_dir,
            db_url,
            lock_timeout=lock_timeout,
            statement_timeout=statement_timeout,
            dry_run=dry_run,
            yes=yes,
            skip_source_check=skip_source_check,
        )
    except typer.Exit:
        raise
    except (KeyboardInterrupt, asyncio.CancelledError):
        _exit(t("apply.error.cancelled"), 3)
    except Exception:
        _exit(t("cli.error.migration_apply_failed"), 3)
