// Views part 1: Connection, Overview, DiffDetail
// Relies on chrome.jsx + data.js being loaded first.

const { CONN: CONN_D, TREE: TREE_D, CHANGES: CHANGES_D, DIFFS: DIFFS_D, AI_SUGGESTIONS } = window.DATA;

// ─── Tiny SQL highlighter (regex, good enough for mock) ────────────────────
const SQL_KW = /\b(BEGIN|COMMIT|ROLLBACK|SET|CREATE|ALTER|DROP|TABLE|TYPE|FUNCTION|TRIGGER|INDEX|UNIQUE|PRIMARY|KEY|FOREIGN|REFERENCES|ON|DELETE|CASCADE|UPDATE|ADD|COLUMN|USING|RETURNS|LANGUAGE|AS|DECLARE|BEGIN|END|FOR|LOOP|SELECT|FROM|WHERE|AND|OR|NULL|NOT|DEFAULT|CONCURRENTLY|IF|EXISTS|VALUE|REPLACE|OR|VIEW|ENUM|CHECK|IN|CASE|WHEN|THEN|ELSE|EXECUTE|EACH|ROW|AFTER|BEFORE|INSERT|INTO|coalesce|sum|now|gen_random_uuid|lower)\b/gi;
const SQL_TYPE = /\b(uuid|text|citext|varchar|bigint|integer|smallint|numeric|jsonb|json|timestamptz|timestamp|bytea|bool|boolean|date|interval|plan_tier_enum|task_priority|subscription_status)\b/g;
const SQL_NUM = /\b\d+\b/g;
const SQL_STR = /'[^']*'/g;
const SQL_COM = /--.*$/gm;

function hl(line) {
  if (typeof line !== 'string') return '';
  // Order matters: strings & comments first to mask, but for mock we just chain replacements.
  let out = line.
  replace(/&/g, '&amp;').
  replace(/</g, '&lt;').
  replace(SQL_COM, (m) => `\u0001com\u0002${m}\u0001/com\u0002`).
  replace(SQL_STR, (m) => `\u0001str\u0002${m}\u0001/str\u0002`).
  replace(SQL_KW, (m) => `\u0001kw\u0002${m}\u0001/kw\u0002`).
  replace(SQL_TYPE, (m) => `\u0001ty\u0002${m}\u0001/ty\u0002`).
  replace(SQL_NUM, (m) => `\u0001num\u0002${m}\u0001/num\u0002`);
  out = out.
  replace(/\u0001com\u0002/g, '<span class="com">').replace(/\u0001\/com\u0002/g, '</span>').
  replace(/\u0001str\u0002/g, '<span class="str">').replace(/\u0001\/str\u0002/g, '</span>').
  replace(/\u0001kw\u0002/g, '<span class="kw">').replace(/\u0001\/kw\u0002/g, '</span>').
  replace(/\u0001ty\u0002/g, '<span class="ty">').replace(/\u0001\/ty\u0002/g, '</span>').
  replace(/\u0001num\u0002/g, '<span class="num">').replace(/\u0001\/num\u0002/g, '</span>');
  return out;
}

