import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Activity as ActivityIcon, Archive, ArrowDown, ArrowRight, ArrowUp, Check, ChevronDown, CircleHelp, Code2, Copy, FileText, Folder, Loader2, Menu, MessageSquare, MoreHorizontal, PanelRightClose, PanelRightOpen, Pencil, Plus, RotateCcw, Search, Settings, Square, Terminal, WifiOff, X } from 'lucide-react';
import { api, ApiError, mergeActivities, mergePreview, statusLabels, type Activity, type Checkpoint, type Config, type Message, type Page, type Preview, type Proposal, type Run, type Session, type StepDetail, type View } from './api';
import ApprovalCard from './ApprovalCard';

const prompts = [
  { icon: MessageSquare, title: '梳理一个想法', detail: '拆开目标与约束', text: '我有一个想法：……请帮我梳理目标、约束和下一步。' },
  { icon: FileText, title: '整理一份计划', detail: '把事情排出顺序', text: '请帮我把这项任务整理成简洁的执行计划：……' },
  { icon: Search, title: '了解当前项目', detail: '按需查看工作区', text: '请先简要介绍当前工作区的项目结构。' },
];

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : '操作未完成，请重试。';
}

function MessageBubble({ message }: { message: Message }) {
  const [copied, setCopied] = useState(false);
  if (!message.text) return null;
  if (message.role === 'tool') return <details className="tool-result">
    <summary><Terminal size={14} /><span>{message.tool_name ?? '工具'} 执行结果</span><ChevronDown size={14} /></summary>
    <pre>{message.text}</pre>{message.truncated && <small>内容较长，已截断展示。</small>}
  </details>;
  return <article className={`message ${message.role}`}>
    <div className="message-meta"><span className={`avatar ${message.role}`}>{message.role === 'user' ? '你' : 'π'}</span><b>{message.role === 'user' ? '你' : 'Pi'}</b>{message.role === 'assistant' && <span className="muted">工作区助手</span>}</div>
    <div className="message-body"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{
      a: ({ children, href }) => <a href={href} target="_blank" rel="noreferrer">{children}</a>,
      img: ({ alt }) => <span className="muted">[图片：{alt}]</span>,
    }}>{message.text}</ReactMarkdown></div>
    {message.truncated && <small className="muted">内容较长，已截断展示。</small>}
    {message.role === 'assistant' && <button className="copy-button" aria-label="复制回复" onClick={async () => {
      try { await navigator.clipboard.writeText(message.text); setCopied(true); setTimeout(() => setCopied(false), 1800); } catch { setCopied(false); }
    }}>{copied ? <Check size={13} /> : <Copy size={13} />}{copied ? '已复制' : '复制'}</button>}
  </article>;
}

function phaseLabel(item: Activity): string {
  const labels: Record<string, string> = { run_start: '任务开始', before_model: '正在生成回复', after_model: '模型响应完成', before_tool: `调用 ${item.tool_name}`, after_tool: `${item.tool_name} 返回结果`, run_end: item.outcome === 'completed' ? '任务完成' : item.outcome === 'cancelled' ? '任务已停止' : item.outcome === 'awaiting_approval' ? '等待人工审批' : '任务未完成' };
  return labels[item.phase] ?? item.phase;
}

