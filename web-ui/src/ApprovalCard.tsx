import type { Proposal } from './api';

const labels: Record<string, string> = { pending: '等待审批', approved: '已批准', rejected: '已拒绝', claimed: '正在执行', completed: '已完成', failed: '执行失败', cancelled: '已停止', uncertain: '结果需核对' };

export default function ApprovalCard({ proposal, disabled, busy, decide }: {
  proposal: Proposal; disabled: boolean; busy: boolean;
  decide: (proposal: Proposal, decision: 'approve' | 'reject') => void;
}) {
  const pending = proposal.status === 'pending';
  return <details className={`approval-card ${pending ? 'pending' : ''}`} open={pending || undefined}>
    <summary><b>{proposal.kind === 'file' ? `${proposal.operation} · ${proposal.path}` : 'command'}</b><span>{labels[proposal.status] ?? proposal.status}</span></summary>
    <div className="approval-body">
      <small>工作区</small><pre>{proposal.workspace}</pre>
      {proposal.kind === 'file' ? <>
        <small>修改预览</small><pre className="approval-diff">{proposal.diff || '换行或末尾内容变化，请查看完整内容。'}</pre>
        <details><summary>完整内容（转义显示换行）</summary><small>修改前</small><pre>{JSON.stringify(proposal.before_text)}</pre><small>修改后</small><pre>{JSON.stringify(proposal.after_text)}</pre></details>
      </> : <>
        <small>可执行程序</small><pre>{proposal.args?.executable}</pre>
        <small>参数 argv（保持每个参数的边界）</small><pre>{JSON.stringify(proposal.args?.argv, null, 2)}</pre>
        <small>超时 {proposal.args?.timeout_seconds} 秒 · 输出最多保留每路 50 KiB / 2000 行</small>
        {pending && <p className="muted">批准后进程将以你的本机权限运行，请核对程序、参数与工作区。</p>}
      </>}
      {proposal.status === 'uncertain' && <p role="status">服务中断后无法确认结果。请核对文件或进程状态；此提案不会自动重跑。</p>}
      {proposal.result && <><small>执行结果</small><pre>{JSON.stringify(proposal.result, null, 2)}</pre></>}
      {pending && <div className="approval-actions"><button disabled={disabled || busy} onClick={() => decide(proposal, 'reject')}>拒绝</button><button className="approve-button" disabled={disabled || busy} onClick={() => decide(proposal, 'approve')}>{busy ? '正在提交…' : '批准并继续'}</button></div>}
    </div>
  </details>;
}