// ─── Connection view ───────────────────────────────────────────────────────
function ConnectionView({ conn, onEditConn }) {
  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div className="section-h">
        <h2>Connections</h2>
        <span className="crumb">pgschemadiff <span className="sep">›</span> connection</span>
        <div className="right">
          <button className="btn"><span className="kb">^t</span>test both</button>
          <button className="btn primary"><span className="kb">^s</span>save profile</button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 30px 1fr', gap: 10, alignItems: 'stretch' }}>
        <ConnectionCard role="source" color="blue" data={conn.source} />
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 22, color: 'var(--overlay2)' }}>→</div>
        <ConnectionCard role="target" color="peach" data={conn.target} />
      </div>

      <div className="panel">
        <div className="panel-title">
          <span>Compare options</span>
          <span className="dim" style={{ fontSize: 11 }}>--opts</span>
        </div>
        <div style={{ padding: 12, display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
          {[
          ['Include schemas', 'public, billing, analytics', 'multi'],
          ['Exclude tables', '__diesel_*, _pgsd_*', 'glob'],
          ['Include data', 'no (schema-only)', 'bool'],
          ['Owner roles', 'preserve from source', 'select'],
          ['Storage params', 'ignore', 'select'],
          ['Extensions', 'compare versions', 'select'],
          ['Generated cols', 'compare expressions', 'select'],
          ['Comments / COMMENT ON', 'sync', 'select'],
          ['Case sensitivity', 'sensitive', 'select']].
          map((row, i) =>
          <div key={i} className="field" style={{ marginBottom: 0 }}>
              <label>{row[0]}</label>
              <div style={{
              background: 'var(--crust)',
              border: '1px solid var(--surface1)',
              borderRadius: 2,
              padding: '4px 8px',
              fontSize: 12,
              color: 'var(--text)',
              display: 'flex',
              alignItems: 'center',
              gap: 6
            }}>
                <span style={{ flex: 1 }}>{row[1]}</span>
                <span className="dim" style={{ fontSize: 10 }}>{row[2]}</span>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel-title">
          <span>Saved profiles</span>
          <span className="dim" style={{ fontSize: 11 }}>~/.config/pgschemadiff/profiles.toml</span>
        </div>
        <table className="tui-table">
          <thead>
            <tr><th>Name</th><th>Source → Target</th><th>Last used</th><th>Owner</th><th>Default</th><th></th></tr>
          </thead>
          <tbody>
            <tr className="sel"><td className="accent">acme · prod → staging</td><td>acme_prod → acme_staging</td><td>just now</td><td>minh.le</td><td className="ok">✓</td><td className="dim">— current —</td></tr>
            <tr><td>acme · prod → dev</td><td>acme_prod → acme_dev</td><td>2 days ago</td><td>thuy.nguyen</td><td className="dim">·</td><td><span className="chip">switch</span></td></tr>
            <tr><td>billing · prod → analytics-mirror</td><td>billing_prod → analytics_mirror</td><td>5 days ago</td><td>duc.tran</td><td className="dim">·</td><td><span className="chip">switch</span></td></tr>
            <tr><td>local · dev → docker</td><td>local → pgsd_dev</td><td>1 week ago</td><td>minh.le</td><td className="dim">·</td><td><span className="chip">switch</span></td></tr>
          </tbody>
        </table>
      </div>
    </div>);

}

function ConnectionCard({ role, color, data }) {
  const accent = role === 'source' ? 'var(--blue)' : 'var(--peach)';
  return (
    <div className="panel" style={{ borderColor: 'var(--surface0)' }}>
      <div className="panel-title">
        <span style={{ color: accent }}>● {role.toUpperCase()}</span>
        <span className="accent">{data.label}</span>
      </div>
      <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12.5 }}>
        <Row k="connection" v={data.url} mono accent={accent} />
        <Row k="host" v={data.host} />
        <Row k="database" v={data.db} />
        <Row k="schemas" v={data.schema} />
        <Row k="role" v={data.role} />
        <Row k="ssl" v={data.ssl} accent="var(--green)" />
        <div style={{ height: 1, background: 'var(--surface0)', margin: '6px 0' }} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
          <Stat label="version" value={data.version.replace('PostgreSQL ', '')} sm />
          <Stat label="latency" value={data.latency} sm />
          <Stat label="tables" value={data.tables} sm />
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 6, fontSize: 11 }}>
          <span className="chip" style={{ background: 'rgba(166,227,161,0.12)', color: 'var(--green)' }}>● online</span>
          <span className="chip">size {data.size}</span>
          <span className="chip">{data.tables} tables</span>
          {role === 'target' && <span className="chip warn">2 extra tables vs source</span>}
        </div>
      </div>
    </div>);

}

function Row({ k, v, mono, accent }) {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
      <span className="muted" style={{ width: 86, fontSize: 11, letterSpacing: 0.4, textTransform: 'uppercase' }}>{k}</span>
      <span style={{ color: accent || 'var(--text)', fontFamily: 'inherit', wordBreak: 'break-all', flex: 1 }}>{v}</span>
    </div>);

}

function Stat({ label, value, sm, cls }) {
  return (
    <div className={`stat ${cls || ''}`} style={sm ? { padding: '8px 10px' } : {}}>
      <span className="label">{label}</span>
      <span className="value" style={sm ? { fontSize: 18 } : {}}>{value}</span>
    </div>);

}

