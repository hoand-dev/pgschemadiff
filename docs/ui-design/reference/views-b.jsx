// Views part 2: Migration, Apply, History, Settings, AI modal

const { MIGRATION_LINES, HISTORY: HISTORY_D } = window.DATA;

// ─── Migration script view ─────────────────────────────────────────────────
function MigrationView({ onApply, onAi }) {
  const [showRollback, setShowRollback] = useState(false);
  const [transactional, setTransactional] = useState(true);
  const [concurrent, setConcurrent] = useState(true);
  const [include, setInclude] = useState({ DDL: true, conflicts: false, data: false });

  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
      <div className="section-h">
        <h2>Migration script</h2>
        <span className="crumb">generated · 97 lines · 25 changes · 1 conflict skipped</span>
        <div className="right">
          <button className="btn">save .sql</button>
          <button className="btn" onClick={() => onAi && onAi()}><span className="kb">⌘a</span>AI review</button>
          <button className="btn">dry-run</button>
          <button className="btn primary" onClick={onApply}><span className="kb">ga</span>apply →</button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 280px', gap: 12, flex: 1, minHeight: 0 }}>
        <div className="panel" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div className="panel-title">
            <span>{showRollback ? 'rollback.sql' : 'migration_20260523_142208.sql'}</span>
            <div style={{ display: 'flex', gap: 6, fontSize: 11, textTransform: 'none', letterSpacing: 0 }}>
              <span onClick={() => setShowRollback(false)} style={{
                cursor: 'pointer', padding: '0 6px',
                background: !showRollback ? 'var(--mauve)' : 'var(--surface0)',
                color: !showRollback ? 'var(--base)' : 'var(--overlay1)',
                borderRadius: 2,
              }}>forward</span>
              <span onClick={() => setShowRollback(true)} style={{
                cursor: 'pointer', padding: '0 6px',
                background: showRollback ? 'var(--mauve)' : 'var(--surface0)',
                color: showRollback ? 'var(--base)' : 'var(--overlay1)',
                borderRadius: 2,
              }}>rollback</span>
            </div>
          </div>
          <div style={{ flex: 1, overflow: 'auto', background: 'var(--crust)' }}>
            {showRollback ? <RollbackScript /> : <ForwardScript />}
          </div>
          <div style={{
            padding: '4px 12px',
            background: 'var(--mantle)',
            borderTop: '1px solid var(--surface0)',
            fontSize: 11,
            color: 'var(--overlay1)',
            display: 'flex',
            gap: 14,
          }}>
            <span>line 1 / 97</span>
            <span>col 1</span>
            <span className="dim">sql · utf-8 · unix · 4 spaces</span>
            <span style={{ marginLeft: 'auto' }} className="dim">checksum sha256:b71f…ce4a</span>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, minHeight: 0, overflow: 'auto' }}>
          <div className="panel">
            <div className="panel-title"><span>Execution plan</span></div>
            <div style={{ padding: 10, display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
              <SettingRow label="transactional" on={transactional} setOn={setTransactional} hint="wrap in BEGIN; … COMMIT;" />
              <SettingRow label="concurrent indexes" on={concurrent} setOn={setConcurrent} hint="CREATE INDEX CONCURRENTLY" />
              <SettingRow label="include DDL" on={include.DDL} setOn={(v) => setInclude({ ...include, DDL: v })} hint="schema + functions + triggers" />
              <SettingRow label="include conflicts" on={include.conflicts} setOn={(v) => setInclude({ ...include, conflicts: v })} hint="leave commented out by default" />
              <SettingRow label="include data" on={include.data} setOn={(v) => setInclude({ ...include, data: v })} hint="seed + lookup tables" />
              <div className="note warn" style={{ marginTop: 6 }}>
                <span className="warn">⚠</span> public.users — ALTER COLUMN TYPE locks table (~14m est).
              </div>
              <div className="note err">
                <span className="err">✗</span> public.legacy_invites — DROP destroys 4,217 rows.
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-title"><span>Lock estimate</span><span className="dim" style={{ fontSize: 11 }}>pg_locks · row counts</span></div>
            <table className="tui-table">
              <thead><tr><th>Step</th><th>Lock</th><th>Rows</th><th>Est.</th></tr></thead>
              <tbody>
                <tr><td>c04 tenants +cols</td><td className="ok">ACCESS SHARE</td><td>284</td><td>&lt; 1s</td></tr>
                <tr><td className="warn">c05 users email</td><td className="warn">ACCESS EXCL</td><td>38M</td><td>~14m</td></tr>
                <tr><td className="warn">c06 workspaces type</td><td className="warn">ACCESS EXCL</td><td>1.2M</td><td>~38s</td></tr>
                <tr><td>c08 tasks</td><td>SHARE UPD EXCL</td><td>92M</td><td>~2m</td></tr>
                <tr><td>c12-c16 indexes</td><td className="ok">SHARE UPD EXCL</td><td>—</td><td>~9m (concurrent)</td></tr>
                <tr><td className="err">c11 DROP legacy</td><td className="err">ACCESS EXCL</td><td>4217</td><td>&lt; 1s</td></tr>
              </tbody>
            </table>
          </div>

          <div className="panel">
            <div className="panel-title"><span>Stats</span></div>
            <div style={{ padding: 10, fontSize: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
              <div><span className="muted">lines</span><div style={{ fontSize: 16, color: 'var(--text)' }}>97</div></div>
              <div><span className="muted">size</span><div style={{ fontSize: 16, color: 'var(--text)' }}>4.7 KB</div></div>
              <div><span className="muted">est. duration</span><div style={{ fontSize: 16, color: 'var(--yellow)' }}>~26 min</div></div>
              <div><span className="muted">downtime</span><div style={{ fontSize: 16, color: 'var(--red)' }}>~15 min</div></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function SettingRow({ label, on, setOn, hint }) {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      <label className={`toggle ${on ? 'on' : ''}`} onClick={() => setOn(!on)}>
        <span className="sw"></span>{label}
      </label>
      <span className="dim" style={{ fontSize: 11, marginLeft: 'auto', textAlign: 'right' }}>{hint}</span>
    </div>
  );
}

function ForwardScript() {
  return (
    <div style={{ padding: '6px 0' }}>
      {MIGRATION_LINES.map((l, i) => {
        let cls = '';
        let sg = ' ';
        if (l.add) { cls = 'add'; sg = '+'; }
        else if (l.del) { cls = 'del'; sg = '−'; }
        else if (l.mod) { cls = 'mod'; sg = '~'; }
        else if (l.com) { cls = ''; sg = ' '; }
        else if (l.warn) { cls = 'mod'; sg = '!'; }
        else if (l.err) { cls = 'del'; sg = '!'; }
        else if (l.conflict) { cls = ''; sg = '!'; }
        else { sg = ' '; }
        return (
          <div key={i} className={`diff-line ${cls}`}>
            <span className="ln">{l.ln}</span>
            <span className="sg" style={
              l.conflict ? { color: 'var(--red)' }
              : l.err ? { color: 'var(--red)' }
              : l.warn ? { color: 'var(--yellow)' }
              : {}
            }>{sg}</span>
            <span className="ct sql" dangerouslySetInnerHTML={{ __html: hl(l.t) }} style={
              l.conflict ? { color: 'var(--overlay1)', fontStyle: 'italic' } : {}
            } />
          </div>
        );
      })}
    </div>
  );
}

function RollbackScript() {
  const lines = [
    '-- rollback for migration_20260523_142208.sql',
    '-- generated automatically · tested against snapshot db-stage@2026-05-23',
    '',
    'BEGIN;',
    'SET lock_timeout = \'5s\';',
    '',
    '-- restore legacy_invites from archive',
    'CREATE TABLE public.legacy_invites AS TABLE legacy.invites_archive;',
    '',
    '-- restore comments.legacy_html (data was archived to public.comments_legacy_html_bak)',
    'ALTER TABLE public.comments ADD COLUMN legacy_html text;',
    'UPDATE public.comments c',
    '   SET legacy_html = b.legacy_html',
    '  FROM public.comments_legacy_html_bak b WHERE b.id = c.id;',
    '',
    '-- drop additions (reverse topological order)',
    'DROP TRIGGER trg_audit_users_changes ON public.users;',
    'DROP TABLE public.task_subscriptions;',
    'DROP INDEX CONCURRENTLY idx_comments_task_id;',
    'DROP INDEX CONCURRENTLY idx_audit_logs_actor_created;',
    'DROP INDEX CONCURRENTLY idx_users_email_lower;',
    'DROP INDEX CONCURRENTLY idx_tasks_workspace_status;',
    'DROP INDEX CONCURRENTLY idx_tasks_due_date;',
    '',
    'ALTER TABLE public.users',
    '  ALTER COLUMN email TYPE varchar(255) USING email::varchar(255),',
    '  DROP COLUMN mfa_secret,',
    '  ADD COLUMN legacy_username varchar(64);',
    '',
    'ALTER TABLE public.tenants',
    '  DROP COLUMN trial_ends_at,',
    '  DROP COLUMN plan_tier;',
    '',
    'DROP TYPE public.task_priority;',
    'DROP TYPE public.plan_tier_enum;',
    '',
    'COMMIT;',
  ];
  return (
    <div style={{ padding: '6px 0' }}>
      {lines.map((t, i) => (
        <div key={i} className="diff-line">
          <span className="ln">{i + 1}</span>
          <span className="sg"> </span>
          <span className="ct sql" dangerouslySetInnerHTML={{ __html: hl(t) }} />
        </div>
      ))}
    </div>
  );
}

// ─── Apply view ────────────────────────────────────────────────────────────
function ApplyView({ onDone }) {
  const [phase, setPhase] = useState('confirm'); // confirm | running | success | failed
  const [progress, setProgress] = useState(0);
  const [step, setStep] = useState(0);
  const [log, setLog] = useState([]);
  const [dryrun, setDryrun] = useState(true);
  const [aborted, setAborted] = useState(false);
  const timerRef = useRef(null);

  const STEPS = [
    { id: 'c01', label: 'CREATE TYPE plan_tier_enum', ms: 320, kind: 'ok' },
    { id: 'c02', label: 'CREATE TYPE task_priority', ms: 220, kind: 'ok' },
    { id: 'c03', label: "ALTER TYPE subscription_status +'paused'", ms: 280, kind: 'ok' },
    { id: 'c04', label: 'ALTER TABLE tenants (+plan_tier, +trial_ends_at)', ms: 410, kind: 'ok' },
    { id: 'c05', label: 'ALTER TABLE users (email→citext, +mfa, -legacy)', ms: 900, kind: 'warn' },
    { id: 'c06', label: 'ALTER TABLE workspaces (storage type)', ms: 460, kind: 'ok' },
    { id: 'c07', label: 'ALTER TABLE projects (+archived_at)', ms: 230, kind: 'ok' },
    { id: 'c08', label: 'ALTER TABLE tasks (+parent_task_id, priority)', ms: 720, kind: 'ok' },
    { id: 'c09', label: 'CREATE TABLE task_subscriptions', ms: 280, kind: 'ok' },
    { id: 'c11', label: 'archive + DROP legacy_invites', ms: 380, kind: 'warn' },
    { id: 'c12', label: 'CREATE INDEX idx_tasks_due_date (concurrent)', ms: 540, kind: 'ok' },
    { id: 'c13', label: 'CREATE INDEX idx_tasks_workspace_status (concurrent)', ms: 600, kind: 'ok' },
    { id: 'c14', label: 'CREATE INDEX idx_users_email_lower (concurrent)', ms: 880, kind: 'ok' },
    { id: 'c19', label: 'REPLACE FUNCTION compute_workspace_usage', ms: 200, kind: 'ok' },
    { id: 'c21', label: 'CREATE TRIGGER trg_audit_users_changes', ms: 180, kind: 'ok' },
    { id: 'c22', label: 'CREATE TABLE billing.usage_records', ms: 250, kind: 'ok' },
    { id: 'c25', label: 'CREATE TABLE analytics.events_daily_rollup', ms: 350, kind: 'ok' },
    { id: '—', label: 'COMMIT;', ms: 220, kind: 'ok' },
  ];

  const start = () => {
    setPhase('running');
    setProgress(0);
    setStep(0);
    setLog([
      { ts: '14:22:08', lvl: 'info', t: `connecting to ${dryrun ? 'dry-run sandbox' : 'acme_staging'} …` },
      { ts: '14:22:08', lvl: 'ok',   t: `connected (postgres 16.2, ssl verify-full, latency 9ms)` },
      { ts: '14:22:08', lvl: 'info', t: `BEGIN; SET lock_timeout = '5s'; SET statement_timeout = '30min';` },
    ]);
    runStep(0);
  };

  const runStep = (i) => {
    if (i >= STEPS.length) {
      setLog((l) => [...l, { ts: stamp(), lvl: 'ok', t: '✓ migration complete · 18 steps · 0 errors' }]);
      setPhase('success');
      setProgress(100);
      return;
    }
    setStep(i);
    setLog((l) => [...l, { ts: stamp(), lvl: 'info', t: `[${STEPS[i].id}] ${STEPS[i].label} …` }]);
    timerRef.current = setTimeout(() => {
      setLog((l) => [...l, {
        ts: stamp(),
        lvl: STEPS[i].kind,
        t: STEPS[i].kind === 'warn'
          ? `  ↳ done in ${(STEPS[i].ms / 1000).toFixed(2)}s · warning: brief AccessExclusive lock`
          : `  ↳ done in ${(STEPS[i].ms / 1000).toFixed(2)}s · 0 rows affected`,
      }]);
      setProgress(Math.round(((i + 1) / STEPS.length) * 100));
      runStep(i + 1);
    }, Math.max(120, STEPS[i].ms / 3));
  };

  const stamp = () => {
    const d = new Date();
    return d.toTimeString().slice(0, 8);
  };

  const abort = () => {
    clearTimeout(timerRef.current);
    setAborted(true);
    setPhase('failed');
    setLog((l) => [...l, { ts: stamp(), lvl: 'err', t: '✗ aborted by user · ROLLBACK; ✓ done' }]);
  };

  useEffect(() => () => clearTimeout(timerRef.current), []);

  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
      <div className="section-h">
        <h2>Apply migration</h2>
        <span className="crumb">→ acme_staging · 25 changes · est ~26 min</span>
        <div className="right">
          {phase === 'confirm' && (
            <>
              <label className={`toggle ${dryrun ? 'on' : ''}`} onClick={() => setDryrun(!dryrun)} style={{ color: 'var(--text)', fontSize: 12 }}>
                <span className="sw"></span>dry-run
              </label>
              <button className="btn">save snapshot</button>
              <button className="btn primary" onClick={start}>
                <span className="kb">⏎</span>{dryrun ? 'run dry-run' : 'apply now'}
              </button>
            </>
          )}
          {phase === 'running' && (
            <>
              <span className="chip warn">running · step {step + 1}/{STEPS.length}</span>
              <button className="btn danger" onClick={abort}><span className="kb">⌘.</span>abort & rollback</button>
            </>
          )}
          {phase === 'success' && (
            <>
              <span className="chip" style={{ background: 'rgba(166,227,161,0.15)', color: 'var(--green)' }}>✓ complete</span>
              <button className="btn">view in history</button>
              <button className="btn primary" onClick={() => { setPhase('confirm'); setProgress(0); setStep(0); setLog([]); }}>new run</button>
            </>
          )}
          {phase === 'failed' && (
            <>
              <span className="chip del">✗ failed / aborted</span>
              <button className="btn" onClick={() => { setPhase('confirm'); setProgress(0); setLog([]); setAborted(false); }}>retry</button>
            </>
          )}
        </div>
      </div>

      {phase === 'confirm' && (
        <div className="panel">
          <div className="panel-title"><span>Pre-flight checklist</span><span className="chip ai">AI verified</span></div>
          <div style={{ padding: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 13 }}>
            {[
              ['✓', 'connected to target (ssl: verify-full, role: pgsd_migrator)', 'ok'],
              ['✓', 'target db responsive — latency 9ms', 'ok'],
              ['✓', 'pre-flight snapshot taken — db-stage_20260523_142208.dump', 'ok'],
              ['✓', 'no active long-running transactions on target', 'ok'],
              ['⚠', 'estimated downtime ~15m (email type rewrite)', 'warn'],
              ['⚠', '1 destructive operation — DROP legacy_invites (archived ✓)', 'warn'],
              ['✗', '1 unresolved conflict — idx_users_email (will be skipped)', 'err'],
              ['ℹ', 'rollback script generated and tested in shadow db', 'info'],
            ].map((r, i) => (
              <div key={i} style={{
                display: 'flex', gap: 10, padding: '6px 10px',
                background: 'var(--mantle)',
                borderLeft: `2px solid var(--${r[2] === 'ok' ? 'green' : r[2] === 'warn' ? 'yellow' : r[2] === 'err' ? 'red' : 'blue'})`,
              }}>
                <span style={{ color: `var(--${r[2] === 'ok' ? 'green' : r[2] === 'warn' ? 'yellow' : r[2] === 'err' ? 'red' : 'blue'})`, fontWeight: 700 }}>{r[0]}</span>
                <span>{r[1]}</span>
              </div>
            ))}
          </div>
          <div style={{
            padding: '10px 12px', borderTop: '1px solid var(--surface0)', background: 'var(--mantle)',
            display: 'flex', gap: 12, fontSize: 12.5, color: 'var(--subtext1)',
          }}>
            <span className="dim">command preview:</span>
            <span style={{ color: 'var(--mauve)', fontWeight: 600 }}>
              pgschemadiff apply --target acme_staging --plan migration_20260523_142208.sql{dryrun ? ' --dry-run' : ''}{' --auto-rollback-on-error'}
            </span>
          </div>
        </div>
      )}

      {phase !== 'confirm' && (
        <>
          <div className="panel">
            <div className="panel-title">
              <span>Progress · {progress}%</span>
              <span className="dim" style={{ fontSize: 11 }}>{step + 1} / {STEPS.length} steps</span>
            </div>
            <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div className="progress"><div style={{ width: `${progress}%` }} /></div>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {STEPS.map((s, i) => (
                  <div key={i} title={s.label} style={{
                    width: 14, height: 14, borderRadius: 2,
                    background: i < step ? 'var(--green)'
                              : i === step ? 'var(--mauve)'
                              : 'var(--surface1)',
                    border: i === step ? '1px solid var(--lavender)' : 'none',
                  }} />
                ))}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, fontSize: 11 }}>
                <Mini label="elapsed" v={`${Math.round(progress * 0.26)}s`} />
                <Mini label="remaining" v={`~${26 - Math.round(progress * 0.26)}s`} />
                <Mini label="locks" v="3" />
                <Mini label="rows touched" v="38M+" />
                <Mini label="warnings" v={String(log.filter((l) => l.lvl === 'warn').length)} />
              </div>
            </div>
          </div>

          <div className="panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div className="panel-title">
              <span>tail -f migration.log</span>
              <span className="dim" style={{ fontSize: 11 }}>auto-scroll · level: debug</span>
            </div>
            <div className="log" style={{ flex: 1, border: 'none', borderRadius: 0 }}>
              {log.map((l, i) => (
                <div key={i}>
                  <span className="ts">{l.ts}</span>{' '}
                  <span className={l.lvl}>{
                    l.lvl === 'ok' ? '[ ok ]'
                    : l.lvl === 'warn' ? '[warn]'
                    : l.lvl === 'err' ? '[ err]'
                    : '[info]'
                  }</span>{' '}
                  {l.t}
                </div>
              ))}
              {phase === 'running' && <div className="dim">▍ <span className="info">step {STEPS[step]?.id}: {STEPS[step]?.label}</span></div>}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Mini({ label, v }) {
  return (
    <div style={{ background: 'var(--mantle)', border: '1px solid var(--surface0)', padding: '4px 8px', borderRadius: 2 }}>
      <div className="muted" style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 14, color: 'var(--text)' }}>{v}</div>
    </div>
  );
}

// ─── History view ─────────────────────────────────────────────────────────
function HistoryView() {
  const [sel, setSel] = useState(HISTORY_D[1].id);
  const row = HISTORY_D.find((h) => h.id === sel);

  const StatusChip = ({ s }) => {
    if (s === 'applied') return <span className="chip" style={{ background: 'rgba(166,227,161,0.14)', color: 'var(--green)' }}>● applied</span>;
    if (s === 'applied (dry)') return <span className="chip info">○ dry-run</span>;
    if (s === 'pending') return <span className="chip warn">◐ pending</span>;
    if (s === 'failed') return <span className="chip del">✗ failed</span>;
    if (s === 'rolled-back') return <span className="chip" style={{ background: 'rgba(203,166,247,0.12)', color: 'var(--mauve)' }}>↶ rolled back</span>;
    return <span className="chip">{s}</span>;
  };

  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
      <div className="section-h">
        <h2>History</h2>
        <span className="crumb">~/.pgsd/state/runs.db <span className="sep">·</span> {HISTORY_D.length} runs</span>
        <div className="right">
          <button className="btn">export csv</button>
          <button className="btn">prune &gt; 30d</button>
        </div>
      </div>

      <div className="panel">
        <div className="panel-title">
          <span>Runs</span>
          <div style={{ display: 'flex', gap: 8, fontSize: 11, textTransform: 'none', letterSpacing: 0 }}>
            <input placeholder="filter author / target / status…" style={{
              background: 'var(--crust)', border: '1px solid var(--surface1)',
              borderRadius: 2, color: 'var(--text)', font: 'inherit', fontSize: 11.5,
              padding: '2px 8px', outline: 'none', width: 240,
            }} />
          </div>
        </div>
        <table className="tui-table">
          <thead>
            <tr>
              <th style={{ width: 64 }}>id</th>
              <th style={{ width: 160 }}>when</th>
              <th>source → target</th>
              <th style={{ width: 110 }}>author</th>
              <th style={{ width: 70 }}>changes</th>
              <th style={{ width: 80 }}>duration</th>
              <th style={{ width: 130 }}>status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {HISTORY_D.map((h) => (
              <tr key={h.id} className={sel === h.id ? 'sel' : ''} onClick={() => setSel(h.id)} style={{ cursor: 'pointer' }}>
                <td className="dim">{h.id}</td>
                <td className="muted">{h.when}</td>
                <td><span className="info">{h.from}</span> <span className="dim">→</span> <span className="warn">{h.to}</span></td>
                <td>{h.author}</td>
                <td className="dim">{h.changes}</td>
                <td className="dim">{h.duration}</td>
                <td><StatusChip s={h.status} /></td>
                <td className="dim" style={{ fontSize: 11 }}>
                  {h.status === 'applied' && <span className="chip" style={{ marginRight: 4 }}>rollback</span>}
                  <span className="chip">view</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div className="panel">
          <div className="panel-title"><span>Run detail · {row.id}</span><StatusChip s={row.status} /></div>
          <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12.5 }}>
            <Row k="when" v={row.when} />
            <Row k="source" v={row.from} accent="var(--blue)" />
            <Row k="target" v={row.to} accent="var(--peach)" />
            <Row k="author" v={row.author} />
            <Row k="changes" v={`${row.changes} (4 add · 6 mod · 2 del · 1 conflict)`} />
            <Row k="duration" v={row.duration} />
            <Row k="checksum" v="sha256:b71f6a91…ce4a" />
            <Row k="snapshot" v={`db-stage_${row.id}.dump (8.2 GB)`} />
            <Row k="rollback" v={row.status === 'applied' ? 'available ✓' : '—'} accent={row.status === 'applied' ? 'var(--green)' : undefined} />
          </div>
        </div>
        <div className="panel" style={{ display: 'flex', flexDirection: 'column' }}>
          <div className="panel-title"><span>Timeline</span></div>
          <div className="log" style={{ flex: 1, border: 'none', borderRadius: 0, minHeight: 200 }}>
            <div><span className="ts">{row.when.slice(0, 10)} 10:31:42</span> <span className="info">[info]</span> pgsd v0.4.2 · invoked by {row.author}</div>
            <div><span className="ts">{row.when.slice(0, 10)} 10:31:43</span> <span className="info">[info]</span> diff {row.from} → {row.to} → {row.changes} changes</div>
            <div><span className="ts">{row.when.slice(0, 10)} 10:31:50</span> <span className="info">[info]</span> snapshot taken (8.2 GB)</div>
            <div><span className="ts">{row.when.slice(0, 10)} 10:31:51</span> <span className="info">[info]</span> BEGIN;</div>
            <div><span className="ts">{row.when.slice(0, 10)} 10:31:51</span> <span className="ok">[ ok ]</span> [c01] CREATE TYPE plan_tier_enum · 0.31s</div>
            <div><span className="ts">{row.when.slice(0, 10)} 10:31:52</span> <span className="ok">[ ok ]</span> [c04] ALTER TABLE tenants · 0.42s</div>
            <div><span className="ts">{row.when.slice(0, 10)} 10:33:10</span> <span className="warn">[warn]</span> [c05] users email rewrite ~78s ACCESS EXCLUSIVE</div>
            <div><span className="ts">{row.when.slice(0, 10)} 10:33:11</span> <span className="ok">[ ok ]</span> [c05] complete · 38,214,902 rows</div>
            <div><span className="ts">{row.when.slice(0, 10)} 10:33:14</span> <span className="ok">[ ok ]</span> CREATE INDEX CONCURRENTLY (×5) · 9m18s</div>
            <div><span className="ts">{row.when.slice(0, 10)} 10:33:24</span> <span className="ok">[ ok ]</span> COMMIT; · checksum verified</div>
            <div className="dim">— end of run —</div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Settings view ────────────────────────────────────────────────────────
function SettingsView({ theme, onTheme }) {
  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div className="section-h">
        <h2>Settings</h2>
        <span className="crumb">~/.config/pgschemadiff/config.toml</span>
        <div className="right">
          <button className="btn">reset to defaults</button>
          <button className="btn primary">save (⌘s)</button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div className="panel">
          <div className="panel-title"><span>Appearance</span></div>
          <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div className="field">
              <label>Theme</label>
              <div style={{ display: 'flex', gap: 8 }}>
                {['mocha', 'latte'].map((t) => (
                  <div key={t} onClick={() => onTheme(t)} style={{
                    flex: 1,
                    padding: 10,
                    border: `1px solid ${theme === t ? 'var(--mauve)' : 'var(--surface1)'}`,
                    borderRadius: 4,
                    cursor: 'pointer',
                    background: theme === t ? 'rgba(203,166,247,0.06)' : 'var(--crust)',
                  }}>
                    <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
                      {(t === 'mocha'
                        ? ['#1e1e2e', '#cba6f7', '#89b4fa', '#a6e3a1', '#f9e2af', '#f38ba8']
                        : ['#eff1f5', '#8839ef', '#1e66f5', '#40a02b', '#df8e1d', '#d20f39']
                      ).map((c, i) => <span key={i} style={{ width: 14, height: 14, background: c, borderRadius: 2 }} />)}
                    </div>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>Catppuccin {t === 'mocha' ? 'Mocha' : 'Latte'}</div>
                    <div className="dim" style={{ fontSize: 11 }}>{t === 'mocha' ? 'dark · default' : 'light'}</div>
                  </div>
                ))}
              </div>
            </div>
            <SettingsField label="Font family" value="JetBrains Mono" help="must be monospaced; Textual reflows on change" />
            <SettingsField label="Font size" value="13.5px" />
            <SettingsField label="Line spacing" value="1.55" />
            <SettingsField label="Show line numbers" toggle on help="in diff + migration panes" />
            <SettingsField label="Compact tree" toggle off help="density: comfy → compact" />
          </div>
        </div>

        <div className="panel">
          <div className="panel-title"><span>Editor & keymap</span></div>
          <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <SettingsField label="Keymap" value="vim" help="vim · emacs · default" />
            <SettingsField label="Leader key" value="<space>" />
            <SettingsField label="Command timeout" value="30s" help="for : commands like :diff" />
            <SettingsField label="Confirm on apply" toggle on />
            <SettingsField label="Confirm on drop" toggle on />
            <SettingsField label="Mouse support" toggle on help="Textual passes mouse events" />
            <SettingsField label="Auto-save profile" toggle off />
          </div>
        </div>

        <div className="panel">
          <div className="panel-title"><span>Diff & migration</span></div>
          <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <SettingsField label="Default diff mode" value="side-by-side" help="side · inline · tree" />
            <SettingsField label="Wrap long lines" toggle off />
            <SettingsField label="Auto-generate rollback" toggle on />
            <SettingsField label="Run rollback in shadow db" toggle on help="verify before saving" />
            <SettingsField label="Auto-archive before DROP" toggle on />
            <SettingsField label="Concurrent indexes" toggle on />
            <SettingsField label="Wrap migration in transaction" toggle on />
            <SettingsField label="Statement timeout" value="30min" />
            <SettingsField label="Lock timeout" value="5s" />
          </div>
        </div>

        <div className="panel">
          <div className="panel-title"><span>AI & telemetry</span><span className="chip ai">opt-in</span></div>
          <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <SettingsField label="AI suggestions" toggle on help="reviews migrations before apply" />
            <SettingsField label="AI provider" value="anthropic · claude-haiku-4-5" />
            <SettingsField label="Allow schema upload" toggle off help="only column names + types, no data" />
            <SettingsField label="Auto-apply low-risk hints" toggle off />
            <SettingsField label="Anonymous error reports" toggle on />
            <SettingsField label="Update channel" value="stable" help="stable · beta · nightly" />
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-title"><span>config.toml</span><span className="dim" style={{ fontSize: 11 }}>preview · read-only</span></div>
        <pre className="sql" style={{ padding: 12, margin: 0, fontSize: 12.5, color: 'var(--subtext1)' }}>{`# ~/.config/pgschemadiff/config.toml

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
`}</pre>
      </div>
    </div>
  );
}

function SettingsField({ label, value, toggle, on, off, help }) {
  const [v, setV] = useState(on);
  return (
    <div className="field" style={{ marginBottom: 0 }}>
      <label>{label}</label>
      {toggle ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <label className={`toggle ${v ? 'on' : ''}`} onClick={() => setV(!v)}>
            <span className="sw"></span>{v ? 'on' : 'off'}
          </label>
          {help && <span className="help" style={{ marginLeft: 'auto' }}>{help}</span>}
        </div>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            flex: 1,
            background: 'var(--crust)', border: '1px solid var(--surface1)',
            borderRadius: 2, padding: '4px 8px', fontSize: 12.5, color: 'var(--text)',
          }}>{value}</div>
          {help && <span className="help">{help}</span>}
        </div>
      )}
    </div>
  );
}

