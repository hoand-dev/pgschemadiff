"""Mock data used by the TUI views until Phase 1-3 lands.

Everything here mirrors the shape that future ``application/`` use cases will
return.  When real implementations land, each view's import of ``_mock``
becomes an import of the real use case.  Do **not** add mock data anywhere
else — keeping it in one file makes the eventual swap mechanical.

The dataset is a faithful subset of the design prototype's ``data.js`` (see
``docs/ui-design/reference/``): a realistic multi-tenant SaaS workload across
three schemas (``public``, ``billing``, ``analytics``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Connection profiles
# --------------------------------------------------------------------------- #


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
    url: str = ""
    version: str = "PostgreSQL 16.2"
    schemas: str = "public, billing, analytics"


SOURCE = ConnectionProfile(
    label="acme_prod",
    host="db-prod-us-east-1.internal",
    database="acme_prod",
    role="pgsd_reader",
    ssl="verify-full",
    latency_ms=14,
    table_count=47,
    size="128 GB",
    url="postgres://reader@db-prod-us-east-1.internal:5432/acme_prod",
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
    url="postgres://migrator@db-stage.internal:5432/acme_staging",
)


@dataclass(frozen=True)
class SavedProfile:
    name: str
    route: str
    last_used: str
    owner: str
    current: bool = False


SAVED_PROFILES: tuple[SavedProfile, ...] = (
    SavedProfile("acme · prod → staging", "acme_prod → acme_staging", "just now", "minh.le", True),
    SavedProfile("acme · prod → dev", "acme_prod → acme_dev", "2 days ago", "thuy.nguyen"),
    SavedProfile(
        "billing · prod → analytics-mirror",
        "billing_prod → analytics_mirror",
        "5 days ago",
        "duc.tran",
    ),
    SavedProfile("local · dev → docker", "local → pgsd_dev", "1 week ago", "minh.le"),
)

# The nine compare-options shown on the Connection view.
COMPARE_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("Include schemas", "public, billing, analytics", "multi"),
    ("Exclude tables", "__diesel_*, _pgsd_*", "glob"),
    ("Include data", "no (schema-only)", "bool"),
    ("Owner roles", "preserve from source", "select"),
    ("Storage params", "ignore", "select"),
    ("Extensions", "compare versions", "select"),
    ("Generated cols", "compare expressions", "select"),
    ("Comments / COMMENT ON", "sync", "select"),
    ("Case sensitivity", "sensitive", "select"),
)

# --------------------------------------------------------------------------- #
# Change summary + detailed change list
# --------------------------------------------------------------------------- #

CHANGE_SUMMARY = {"add": 4, "mod": 6, "del": 2, "conflict": 1}


@dataclass(frozen=True)
class ChangeRow:
    op: str  # add / mod / del / conflict
    schema: str
    object: str
    risk: str  # SAFE / WARNING / DANGEROUS / DESTRUCTIVE / BLOCKED
    lock: str
    est_ms: int


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


@dataclass(frozen=True)
class Change:
    """One entry in the Overview change table (mirrors ``CHANGES`` in data.js)."""

    id: str
    op: str  # CREATE / ALTER / DROP / REPLACE / CONFLICT
    kind: str  # TABLE / TYPE / INDEX / FUNCTION / TRIGGER
    obj: str  # qualified name (matches a DIFFS key where a diff exists)
    risk: str  # low / medium / high / conflict
    detail: str = ""
    deps: int = 0


CHANGES: tuple[Change, ...] = (
    Change("c01", "CREATE", "TYPE", "public.plan_tier_enum", "low"),
    Change("c02", "CREATE", "TYPE", "public.task_priority", "low"),
    Change("c03", "ALTER", "TYPE", "public.subscription_status", "low", "+VALUE 'paused'"),
    Change("c04", "ALTER", "TABLE", "public.tenants", "low", "+plan_tier, +trial_ends_at", 1),
    Change(
        "c05",
        "ALTER",
        "TABLE",
        "public.users",
        "medium",
        "email→citext, +mfa_secret, -legacy_username",
    ),
    Change(
        "c06", "ALTER", "TABLE", "public.workspaces", "medium", "storage_quota_bytes type change"
    ),
    Change("c07", "ALTER", "TABLE", "public.projects", "low", "+archived_at"),
    Change(
        "c08",
        "ALTER",
        "TABLE",
        "public.tasks",
        "medium",
        "+parent_task_id (FK self), priority→task_priority",
        1,
    ),
    Change("c09", "CREATE", "TABLE", "public.task_subscriptions", "low", "", 1),
    Change("c10", "ALTER", "TABLE", "public.comments", "high", "-legacy_html"),
    Change("c11", "DROP", "TABLE", "public.legacy_invites", "high"),
    Change("c12", "CREATE", "INDEX", "public.idx_tasks_due_date", "low", "", 1),
    Change("c13", "CREATE", "INDEX", "public.idx_tasks_workspace_status", "low"),
    Change("c14", "CREATE", "INDEX", "public.idx_users_email_lower", "low", "", 1),
    Change("c15", "CREATE", "INDEX", "public.idx_audit_logs_actor_created", "low"),
    Change("c16", "CREATE", "INDEX", "public.idx_comments_task_id", "low"),
    Change(
        "c17",
        "CONFLICT",
        "INDEX",
        "public.idx_users_email",
        "conflict",
        "Name exists in target with different definition",
    ),
    Change("c18", "CREATE", "FUNCTION", "public.fn_archive_project", "low", "", 1),
    Change("c19", "REPLACE", "FUNCTION", "public.compute_workspace_usage", "low"),
    Change("c20", "REPLACE", "FUNCTION", "public.fn_assign_task", "low"),
    Change("c21", "CREATE", "TRIGGER", "public.trg_audit_users_changes", "low", "", 1),
    Change("c22", "CREATE", "TABLE", "billing.usage_records", "low"),
    Change("c23", "ALTER", "TABLE", "billing.subscriptions", "low", "+pause_until", 1),
    Change("c24", "ALTER", "TABLE", "billing.payment_methods", "low", "+last_verified_at"),
    Change("c25", "CREATE", "TABLE", "analytics.events_daily_rollup", "low"),
)

# --------------------------------------------------------------------------- #
# Schema tree
# --------------------------------------------------------------------------- #


@dataclass
class TreeNode:
    """A node in the schema explorer tree.

    ``kind`` is one of: schema / group / table / view / func / index /
    trigger / type / col.  ``status`` (when set) drives the change glyph.
    """

    kind: str
    name: str
    status: str = ""  # add / mod / del / conflict / ""
    badge: dict[str, int] = field(default_factory=dict)
    expanded: bool = False
    children: list[TreeNode] = field(default_factory=list)


def _t(kind: str, name: str, status: str = "", **kw: object) -> TreeNode:
    return TreeNode(kind=kind, name=name, status=status, **kw)  # type: ignore[arg-type]


TREE: tuple[TreeNode, ...] = (
    TreeNode(
        "schema",
        "public",
        badge={"add": 4, "mod": 6, "del": 2, "conflict": 1},
        expanded=True,
        children=[
            TreeNode(
                "group",
                "tables",
                badge={"add": 2, "mod": 4, "del": 1},
                expanded=True,
                children=[
                    _t("table", "tenants", "mod"),
                    _t("table", "users", "mod"),
                    _t("table", "workspaces", "mod"),
                    _t("table", "workspace_members"),
                    _t("table", "projects", "mod"),
                    _t("table", "tasks", "mod"),
                    _t("table", "task_assignees"),
                    _t("table", "task_subscriptions", "add"),
                    _t("table", "comments", "mod"),
                    _t("table", "attachments"),
                    _t("table", "legacy_invites", "del"),
                    _t("table", "audit_logs"),
                    _t("table", "api_keys"),
                    _t("table", "webhooks"),
                    _t("table", "feature_flags"),
                ],
            ),
            TreeNode(
                "group",
                "views",
                children=[
                    _t("view", "v_active_workspaces"),
                    _t("view", "v_user_activity_30d", "mod"),
                ],
            ),
            TreeNode(
                "group",
                "functions",
                badge={"mod": 2, "add": 1},
                expanded=True,
                children=[
                    _t("func", "compute_workspace_usage", "mod"),
                    _t("func", "fn_assign_task", "mod"),
                    _t("func", "fn_archive_project", "add"),
                ],
            ),
            TreeNode(
                "group",
                "indexes",
                badge={"add": 5, "conflict": 1},
                expanded=True,
                children=[
                    _t("index", "idx_tasks_due_date", "add"),
                    _t("index", "idx_tasks_workspace_status", "add"),
                    _t("index", "idx_users_email_lower", "add"),
                    _t("index", "idx_audit_logs_actor_created", "add"),
                    _t("index", "idx_comments_task_id", "add"),
                    _t("index", "idx_users_email", "conflict"),
                ],
            ),
            TreeNode(
                "group",
                "triggers",
                badge={"add": 1},
                children=[_t("trigger", "trg_audit_users_changes", "add")],
            ),
            TreeNode(
                "group",
                "types",
                badge={"add": 2, "mod": 1},
                children=[
                    _t("type", "plan_tier_enum", "add"),
                    _t("type", "task_priority", "add"),
                    _t("type", "subscription_status", "mod"),
                ],
            ),
        ],
    ),
    TreeNode(
        "schema",
        "billing",
        badge={"mod": 2, "add": 1},
        children=[
            TreeNode(
                "group",
                "tables",
                children=[
                    _t("table", "subscriptions", "mod"),
                    _t("table", "invoices"),
                    _t("table", "payment_methods", "mod"),
                    _t("table", "usage_records", "add"),
                ],
            ),
            TreeNode("group", "functions", children=[_t("func", "fn_apply_credit")]),
        ],
    ),
    TreeNode(
        "schema",
        "analytics",
        badge={"add": 1},
        children=[
            TreeNode(
                "group",
                "tables",
                children=[
                    _t("table", "events_raw"),
                    _t("table", "events_daily_rollup", "add"),
                ],
            ),
            TreeNode("group", "views", children=[_t("view", "v_dau"), _t("view", "v_mau")]),
        ],
    ),
)

# --------------------------------------------------------------------------- #
# Per-object SQL diffs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DiffLine:
    """One line in a unified (inline) diff.  ``sig`` is ' ' | '+' | '-'."""

    sig: str
    ln: int
    text: str


@dataclass(frozen=True)
class ObjectDiff:
    title: str
    kind: str
    summary: str
    inline: tuple[DiffLine, ...]
    forward: tuple[str, ...]
    backward: tuple[str, ...] = ()
    conflict: bool = False
    # Optional explicit side-by-side (line text only); when empty it is
    # derived from ``inline`` by the view.
    source: tuple[str, ...] = ()
    target: tuple[str, ...] = ()


def _il(rows: list[tuple[str, int, str]]) -> tuple[DiffLine, ...]:
    return tuple(DiffLine(sig, ln, text) for sig, ln, text in rows)


DIFFS: dict[str, ObjectDiff] = {
    "public.tenants": ObjectDiff(
        title="public.tenants",
        kind="table",
        summary="2 columns added · DEFAULT requires backfill",
        inline=_il(
            [
                (" ", 1, "CREATE TABLE public.tenants ("),
                (
                    " ",
                    2,
                    "  id              uuid             PRIMARY KEY DEFAULT gen_random_uuid(),",
                ),
                (" ", 3, "  name            text             NOT NULL,"),
                (" ", 4, "  slug            citext           UNIQUE NOT NULL,"),
                (" ", 5, "  region          text             NOT NULL DEFAULT 'us-east-1',"),
                ("+", 6, "  plan_tier       plan_tier_enum   NOT NULL DEFAULT 'starter',"),
                ("+", 7, "  trial_ends_at   timestamptz,"),
                (" ", 8, "  settings        jsonb            NOT NULL DEFAULT '{}'::jsonb,"),
                (" ", 9, "  created_at      timestamptz      NOT NULL DEFAULT now(),"),
                (" ", 10, "  updated_at      timestamptz      NOT NULL DEFAULT now()"),
                (" ", 11, ");"),
            ]
        ),
        source=(
            "CREATE TABLE public.tenants (",
            "  id           uuid          PRIMARY KEY DEFAULT gen_random_uuid(),",
            "  name         text          NOT NULL,",
            "  slug         citext        UNIQUE NOT NULL,",
            "  region       text          NOT NULL DEFAULT 'us-east-1',",
            "  settings     jsonb         NOT NULL DEFAULT '{}'::jsonb,",
            "  created_at   timestamptz   NOT NULL DEFAULT now(),",
            "  updated_at   timestamptz   NOT NULL DEFAULT now()",
            ");",
        ),
        target=(
            "CREATE TABLE public.tenants (",
            "  id              uuid             PRIMARY KEY DEFAULT gen_random_uuid(),",
            "  name            text             NOT NULL,",
            "  slug            citext           UNIQUE NOT NULL,",
            "  region          text             NOT NULL DEFAULT 'us-east-1',",
            "  plan_tier       plan_tier_enum   NOT NULL DEFAULT 'starter',",
            "  trial_ends_at   timestamptz,",
            "  settings        jsonb            NOT NULL DEFAULT '{}'::jsonb,",
            "  created_at      timestamptz      NOT NULL DEFAULT now(),",
            "  updated_at      timestamptz      NOT NULL DEFAULT now()",
            ");",
        ),
        forward=(
            "-- forward migration: public.tenants",
            "ALTER TABLE public.tenants",
            "  ADD COLUMN plan_tier plan_tier_enum NOT NULL DEFAULT 'starter',",
            "  ADD COLUMN trial_ends_at timestamptz;",
        ),
        backward=(
            "-- rollback: public.tenants",
            "ALTER TABLE public.tenants",
            "  DROP COLUMN plan_tier,",
            "  DROP COLUMN trial_ends_at;",
        ),
    ),
    "public.users": ObjectDiff(
        title="public.users",
        kind="table",
        summary="email type widened · mfa_secret added · legacy_username dropped",
        inline=_il(
            [
                (" ", 1, "CREATE TABLE public.users ("),
                (
                    " ",
                    2,
                    "  id                uuid          PRIMARY KEY DEFAULT gen_random_uuid(),",
                ),
                (
                    " ",
                    3,
                    "  tenant_id         uuid          NOT NULL REFERENCES public.tenants(id),",
                ),
                ("-", 4, "  email             varchar(255)  UNIQUE NOT NULL,"),
                ("+", 4, "  email             citext        UNIQUE NOT NULL,"),
                (" ", 5, "  password_hash     text          NOT NULL,"),
                ("-", 6, "  legacy_username   varchar(64),"),
                ("+", 6, "  mfa_secret        bytea,"),
                (" ", 7, "  display_name      text,"),
                (" ", 8, "  avatar_url        text,"),
                (" ", 9, "  last_login_at     timestamptz,"),
                (" ", 10, "  created_at        timestamptz   NOT NULL DEFAULT now()"),
                (" ", 11, ");"),
            ]
        ),
        forward=(
            "-- forward migration: public.users",
            "-- ! warning: changing email to citext rewrites the column (ACCESS EXCLUSIVE)",
            "ALTER TABLE public.users",
            "  ALTER COLUMN email TYPE citext USING email::citext,",
            "  ADD COLUMN mfa_secret bytea,",
            "  DROP COLUMN legacy_username;",
        ),
        backward=(
            "-- rollback: public.users",
            "ALTER TABLE public.users",
            "  ALTER COLUMN email TYPE varchar(255) USING email::varchar(255),",
            "  DROP COLUMN mfa_secret,",
            "  ADD COLUMN legacy_username varchar(64);",
        ),
    ),
    "public.task_subscriptions": ObjectDiff(
        title="public.task_subscriptions",
        kind="table",
        summary="New junction table for task watcher notifications",
        inline=_il(
            [
                ("+", 1, "CREATE TABLE public.task_subscriptions ("),
                ("+", 2, "  task_id      uuid         NOT NULL REFERENCES public.tasks(id),"),
                ("+", 3, "  user_id      uuid         NOT NULL REFERENCES public.users(id),"),
                ("+", 4, "  reason       text         NOT NULL CHECK (reason IN ('assignee')),"),
                ("+", 5, "  created_at   timestamptz  NOT NULL DEFAULT now(),"),
                ("+", 6, "  PRIMARY KEY (task_id, user_id)"),
                ("+", 7, ");"),
                ("+", 8, "CREATE INDEX idx_task_subs_user ON public.task_subscriptions(user_id);"),
            ]
        ),
        forward=(
            "-- forward migration: public.task_subscriptions",
            "CREATE TABLE public.task_subscriptions (",
            "  task_id      uuid         NOT NULL REFERENCES public.tasks(id) ON DELETE CASCADE,",
            "  user_id      uuid         NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,",
            "  reason       text         NOT NULL CHECK (reason IN ('assignee','mention','manual')),",
            "  created_at   timestamptz  NOT NULL DEFAULT now(),",
            "  PRIMARY KEY (task_id, user_id)",
            ");",
            "CREATE INDEX idx_task_subs_user ON public.task_subscriptions(user_id);",
        ),
        backward=(
            "-- rollback: public.task_subscriptions",
            "DROP TABLE public.task_subscriptions;",
        ),
    ),
    "public.idx_users_email": ObjectDiff(
        title="public.idx_users_email",
        kind="index",
        summary="CONFLICT — index name exists with different definition",
        conflict=True,
        inline=_il(
            [
                ("-", 1, "CREATE UNIQUE INDEX idx_users_email"),
                ("-", 2, "  ON public.users (email);"),
                ("+", 1, "CREATE INDEX idx_users_email"),
                ("+", 2, "  ON public.users (lower(email))"),
                ("+", 3, "  WHERE deleted_at IS NULL;"),
            ]
        ),
        source=(
            "-- source",
            "CREATE UNIQUE INDEX idx_users_email",
            "  ON public.users (email);",
        ),
        target=(
            "-- target (already present, conflicting)",
            "CREATE INDEX idx_users_email",
            "  ON public.users (lower(email))",
            "  WHERE deleted_at IS NULL;",
        ),
        forward=(
            "-- conflict resolution required",
            "-- option A (auto-suggested): drop & recreate as in source",
            "DROP INDEX IF EXISTS public.idx_users_email;",
            "CREATE UNIQUE INDEX idx_users_email ON public.users (email);",
        ),
    ),
    "public.compute_workspace_usage": ObjectDiff(
        title="public.compute_workspace_usage()",
        kind="function",
        summary="CPU optimisation — switch from FOR loop to set-based aggregation",
        inline=_il(
            [
                (" ", 1, "CREATE OR REPLACE FUNCTION public.compute_workspace_usage("),
                (" ", 2, "  p_workspace_id uuid"),
                (" ", 3, ") RETURNS bigint LANGUAGE plpgsql AS $$"),
                (" ", 4, "DECLARE v_total bigint := 0;"),
                (" ", 5, "BEGIN"),
                (
                    "-",
                    6,
                    "  FOR row IN SELECT size FROM attachments WHERE workspace_id = p_id LOOP",
                ),
                ("-", 7, "    v_total := v_total + row.size;"),
                ("-", 8, "  END LOOP;"),
                ("+", 6, "  SELECT coalesce(sum(size),0) INTO v_total"),
                ("+", 7, "    FROM public.attachments"),
                ("+", 8, "   WHERE workspace_id = p_workspace_id"),
                ("+", 9, "     AND deleted_at IS NULL;"),
                (" ", 10, "  RETURN v_total;"),
                (" ", 11, "END $$;"),
            ]
        ),
        forward=(
            "-- forward: public.compute_workspace_usage",
            "CREATE OR REPLACE FUNCTION public.compute_workspace_usage(p_workspace_id uuid)",
            "RETURNS bigint LANGUAGE plpgsql AS $$",
            "DECLARE v_total bigint := 0;",
            "BEGIN",
            "  SELECT coalesce(sum(size),0) INTO v_total",
            "    FROM public.attachments",
            "   WHERE workspace_id = p_workspace_id",
            "     AND deleted_at IS NULL;",
            "  RETURN v_total;",
            "END $$;",
        ),
    ),
}

# --------------------------------------------------------------------------- #
# Generated migration script
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MigLine:
    """A line in the generated migration.

    ``cls`` ∈ {"", add, del, mod, com, kw, warn, err, conflict}.
    """

    ln: int
    text: str
    cls: str = ""


def _ml(rows: list[tuple[int, str, str]]) -> tuple[MigLine, ...]:
    return tuple(MigLine(ln, text, cls) for ln, text, cls in rows)


MIGRATION_LINES: tuple[MigLine, ...] = _ml(
    [
        (1, "-- generated by pgschemadiff @ 2026-05-23 14:22:08+07", "com"),
        (2, "-- source: postgres://db-prod-us-east-1.internal/acme_prod", "com"),
        (3, "-- target: postgres://db-stage.internal/acme_staging", "com"),
        (4, "-- changes: 25 (4 add / 6 mod / 2 del / 1 conflict)", "com"),
        (5, "", ""),
        (6, "BEGIN;", "kw"),
        (7, "SET lock_timeout = '5s';", "kw"),
        (8, "SET statement_timeout = '30min';", "kw"),
        (9, "", ""),
        (10, "-- [c01] CREATE TYPE public.plan_tier_enum", "com"),
        (11, "CREATE TYPE public.plan_tier_enum AS ENUM (", "add"),
        (12, "  'starter', 'pro', 'business', 'enterprise'", "add"),
        (13, ");", "add"),
        (14, "", ""),
        (15, "-- [c02] CREATE TYPE public.task_priority", "com"),
        (16, "CREATE TYPE public.task_priority AS ENUM (", "add"),
        (17, "  'low', 'normal', 'high', 'urgent', 'critical'", "add"),
        (18, ");", "add"),
        (19, "", ""),
        (20, "-- [c03] ALTER TYPE public.subscription_status — append value", "com"),
        (21, "ALTER TYPE public.subscription_status ADD VALUE IF NOT EXISTS 'paused';", "mod"),
        (22, "", ""),
        (23, "-- [c04] ALTER TABLE public.tenants", "com"),
        (24, "ALTER TABLE public.tenants", "mod"),
        (25, "  ADD COLUMN plan_tier plan_tier_enum NOT NULL DEFAULT 'starter',", "mod"),
        (26, "  ADD COLUMN trial_ends_at timestamptz;", "mod"),
        (27, "", ""),
        (28, "-- [c05] ALTER TABLE public.users", "com"),
        (29, "-- ! warning: type change rewrites email column (ACCESS EXCLUSIVE)", "warn"),
        (30, "ALTER TABLE public.users", "mod"),
        (31, "  ALTER COLUMN email TYPE citext USING email::citext,", "mod"),
        (32, "  ADD COLUMN mfa_secret bytea,", "add"),
        (33, "  DROP COLUMN legacy_username;", "del"),
        (34, "", ""),
        (35, "-- [c06] ALTER TABLE public.workspaces", "com"),
        (36, "ALTER TABLE public.workspaces", "mod"),
        (37, "  ALTER COLUMN storage_quota_bytes TYPE numeric(20,0)", "mod"),
        (38, "    USING storage_quota_bytes::numeric(20,0);", "mod"),
        (39, "", ""),
        (40, "-- [c07] ALTER TABLE public.projects", "com"),
        (41, "ALTER TABLE public.projects ADD COLUMN archived_at timestamptz;", "add"),
        (42, "", ""),
        (43, "-- [c08] ALTER TABLE public.tasks", "com"),
        (44, "ALTER TABLE public.tasks", "mod"),
        (45, "  ADD COLUMN parent_task_id uuid REFERENCES public.tasks(id),", "add"),
        (46, "  ALTER COLUMN priority TYPE task_priority", "mod"),
        (47, "    USING (CASE priority WHEN 0 THEN 'low' WHEN 1 THEN 'normal'", "mod"),
        (48, "                          WHEN 2 THEN 'high' WHEN 3 THEN 'urgent'", "mod"),
        (49, "                          ELSE 'critical' END)::task_priority;", "mod"),
        (50, "", ""),
        (51, "-- [c09] CREATE TABLE public.task_subscriptions", "com"),
        (52, "CREATE TABLE public.task_subscriptions (", "add"),
        (
            53,
            "  task_id     uuid        NOT NULL REFERENCES public.tasks(id) ON DELETE CASCADE,",
            "add",
        ),
        (
            54,
            "  user_id     uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,",
            "add",
        ),
        (
            55,
            "  reason      text        NOT NULL CHECK (reason IN ('assignee','mention','manual')),",
            "add",
        ),
        (56, "  created_at  timestamptz NOT NULL DEFAULT now(),", "add"),
        (57, "  PRIMARY KEY (task_id, user_id)", "add"),
        (58, ");", "add"),
        (59, "", ""),
        (60, "-- [c10] ALTER TABLE public.comments — DROP COLUMN legacy_html", "com"),
        (61, "-- ! danger: data loss; suggest dry-run + backup", "err"),
        (62, "ALTER TABLE public.comments DROP COLUMN legacy_html;", "del"),
        (63, "", ""),
        (64, "-- [c11] DROP TABLE public.legacy_invites", "com"),
        (65, "-- ! danger: 4,217 rows will be lost; AI suggests archiving first", "err"),
        (66, "DROP TABLE public.legacy_invites;", "del"),
        (67, "", ""),
        (68, "-- [c12..c16] CREATE INDEX (5 new)", "com"),
        (69, "CREATE INDEX CONCURRENTLY idx_tasks_due_date ON public.tasks (due_date);", "add"),
        (70, "CREATE INDEX CONCURRENTLY idx_tasks_workspace_status", "add"),
        (71, "  ON public.tasks (workspace_id, status) WHERE status <> 'archived';", "add"),
        (
            72,
            "CREATE INDEX CONCURRENTLY idx_users_email_lower ON public.users (lower(email));",
            "add",
        ),
        (73, "CREATE INDEX CONCURRENTLY idx_audit_logs_actor_created", "add"),
        (74, "  ON public.audit_logs (actor_id, created_at DESC);", "add"),
        (75, "CREATE INDEX CONCURRENTLY idx_comments_task_id ON public.comments (task_id);", "add"),
        (76, "", ""),
        (77, "-- [c17] CONFLICT — public.idx_users_email (manual resolution required)", "com"),
        (78, "-- DROP INDEX IF EXISTS public.idx_users_email;", "conflict"),
        (79, "-- CREATE UNIQUE INDEX idx_users_email ON public.users (email);", "conflict"),
        (80, "", ""),
        (81, "-- [c18..c20] FUNCTIONS", "com"),
        (82, "CREATE OR REPLACE FUNCTION public.fn_archive_project(p_id uuid) ...", "add"),
        (83, "CREATE OR REPLACE FUNCTION public.compute_workspace_usage(p_ws uuid) ...", "mod"),
        (84, "CREATE OR REPLACE FUNCTION public.fn_assign_task(t uuid, u uuid) ...", "mod"),
        (85, "", ""),
        (86, "-- [c21] TRIGGER public.trg_audit_users_changes", "com"),
        (87, "CREATE TRIGGER trg_audit_users_changes", "add"),
        (88, "  AFTER INSERT OR UPDATE OR DELETE ON public.users", "add"),
        (89, "  FOR EACH ROW EXECUTE FUNCTION public.fn_log_user_change();", "add"),
        (90, "", ""),
        (91, "-- [c22..c25] schemas billing, analytics (collapsed)", "com"),
        (92, "CREATE TABLE billing.usage_records ( ... );", "add"),
        (93, "ALTER TABLE billing.subscriptions ADD COLUMN pause_until timestamptz;", "add"),
        (94, "ALTER TABLE billing.payment_methods ADD COLUMN last_verified_at timestamptz;", "add"),
        (95, "CREATE TABLE analytics.events_daily_rollup ( ... );", "add"),
        (96, "", ""),
        (97, "COMMIT;", "kw"),
    ]
)

ROLLBACK_LINES: tuple[str, ...] = (
    "-- rollback for migration_20260523_142208.sql",
    "-- generated automatically · tested against snapshot db-stage@2026-05-23",
    "",
    "BEGIN;",
    "SET lock_timeout = '5s';",
    "",
    "-- restore legacy_invites from archive",
    "CREATE TABLE public.legacy_invites AS TABLE legacy.invites_archive;",
    "",
    "-- restore comments.legacy_html (data archived to public.comments_legacy_html_bak)",
    "ALTER TABLE public.comments ADD COLUMN legacy_html text;",
    "UPDATE public.comments c",
    "   SET legacy_html = b.legacy_html",
    "  FROM public.comments_legacy_html_bak b WHERE b.id = c.id;",
    "",
    "-- drop additions (reverse topological order)",
    "DROP TRIGGER trg_audit_users_changes ON public.users;",
    "DROP TABLE public.task_subscriptions;",
    "DROP INDEX CONCURRENTLY idx_comments_task_id;",
    "DROP INDEX CONCURRENTLY idx_audit_logs_actor_created;",
    "DROP INDEX CONCURRENTLY idx_users_email_lower;",
    "DROP INDEX CONCURRENTLY idx_tasks_workspace_status;",
    "DROP INDEX CONCURRENTLY idx_tasks_due_date;",
    "",
    "ALTER TABLE public.users",
    "  ALTER COLUMN email TYPE varchar(255) USING email::varchar(255),",
    "  DROP COLUMN mfa_secret,",
    "  ADD COLUMN legacy_username varchar(64);",
    "",
    "ALTER TABLE public.tenants",
    "  DROP COLUMN trial_ends_at,",
    "  DROP COLUMN plan_tier;",
    "",
    "DROP TYPE public.task_priority;",
    "DROP TYPE public.plan_tier_enum;",
    "",
    "COMMIT;",
)

# Migration sidebar facts.
MIGRATION_TOGGLES: tuple[tuple[str, bool, str], ...] = (
    ("transactional", True, "wrap in BEGIN; … COMMIT;"),
    ("concurrent indexes", True, "CREATE INDEX CONCURRENTLY"),
    ("include DDL", True, "schema + functions + triggers"),
    ("include conflicts", False, "leave commented out by default"),
    ("include data", False, "seed + lookup tables"),
)


@dataclass(frozen=True)
class LockEstimate:
    step: str
    lock: str
    rows: str
    est: str
    sev: str = ""  # "" / warn / err / ok


LOCK_ESTIMATES: tuple[LockEstimate, ...] = (
    LockEstimate("c04 tenants +cols", "ACCESS SHARE", "284", "< 1s", "ok"),
    LockEstimate("c05 users email", "ACCESS EXCL", "38M", "~14m", "warn"),
    LockEstimate("c06 workspaces type", "ACCESS EXCL", "1.2M", "~38s", "warn"),
    LockEstimate("c08 tasks", "SHARE UPD EXCL", "92M", "~2m", ""),
    LockEstimate("c12-c16 indexes", "SHARE UPD EXCL", "—", "~9m (concurrent)", "ok"),
    LockEstimate("c11 DROP legacy", "ACCESS EXCL", "4217", "< 1s", "err"),
)

MIGRATION_STATS: tuple[tuple[str, str, str], ...] = (
    ("lines", "97", ""),
    ("size", "4.7 KB", ""),
    ("est. duration", "~26 min", "warn"),
    ("downtime", "~15 min", "err"),
)

# --------------------------------------------------------------------------- #
# Apply (pre-flight, steps)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PreflightItem:
    glyph: str
    text: str
    sev: str  # ok / warn / err / info


PREFLIGHT: tuple[PreflightItem, ...] = (
    PreflightItem("✓", "connected to target (ssl: verify-full, role: pgsd_migrator)", "ok"),
    PreflightItem("✓", "target db responsive — latency 9ms", "ok"),
    PreflightItem("✓", "pre-flight snapshot taken — db-stage_20260523_142208.dump", "ok"),
    PreflightItem("✓", "no active long-running transactions on target", "ok"),
    PreflightItem("⚠", "estimated downtime ~15m (email type rewrite)", "warn"),
    PreflightItem("⚠", "1 destructive operation — DROP legacy_invites (archived ✓)", "warn"),
    PreflightItem("✗", "1 unresolved conflict — idx_users_email (will be skipped)", "err"),
    PreflightItem("ℹ", "rollback script generated and tested in shadow db", "info"),
)


@dataclass(frozen=True)
class ApplyStep:
    id: str
    label: str
    kind: str  # ok / warn


APPLY_STEPS: tuple[ApplyStep, ...] = (
    ApplyStep("c01", "CREATE TYPE plan_tier_enum", "ok"),
    ApplyStep("c02", "CREATE TYPE task_priority", "ok"),
    ApplyStep("c03", "ALTER TYPE subscription_status +'paused'", "ok"),
    ApplyStep("c04", "ALTER TABLE tenants (+plan_tier, +trial_ends_at)", "ok"),
    ApplyStep("c05", "ALTER TABLE users (email→citext, +mfa, -legacy)", "warn"),
    ApplyStep("c06", "ALTER TABLE workspaces (storage type)", "ok"),
    ApplyStep("c07", "ALTER TABLE projects (+archived_at)", "ok"),
    ApplyStep("c08", "ALTER TABLE tasks (+parent_task_id, priority)", "ok"),
    ApplyStep("c09", "CREATE TABLE task_subscriptions", "ok"),
    ApplyStep("c11", "archive + DROP legacy_invites", "warn"),
    ApplyStep("c12", "CREATE INDEX idx_tasks_due_date (concurrent)", "ok"),
    ApplyStep("c13", "CREATE INDEX idx_tasks_workspace_status (concurrent)", "ok"),
    ApplyStep("c14", "CREATE INDEX idx_users_email_lower (concurrent)", "ok"),
    ApplyStep("c19", "REPLACE FUNCTION compute_workspace_usage", "ok"),
    ApplyStep("c21", "CREATE TRIGGER trg_audit_users_changes", "ok"),
    ApplyStep("c22", "CREATE TABLE billing.usage_records", "ok"),
    ApplyStep("c25", "CREATE TABLE analytics.events_daily_rollup", "ok"),
    ApplyStep("—", "COMMIT;", "ok"),
)

# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HistoryEntry:
    id: str
    when: str
    src: str
    tgt: str
    author: str
    status: str  # applied / applied (dry) / pending / failed / rolled-back
    changes: int
    duration: str
    dryrun: bool = False


HISTORY: tuple[HistoryEntry, ...] = (
    HistoryEntry(
        "h-241",
        "2026-05-23 14:09:12",
        "acme_prod",
        "acme_staging",
        "minh.le",
        "pending",
        25,
        "—",
        True,
    ),
    HistoryEntry(
        "h-240",
        "2026-05-22 10:31:45",
        "acme_prod",
        "acme_staging",
        "minh.le",
        "applied",
        18,
        "01:42",
    ),
    HistoryEntry(
        "h-239",
        "2026-05-21 16:55:02",
        "acme_prod",
        "acme_dev",
        "thuy.nguyen",
        "applied",
        23,
        "03:08",
    ),
    HistoryEntry(
        "h-238",
        "2026-05-20 09:14:33",
        "acme_prod",
        "acme_staging",
        "thuy.nguyen",
        "rolled-back",
        12,
        "00:51",
    ),
    HistoryEntry(
        "h-237", "2026-05-19 22:08:11", "acme_prod", "acme_dev", "minh.le", "failed", 9, "00:12"
    ),
    HistoryEntry(
        "h-236",
        "2026-05-18 11:42:50",
        "acme_prod",
        "acme_staging",
        "duc.tran",
        "applied",
        31,
        "04:27",
    ),
    HistoryEntry(
        "h-235",
        "2026-05-17 08:09:18",
        "acme_prod",
        "acme_staging",
        "duc.tran",
        "applied",
        6,
        "00:33",
    ),
    HistoryEntry(
        "h-234", "2026-05-15 19:23:04", "acme_prod", "acme_dev", "minh.le", "applied", 14, "01:11"
    ),
    HistoryEntry(
        "h-233",
        "2026-05-14 13:50:22",
        "acme_prod",
        "acme_staging",
        "thuy.nguyen",
        "applied (dry)",
        19,
        "00:08",
        True,
    ),
)

# --------------------------------------------------------------------------- #
# AI suggestions
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AiSuggestion:
    target: str
    change: str
    title: str
    body: tuple[str, ...]
    severity: str  # medium / high
    accept_label: str
    patch: str = ""


_EMAIL_PATCH = """-- phased email type change
ALTER TABLE public.users ADD COLUMN email_new citext;