// ─── Overview view ─────────────────────────────────────────────────────────
function OverviewView({ onPickChange, onAi }) {
  const [riskFilter, setRiskFilter] = useState('all');
  const [opFilter, setOpFilter] = useState('all');
  const [selectedIds, setSelectedIds] = useState(new Set(CHANGES_D.map((c) => c.id)));

  const summary = useMemo(() => {
    const s = { add: 0, mod: 0, del: 0, conflict: 0 };
    for (const c of CHANGES_D) {
      if (c.op === 'CREATE') s.add++;else
      if (c.op === 'ALTER' || c.op === 'REPLACE') s.mod++;else
      if (c.op === 'DROP') s.del++;else
      if (c.op === 'CONFLICT') s.conflict++;
    }
    return s;
  }, []);

  const rows = useMemo(() => CHANGES_D.filter((c) => {
    if (riskFilter !== 'all' && c.risk !== riskFilter) return false;
    if (opFilter !== 'all' && c.op !== opFilter) return false;
    return true;
  }), [riskFilter, opFilter]);

  const toggle = (id) => {
    const n = new Set(selectedIds);
    if (n.has(id)) n.delete(id);else n.add(id);
    setSelectedIds(n);
  };

  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div className="section-h">
        <h2>Overview</h2>
        <span className="crumb">acme_prod <span className="sep">→</span> acme_staging <span className="sep">·</span> generated 14:22:08</span>
        <div className="right">
          <button className="btn" onClick={onAi}><span className="kb">⌘a</span>AI review</button>
          <button className="btn">re-diff</button>
          <button className="btn primary"><span className="kb">ga</span>generate migration</button>
        </div>
      </div>

      <div className="stat-grid">
        <div className="stat add">
          <span className="label">added</span>
          <span className="value">+{summary.add}</span>
          <span className="delta">4 tables · 5 indexes · 2 types · 1 function · 1 trigger</span>
        </div>
        <div className="stat mod">
          <span className="label">modified</span>
          <span className="value">~{summary.mod}</span>
          <span className="delta">5 tables · 2 functions · 1 type</span>
        </div>
        <div className="stat del">
          <span className="label">dropped</span>
          <span className="value">-{summary.del}</span>
          <span className="delta">1 table · 2 columns — <span className="err">data loss</span></span>
        </div>
        <div className="stat conflict">
          <span className="label">conflicts</span>
          <span className="value">!{summary.conflict}</span>
          <span className="delta">1 index — needs resolution</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 12 }}>
        <div className="panel">
          <div className="panel-title">
            <span>Changes ({rows.length}/{CHANGES_D.length})</span>
            <div style={{ display: 'flex', gap: 8, fontSize: 11, textTransform: 'none', letterSpacing: 0 }}>
              <span className="dim">op:</span>
              {['all', 'CREATE', 'ALTER', 'DROP', 'CONFLICT'].map((o) =>
              <span key={o} onClick={() => setOpFilter(o)} style={{
                cursor: 'pointer',
                color: opFilter === o ? 'var(--mauve)' : 'var(--overlay1)',
                borderBottom: opFilter === o ? '1px solid var(--mauve)' : '1px solid transparent'
              }}>{o.toLowerCase()}</span>
              )}
              <span className="dim" style={{ marginLeft: 8 }}>risk:</span>
              {['all', 'low', 'medium', 'high', 'conflict'].map((o) =>
              <span key={o} onClick={() => setRiskFilter(o)} style={{
                cursor: 'pointer',
                color: riskFilter === o ? 'var(--mauve)' : 'var(--overlay1)',
                borderBottom: riskFilter === o ? '1px solid var(--mauve)' : '1px solid transparent'
              }}>{o}</span>
              )}
            </div>
          </div>
          <table className="tui-table">
            <thead>
              <tr>
                <th style={{ width: 22 }}></th>
                <th style={{ width: 38 }}>#</th>
                <th style={{ width: 80 }}>op</th>
                <th style={{ width: 80 }}>kind</th>
                <th>object</th>
                <th>detail</th>
                <th style={{ width: 80 }}>risk</th>
                <th style={{ width: 70 }}></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) =>
              <tr key={c.id} onClick={() => onPickChange && onPickChange(c)}
              style={{ cursor: 'pointer' }}>
                  <td>
                    <span onClick={(e) => {e.stopPropagation();toggle(c.id);}} style={{
                    display: 'inline-block', width: 13, height: 13,
                    border: '1px solid var(--surface2)',
                    background: selectedIds.has(c.id) ? 'var(--mauve)' : 'transparent',
                    color: 'var(--base)', textAlign: 'center', lineHeight: '11px', fontSize: 10
                  }}>{selectedIds.has(c.id) ? '✓' : ''}</span>
                  </td>
                  <td className="dim">{c.id}</td>
                  <td><span className={`chip ${
                  c.op === 'CREATE' ? 'add' :
                  c.op === 'DROP' ? 'del' :
                  c.op === 'CONFLICT' ? 'conflict' :
                  'mod'}`
                  }>{c.op}</span></td>
                  <td className="muted">{c.kind}</td>
                  <td><span className="accent">{c.obj}</span></td>
                  <td className="muted" style={{ fontSize: 12 }}>{c.detail || '—'}</td>
                  <td>
                    {c.risk === 'high' && <span className="chip del">high</span>}
                    {c.risk === 'medium' && <span className="chip warn">medium</span>}
                    {c.risk === 'low' && <span className="chip" style={{ background: 'rgba(166,227,161,0.10)', color: 'var(--green)' }}>low</span>}
                    {c.risk === 'conflict' && <span className="chip conflict">conflict</span>}
                  </td>
                  <td className="dim" style={{ fontSize: 11 }}>{c.deps.length ? `↳ ${c.deps.length}` : ''}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <div className="panel-title"><span>AI review</span><span className="chip ai">3 hints</span></div>
          <div style={{ padding: 10, display: 'flex', flexDirection: 'column', gap: 10 }}>
            {AI_SUGGESTIONS.map((s, i) =>
            <div key={i} className="ai-card" onClick={() => onAi && onAi(s)} style={{ cursor: 'pointer' }}>
                <div className="ai-h">
                  <span>✦</span>
                  <span>{s.title}</span>
                  <span className={`chip ${s.severity === 'high' ? 'del' : 'warn'}`} style={{ marginLeft: 'auto' }}>{s.severity}</span>
                </div>
                <div className="muted" style={{ fontSize: 11.5 }}>{s.target}</div>
                <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                  <span className="btn primary" style={{ fontSize: 11, padding: '1px 8px' }}>{s.acceptLabel}</span>
                  <span className="btn" style={{ fontSize: 11, padding: '1px 8px' }}>dismiss</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-title"><span>Dependency graph</span><span className="dim" style={{ fontSize: 11 }}>topological order · 25 nodes</span></div>
        <div style={{ padding: 14, overflowX: 'auto' }}>
          <DepGraph />
        </div>
      </div>
    </div>);

}

