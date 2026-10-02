import type { TokenTotals, UsageView } from './api';

export function tokenNumber(value: number | null): string {
  return value === null ? '—' : value.toLocaleString('en-US');
}

function Counter({ label, totals, loading = false }: { label: string; totals: TokenTotals; loading?: boolean }) {
  return <section className="token-counter" aria-label={label}>
    <div><span>{label}</span><b>{loading ? '读取中' : totals.total_tokens === null ? totals.pending_calls ? '统计中' : '未提供' : tokenNumber(totals.total_tokens)}
      {totals.total_tokens !== null && totals.unknown_calls > 0 && <small>已知</small>}</b></div>
    <p>输入 {tokenNumber(loading ? null : totals.input_tokens)} <span>·</span> 输出 {tokenNumber(loading ? null : totals.output_tokens)}</p>
    <small>{loading ? '正在读取统计' : totals.pending_calls > 0 ? `${totals.pending_calls} 次请求等待用量` : totals.unknown_calls > 0 ? `${totals.unknown_calls} 次未提供完整用量` : `${totals.recorded_calls} 次模型请求`}</small>
  </section>;
}

export default function TokenUsage({ usage, currentLoading = false }: { usage: UsageView | null; currentLoading?: boolean }) {
  const empty: TokenTotals = { input_tokens: 0, output_tokens: 0, total_tokens: 0, recorded_calls: 0, unknown_calls: 0, pending_calls: 0 };
  return <div className="token-usage" aria-label="Token 用量" title="按模型回传的 usage 统计。累计包含全部会话及归档；当前会话统计实际模型请求，复制的分支历史不重复计入。">
    <Counter label="累计 Token" totals={usage?.overall ?? empty} loading={usage === null} />
    <Counter label="当前会话 Token" totals={usage?.session ?? empty} loading={usage === null || currentLoading} />
  </div>;
}
