// Chrome: Header, Sidebar (schema tree), Statusbar, Command line, Modal
// Exports to window for sibling babel scripts.

const { useState, useEffect, useRef, useMemo, useCallback } = React;

// ─── Icons (text glyphs, monospace-safe) ───────────────────────────────────
const ICONS = {
  schema: '◈',
  group: '▾',
  groupCollapsed: '▸',
  table: '▦',
  view: '◫',
  func: 'ƒ',
  index: '⌘',
  trigger: '⚡',
  type: '𝒯',
  col: '·',
};

// ─── Header ────────────────────────────────────────────────────────────────
function Header({ mode, theme, onThemeToggle, conn, onOpenCmd }) {
  return (
    <div className="header">
      <div className="brand">
        <span style={{ fontSize: 16 }}>◈</span>
        <span>pgschemadiff</span>
        <span className="ver">v0.4.2</span>
      </div>
      <span className={`mode-badge ${mode}`}>{mode.toUpperCase()}</span>

      <div className="conn-pill">
        <span className="dot" />
        <span className="label">src</span>
        <span className="val">{conn.source.label}</span>
        <span className="dim" style={{ fontSize: 11 }}>@{conn.source.host.split('.')[0]}</span>
      </div>
      <span style={{ color: 'var(--overlay0)' }}>→</span>
      <div className="conn-pill">
        <span className="dot" />
        <span className="label">tgt</span>
        <span className="val tgt">{conn.target.label}</span>
        <span className="dim" style={{ fontSize: 11 }}>@{conn.target.host.split('.')[0]}</span>
      </div>

      <div className="header-right">
        <span className="muted">branch <span style={{ color: 'var(--green)' }}>main</span></span>
        <span className="muted">git@9af3c12</span>
        <span
          className="btn"
          style={{ padding: '1px 8px' }}
          onClick={onThemeToggle}
          title="Toggle theme (gT)"
        >
          {theme === 'mocha' ? '☾ mocha' : '☀ latte'}
        </span>
        <span className="btn" style={{ padding: '1px 8px' }} onClick={onOpenCmd}>
          : <span className="dim">cmd</span>
        </span>
      </div>
    </div>
  );
}

// ─── Sidebar / Schema tree ─────────────────────────────────────────────────
function StatusGlyph({ s }) {
  if (!s) return <span className="tw-icon t-col">{ICONS.col}</span>;
  const map = { add: '+', mod: '~', del: '-', conflict: '!' };
  return <span className={`change-mark ${s}`}>{map[s]}</span>;
}

function TreeBadges({ badge }) {
  if (!badge) return null;
  const out = [];
  if (badge.add) out.push(<span key="a" className="tw-badge add">+{badge.add}</span>);
  if (badge.mod) out.push(<span key="m" className="tw-badge mod">~{badge.mod}</span>);
  if (badge.del) out.push(<span key="d" className="tw-badge del">-{badge.del}</span>);
  if (badge.conflict) out.push(<span key="c" className="tw-badge conflict">!{badge.conflict}</span>);
  return <span style={{ marginLeft: 'auto', display: 'flex', gap: 3 }}>{out}</span>;
}