// Static box-drawing dep graph (mock)
function DepGraph() {
  const txt = `
  ┌───────────────────────┐   ┌──────────────────────┐   ┌─────────────────────┐
  │ c01 CREATE plan_tier  │   │ c02 CREATE task_pri  │   │ c03 ALTER subscr_st │
  │       ⟶ enum          │   │       ⟶ enum         │   │     +'paused'       │
  └─────────┬─────────────┘   └──────────┬───────────┘   └──────────┬──────────┘
            │                            │                          │
            ▼                            ▼                          ▼
  ┌───────────────────────┐   ┌──────────────────────┐   ┌─────────────────────┐
  │ c04 ALTER tenants     │   │ c08 ALTER tasks      │   │ c23 ALTER subscr.   │
  │  +plan_tier            │   │  +parent_task_id    │   │  +pause_until       │
  │  +trial_ends_at        │   │  priority → enum    │   └─────────────────────┘
  └────────────────────────┘   └──────────┬───────────┘
                                         │
                ┌────────────────────────┼─────────────────────────┐
                ▼                        ▼                         ▼
  ┌───────────────────────┐   ┌──────────────────────┐   ┌─────────────────────┐
  │ c09 task_subscript.   │   │ c12 idx tasks_due    │   │ c13 idx ws_status   │
  └───────────┬───────────┘   └──────────────────────┘   └─────────────────────┘
              │
              ▼
  ┌───────────────────────┐
  │ c21 trg_audit_users   │ ◀── depends on c05 (users)
  └───────────────────────┘
`;
  return <pre className="ascii-box" style={{ margin: 0, fontSize: 11.5, color: 'var(--subtext0)' }}>{txt}</pre>;
}