UPDATE public.users SET email_new = email::citext
 WHERE id BETWEEN $1 AND $2;   -- batched, repeatable

CREATE UNIQUE INDEX CONCURRENTLY users_email_new_unq
  ON public.users(email_new);

BEGIN;
  ALTER TABLE public.users DROP CONSTRAINT users_email_key;
  ALTER TABLE public.users DROP COLUMN email;
  ALTER TABLE public.users RENAME COLUMN email_new TO email;
  ALTER TABLE public.users RENAME CONSTRAINT users_email_new_unq TO users_email_key;
COMMIT;"""

AI_SUGGESTIONS: tuple[AiSuggestion, ...] = (
    AiSuggestion(
        target="public.users",
        change="c05",
        title="Two-phase email type change to avoid 14-min lock",
        body=(
            "The current plan widens public.users.email from varchar(255) to citext in a",
            "single ALTER COLUMN, which rewrites the table under ACCESS EXCLUSIVE lock",
            "(est. ~14m on 38M rows).",
            "",
            "Suggested phased approach:",
            "  1. ADD COLUMN email_new citext;",
            "  2. backfill with batched UPDATE (no long lock);",
            "  3. swap column under a brief AccessExclusive (~2s);",
            "  4. recreate UNIQUE constraint.",
        ),
        severity="medium",
        accept_label="Apply 4-step refactor",
        patch=_EMAIL_PATCH,
    ),
    AiSuggestion(
        target="public.legacy_invites",
        change="c11",
        title="Archive before drop",
        body=(
            "DROP TABLE public.legacy_invites destroys 4,217 rows.",
            "Suggest CREATE TABLE legacy.invites_archive AS TABLE public.legacy_invites;",
            "before DROP.",
        ),
        severity="high",
        accept_label="Insert archive step",
        patch=(
            "CREATE TABLE legacy.invites_archive AS TABLE public.legacy_invites;\n"
            "DROP TABLE public.legacy_invites;"
        ),
    ),
    AiSuggestion(
        target="public.idx_users_email",
        change="c17",
        title="Resolve index name collision",
        body=(
            "Target has a partial functional index with the same name.",
            "Option A — keep source: DROP target index, CREATE source's UNIQUE on (email).",
            "Option B — keep target: rename source to idx_users_email_unique.",
            "Option C — keep both: rename source's index and skip drop.",
        ),
        severity="high",
        accept_label="Apply option A",
        patch=(
            "DROP INDEX IF EXISTS public.idx_users_email;\n"
            "CREATE UNIQUE INDEX idx_users_email ON public.users (email);"
        ),
    ),
)


def ai_for(target: str) -> AiSuggestion:
    """Return the AI suggestion for an object, defaulting to the first."""
    for s in AI_SUGGESTIONS:
        if s.target == target:
            return s
    return AI_SUGGESTIONS[0]


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SettingField:
    label: str
    value: str = ""
    toggle: bool = False
    on: bool = False
    help: str = ""


@dataclass(frozen=True)
class SettingGroup:
    title: str
    fields: tuple[SettingField, ...]
    badge: str = ""


SETTINGS_GROUPS: tuple[SettingGroup, ...] = (
    SettingGroup(
        "Appearance",
        (
            SettingField("Font family", "JetBrains Mono", help="must be monospaced"),
            SettingField("Font size", "13.5px"),
            SettingField("Line spacing", "1.55"),
            SettingField("Show line numbers", toggle=True, on=True, help="in diff + migration"),
            SettingField("Compact tree", toggle=True, on=False, help="comfy → compact"),
        ),
    ),
    SettingGroup(
        "Editor & keymap",
        (
            SettingField("Keymap", "vim", help="vim · emacs · default"),
            SettingField("Leader key", "<space>"),
            SettingField("Command timeout", "30s", help="for : commands"),
            SettingField("Confirm on apply", toggle=True, on=True),
            SettingField("Confirm on drop", toggle=True, on=True),
            SettingField("Mouse support", toggle=True, on=True),
            SettingField("Auto-save profile", toggle=True, on=False),
        ),
    ),
    SettingGroup(
        "Diff & migration",
        (
            SettingField("Default diff mode", "side-by-side", help="side · inline · tree"),
            SettingField("Wrap long lines", toggle=True, on=False),
            SettingField("Auto-generate rollback", toggle=True, on=True),
            SettingField("Run rollback in shadow db", toggle=True, on=True),
            SettingField("Auto-archive before DROP", toggle=True, on=True),
            SettingField("Concurrent indexes", toggle=True, on=True),
            SettingField("Wrap migration in transaction", toggle=True, on=True),
            SettingField("Statement timeout", "30min"),
            SettingField("Lock timeout", "5s"),
        ),
    ),
    SettingGroup(
        "AI & telemetry",
        (
            SettingField("AI suggestions", toggle=True, on=True, help="reviews before apply"),
            SettingField("AI provider", "anthropic · claude-haiku-4-5"),
            SettingField("Allow schema upload", toggle=True, on=False, help="names + types only"),
            SettingField("Auto-apply low-risk hints", toggle=True, on=False),
            SettingField("Anonymous error reports", toggle=True, on=True),
            SettingField("Update channel", "stable", help="stable · beta · nightly"),
        ),
        badge="opt-in",
    ),
)

CONFIG_TOML = """# ~/.config/pgschemadiff/config.toml