function TreeNode({ node, depth, expanded, setExpanded, selected, onSelect, path }) {
  const id = path.join('/');
  const isOpen = expanded[id] ?? !!node.expanded;
  const hasChildren = node.children && node.children.length > 0;

  let icon = null;
  let iconCls = '';
  switch (node.type) {
    case 'schema': icon = ICONS.schema; iconCls = 't-schema'; break;
    case 'group': icon = isOpen ? ICONS.group : ICONS.groupCollapsed; iconCls = 'muted'; break;
    case 'table': icon = ICONS.table; iconCls = 't-table'; break;
    case 'view': icon = ICONS.view; iconCls = 't-view'; break;
    case 'func': icon = ICONS.func; iconCls = 't-func'; break;
    case 'index': icon = ICONS.index; iconCls = 't-index'; break;
    case 'trigger': icon = ICONS.trigger; iconCls = 't-trigger'; break;
    case 'type': icon = ICONS.type; iconCls = 't-type'; break;
    case 'col': icon = null; iconCls = 't-col'; break;
    default: icon = '·';
  }

  const click = () => {
    if (hasChildren) setExpanded({ ...expanded, [id]: !isOpen });
    onSelect(node, path);
  };

  const isSel = selected === id;

  return (
    <>
      <div
        className={`tree-row indent-${depth} ${isSel ? 'selected' : ''}`}
        onClick={click}
      >
        <span className="tw-caret">
          {hasChildren ? (isOpen ? '▾' : '▸') : ''}
        </span>
        <StatusGlyph s={node.status} />
        {icon && <span className={`tw-icon ${iconCls}`}>{icon}</span>}
        <span className={`tw-name`} style={{
          color: node.status === 'del' ? 'var(--diff-del-fg)'
               : node.status === 'add' ? 'var(--diff-add-fg)'
               : node.status === 'conflict' ? 'var(--red)'
               : node.type === 'group' ? 'var(--overlay2)'
               : 'var(--text)',
          textDecoration: node.status === 'del' ? 'line-through' : 'none',
        }}>{node.name}</span>
        {node.type === 'group' && node.children && (
          <span className="dim" style={{ marginLeft: 6, fontSize: 11 }}>{node.children.length}</span>
        )}
        <TreeBadges badge={node.badge} />
      </div>
      {isOpen && hasChildren && node.children.map((c, i) => (
        <TreeNode
          key={i}
          node={c}
          depth={depth + 1}
          expanded={expanded}
          setExpanded={setExpanded}
          selected={selected}
          onSelect={onSelect}
          path={[...path, c.name]}
        />
      ))}
    </>
  );
}

function Sidebar({ tree, onSelect, selected }) {
  const [expanded, setExpanded] = useState({});
  const [filter, setFilter] = useState('');
  const [showOnlyChanges, setShowOnlyChanges] = useState(true);

  // simple filter — for brevity, only top-level + first-level
  return (
    <div className="sidebar">
      <div className="sb-header">
        <span>Schema Explorer</span>
        <span className="dim" style={{ fontSize: 10 }}>{'<C-b>'}</span>
      </div>
      <div className="sb-search">
        <span className="dim">/</span>
        <input
          placeholder="filter… (e.g. tasks, fn_*, idx_)"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      <div style={{
        padding: '4px 10px',
        borderBottom: '1px solid var(--surface0)',
        fontSize: 11,
        display: 'flex',
        gap: 10,
        color: 'var(--overlay1)',
      }}>
        <label className={`toggle ${showOnlyChanges ? 'on' : ''}`} onClick={() => setShowOnlyChanges(!showOnlyChanges)}>
          <span className="sw"></span>changes only
        </label>
        <span className="dim" style={{ marginLeft: 'auto' }}>
          <span className="ok">+4</span> · <span className="warn">~6</span> · <span className="err">-2</span> · <span style={{ color: 'var(--peach)' }}>!1</span>
        </span>
      </div>
      <div className="tree">
        {tree.map((n, i) => (
          <TreeNode
            key={i}
            node={n}
            depth={1}
            expanded={expanded}
            setExpanded={setExpanded}
            selected={selected}
            onSelect={onSelect}
            path={[n.name]}
          />
        ))}
      </div>
      <div style={{
        padding: '6px 10px',
        borderTop: '1px solid var(--surface0)',
        fontSize: 11,
        color: 'var(--overlay1)',
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
      }}>
        <div>legend: <span className="ok">+</span> add · <span className="warn">~</span> mod · <span className="err">-</span> del · <span style={{ color: 'var(--peach)' }}>!</span> conflict</div>
        <div className="dim">25 changes across 3 schemas</div>
      </div>
    </div>
  );
}

// ─── Statusbar (vim-style modeline) ────────────────────────────────────────
function Statusbar({ mode, view, selected, changeCount, hasConflict }) {
  return (
    <div className="statusbar">
      <span className="seg pill">{mode.toUpperCase()}</span>
      <span className="seg">pgschemadiff/<span style={{ opacity: 0.85 }}>{view}</span></span>
      <span className="seg">{selected || '—'}</span>
      {hasConflict && <span className="seg pill" style={{ background: 'rgba(0,0,0,0.25)', color: '#fff' }}>⚠ 1 conflict</span>}
      <span className="seg r">
        <span className="pill">{changeCount} changes</span>
        <span className="pill">utf-8</span>
        <span className="pill">postgresql 16</span>
        <span className="pill">{'14:22:08'}</span>
      </span>
    </div>
  );
}