// ─── Diff Detail view ──────────────────────────────────────────────────────
function DiffView({ objectKey, onPickKey, onAi }) {
  const [mode, setMode] = useState('side'); // 'side' | 'inline' | 'tree'
  const obj = DIFFS_D[objectKey] || DIFFS_D['public.tenants'];
  const allKeys = Object.keys(DIFFS_D);

  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
      <div className="section-h">
        <h2>Diff: <span className="accent">{obj.title}</span></h2>
        <span className="crumb">
          acme_prod <span className="sep">→</span> acme_staging
          <span className="sep">·</span> {obj.kind}
          <span className="sep">·</span> {obj.summary}
        </span>
        <div className="right">
          <div style={{ display: 'flex', border: '1px solid var(--surface1)', borderRadius: 2, overflow: 'hidden', height: 22 }}>
            {['side', 'inline', 'tree'].map((m) =>
            <span key={m}
            onClick={() => setMode(m)}
            style={{
              padding: '0 12px',
              minWidth: 56,
              height: '100%',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 11.5,
              cursor: 'pointer',
              background: mode === m ? 'var(--mauve)' : 'transparent',
              color: mode === m ? 'var(--base)' : 'var(--overlay1)',
              fontWeight: mode === m ? 600 : 400
            }}>
              {m}</span>
            )}
          </div>
          <button className="btn" onClick={() => onAi && onAi(AI_SUGGESTIONS.find((s) => s.target === objectKey))} data-comment-anchor="6ac4c1a198-button-387-11">
            <span className="kb">⌘a</span>AI suggest
          </button>
          <button className="btn">copy SQL</button>
          <button className="btn success"><span className="kb">␣a</span>accept</button>
          <button className="btn"><span className="kb">␣s</span>skip</button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', fontSize: 11.5 }}>
        <span className="dim">jump:</span>
        {allKeys.map((k) =>
        <span key={k} onClick={() => onPickKey && onPickKey(k)} className="chip"
        style={{
          cursor: 'pointer',
          background: k === objectKey ? 'var(--mauve)' : 'var(--surface0)',
          color: k === objectKey ? 'var(--base)' : 'var(--subtext1)',
          fontWeight: k === objectKey ? 600 : 400
        }}>{k}</span>
        )}
        {obj.conflict && <span className="chip conflict" style={{ marginLeft: 8 }}>⚠ conflict — needs resolution</span>}
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 12, minHeight: 0 }}>
        {mode === 'side' && <SideBySideDiff obj={obj} />}
        {mode === 'inline' && <InlineDiff obj={obj} />}
        {mode === 'tree' && <TreeDiff />}

        <div className="panel">
          <div className="panel-title">
            <span>Forward migration · DDL</span>
            <span className="dim" style={{ fontSize: 11 }}>copy · run :apply</span>
          </div>
          <div style={{ padding: 8 }}>
            {(obj.forward || []).map((l, i) =>
            <div key={i} className="sql" dangerouslySetInnerHTML={{ __html: hl(l) }} />
            )}
          </div>
          {obj.backward &&
          <>
              <div className="panel-title" style={{ borderTop: '1px solid var(--surface0)' }}>
                <span>Rollback · auto-generated</span>
                <span className="dim" style={{ fontSize: 11 }}>tested ✓</span>
              </div>
              <div style={{ padding: 8 }}>
                {obj.backward.map((l, i) =>
              <div key={i} className="sql" dangerouslySetInnerHTML={{ __html: hl(l) }} />
              )}
              </div>
            </>
          }
        </div>
      </div>
    </div>);

}