[ui]
theme        = "mocha"           # mocha | latte
font_family  = "JetBrains Mono"
font_size    = 13.5
keymap       = "vim"
leader       = "<space>"

[diff]
default_view       = "side"      # side | inline | tree
auto_rollback      = true
verify_rollback    = true
wrap_lines         = false

[apply]
transactional      = true
statement_timeout  = "30min"
lock_timeout       = "5s"
concurrent_indexes = true
auto_archive_drop  = true

[ai]
enabled    = true
provider   = "anthropic"
model      = "claude-haiku-4-5"
upload_schema_only = true
"""

# Dependency graph (Overview) — static ASCII art from the design prototype.
DEP_GRAPH = """\
┌───────────────────────┐   ┌──────────────────────┐   ┌─────────────────────┐
│ c01 CREATE plan_tier  │   │ c02 CREATE task_pri  │   │ c03 ALTER subscr_st │
│       ⟶ enum          │   │       ⟶ enum         │   │     +'paused'       │
└─────────┬─────────────┘   └──────────┬───────────┘   └──────────┬──────────┘
          │                            │                          │
          ▼                            ▼                          ▼
┌───────────────────────┐   ┌──────────────────────┐   ┌─────────────────────┐
│ c04 ALTER tenants     │   │ c08 ALTER tasks      │   │ c23 ALTER subscr.   │
│  +plan_tier           │   │  +parent_task_id     │   │  +pause_until       │
│  +trial_ends_at       │   │  priority → enum     │   └─────────────────────┘
└───────────────────────┘   └──────────┬───────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              ▼                         ▼                          ▼
┌───────────────────────┐   ┌──────────────────────┐   ┌─────────────────────┐
│ c09 task_subscript.   │   │ c12 idx tasks_due    │   │ c13 idx ws_status   │
└───────────┬───────────┘   └──────────────────────┘   └─────────────────────┘
            │
            ▼
┌───────────────────────┐
│ c21 trg_audit_users   │ ◀── depends on c05 (users)
└───────────────────────┘
"""