// ─── Command bar (vim-style ':') ───────────────────────────────────────────
function Cmdbar({ mode, onCommand, hint }) {
  const [val, setVal] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    if (mode === 'command') inputRef.current?.focus();
  }, [mode]);

  const submit = (e) => {
    if (e.key === 'Enter') {
      onCommand(val);
      setVal('');
    } else if (e.key === 'Escape') {
      setVal('');
      onCommand('__escape');
    }
  };

  if (mode === 'command') {
    return (
      <div className="cmdbar">
        <span className="prompt">:</span>
        <input
          ref={inputRef}
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={submit}
          autoFocus
          placeholder="diff users  · apply --dry-run  · set bg=latte  · history  · q"
        />
        <span className="dim">↵ run · esc cancel</span>
      </div>
    );
  }

  return (
    <div className="cmdbar">
      <span className="hint"><span className="key">:</span> command</span>
      <span className="sep">│</span>
      <span className="hint"><span className="key">?</span> help</span>
      <span className="sep">│</span>
      <span className="hint"><span className="key">gc</span> conn</span>
      <span className="hint"><span className="key">go</span> overview</span>
      <span className="hint"><span className="key">gd</span> diff</span>
      <span className="hint"><span className="key">gm</span> migration</span>
      <span className="hint"><span className="key">ga</span> apply</span>
      <span className="hint"><span className="key">gh</span> history</span>
      <span className="hint"><span className="key">gs</span> settings</span>
      <span className="sep">│</span>
      <span className="hint"><span className="key">j/k</span> move</span>
      <span className="hint"><span className="key">/</span> search</span>
      <span className="sep">│</span>
      <span className="hint"><span className="key">gT</span> theme</span>
      <span className="hint"><span className="key">ZZ</span> quit</span>
      <span style={{ marginLeft: 'auto' }} className="dim">{hint}</span>
    </div>
  );
}

// ─── Modal ─────────────────────────────────────────────────────────────────
function Modal({ title, onClose, children, footer, width = 640 }) {
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" style={{ width }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="title">{title}</span>
          <span className="x" onClick={onClose}>[esc]</span>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

// ─── Help modal ────────────────────────────────────────────────────────────
function HelpModal({ onClose }) {
  const groups = [
    {
      title: 'Navigation',
      rows: [
        ['j / k', 'down / up in lists'],
        ['h / l', 'collapse / expand tree node'],
        ['gg / G', 'top / bottom'],
        ['/ ', 'search / filter'],
        ['<C-b>', 'toggle sidebar'],
      ],
    },
    {
      title: 'Views',
      rows: [
        ['gc', 'Connection'],
        ['go', 'Overview'],
        ['gd', 'Diff detail'],
        ['gm', 'Migration script'],
        ['ga', 'Apply migration'],
        ['gh', 'History'],
        ['gs', 'Settings'],
      ],
    },
    {
      title: 'Actions',
      rows: [
        [': ', 'command palette'],
        ['<space> a', 'accept change'],
        ['<space> s', 'skip change'],
        ['<space> ai', 'AI suggest'],
        ['gT', 'cycle theme'],
        ['ZZ', 'quit'],
      ],
    },
    {
      title: 'Commands (:)',
      rows: [
        [':diff <name>', 'show diff for object'],
        [':apply [--dry-run]', 'execute migration'],
        [':rollback <id>', 'rollback past run'],
        [':set bg=mocha|latte', 'theme'],
        [':conn switch <name>', 'change source/target'],
      ],
    },
  ];
  return (
    <Modal title="Keyboard help — pgschemadiff" onClose={onClose} width={760}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
        {groups.map((g, i) => (
          <div key={i}>
            <div className="muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 6 }}>{g.title}</div>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <tbody>
                {g.rows.map((r, j) => (
                  <tr key={j}>
                    <td style={{ padding: '3px 0', width: '38%' }}><kbd>{r[0]}</kbd></td>
                    <td style={{ padding: '3px 0', color: 'var(--subtext1)' }}>{r[1]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </Modal>
  );
}

// Export
Object.assign(window, {
  Header, Sidebar, Statusbar, Cmdbar, Modal, HelpModal, StatusGlyph, ICONS,
});