// ─── AI modal ──────────────────────────────────────────────────────────────
function AiModal({ suggestion, onClose }) {
  return (
    <Modal title={`AI suggestion · ${suggestion.target}`} onClose={onClose} width={680}
      footer={
        <>
          <button className="btn" onClick={onClose}>dismiss</button>
          <button className="btn">refine prompt</button>
          <button className="btn primary" onClick={onClose}>{suggestion.acceptLabel}</button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className="chip ai">✦ claude-haiku-4-5</span>
          <span className={`chip ${suggestion.severity === 'high' ? 'del' : 'warn'}`}>{suggestion.severity} risk</span>
          <span className="chip">change {suggestion.change}</span>
        </div>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{suggestion.title}</div>
        <div style={{ fontSize: 12.5, color: 'var(--subtext1)', whiteSpace: 'pre-wrap', background: 'var(--mantle)', padding: 10, borderRadius: 4 }}>
          {suggestion.body.join('\n')}
        </div>
        <div className="panel">
          <div className="panel-title"><span>Proposed patch</span></div>
          <pre className="sql" style={{ padding: 10, margin: 0, fontSize: 12 }}>
{`-- phased email type change
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
COMMIT;`}
          </pre>
        </div>
      </div>
    </Modal>
  );
}

Object.assign(window, { MigrationView, ApplyView, HistoryView, SettingsView, AiModal });
