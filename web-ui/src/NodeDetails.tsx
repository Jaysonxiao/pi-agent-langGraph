import { useEffect, useRef, useState } from 'react';
import { Check, Copy, Loader2, X } from 'lucide-react';
import { toolLabel, type StepDetail } from './api';

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return <button className="snapshot-copy" aria-label={label} onClick={async () => {
    try { await navigator.clipboard.writeText(text); setCopied(true); } catch { setCopied(false); }
  }}>{copied ? <Check size={13} /> : <Copy size={13} />}{copied ? '已复制' : '复制'}</button>;
}

function StepMessages({ label, messages }: { label: string; messages: StepDetail['input'] }) {
  return <section className="step-messages"><div className="step-panel-heading"><h3>{label}</h3><span>{messages.length} 条消息</span></div><div className="step-panel-content">{messages.length ? messages.map((message, index) => <article key={index}><small>{message.role === 'user' ? '用户输入' : message.role === 'tool' ? `工具 ${toolLabel(message.tool_name)} 输出` : '模型消息'}</small><pre>{message.text || (message.tool_calls?.length ? '' : '（无文本内容）')}</pre>{message.tool_calls?.map((call, callIndex) => <div className="call-block" key={`${call.name}-${callIndex}`}><b>{toolLabel(call.name)}</b><pre>{JSON.stringify(call.args, null, 2)}</pre></div>)}</article>) : <p className="muted">此节点没有可展示内容</p>}</div></section>;
}

function Snapshot({ label, value }: { label: string; value: Record<string, unknown> }) {
  return <details open><summary>{label}</summary><div className="snapshot-toolbar"><span>状态 {String(value.status ?? '未知')} · 工具轮次 {String(value.tool_rounds ?? 0)}</span><CopyButton label={`复制${label}`} text={JSON.stringify(value, null, 2)} /></div><pre>{JSON.stringify(value, null, 2)}</pre></details>;
}

export default function NodeDetails({ loading, error, detail, close }: {
  loading: boolean; error: string; detail: StepDetail | null; close: () => void;
}) {
  const root = useRef<HTMLElement>(null);
  const closeRef = useRef(close); closeRef.current = close;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    root.current?.querySelector<HTMLButtonElement>('button')?.focus();
    return () => { previous?.focus(); };
  }, []);
  return <div className="modal-backdrop" onClick={close}><section ref={root} className="modal step-modal" role="dialog" aria-modal="true" aria-labelledby="node-title"
    onClick={event => event.stopPropagation()} onKeyDown={event => {
      if (event.key === 'Escape') { event.stopPropagation(); closeRef.current(); }
      if (event.key === 'Tab') {
        const buttons = root.current?.querySelectorAll<HTMLButtonElement>('button');
        if (!buttons?.length) return;
        const first = buttons[0], last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    }}>
    <header className="step-header"><div><div className="eyebrow">{detail ? `${detail.node === 'tools' ? 'TOOLS' : 'MODEL'} · 执行详情` : '执行详情'}</div><h2 id="node-title">执行节点详情{detail && <span> / {detail.title.replace('propose_command', 'command')}</span>}</h2></div><button className="icon-button" aria-label="关闭节点详情" onClick={close}><X size={19} /></button></header>
    <div className="step-body">{loading ? <div className="loading-state"><Loader2 size={18} className="spin" />读取节点快照…</div> : error ? <div className="step-error" role="alert"><h3>节点详情暂不可用</h3><p>{error}</p></div> : detail && <>
      {detail.checkpoint_id && <div className="checkpoint-reference"><span>Checkpoint:</span><code>{detail.checkpoint_id}</code><CopyButton label="复制 checkpoint ID" text={detail.checkpoint_id} /></div>}
      {detail.node === 'tools' && <p className="form-note">快照覆盖本批全部工具调用；下方输出对应当前工具。</p>}
      <div className="step-grid"><StepMessages label="输入" messages={detail.input} /><StepMessages label="输出" messages={detail.output} /></div>
      <div className="snapshot-grid"><Snapshot label="执行前快照" value={detail.snapshot_before} /><Snapshot label="执行后快照" value={detail.snapshot_after} /></div>
      <p className="step-footnote">快照按展示范围裁剪，保留最近消息与状态信息。</p>
    </>}</div>
  </section></div>;
}
