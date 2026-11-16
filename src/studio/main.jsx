import { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CustomIcon as Icon } from './vendor/zoo/CustomIcon';
import { ActionButton, ChatBubble, Composer, LayoutPanelHeader, WelcomeItem } from './vendor/zoo/Presentation';
import { Viewport } from './Viewport';
import { request } from './api';
import { copyText, requestId } from './browser';
import { conditionTypes, conditionSummary } from '../boundaries/conditions';
import './studio.css';

function MarkdownText({ children }) {
  return <div className="markdown"><Markdown remarkPlugins={[remarkGfm]} components={{
    a: props => <a {...props} target="_blank" rel="noreferrer noopener"/>,
    img: () => null,
  }}>{children}</Markdown></div>;
}

function IconButton({ name, label, active, ...props }) {
  return <button type="button" title={label} aria-label={label} aria-pressed={active === undefined ? undefined : active} className={`icon-button ${active ? 'active' : ''}`} {...props}><Icon name={name} width={20} height={20}/></button>;
}

function App() {
  const [snapshot, setSnapshot] = useState(null), snapshotRef = useRef(null), session = useRef(null);
  const [connected, setConnected] = useState(true), [error, setError] = useState(''), [working, setWorking] = useState(false);
  const [message, setMessage] = useState(''), [panel, setPanel] = useState(null), [chatOpen, setChatOpen] = useState(true);
  const [menu, setMenu] = useState(null), [dialog, setDialog] = useState(null), [faceSearch, setFaceSearch] = useState('');
  const [theme, setTheme] = useState(localStorage.getItem('studio-theme') || 'dark');
  const [split, setSplit] = useState(Number(localStorage.getItem('studio-split')) || 50);
  const [connectionMessage, setConnectionMessage] = useState(''), [checking, setChecking] = useState(false);
  const [exporting, setExporting] = useState(false);
  const viewport = useRef(null), fileInput = useRef(null), input = useRef(null), scroll = useRef(null), shell = useRef(null);
  const scrollPinned = useRef(true), applying = useRef(false);
  const handledVisualRequest = useRef(null);
  const apply = useCallback(data => {
    const before = snapshotRef.current;
    if (before?.context.sessionId === data.context.sessionId && before.context.revision > data.context.revision) return;
    snapshotRef.current = data; session.current = data.context.sessionId;
    sessionStorage.setItem('studio-session', data.context.sessionId);
    setSnapshot(data); setConnected(true);
  }, []);
  useEffect(() => {
    let disposed = false, timer;
    async function poll() {
      try {
        let data;
        const sid = session.current || sessionStorage.getItem('studio-session');
        if (sid) {
          try { data = await request(`/sessions/${sid}`); }
          catch (e) { if (e.status !== 404) throw e; data = await request('/sessions', {}); }
        } else data = await request('/sessions', {});
        if (!disposed) apply(data);
      } catch { if (!disposed) setConnected(false); }
      finally { if (!disposed) timer = setTimeout(poll, snapshotRef.current?.busy ? 450 : 1000); }
    }
    poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [apply]);
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    document.body.classList.toggle('dark', theme === 'dark');
    localStorage.setItem('studio-theme', theme);
  }, [theme]);
  useEffect(() => {
    if (scrollPinned.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [snapshot?.messages.length, snapshot?.busy, snapshot?.proposalToken, chatOpen]);
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') { setMenu(null); setDialog(null); }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setDialog('commands'); }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'o') { e.preventDefault(); fileInput.current?.click(); }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  const c = snapshot?.context;
  const visualRequest = c?.visualAssistance?.request;
  useEffect(() => {
    if (!visualRequest || handledVisualRequest.current === visualRequest.id) return;
    handledVisualRequest.current = visualRequest.id;
    const body = { model_id: visualRequest.modelId };
    try { Object.assign(body, viewport.current.visual(visualRequest)); }
    catch (e) { body.error = e.message; }
    request(`/sessions/${session.current}/visual/${visualRequest.id}`, body).catch(e => {
      if (e.status !== 409) setError('Could not return the viewport to the assistant: ' + e.message);
    });
  }, [visualRequest?.id]);
  const busy = working || !!snapshot?.busy || !snapshot || !connected, hasModel = !!c?.modelId;
  const exportChoices = [['setup', 'Export setup (.mechdat)', 'exportFile'], ['solved', 'Export solved simulation (.mechpz)', 'download']];
  const canExport = kind => !busy && !!snapshot?.exportOptions?.[kind]?.enabled;
  const pending = c?.pendingConfirmation;
  const messages = snapshot?.messages || [];
  const hasConversation = !!c?.awaitingSimulationChoice || messages.some(m => m.role === 'user');
  const latestCode = [...messages].reverse().find(m => typeof m.content === 'object' && m.content.code)?.content;
  const images = messages.filter(m => typeof m.content === 'object' && m.content.image).map(m => m.content);
  const selected = c?.selectedFace;
  const highlights = c?.highlightedFaceKeys.map(key => c.faces.find(f => f.key === key)?.index ?? key.split(':').pop()) || [];
  const togglePanel = value => { setPanel(p => p === value ? null : value); setMenu(null); };
  const importModel = () => { setMenu(null); setDialog(null); fileInput.current?.click(); };

  async function act(path, body, options = {}) {
    if (!session.current) return;
    if (!options.selection && applying.current) return;
    if (!options.selection) { applying.current = true; setWorking(true); }
    setError('');
    try { const data = await request(`/sessions/${session.current}${path}`, body); apply(data); return data; }
    catch (e) { setError(e.message); throw e; }
    finally { if (!options.selection) { applying.current = false; setWorking(false); } }
  }
  async function upload(file) {
    if (busy) return;
    const body = new FormData(); body.append('file', file);
    try { await act('/upload', body); setPanel(null); scrollPinned.current = true; } catch { /* Visible error above. */ }
  }
  async function send(text = message, token) {
    if (!text.trim() || busy) return;
    scrollPinned.current = true; setChatOpen(true);
    try {
      const body = { text: text.trim(), request_id: requestId() };
      if (token) body.proposal_token = token;
      if (await act('/messages', body)) setMessage('');
    } catch { /* Preserve the draft for correction/retry. */ }
  }
  async function chooseAnswers(token, ids) {
    if (busy || !ids.length) return;
    scrollPinned.current = true;
    try { await act('/messages',{request_id:requestId(),choice_token:token,choice_ids:ids}); }
    catch { /* Keep the selection available when a request fails. */ }
  }
  function chooseFace(key, focus = false) {
    if (!snapshotRef.current?.context.modelId) return;
    act('/select', { model_id: snapshotRef.current.context.modelId, face_key: key, focus }, { selection: true }).catch(() => {});
  }
  async function checkConnection() {
    setChecking(true);
    try { const r = await request('/connection', {}); setConnectionMessage(r.message); }
    catch (e) { setConnectionMessage(e.message); }
    finally { setChecking(false); }
  }
  async function setPreferences(mode, visual) {
    if (busy) return;
    try { await act('/preferences', { revision: c.revision, interaction_mode: mode, visual_enabled: visual }); }
    catch { /* Displayed by act; retain the server's actual settings. */ }
  }
  async function downloadSetup(kind = 'setup') {
    if (!c?.modelId || !canExport(kind) || applying.current) return;
    applying.current = true; setWorking(true); setExporting(true); setError(''); setMenu(null);
    try {
      const data = await request(`/sessions/${session.current}/export-mechanical`, { model_id: c.modelId, revision: c.revision, kind });
      const a = document.createElement('a'); a.href = data.url; a.download = data.filename;
      document.body.appendChild(a); a.click(); a.remove();
    } catch (e) { setError(e.message); }
    finally { applying.current = false; setWorking(false); setExporting(false); }
  }
  function beginResize(e) {
    e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId);
    const rect = shell.current.getBoundingClientRect();
    const move = event => setSplit(Math.min(72, Math.max(30, (event.clientX - rect.left) / rect.width * 100)));
    const end = () => { document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', end); };
    document.addEventListener('pointermove', move); document.addEventListener('pointerup', end);
  }
  useEffect(() => { localStorage.setItem('studio-split', String(split)); }, [split]);

  const panelTitles = { model: 'Model', files: 'Project files', setup: 'Simulation setup', code: 'Python', results: 'Results', activity: 'Activity' };
  const panelIcons = { model: 'model', files: 'folder', setup: 'clipboardCheckmark', code: 'code', results: 'beaker', activity: 'logs' };
  return <div className="studio-app" data-session-id={c?.sessionId || ''}>
    <input className="hidden" ref={fileInput} type="file" accept=".step,.stp" aria-label="Upload STEP file" onChange={e => { if (e.target.files[0]) upload(e.target.files[0]); e.target.value = ''; }}/>
    <header className="app-header">
      <button className="app-mark" title="Simulation Studio" aria-label="About Simulation Studio" onClick={() => setDialog('about')}><Icon name="model" width={24} height={24}/></button>
      <div className="project-menu">
        <button className="project-button" onClick={() => setMenu(menu === 'project' ? null : 'project')} aria-expanded={menu === 'project'}><span>Simulation Studio</span><span className="project-slash">/</span><strong>{c?.filename || 'Untitled project'}</strong><Icon name="caretDown" width={16}/></button>
        {menu === 'project' && <div className="dropdown project-dropdown"><button onClick={importModel}><Icon name="importFile"/>Open STEP model<kbd>⌘ O</kbd></button><button onClick={() => togglePanel('files')}><Icon name="folder"/>Saved models</button>{exportChoices.map(([kind, label, icon]) => <button key={kind} disabled={!canExport(kind)} title={snapshot?.exportOptions?.[kind]?.reason} onClick={() => downloadSetup(kind)}><Icon name={icon}/>{label}</button>)}<div className="menu-separator"/><button onClick={() => { setTheme(theme === 'dark' ? 'light' : 'dark'); setMenu(null); }}><Icon name="eyeOpen"/>{theme === 'dark' ? 'Light' : 'Dark'} appearance</button></div>}
      </div>
      <span className="header-divider"/>
      <span className="header-description">Simulation workspace</span>
      <div className="header-actions">
        <ActionButton iconStart={{ icon: 'command', bgClassName: '!bg-transparent' }} onClick={() => setDialog('commands')}>Commands <kbd>⌘ K</kbd></ActionButton>
        <ActionButton iconStart={{ icon: 'importFile', bgClassName: '!bg-transparent' }} onClick={importModel} disabled={busy}>Import CAD</ActionButton>
        <button className="user-avatar" aria-label="Workspace settings" onClick={() => setDialog('settings')}><Icon name="person" width={18}/></button>
      </div>
    </header>
    <div className="main-workspace" ref={shell}>
      <nav className="left-rail" aria-label="Workspace panels">
        {['model', 'files', 'setup', 'code', 'results', 'activity'].map(key => <IconButton key={key} name={panelIcons[key]} label={panelTitles[key]} active={panel === key} onClick={() => togglePanel(key)}/>)}
        <span className="rail-divider"/><IconButton name="importFile" label="Import model" disabled={busy} onClick={importModel}/>{exportChoices.map(([kind, label, icon]) => <IconButton key={kind} name={icon} label={label} title={label + " — " + (snapshot?.exportOptions?.[kind]?.reason || "Confirm a simulation setup first.")} disabled={!canExport(kind)} onClick={() => downloadSetup(kind)}/>)}
        <div className="rail-spacer"/><IconButton name="settings" label="Settings" onClick={() => setDialog('settings')}/>
      </nav>
      {panel && <aside className="inspector" aria-label={panelTitles[panel]}><LayoutPanelHeader icon={panelIcons[panel]} title={panelTitles[panel]} onClose={() => setPanel(null)}/><div className="inspector-body">
        {panel === 'model' && <>
          {hasModel ? <><div className="tree-model"><Icon name="body" width={18}/><span>{c.filename}</span></div><div className="panel-section-label">CAD faces <span>{c.faceCount}</span></div><input className="search-input" aria-label="Find a face" placeholder="Find a face…" value={faceSearch} onChange={e => setFaceSearch(e.target.value)}/><div className="face-list">{c.faces.filter(f => String(f.index).includes(faceSearch)).map(f => <button className={`face-row ${selected?.key === f.key ? 'selected' : ''} ${c.highlightedFaceKeys.includes(f.key) ? 'highlighted' : ''}`} key={f.key} onClick={() => chooseFace(f.key, true)}><Icon name="plane" width={16}/><span>Face {f.index}</span><small>{f.areaMm2.toPrecision(3)} mm²</small></button>)}</div>{c.facesTruncated && <p className="muted">Showing the first 500 faces. All faces remain selectable in the viewport.</p>}</> : <EmptyPanel icon="model" text="Import a CAD model to inspect its faces." onClick={importModel} action="Import CAD"/>}
        </>}
        {panel === 'files' && <><div className="panel-section-label">Saved models <span>{snapshot?.projects.length || 0}</span></div>{snapshot?.projects.map(p => <button key={p.modelId} disabled={busy} className={`saved-model ${p.modelId === c.modelId ? 'current' : ''}`} onClick={() => act('/open', { model_id: p.modelId }).catch(() => {})}><Icon name="file" width={20}/><span>{p.label.split(' · ')[0]}<small>STEP geometry</small></span>{p.modelId === c.modelId && <Icon name="checkmark" width={16}/>}</button>)}<button className="panel-import" disabled={busy} onClick={importModel}><Icon name="plus" width={16}/>Import another model</button></>}
        {panel === 'setup' && <><div className="panel-section-label">Saved conditions <span>{c?.boundaryConditions.length || 0}</span></div>{c?.boundaryConditions.length ? c.boundaryConditions.map(b => <button className="condition-row" key={b.id} onClick={() => chooseFace(b.faceKey, true)}><Icon name={b.type === 'fixed' ? 'fix' : 'arrowDown'} width={18}/><span><strong>{conditionTypes[b.type]?.label || b.type}</strong><small>Face {c.faces.find(f => f.key === b.faceKey)?.index || b.faceKey.split(':').pop()} · {conditionSummary(b)}</small></span></button>) : <EmptyPanel icon="clipboardCheckmark" text="Select a face, then describe its support or load in the conversation."/>}{c?.analysis.material && <div className="setup-details"><span>Material<strong>{c.analysis.material}</strong></span><span>Mesh setting<strong>{c.analysis.elementSizeMm} mm</strong></span></div>}<button className="panel-import" disabled={!hasModel || busy} onClick={() => send('Help me review my simulation setup. Highlight any faces we need to check and ask about missing assumptions.')}><Icon name="sparkles" width={16}/>Review setup together</button></>}
        {panel === 'code' && (latestCode ? <><div className="panel-section-label">{latestCode.title}</div><pre className="code-view"><code>{latestCode.code}</code></pre><button className="panel-import" onClick={() => copyText(latestCode.code).catch(() => setError('Could not copy the code.'))}><Icon name="clipboard" width={16}/>Copy Python</button></> : <EmptyPanel icon="code" text="The assistant’s generated Python will appear here for review before it runs."/>)}
        {panel === 'results' && <>{images.length ? <>{images.map((im, i) => <a href={im.image} target="_blank" rel="noreferrer" className="result-thumbnail" key={i}><img src={im.image} alt={im.label}/><span>{im.label}</span></a>)}{snapshot.downloads.map(d => <a key={d.url} className="download-link" href={d.url} download={d.filename}><Icon name="download" width={16}/>{d.label}</a>)}</> : <EmptyPanel icon="beaker" text="Result plots and files will appear here after an Ansys run."/>}{c?.lastResult && <div className="result-status"><span className={`status-dot ${c.lastResult.status === 'succeeded' ? '' : 'warn'}`}/>{c.lastResult.status === 'succeeded' ? 'Latest run completed' : c.lastResult.status}</div>}</>}
        {panel === 'activity' && <><div className="panel-section-label">Execution history</div>{c?.programAttempts.length ? c.programAttempts.map((a, i) => <div className="attempt" key={i}><span className={`status-dot ${a.status === 'succeeded' ? '' : 'warn'}`}/><div><strong>{a.title}</strong><small>{a.status}</small>{a.error && <p>{a.error}</p>}</div></div>) : <EmptyPanel icon="logs" text="Your simulation runs and their status will appear here."/>}{c?.lastResult?.stdout && <pre className="code-view">{c.lastResult.stdout}</pre>}</>}
      </div></aside>}
      <section className="model-workspace" aria-label="CAD workspace" style={{ flex: chatOpen ? `${split} 1 0%` : '1' }}>
        <Viewport ref={viewport} state={snapshot?.viewer} onSelect={chooseFace} onUpload={upload} disabled={busy} theme={theme}>
          <div className="floating-toolbar" role="toolbar" aria-label="View controls">
            <button disabled={!hasModel} onClick={() => viewport.current?.fit()} title="Fit model"><Icon name="viewFrame" width={18}/><span>Fit view</span></button><span className="toolbar-divider"/>
            <IconButton name="model" label="Isometric view" disabled={!hasModel} onClick={() => viewport.current?.view('iso')}/>
            <IconButton name="plane" label="Top view" disabled={!hasModel} onClick={() => viewport.current?.view('top')}/>
            <IconButton name="camera" label="Save viewport image" disabled={!hasModel} onClick={() => viewport.current?.image()}/>
            <span className="toolbar-divider"/><button disabled={!selected} onClick={() => chooseFace(null)} title="Clear face selection"><Icon name="close" width={18}/><span>Clear selection</span></button>
          </div>
          {hasModel && <div className="model-caption"><Icon name="body" width={15}/>{c.filename}<span>{c.faceCount} faces</span></div>}
          {selected && <div className="selection-info" data-testid="selected-face"><span className="selection-dot"/><strong>Face {selected.index}</strong><span>{selected.areaMm2.toPrecision(4)} mm²</span><button title="Clear selection" aria-label="Clear selected face" onClick={() => chooseFace(null)}><Icon name="close" width={14}/></button></div>}
          {!!highlights.length && <div className="highlight-info"><span/>Assistant highlights: {highlights.map(n => `Face ${n}`).join(', ')}</div>}
          <div className="view-cube" aria-label="Camera orientation"><button className="cube-top" disabled={!hasModel} onClick={() => viewport.current?.view('top')}>TOP</button><button className="cube-front" disabled={!hasModel} onClick={() => viewport.current?.view('front')}>FRONT</button><button className="cube-right" disabled={!hasModel} onClick={() => viewport.current?.view('right')}>RIGHT</button><button className="cube-reset" aria-label="Reset camera" title="Isometric view" disabled={!hasModel} onClick={() => viewport.current?.view('iso')}><Icon name="refresh" width={13}/></button></div>
        </Viewport>
      </section>
      {chatOpen && <><div className="split-handle" role="separator" aria-label="Resize chat panel" aria-orientation="vertical" aria-valuemin={30} aria-valuemax={72} aria-valuenow={Math.round(split)} tabIndex={0} onPointerDown={beginResize} onKeyDown={e => { if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); setSplit(s => Math.max(30, Math.min(72, s + (e.key === 'ArrowRight' ? 2 : -2)))); } }}/>
      <section className="chat-panel" aria-label="Simulation assistant" style={{ flex: `${100 - split} 1 0%` }}>
        <LayoutPanelHeader icon="sparkles" title="Simulation assistant" onClose={() => setChatOpen(false)}><button className="icon-button small" aria-label="New conversation" title="New conversation" disabled={busy} onClick={() => setDialog('clear')}><Icon name="plus" width={16}/></button></LayoutPanelHeader>
        <div className="chat-scroll" ref={scroll} onScroll={e => { const el = e.currentTarget; scrollPinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 90; }}>
          <div className={`conversation ${hasConversation ? '' : 'welcome-conversation'}`}>
            {!hasConversation ? <div className="zoo-welcome px-4 py-3"><div className="assistant-emblem"><Icon name="sparkles" width={34} height={34}/></div><h2 className="text-lg font-semibold my-2">Let’s set up your simulation.</h2><p className="text-2 text-sm">{hasModel ? `${c.filename} is ready. Tell me what you want to learn about it.` : 'Bring your CAD model. We’ll work through the setup together, one decision at a time.'}</p><WelcomeItem graphic={<div className="welcome-graphic"><Icon name="model" width={32}/></div>} heading="Start with your model"><p>Import a STEP file and select the faces you want to discuss.</p></WelcomeItem><WelcomeItem graphic={<div className="welcome-graphic violet"><Icon name="plane" width={32}/></div>} heading="See exactly what I mean"><p>{c?.interactionMode === 'autonomous' ? 'I’ll identify faces and work through the setup, asking when essential details are missing.' : 'I’ll highlight proposed faces, explain assumptions, and ask you to confirm.'}</p></WelcomeItem><WelcomeItem graphic={<div className="welcome-graphic mint"><Icon name="beaker" width={32}/></div>} heading="From setup to results"><p>Run an Ansys analysis, compare meshes, and explore the result plots here.</p></WelcomeItem><div className="starter-prompts">{['Help me set up an analysis', 'Where should I apply a load?', 'Compare mesh sizes'].map(text => <button disabled={!hasModel || busy} key={text} onClick={() => send(text)}>{text}<Icon name="arrowShortRight" width={16}/></button>)}</div></div>
              : messages.map((m, i) => <MessageCard key={m.id || `${c.modelId}-${i}`} message={m} onCopyError={setError} onChoose={chooseAnswers} busy={busy} currentQuestion={c?.question}/>)}
            {busy && <div className="assistant-thinking" role="status"><span className="spinner"/>{exporting ? 'Exporting Mechanical setup…' : snapshot?.status || 'Working…'}</div>}
            {pending && !busy && <div className="confirmation-card" data-testid="confirmation-card"><div className="confirmation-title"><Icon name="clipboardCheckmark" width={18}/>Review before continuing</div><MarkdownText>{pending.summary}</MarkdownText>{pending.details && <details className="message-context"><summary>More context</summary><MarkdownText>{pending.details}</MarkdownText></details>}<div className="confirmation-actions"><button className="confirm-button" onClick={() => send('Confirm', snapshot.proposalToken)}><Icon name="checkmark" width={17}/>Confirm</button><button onClick={() => { setMessage('I want to change '); input.current?.focus(); }}>Change something</button></div></div>}
            {!!snapshot?.downloads.length && <div className="chat-downloads">{snapshot.downloads.map(d => <a key={d.url} href={d.url} download={d.filename}><Icon name="download" width={16}/>{d.label}</a>)}</div>}
          </div>
        </div>
        <div className="chat-composer"><Composer value={message} onChange={setMessage} onSend={() => send()} busy={busy || !connected || !snapshot} selected={selected} onImport={importModel} inputRef={input}
          mode={c?.interactionMode || 'guided'} visualEnabled={!!c?.visualAssistance?.enabled}
          onModeChange={mode => setPreferences(mode, !!c?.visualAssistance?.enabled)}
          onVisualChange={visual => setPreferences(c?.interactionMode || 'guided', visual)}/></div>
      </section></>}
      <nav className="right-rail" aria-label="Assistant panels"><IconButton name="sparkles" label="Toggle assistant" active={chatOpen} onClick={() => setChatOpen(!chatOpen)}/></nav>
    </div>
    <footer className="status-bar"><button onClick={() => setDialog('settings')} className="connection-status"><Icon name={connected ? 'network' : 'networkCrossedOut'} width={16}/><span>{connected ? 'Local workspace' : 'Reconnecting…'}</span></button><span className="status-separator"/><button onClick={() => setDialog('settings')}><Icon name="settings" width={14}/>Settings</button><span className="status-middle">{busy ? exporting ? 'Exporting Mechanical setup…' : snapshot?.status || 'Working…' : pending ? 'Waiting for your confirmation' : 'Ready'}</span><span>{selected ? `Face ${selected.index} selected` : 'No selection'}</span><span className="status-separator"/><span><Icon name="ruler" width={16}/>mm</span><span className="solver-badge"><Icon name="beaker" width={14}/>Ansys</span><button title="About" aria-label="About" onClick={() => setDialog('about')}><Icon name="questionMark" width={14}/></button></footer>
    {error && <div className="error-toast" role="alert"><Icon name="triangleExclamation" width={20}/><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError('')}><Icon name="close" width={16}/></button></div>}
    {!connected && <div className="offline-banner" role="status">Reconnecting to the local app. Your draft is kept here.</div>}
    {menu && <button className="menu-dismiss" aria-label="Close menu" onClick={() => setMenu(null)}/>}
    {dialog && <div className="modal-backdrop" onClick={() => setDialog(null)}><div className="studio-dialog" role="dialog" aria-modal="true" aria-label={dialog === 'commands' ? 'Commands' : dialog === 'clear' ? 'New conversation' : dialog === 'settings' ? 'Settings' : 'About Simulation Studio'} onClick={e => e.stopPropagation()}><LayoutPanelHeader icon={dialog === 'commands' ? 'command' : 'settings'} title={dialog === 'commands' ? 'Commands' : dialog === 'clear' ? 'New conversation' : dialog === 'settings' ? 'Settings' : 'Simulation Studio'} onClose={() => setDialog(null)}/><div className="dialog-content">
      {dialog === 'commands' && <div className="command-list">{[['importFile', 'Import CAD model', importModel], ['folder', 'Open saved models', () => { setPanel('files'); setDialog(null); }], ['viewFrame', 'Fit model to view', () => { viewport.current?.fit(); setDialog(null); }], ['clipboardCheckmark', 'Review simulation setup', () => { setPanel('setup'); setDialog(null); }], ['beaker', 'View results', () => { setPanel('results'); setDialog(null); }], ['code', 'Review generated Python', () => { setPanel('code'); setDialog(null); }]].map(([icon, text, action]) => <button key={text} onClick={action}><Icon name={icon} width={20}/>{text}<Icon name="arrowShortRight" width={16}/></button>)}</div>}
      {dialog === 'clear' && <><h2>Start a new conversation?</h2><p>Your CAD model, saved conditions, and run records will stay in this workspace.</p><div className="dialog-actions"><button onClick={() => setDialog(null)}>Keep conversation</button><button className="confirm-button" disabled={busy} onClick={async () => { try { await act('/clear', {}); setDialog(null); setMessage(''); } catch {} }}>New conversation</button></div></>}
      {dialog === 'settings' && <><div className="settings-row"><span>Appearance</span><div className="segmented"><button className={theme === 'light' ? 'active' : ''} onClick={() => setTheme('light')}>Light</button><button className={theme === 'dark' ? 'active' : ''} onClick={() => setTheme('dark')}>Dark</button></div></div><div className="settings-row"><span>Workspace split</span><button onClick={() => setSplit(50)}>Reset to 50 / 50</button></div><div className="settings-row"><span>Ansys worker</span><button disabled={checking} onClick={checkConnection}>{checking ? 'Checking…' : 'Check connection'}</button></div>{connectionMessage && <div className="connection-result"><MarkdownText>{connectionMessage}</MarkdownText></div>}<p className="muted">The assistant uses the model configured in OpenCode. Analyses run on your remote computer.</p></>}
      {dialog === 'about' && <><div className="about-brand"><div className="app-mark"><Icon name="model" width={28}/></div><h2>Simulation Studio</h2></div><p>A shared CAD workspace for setting up and reviewing Ansys simulations with an AI assistant.</p><p className="muted">Interface components adapted from Zoo Design Studio. Copyright © 2023 The Zoo Authors. MIT licensed. Inter font: SIL Open Font License.</p><details><summary>Third-party notices</summary><pre className="license-text">{licenseText}{'\n\nInter font\n\n'}{fontLicense}</pre></details><a href="https://github.com/KittyCAD/modeling-app" target="_blank" rel="noreferrer">Zoo Design Studio source ↗</a></>}
    </div></div></div>}
  </div>;
}