function SideBySideDiff({ obj }) {
  // For tenants we have explicit source/target. Otherwise derive from inline.
  let src = obj.source,tgt = obj.target;
  if (!src || !tgt) {
    src = [];tgt = [];
    let snum = 1,tnum = 1;
    for (const l of obj.inline || []) {
      if (l.sig === '+') {tgt.push({ ln: tnum++, t: l.t, cls: 'add' });src.push({ ln: '', t: '', cls: 'empty' });} else
      if (l.sig === '-') {src.push({ ln: snum++, t: l.t, cls: 'del' });tgt.push({ ln: '', t: '', cls: 'empty' });} else
      {src.push({ ln: snum++, t: l.t });tgt.push({ ln: tnum++, t: l.t });}
    }
  }

  const renderSide = (lines) => lines.map((l, i) =>
  <div key={i} className={`diff-line ${l.cls || ''}`}>
      <span className="ln">{l.ln}</span>
      <span className="sg">{l.cls === 'add' ? '+' : l.cls === 'del' ? '−' : l.cls === 'empty' ? '' : ' '}</span>
      <span className="ct sql" dangerouslySetInnerHTML={{ __html: hl(l.t || '') }} />
    </div>
  );

  return (
    <div className="split-h" style={{ flex: '0 0 auto' }}>
      <div>
        <div className="split-head src">● SOURCE · acme_prod {obj.title && <span style={{ color: 'var(--overlay1)' }}>— {obj.title}</span>}</div>
        <div style={{ padding: '6px 0' }}>{renderSide(src)}</div>
      </div>
      <div>
        <div className="split-head tgt">● TARGET · acme_staging {obj.title && <span style={{ color: 'var(--overlay1)' }}>— {obj.title}</span>}</div>
        <div style={{ padding: '6px 0' }}>{renderSide(tgt)}</div>
      </div>
    </div>);

}

function InlineDiff({ obj }) {
  return (
    <div className="panel" style={{ flex: '0 0 auto' }}>
      <div className="panel-title"><span>Inline diff</span><span className="dim" style={{ fontSize: 11 }}>--no-color=false</span></div>
      <div style={{ padding: '6px 0' }}>
        {(obj.inline || []).map((l, i) =>
        <div key={i} className={`diff-line ${l.sig === '+' ? 'add' : l.sig === '-' ? 'del' : ''}`}>
            <span className="ln">{l.ln}</span>
            <span className="sg">{l.sig}</span>
            <span className="ct sql" dangerouslySetInnerHTML={{ __html: hl(l.t) }} />
          </div>
        )}
      </div>
    </div>);

}

// Tree diff — column-level breakdown
function TreeDiff() {
  const rows = [
  { lvl: 0, t: '◈ public.tenants', state: 'mod' },
  { lvl: 1, t: '▾ columns', state: '' },
  { lvl: 2, t: 'id            uuid          PRIMARY KEY', state: '' },
  { lvl: 2, t: 'name          text          NOT NULL', state: '' },
  { lvl: 2, t: 'slug          citext        UNIQUE NOT NULL', state: '' },
  { lvl: 2, t: 'region        text          NOT NULL DEFAULT \'us-east-1\'', state: '' },
  { lvl: 2, t: 'plan_tier     plan_tier_enum NOT NULL DEFAULT \'starter\'', state: 'add' },
  { lvl: 2, t: 'trial_ends_at timestamptz', state: 'add' },
  { lvl: 2, t: 'settings      jsonb         NOT NULL DEFAULT \'{}\'::jsonb', state: '' },
  { lvl: 1, t: '▾ constraints', state: '' },
  { lvl: 2, t: 'PRIMARY KEY (id)', state: '' },
  { lvl: 2, t: 'UNIQUE (slug)', state: '' },
  { lvl: 1, t: '▾ indexes', state: '' },
  { lvl: 2, t: 'tenants_pkey  btree(id)', state: '' },
  { lvl: 2, t: 'tenants_slug_unq  btree(slug)', state: '' },
  { lvl: 1, t: '▸ triggers (0)', state: '' },
  { lvl: 1, t: '▸ policies (0)', state: '' },
  { lvl: 1, t: '▸ stats', state: '' }];

  const sym = (s) => s === 'add' ? '+' : s === 'del' ? '−' : s === 'mod' ? '~' : '·';
  return (
    <div className="panel" style={{ flex: '0 0 auto' }}>
      <div className="panel-title"><span>Tree diff</span><span className="dim" style={{ fontSize: 11 }}>column-level breakdown</span></div>
      <div style={{ padding: '6px 0' }}>
        {rows.map((r, i) =>
        <div key={i} className={`diff-line ${r.state}`} style={{ paddingLeft: 8 + r.lvl * 18 }}>
            <span className="sg" style={{ color: r.state === 'add' ? 'var(--green)' : r.state === 'del' ? 'var(--red)' : r.state === 'mod' ? 'var(--yellow)' : 'var(--overlay0)' }}>{sym(r.state)}</span>
            <span className="ct sql" dangerouslySetInnerHTML={{ __html: hl(r.t) }} />
          </div>
        )}
      </div>
    </div>);

}

Object.assign(window, { ConnectionView, OverviewView, DiffView, hl });