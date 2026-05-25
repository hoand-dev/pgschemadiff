"""Mock data used by the TUI views until Phase 1-3 lands.

Everything here mirrors the shape that future ``application/`` use cases will
return.  When real implementations land, each view's import of ``_mock``
becomes an import of the real use case.  Do **not** add mock data anywhere
else — keeping it in one file makes the eventual swap mechanical.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionProfile:
    label: str
    host: str
    database: str
    role: str
    ssl: str
    latency_ms: int
    table_count: int
    size: str


@dataclass(frozen=True)
class ChangeRow:
    op: str  # add / mod / del / conflict
    schema: str
    object: str
    risk: str  # SAFE / WARNING / DANGEROUS / DESTRUCTIVE / BLOCKED
    lock: str
    est_ms: int


SOURCE = ConnectionProfile(
    label="acme_prod",
    host="db-prod-us-east-1.internal",
    database="acme_prod",
    role="pgsd_reader",
    ssl="verify-full",
    latency_ms=14,
    table_count=47,
    size="128 GB",
)

TARGET = ConnectionProfile(
    label="acme_staging",
    host="db-stage.internal",
    database="acme_staging",
    role="pgsd_migrator",
    ssl="verify-full",
    latency_ms=9,
    table_count=49,
    size="12 GB",
)

CHANGE_SUMMARY = {"add": 4, "mod": 6, "del": 2, "conflict": 1}

CHANGE_ROWS: tuple[ChangeRow, ...] = (
    ChangeRow("add", "public", "task_subscriptions", "SAFE", "ACCESS EXCLUSIVE", 120),
    ChangeRow("mod", "public", "users.email", "DANGEROUS", "ACCESS EXCLUSIVE", 4_200),
    ChangeRow("mod", "public", "tenants", "WARNING", "ACCESS EXCLUSIVE", 320),
    ChangeRow(
        "mod", "public", "workspaces.storage_quota_bytes", "WARNING", "ACCESS EXCLUSIVE", 880
    ),
    ChangeRow("add", "public", "idx_tasks_due_date", "SAFE", "SHARE UPDATE EXCLUSIVE", 1_400),
    ChangeRow("add", "public", "idx_users_email_lower", "SAFE", "SHARE UPDATE EXCLUSIVE", 900),
    ChangeRow("del", "public", "legacy_invites", "DESTRUCTIVE", "ACCESS EXCLUSIVE", 80),
    ChangeRow("del", "public", "comments.legacy_html", "DESTRUCTIVE", "ACCESS EXCLUSIVE", 40),
    ChangeRow("conflict", "public", "idx_users_email", "BLOCKED", "—", 0),
)