function EmptyPanel({ icon, text, onClick, action }) { return <div className="empty-panel"><Icon name={icon} width={28}/><p>{text}</p>{action && <button onClick={onClick}>{action}</button>}</div>; }

function ChoiceCards({ question, active, busy, onChoose }) {
  const [selected,setSelected] = useState([]);
  const disabled = !active || busy;
  return <form className="choice-form" onSubmit={e => {e.preventDefault(); if (!disabled && selected.length) onChoose(question.token,selected);}}>
    <fieldset disabled={disabled}><legend>{question.multiple ? 'Select all that apply' : 'Select one'}</legend>
      <div className="choice-grid">{question.choices.map(c => <label key={c.id} className={`choice-card ${selected.includes(c.id) ? 'selected' : ''}`}>
        <input type={question.multiple ? 'checkbox' : 'radio'} name={'question-'+question.token} checked={selected.includes(c.id)}
          onChange={() => setSelected(question.multiple ? selected.includes(c.id) ? selected.filter(i => i !== c.id) : [...selected,c.id] : [c.id])}/>
        <span>{c.label}</span></label>)}</div>
      {active && <button className="choice-submit" type="submit" disabled={disabled || !selected.length}>Continue</button>}
    </fieldset>
  </form>;
}

function MessageCard({ message: m, onCopyError, onChoose, busy, currentQuestion }) {
  const content = m.content;
  if (typeof content === 'object' && content.code) return <div className="message-code"><details><summary><Icon name="code" width={16}/><span>{content.title}</span><span className="code-language">Python</span><Icon name="caretDown" width={16}/></summary><pre><code>{content.code}</code></pre></details></div>;
  if (typeof content === 'object' && content.image) return <figure className="message-image"><a href={content.image} target="_blank" rel="noreferrer"><img src={content.image} alt={content.label} loading="lazy"/></a><figcaption>{content.label}</figcaption></figure>;
  if (typeof content !== 'string') return <p className="muted">{content.unavailable || 'This message is unavailable.'}</p>;
  const user = m.role === 'user';
  return <div className={`exchange ${user ? 'user-exchange' : 'assistant-exchange'}`}><ChatBubble side={user ? 'right' : 'left'} className="py-2" avatar={<span className={user ? 'message-avatar human' : 'message-avatar assistant'}><Icon name={user ? 'person' : 'sparkles'} width={18}/></span>}><MarkdownText>{content}</MarkdownText>{m.question && <ChoiceCards question={m.question} active={currentQuestion?.token === m.question.token} busy={busy} onChoose={onChoose}/>} {m.details && <details className="message-context"><summary>More context</summary><MarkdownText>{m.details}</MarkdownText></details>}</ChatBubble>{!user && <div className="response-toolbar"><button aria-label="Copy response" title="Copy response" onClick={() => copyText([content,m.details].filter(Boolean).join('\n\n')).catch(() => onCopyError('Could not copy the response.'))}><Icon name="clipboard" width={15}/></button></div>}</div>;
}

import licenseText from './vendor/zoo/LICENSE?raw';
import fontLicense from './vendor/zoo/fonts/LICENSE.txt?raw';
createRoot(document.getElementById('root')).render(<App/>);