function StepMessages({ label, messages }: { label: string; messages: StepDetail['input'] }) {
  return <section className="step-messages"><h3>{label}</h3>{messages.length ? messages.map((message, index) => <article key={`${message.role}-${index}`}><small>{message.role === 'user' ? '用户输入' : message.role === 'tool' ? `工具 ${message.tool_name ?? ''} 输出` : '模型消息'}</small><pre>{message.text || (message.tool_calls?.length ? '' : '（无文本内容）')}</pre>{message.tool_calls?.map((call, callIndex) => <div className="call-block" key={`${call.name}-${callIndex}`}><b>{call.name}</b><pre>{JSON.stringify(call.args, null, 2)}</pre></div>)}</article>) : <p className="muted">此节点没有可展示内容</p>}</section>;
}

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState<string | null>(() => localStorage.getItem('pi.session'));
  const [view, setView] = useState<View | null>(null);
  const [older, setOlder] = useState<Message[]>([]);
  const [page, setPage] = useState<Page | null>(null);
  const [draft, setDraft] = useState('');
  const [search, setSearch] = useState('');
  const [archived, setArchived] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [creating, setCreating] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [connected, setConnected] = useState(false);
  const [rightOpen, setRightOpen] = useState(() => window.matchMedia('(min-width: 721px)').matches);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const [showHelp, setShowHelp] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [workspaceDraft, setWorkspaceDraft] = useState('');
  const [toolsDraft, setToolsDraft] = useState<string[]>([]);
  const [toolLimitsDraft, setToolLimitsDraft] = useState<Record<string, number>>({});
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsError, setSettingsError] = useState('');
  const [stepDetail, setStepDetail] = useState<StepDetail | null>(null);
  const [stepLoading, setStepLoading] = useState(false);
  const [stepError, setStepError] = useState('');
  const [branchOpen, setBranchOpen] = useState(false);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [checkpointId, setCheckpointId] = useState('');
  const [branchError, setBranchError] = useState('');
  const [branchLoading, setBranchLoading] = useState(false);
  const [continuing, setContinuing] = useState(false);
  const [approving, setApproving] = useState<string | null>(null);
  const approvalRequests = useRef(new Map<string, string>());
  const actionRequest = useRef<{ kind: string; session: string; checkpoint: string; id: string } | null>(null);
  const [pending, setPending] = useState<{ session: string; text: string; id: string } | null>(null);
  const activeId = useRef(selected);
  const fetchVersion = useRef(0);
  const bootVersion = useRef(0);
  const listVersion = useRef(0);
  const busyRef = useRef(false);
  const scroll = useRef<HTMLDivElement>(null);
  const autoScroll = useRef(true);
  const input = useRef<HTMLTextAreaElement>(null);
  const running = view?.run?.status === 'running';

  useEffect(() => { activeId.current = selected; if (selected) localStorage.setItem('pi.session', selected); else localStorage.removeItem('pi.session'); }, [selected]);

  const loadSessions = useCallback(async () => {
    const version = ++listVersion.current;
    const result = await api<Session[]>(`/sessions?archived=${archived}`);
    if (version === listVersion.current) setSessions(result);
  }, [archived]);

  const loadView = useCallback(async (id: string) => {
    const version = ++fetchVersion.current;
    const result = await api<View>(`/sessions/${id}`);
    if (activeId.current === id && fetchVersion.current === version) {
      setView(current => ({ ...result, preview: result.run?.status === 'running' && current?.server_epoch === result.server_epoch ? mergePreview(current.preview, result.preview) : result.preview }));
      setPending(current => current?.session === id && result.run?.request_id === current.id ? null : current);
    }
  }, []);

  const bootstrap = useCallback(async () => {
    const version = ++bootVersion.current;
    try {
      const value = await api<Config>('/bootstrap');
      if (version !== bootVersion.current) return;
      setConfig(value); setError('');
    } catch (reason) { setError(errorText(reason)); }
  }, []);

  useEffect(() => { void bootstrap(); }, [bootstrap]);
  useEffect(() => { if (config) void loadSessions().catch(reason => setError(errorText(reason))); }, [config, loadSessions]);
  useEffect(() => {
    const media = window.matchMedia('(min-width: 721px)');
    const syncDetails = () => setRightOpen(media.matches);
    media.addEventListener('change', syncDetails);
    syncDetails();
    return () => media.removeEventListener('change', syncDetails);
  }, []);

  useEffect(() => {
    setView(null); setOlder([]); setPage(null); setMenuOpen(false); setError(''); setConnected(false); setCancelling(false); setBranchOpen(false); setStepDetail(null); setStepError('');
    autoScroll.current = true;
    if (!selected || !config) { setLoading(false); return; }
    const id = selected;
    setLoading(true);
    let alive = true;
    const refresh = () => loadView(id).catch(reason => {
      if (alive) {
        setError(errorText(reason));
        if (reason instanceof ApiError && reason.status === 401) void bootstrap();
      }
    }).finally(() => { if (alive) setLoading(false); });
    void refresh();
    const stream = new EventSource(`/api/sessions/${id}/events`);
    stream.addEventListener('sync', () => { setConnected(true); void refresh(); });
    stream.addEventListener('activity', event => {
      if (!alive) return;
      const entries = JSON.parse((event as MessageEvent).data) as Activity[];
      setView(current => current?.session.session_id === id ? { ...current, activities: mergeActivities(current.activities, entries) } : current);
      void refresh();
      if (entries.some(item => item.phase === 'run_end')) { setCancelling(false); void loadSessions(); }
    });
    stream.addEventListener('preview', event => {
      if (!alive) return;
      const preview = JSON.parse((event as MessageEvent).data) as Preview;
      setView(current => current?.session.session_id === id && current.run?.run_id === preview.run_id && current.run.status === 'running' ? { ...current, preview: mergePreview(current.preview, preview) } : current);
    });
    stream.onerror = () => { if (alive) setConnected(false); };
    // Polling is a fallback for dropped terminal notifications and a restarted service.
    const timer = window.setInterval(() => { void refresh(); }, 5000);
    return () => { alive = false; stream.close(); clearInterval(timer); fetchVersion.current++; };
  }, [selected, config, loadView, loadSessions, bootstrap]);

  useEffect(() => {
    if (autoScroll.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [view?.history.messages, view?.preview, pending]);

  function checkpointRequest(kind: string, id: string, checkpoint: string) {
    const prior = actionRequest.current;
    if (!prior || prior.kind !== kind || prior.session !== id || prior.checkpoint !== checkpoint) {
      actionRequest.current = { kind, session: id, checkpoint, id: crypto.randomUUID() };
    }
    return { checkpoint_id: checkpoint, request_id: actionRequest.current!.id };
  }

  async function decideProposal(proposal: Proposal, decision: 'approve' | 'reject') {
    const id = selected;
    if (!id || busyRef.current || running || view?.session.archived) return;
    const key = `${id}:${proposal.proposal_id}:${proposal.version}:${decision}`;
    if (!approvalRequests.current.has(key)) approvalRequests.current.set(key, crypto.randomUUID());
    busyRef.current = true; setApproving(proposal.proposal_id); setError('');
    try {
      await api<Run>(`/sessions/${id}/proposals/${proposal.proposal_id}/decision`, { method: 'POST', body: JSON.stringify({ version: proposal.version, decision, request_id: approvalRequests.current.get(key) }) });
      await loadView(id);
    } catch (reason) { setError(errorText(reason)); void loadView(id); }
    finally { busyRef.current = false; setApproving(null); }
  }

  async function resume() {
    const id = selected;
    const checkpoint = view?.history.checkpoint_id;
    if (!id || !checkpoint || busyRef.current || running) return;
    busyRef.current = true; setContinuing(true); setError('');
    try {
      await api<Run>(`/sessions/${id}/resume`, { method: 'POST', body: JSON.stringify(checkpointRequest('resume', id, checkpoint)) });
      await loadView(id);
    } catch (reason) { setError(errorText(reason)); }
    finally { busyRef.current = false; setContinuing(false); }
  }

  async function openBranches() {
    if (!selected) return;
    const id = selected;
    setMenuOpen(false); setBranchOpen(true); setBranchLoading(true); setBranchError(''); setCheckpoints([]); setCheckpointId('');
    try {
      const entries = await api<Checkpoint[]>(`/sessions/${id}/checkpoints`);
      if (activeId.current !== id) return;
      setCheckpoints(entries); setCheckpointId(entries[0]?.checkpoint_id ?? '');
    } catch (reason) { setBranchError(errorText(reason)); }
    finally { setBranchLoading(false); }
  }

  async function createBranch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !checkpointId || busyRef.current) return;
    const id = selected;
    busyRef.current = true; setBranchLoading(true); setBranchError('');
    try {
      const branch = await api<Session>(`/sessions/${id}/branches`, { method: 'POST', body: JSON.stringify(checkpointRequest('branch', id, checkpointId)) });
      setBranchOpen(false); activeId.current = branch.session_id; setSelected(branch.session_id); setArchived(false);
      await loadSessions();
    } catch (reason) { setBranchError(errorText(reason)); }
    finally { busyRef.current = false; setBranchLoading(false); }
  }

  async function newSession() {
    if (busyRef.current) return;
    busyRef.current = true;
    setCreating(true); setDraft('');
    try {
      const session = await api<Session>('/sessions', { method: 'POST' });
      setArchived(false); setSelected(session.session_id); setSidebarOpen(false);
      await loadSessions(); input.current?.focus();
    } catch (reason) { setError(errorText(reason)); } finally { busyRef.current = false; setCreating(false); }
  }

  async function send(text = draft, retry = false) {
    if ((!text.trim() && !retry) || busyRef.current || running || view?.needs_recovery || view?.awaiting_approval || view?.session.archived) return;
    busyRef.current = true; setSending(true); setError(''); autoScroll.current = true;
    try {
      let id = selected;
      if (!id) {
        const created = await api<Session>('/sessions', { method: 'POST' });
        id = created.session_id; activeId.current = id; setSelected(id);
      }
      const request = retry && pending?.session === id ? pending : { session: id, text: text.trim(), id: crypto.randomUUID() };
      setPending(request); setDraft('');
      await api<Run>(`/sessions/${id}/runs`, { method: 'POST', body: JSON.stringify({ text: request.text, request_id: request.id }) });
      await loadView(id); await loadSessions();
    } catch (reason) {
      setError(errorText(reason));
      if (reason instanceof ApiError && reason.status < 500) {
        setDraft(retry && pending ? pending.text : text); setPending(null);
      }
    } finally { setSending(false); busyRef.current = false; input.current?.focus(); }
  }

  async function stop() {
    if (!view?.run || cancelling) return;
    setCancelling(true);
    try {
      await api(`/runs/${view.run.run_id}/cancel`, { method: 'POST' });
      await loadView(view.session.session_id);
    } catch (reason) { setError(errorText(reason)); } finally { setCancelling(false); }
  }

  async function editSession(edit: { title?: string; archived?: boolean }) {
    if (!selected) return;
    try {
      await api(`/sessions/${selected}`, { method: 'PATCH', body: JSON.stringify(edit) });
      setMenuOpen(false); setRenaming(false);
      if (edit.archived !== undefined) setSelected(null); else await loadView(selected);
      await loadSessions();
    } catch (reason) { setError(errorText(reason)); }
  }

  async function moreHistory() {
    const current = page ?? view?.history;
    if (!selected || !current?.checkpoint_id || current.next_before === null) return;
    const id = selected;
    try {
      const loaded = await api<Page>(`/sessions/${id}/messages?checkpoint=${encodeURIComponent(current.checkpoint_id)}&before=${current.next_before}`);
      if (activeId.current !== id) return;
      autoScroll.current = false; setOlder(previous => [...loaded.messages, ...previous]); setPage(loaded);
    } catch (reason) { setError(errorText(reason)); }
  }

  function openSettings() {
    setWorkspaceDraft(config?.workspace ?? '');
    setToolsDraft(config?.capabilities ?? []);
    setToolLimitsDraft(config?.tool_limits ?? {});
    setError(''); setSettingsError(''); setSettingsOpen(true);
  }

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!config) return;
    setSavingSettings(true); setSettingsError('');
    try {
      const updated = await api<Config>('/settings', { method: 'PUT', body: JSON.stringify({ workspace: workspaceDraft.trim(), tools: toolsDraft, tool_limits: toolLimitsDraft }) });
      const workspaceChanged = updated.workspace !== config.workspace;
      setConfig(updated); setSettingsOpen(false);
      if (workspaceChanged) setSelected(null);
    } catch (reason) { setSettingsError(errorText(reason)); }
    finally { setSavingSettings(false); }
  }

  async function openStep(eventId: number) {
    if (!selected) return;
    setStepLoading(true); setStepError(''); setStepDetail(null);
    try { setStepDetail(await api<StepDetail>(`/sessions/${selected}/activities/${eventId}`)); }
    catch (reason) { setStepError(errorText(reason)); }
    finally { setStepLoading(false); }
  }

  const shown = sessions.filter(item => item.title.toLowerCase().includes(search.toLowerCase()));
  const messageMap = new Map([...older, ...(view?.history.messages ?? [])].map(item => [item.message_id, item]));
  const messages = [...messageMap.values()];
  const preview = view?.preview;
  const previewMessage: Message | null = running && preview && preview.status !== 'discarded' && preview.text && !messageMap.has(preview.message_id) ? { message_id: preview.message_id, role: 'assistant', text: preview.text, tool_name: null, truncated: preview.truncated } : null;
  const hasMessages = messages.some(item => item.text);
  const activity = view?.activities ?? [];
  const latestRunId = view?.run?.run_id;
  const currentActivities = activity.filter(item => item.run_id === latestRunId);
  const toolCount = currentActivities.filter(item => item.phase === 'after_tool').length;

  return <div className={`workbench ${rightOpen ? '' : 'hide-details'}`}>
    {sidebarOpen && <button className="sidebar-scrim" aria-label="关闭会话栏" onClick={() => setSidebarOpen(false)} />}
    <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
      <a className="brand" href="#" onClick={event => { event.preventDefault(); setSelected(null); }}><span className="brand-mark">π</span><span>Pi<span className="brand-sub">WORKBENCH</span></span></a>
      <button className="new-session" onClick={() => void newSession()} disabled={!config}><Plus size={17} />新建会话<span>＋</span></button>
      <label className="search"><Search size={15} /><input aria-label="搜索会话" placeholder="搜索会话" value={search} onChange={event => setSearch(event.target.value)} /><kbd>⌕</kbd></label>
      <div className="section-label"><span>{archived ? '已归档' : '最近会话'}</span><span>{shown.length}</span></div>
      <nav className="session-list" aria-label="会话列表">
        {shown.map(item => <button key={item.session_id} className={`session-item ${selected === item.session_id ? 'active' : ''}`} onClick={() => { setSelected(item.session_id); setSidebarOpen(false); }}>
          <MessageSquare size={15} /><span>{item.title}</span><i /></button>)}
        {!shown.length && <p className="empty-list">{search ? '没有匹配的会话' : archived ? '还没有归档会话' : '你的任务会保存在这里'}</p>}
      </nav>
      <div className="sidebar-bottom">
        <button className={archived ? 'selected' : ''} onClick={() => { setArchived(value => !value); setSelected(null); }}><Archive size={16} />{archived ? '返回最近会话' : '已归档会话'}</button>
        <button onClick={() => setShowHelp(true)}><CircleHelp size={16} />使用说明</button>
        <button onClick={openSettings}><Settings size={16} />工作区与工具</button>
        <div className="workspace-card"><div className="workspace-icon"><Folder size={18} /></div><div><b>{(view?.session.workspace ?? config?.workspace)?.split(/[\\/]/).pop() ?? '本地工作区'}</b><small><span className="status-dot" />本机 · {config?.capabilities.length ?? 0} 项工具</small></div></div>
      </div>
    </aside>

    <main className="main-panel">
      <header className="topbar">
        <button className="icon-button mobile-menu" aria-label="打开会话栏" onClick={() => setSidebarOpen(true)}><Menu size={19} /></button>
        <div className="breadcrumb"><span>工作台</span><span className="slash">/</span><b>{view?.session.title ?? '新任务'}</b></div>
        <div className="topbar-actions"><span className={`connection ${!connected && selected ? 'offline' : ''}`}><span className="status-dot" />{!config ? '未连接' : !connected && selected ? '重连中' : '本地已连接'}</span>
          {selected && <div className="menu-wrap"><button aria-label="会话操作" className="icon-button" onClick={() => setMenuOpen(!menuOpen)}><MoreHorizontal size={19} /></button>{menuOpen && <div className="dropdown"><button onClick={() => { setTitleDraft(view?.session.title ?? ''); setRenaming(true); setMenuOpen(false); }}><Pencil size={14} />重命名</button><button disabled={running || continuing || view?.session.archived} onClick={() => void openBranches()}><Plus size={14} />从检查点创建分支</button><button disabled={running} onClick={() => void editSession({ archived: !view?.session.archived })}><Archive size={14} />{view?.session.archived ? '恢复会话' : '归档会话'}</button></div>}</div>}
          <button className="icon-button" aria-label={rightOpen ? '收起运行详情' : '展开运行详情'} onClick={() => setRightOpen(!rightOpen)}>{rightOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}</button>
        </div>
      </header>

      <div className="conversation" ref={scroll} onScroll={() => { const element = scroll.current; if (element) autoScroll.current = element.scrollHeight - element.scrollTop - element.clientHeight < 100; }}>
        {loading && !view ? <div className="loading-state"><Loader2 className="spin" size={20} />正在加载会话…</div> : !hasMessages && !pending ? <div className="welcome">
          <div className="welcome-emblem"><span>π</span><i /></div>
          <div className="eyebrow">你的本地 AI 工作空间</div>
          <h1>让每个想法，<br /><span>都能找到下一步。</span></h1>
          <p>写作、分析、规划，或处理工作区任务。<br />需要读取文件时，执行过程会清楚展示。</p>
          <div className="prompt-cards">{prompts.map(({ icon: Icon, title, detail, text }) => <button key={title} onClick={() => { setDraft(text); input.current?.focus(); }}><Icon size={20} /><b>{title}</b><span>{detail}<ArrowRight size={14} /></span></button>)}</div>
          <div className="welcome-note"><span className="small-pi">π</span>{config?.provider === 'fake' ? '离线演示已就绪 · 可按需使用本地工具' : '由你选择工作区与可用工具 · 本机运行'}</div>
        </div> : <div className="message-list">
          {(page ?? view?.history)?.next_before != null && <button className="history-button" onClick={() => void moreHistory()}>加载更早的消息 <ArrowUp size={13} /></button>}
          {messages.map(message => <MessageBubble key={message.message_id} message={message} />)}
          {view?.proposals?.map(proposal => <ApprovalCard key={proposal.proposal_id} proposal={proposal} disabled={!!running || !!view.session.archived || !!approving} busy={approving === proposal.proposal_id} decide={(item, decision) => void decideProposal(item, decision)} />)}
          {previewMessage && <div className="stream-preview" aria-label="正在生成的回复"><MessageBubble message={previewMessage} /><small className="muted">正在生成…</small></div>}
          {pending?.session === selected && !messages.some(item => item.role === 'user' && item.text === pending.text) && <div className="message user pending"><div className="message-meta"><span className="avatar user">你</span><b>你</b><span className="muted">等待确认</span></div><div className="message-body">{pending.text}</div></div>}
          {running && <div className="thinking"><span className="avatar assistant">π</span><div className="thinking-dots"><i /><i /><i /></div><span>{cancelling ? '正在停止并清理…' : currentActivities.length ? phaseLabel(currentActivities[currentActivities.length - 1]) : '正在准备任务…'}</span></div>}
          {view?.run && !running && <div className={`run-summary ${view.run.status}`}><span className="status-dot" />{statusLabels[view.run.status]}{toolCount > 0 && <span> · {toolCount} 次工具调用</span>}</div>}
        </div>}
      </div>

      <div className="composer-zone">
        {error && <div className="error-banner" role="alert"><WifiOff size={16} /><span>{error}</span>{pending?.session === selected && <button onClick={() => void send('', true)}>核对并重试</button>}<button className="icon-button" aria-label="关闭提示" onClick={() => setError('')}><X size={14} /></button></div>}
        {!config && <button className="reconnect-button" onClick={() => void bootstrap()}><RotateCcw size={15} />重新连接本地服务</button>}
        {view?.awaiting_approval && <div className="notice">任务已暂停，请先查看上方提案并批准或拒绝。刷新页面会保留提案。</div>}
        {view?.needs_recovery && <div className="notice">上一轮尚未完成。继续运行会恢复待完成节点；已认领但结果不明的操作不会重跑。<button disabled={continuing || view.session.archived} onClick={() => void resume()}>{continuing ? "正在继续…" : "继续运行"}</button><button disabled={continuing || view.session.archived} onClick={() => void openBranches()}>从已完成检查点创建分支</button></div>}
        {view?.run?.error && !running && <div className="notice">{view.run.error}</div>}
        {view?.session.archived ? <div className="notice">这个会话已归档。<button onClick={() => void editSession({ archived: false })}>恢复会话</button></div> : <div className={`composer ${running ? 'is-running' : ''}`}>
          <textarea ref={input} aria-label="输入消息" placeholder="给 Pi 一个任务，或问问这个项目…" value={draft} maxLength={32768} rows={2} disabled={!config || view?.needs_recovery || view?.awaiting_approval || sending || creating} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) { event.preventDefault(); if (!running) void send(); } }} />
          <div className="composer-toolbar"><div className="model-chip"><span className="model-symbol">✳</span>{config?.model ?? '连接模型中'}<span className="model-mode">{config?.provider === 'fake' ? 'DEMO' : 'API'}</span></div><div className="send-area"><small>{running ? '刷新页面不会中断运行' : 'Enter 发送 · Shift + Enter 换行'}</small>{running ? <button className="stop-button" aria-label="停止运行" onClick={() => void stop()} disabled={cancelling}>{cancelling ? <Loader2 size={16} className="spin" /> : <Square size={13} fill="currentColor" />}</button> : <button className="send-button" aria-label="发送消息" disabled={!draft.trim() || sending || creating || !config || !!view?.needs_recovery || !!view?.awaiting_approval} onClick={() => void send()}>{sending ? <Loader2 size={18} className="spin" /> : <ArrowUp size={19} />}</button>}</div></div>
        </div>}
      <div className="composer-footer"><span><Folder size={12} />{(view?.session.workspace ?? config?.workspace)?.split(/[\\/]/).pop() ?? '本地工作区'}</span><span>Pi 的回答可能有误，请核对重要信息。</span></div>
      </div>
    </main>

    {rightOpen && <aside className="details-panel"><div className="details-heading"><ActivityIcon size={16} /><b>运行详情</b><span>LIVE</span><button className="icon-button" aria-label="设置工作区和工具" onClick={openSettings}><Settings size={15} /></button></div>
      <div className="detail-section"><div className="section-label">当前环境 <button className="text-button" onClick={openSettings}>修改</button></div><div className="environment-card"><div><span className="workspace-icon"><Code2 size={18} /></span><b>本地工作区</b><span className="readonly">{config?.approval_capabilities?.length ? '修改需审批' : '只读'}</span></div><p title={view?.session.workspace ?? config?.workspace}>{view?.session.workspace ?? config?.workspace ?? '等待服务连接'}</p></div><div className="tools-label">可用工具</div><div className="tool-chips">{(config?.capabilities ?? []).map(tool => <span key={tool}>{tool === 'read' ? <FileText size={12} /> : tool === 'list' ? <Folder size={12} /> : <Search size={12} />}{tool}</span>)}{(config?.approval_capabilities ?? []).map(tool => <span key={tool}><Check size={12} />{tool} · 审批</span>)}{!config?.capabilities.length && !config?.approval_capabilities?.length && <small>未启用工作区工具</small>}</div></div>
      <div className="detail-section activity-section"><div className="section-label"><span>执行过程</span>{running && <span className="pulse-label">运行中</span>}</div>
        {currentActivities.length ? <ol className="activity-list">{currentActivities.map((item, index) => { const inspectable = item.phase === 'after_model' || item.phase === 'after_tool'; return <li key={item.event_id} className={`${item.outcome === 'failed' ? 'failed' : ''} ${inspectable ? 'inspectable' : ''}`}><span className="timeline-dot">{running && index === currentActivities.length - 1 ? <Loader2 size={12} className="spin" /> : item.phase.includes('tool') ? <Terminal size={11} /> : <Check size={11} />}</span><div><button className="activity-node" disabled={!inspectable} onClick={() => void openStep(item.event_id)}>{phaseLabel(item)}{inspectable && <ArrowRight size={12} />}</button><time>{new Date(item.created_at).toLocaleTimeString('zh-CN', { hour12: false })}</time></div></li>; })}</ol> : <div className="activity-empty"><div className="empty-route"><i /><span /><i /><span /><i /></div><b>每一步，都有迹可循</b><p>发送任务后，这里会显示<br />模型响应与工具执行过程。</p></div>}
      </div>
      <div className="detail-bottom"><span className="status-dot" /><div><b>会话自动保存</b><p>关闭页面后，仍可回来继续。</p></div></div>
    </aside>}

    {branchOpen && <div className="modal-backdrop" onClick={() => { if (!branchLoading) setBranchOpen(false); }}><section className="modal" role="dialog" aria-modal="true" aria-label="创建会话分支" onClick={event => event.stopPropagation()}><button className="icon-button modal-close" aria-label="关闭分支对话框" disabled={branchLoading} onClick={() => setBranchOpen(false)}><X size={18} /></button><form onSubmit={event => void createBranch(event)}><h2>从检查点创建分支</h2><p>复制已完成的对话到独立会话，保留原会话和工作区。</p><label>已完成的检查点<select aria-label="已完成的检查点" value={checkpointId} onChange={event => setCheckpointId(event.target.value)} disabled={branchLoading}>{checkpoints.map(item => <option key={item.checkpoint_id} value={item.checkpoint_id}>{new Date(item.created_at).toLocaleString()} · {item.preview}</option>)}</select></label>{!branchLoading && !checkpoints.length && <p>还没有已完成的检查点。可以先继续当前运行，或新建会话。</p>}{branchError && <div className="error-banner" role="alert">{branchError}</div>}<button className="primary-button" disabled={branchLoading || !checkpointId} type="submit">{branchLoading ? '正在处理…' : '创建分支'}</button></form></section></div>}

    {(renaming || showHelp || settingsOpen) && <div className="modal-backdrop" onClick={() => { setRenaming(false); setShowHelp(false); setSettingsOpen(false); }}><section className={`modal ${settingsOpen ? 'settings-modal' : ''}`} role="dialog" aria-modal="true" aria-label={renaming ? '重命名会话' : settingsOpen ? '工作区与工具设置' : '使用说明'} onClick={event => event.stopPropagation()}><button className="icon-button modal-close" aria-label="关闭对话框" onClick={() => { setRenaming(false); setShowHelp(false); setSettingsOpen(false); }}><X size={18} /></button>{renaming ? <form onSubmit={event => { event.preventDefault(); if (titleDraft.trim()) void editSession({ title: titleDraft.trim() }); }}><h2>重命名会话</h2><label>会话名称<input autoFocus value={titleDraft} maxLength={100} onChange={event => setTitleDraft(event.target.value)} /></label><button className="primary-button" type="submit" disabled={!titleDraft.trim()}>保存名称</button></form> : settingsOpen ? <form onSubmit={event => void saveSettings(event)}><div className="eyebrow">PI WORKSPACE CONFIG</div><h2>工作区与工具</h2><label>本机目录<input autoFocus value={workspaceDraft} onChange={event => setWorkspaceDraft(event.target.value)} placeholder="例如 C:\\workspace\\my-project" /></label><p className="form-note">填写本机已存在的目录。新会话使用新工作区；已有会话保留创建时的工作区。每个数值表示本轮用户请求中该工具最多执行次数；0 表示不允许调用。</p><fieldset><legend>只读工具与单轮调用上限</legend>{[['read', '读取文件'], ['list', '列出目录'], ['search', '搜索文本']].map(([name, label]) => <div className="tool-option" key={name}><label className="tool-enabled"><input type="checkbox" checked={toolsDraft.includes(name)} onChange={event => setToolsDraft(current => event.target.checked ? [...current, name] : current.filter(tool => tool !== name))} /><span><b>{name}</b><small>{label}</small></span></label><label className="limit-input">最多<input aria-label={`${name} 最大调用次数`} type="number" min="0" max="20" value={toolLimitsDraft[name] ?? 0} onChange={event => setToolLimitsDraft(current => ({ ...current, [name]: Math.max(0, Math.min(20, Number(event.target.value))) }))} />次</label></div>)}</fieldset>{settingsError && <div className="error-banner" role="alert">{settingsError}</div>}<button className="primary-button" type="submit" disabled={savingSettings || !workspaceDraft.trim()}>{savingSettings ? '正在保存…' : '保存设置'}</button></form> : <><div className="brand-mark">π</div><h2>你的本地 AI 工作空间。</h2><p>你可以聊天、写作、分析、规划，也可以让 Pi 按需查看当前工作区。</p><p>执行过程会在右侧呈现。工作区和只读工具可以在设置中更换。</p><p>会话保存在本机。使用真实模型时，服务密钥只在本机服务端配置。</p><button className="primary-button" onClick={() => setShowHelp(false)}>开始使用 <ArrowRight size={15} /></button></>}</section></div>}

    {(stepLoading || stepError || stepDetail) && <div className="modal-backdrop" onClick={() => { setStepDetail(null); setStepError(''); }}><section className="modal step-modal" role="dialog" aria-modal="true" aria-label="执行节点详情" onClick={event => event.stopPropagation()}><button className="icon-button modal-close" aria-label="关闭节点详情" onClick={() => { setStepDetail(null); setStepError(''); }}><X size={18} /></button>{stepLoading ? <div className="loading-state"><Loader2 size={18} className="spin" />读取 checkpoint 展示快照…</div> : stepError ? <><h2>节点详情暂不可用</h2><p>{stepError}</p></> : stepDetail && <><div className="eyebrow">RUN NODE / {stepDetail.node.toUpperCase()}</div><h2>{stepDetail.title}</h2><div className="step-grid"><StepMessages label="输入" messages={stepDetail.input} /><StepMessages label="输出" messages={stepDetail.output} /></div><div className="snapshot-grid"><details><summary>执行前快照</summary><pre>{JSON.stringify(stepDetail.snapshot_before, null, 2)}</pre></details><details><summary>执行后快照</summary><pre>{JSON.stringify(stepDetail.snapshot_after, null, 2)}</pre></details></div></>}</section></div>}
  </div>;
}
