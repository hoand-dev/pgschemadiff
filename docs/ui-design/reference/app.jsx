// Main App — ties together chrome + views + vim navigation

const VIEWS = [
  { id: 'connection', key: 'c', label: 'Connection', kb: 'gc' },
  { id: 'overview',   key: 'o', label: 'Overview',   kb: 'go', count: 25 },
  { id: 'diff',       key: 'd', label: 'Diff',       kb: 'gd' },
  { id: 'migration',  key: 'm', label: 'Migration',  kb: 'gm' },
  { id: 'apply',      key: 'a', label: 'Apply',      kb: 'ga' },
  { id: 'history',    key: 'h', label: 'History',    kb: 'gh' },
  { id: 'settings',   key: 's', label: 'Settings',   kb: 'gs' },
];

function App() {
  const [theme, setTheme] = useState('mocha');
  const [view, setView] = useState('overview');
  const [mode, setMode] = useState('normal'); // normal | command | insert
  const [diffKey, setDiffKey] = useState('public.tenants');
  const [selectedTreeId, setSelectedTreeId] = useState('public/tables/tenants');
  const [showHelp, setShowHelp] = useState(false);
  const [aiOpen, setAiOpen] = useState(null);
  const [hint, setHint] = useState('press ? for help');
  const pendingG = useRef(false);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const switchTheme = () => setTheme((t) => (t === 'mocha' ? 'latte' : 'mocha'));

  const runCommand = (cmd) => {
    if (cmd === '__escape' || cmd === '') { setMode('normal'); return; }
    const c = cmd.trim().toLowerCase();
    setHint(`:${c} — executed`);
    if (c === 'q' || c === 'quit' || c === 'zz') { setHint('goodbye :)'); }
    else if (c === '?' || c === 'help') { setShowHelp(true); }
    else if (c.startsWith('set bg=') || c.startsWith('set theme=')) {
      const t = c.split('=')[1];
      if (t === 'mocha' || t === 'latte') setTheme(t);
    }
    else if (c === 'apply' || c === 'apply --dry-run') { setView('apply'); }
    else if (c === 'overview' || c === 'o') setView('overview');
    else if (c === 'diff' || c.startsWith('diff ')) {
      setView('diff');
      const rest = c.slice(5).trim();
      if (rest) {
        const k = Object.keys(window.DATA.DIFFS).find((x) => x.toLowerCase().includes(rest));
        if (k) setDiffKey(k);
      }
    }
    else if (c === 'migration' || c === 'm') setView('migration');
    else if (c === 'history' || c === 'h') setView('history');
    else if (c === 'settings' || c === 'config') setView('settings');
    else if (c === 'conn' || c === 'connection') setView('connection');
    else if (c.startsWith('rollback')) { setHint('rollback queued — see history'); setView('history'); }
    else setHint(`E492: not an editor command: ${cmd}`);
    setMode('normal');
  };

  // Vim-style keybindings
  useEffect(() => {
    const handler = (e) => {
      if (mode === 'command') return; // input handles it
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      if (e.key === ':') { e.preventDefault(); setMode('command'); return; }
      if (e.key === '?') { e.preventDefault(); setShowHelp(true); return; }
      if (e.key === 'Escape') { setMode('normal'); setShowHelp(false); pendingG.current = false; return; }

      if (pendingG.current) {
        pendingG.current = false;
        const map = { c: 'connection', o: 'overview', d: 'diff', m: 'migration', a: 'apply', h: 'history', s: 'settings' };
        if (map[e.key]) { setView(map[e.key]); setHint(`g${e.key} — ${map[e.key]}`); return; }
        if (e.key === 'T') { switchTheme(); setHint('theme toggled'); return; }
        if (e.key === 'g') { setHint('top'); return; }
      }
      if (e.key === 'g') { pendingG.current = true; setHint('g…'); return; }
      if (e.key === 'Z' && e.shiftKey) { setHint('ZZ — bye'); return; }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [mode]);

  // Tab labels with change counts
  const tabbar = (
    <div className="tabbar">
      {VIEWS.map((v) => (
        <div key={v.id} className={`tab ${view === v.id ? 'active' : ''}`} onClick={() => setView(v.id)}>
          <span>{v.label}</span>
          <span className="tkey">{v.kb}</span>
          {v.id === 'overview' && <span className="tcount">25</span>}
          {v.id === 'diff' && <span className="tcount">{Object.keys(window.DATA.DIFFS).length}</span>}
          {v.id === 'apply' && <span className="tcount" style={{ color: 'var(--green)' }}>●</span>}
          {v.id === 'history' && <span className="tcount" style={{ color: 'var(--overlay1)' }}>9</span>}
        </div>
      ))}
      <div style={{ flex: 1, borderBottom: '1px solid var(--surface0)' }} />
      <div style={{
        display: 'flex',
        alignItems: 'center',
        padding: '0 12px',
        fontSize: 11,
        color: 'var(--overlay1)',
        gap: 12,
        borderBottom: '1px solid var(--surface0)',
        borderLeft: '1px solid var(--surface0)',
      }}>
        <span><span className="ok">+4</span> added</span>
        <span><span className="warn">~6</span> modified</span>
        <span><span className="err">-2</span> dropped</span>
        <span style={{ color: 'var(--peach)' }}>!1 conflict</span>
      </div>
    </div>
  );

  const onSelectTreeNode = (node, path) => {
    setSelectedTreeId(path.join('/'));
    if (node.type === 'table' || node.type === 'view' || node.type === 'func' || node.type === 'index' || node.type === 'trigger' || node.type === 'type') {
      const schema = path[0];
      const key = `${schema}.${node.name.replace(/\(.*\)$/, '')}`;
      if (window.DATA.DIFFS[key]) {
        setDiffKey(key);
        setView('diff');
      }
    }
  };

  return (
    <div className="terminal">
      <div className="term-titlebar">
        <div className="term-dots"><span className="term-dot r" /><span className="term-dot y" /><span className="term-dot g" /></div>
        <div className="term-title">pgschemadiff — zsh — acme_prod → acme_staging — 164×48</div>
        <div style={{ color: 'var(--overlay0)', fontSize: 11 }}>tmux 0:pgsd*</div>
      </div>
      <div className="app">
        <Header
          mode={mode}
          theme={theme}
          onThemeToggle={switchTheme}
          conn={window.DATA.CONN}
          onOpenCmd={() => setMode('command')}
        />
        <div className="body">
          <Sidebar
            tree={window.DATA.TREE}
            onSelect={onSelectTreeNode}
            selected={selectedTreeId}
          />
          <div className="main">
            {tabbar}
            <div className="view">
              {view === 'connection' && <ConnectionView conn={window.DATA.CONN} />}
              {view === 'overview' && <OverviewView onPickChange={(c) => {
                const k = c.obj;
                if (window.DATA.DIFFS[k]) { setDiffKey(k); setView('diff'); }
              }} onAi={(s) => setAiOpen(s || window.DATA.AI_SUGGESTIONS[0])} />}
              {view === 'diff' && <DiffView objectKey={diffKey} onPickKey={setDiffKey} onAi={(s) => setAiOpen(s || window.DATA.AI_SUGGESTIONS[0])} />}
              {view === 'migration' && <MigrationView onApply={() => setView('apply')} onAi={() => setAiOpen(window.DATA.AI_SUGGESTIONS[0])} />}
              {view === 'apply' && <ApplyView />}
              {view === 'history' && <HistoryView />}
              {view === 'settings' && <SettingsView theme={theme} onTheme={setTheme} />}
            </div>
          </div>
        </div>
        <Statusbar mode={mode} view={view} selected={selectedTreeId.split('/').slice(-1)[0]} changeCount={25} hasConflict={true} />
        <Cmdbar mode={mode} onCommand={runCommand} hint={hint} />
      </div>
      {showHelp && <HelpModal onClose={() => setShowHelp(false)} />}
      {aiOpen && <AiModal suggestion={aiOpen} onClose={() => setAiOpen(null)} />}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
