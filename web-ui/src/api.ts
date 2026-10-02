export type ToolName = 'read' | 'list' | 'search' | 'write' | 'edit' | 'propose_command';
export interface Config { workspace: string; provider: string; model: string; server_epoch: string; capabilities: string[]; available_tools: string[]; tool_limits: Record<ToolName, number>; approval_capabilities: string[]; allowed_executables: string[]; require_approval: boolean }
export interface Session { session_id: string; title: string; workspace: string; workspace_known?: boolean; archived: boolean; created_at: string; updated_at: string }
export interface Run { run_id: string; session_id: string; request_id: string; status: 'running' | 'completed' | 'failed' | 'cancelled' | 'needs_recovery' | 'awaiting_approval'; error: string | null }
export interface Message { message_id: string; role: 'user' | 'assistant' | 'tool'; text: string; tool_name: string | null; truncated: boolean; proposals?: Proposal[] }
export interface Page { messages: Message[]; checkpoint_id: string | null; next_before: number | null }
export interface Activity { event_id: number; session_id: string; run_id: string; phase: string; tool_name: string | null; outcome: string | null; created_at: string }
export interface Preview { run_id: string; message_id: string; revision: number; text: string; status: 'streaming' | 'complete' | 'discarded'; truncated: boolean }
export interface Checkpoint { checkpoint_id: string; created_at: string; preview: string }
export interface Proposal { proposal_id: string; version: string; kind: 'file' | 'command'; status: string; workspace: string; operation: string; path: string | null; diff: string | null; before_text: string | null; after_text: string | null; args: { executable: string; argv: string[]; timeout_seconds: number } | null; result: Record<string, unknown> | null }
export interface View { session: Session; server_epoch: string; run: Run | null; needs_recovery: boolean; history: Page; activities: Activity[]; preview: Preview | null; awaiting_approval: boolean; proposals: Proposal[] }
export interface StepMessage { role: 'user' | 'assistant' | 'tool'; text: string; tool_name?: string; tool_calls?: { name: string; args: Record<string, string | number | boolean> }[] }
export interface StepDetail { event_id: number; checkpoint_id?: string; title: string; node: string; input: StepMessage[]; output: StepMessage[]; snapshot_before: Record<string, unknown>; snapshot_after: Record<string, unknown> }

export function toolLabel(name: string | null | undefined): string {
  return name === 'propose_command' ? 'command' : name ?? '工具';
}

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init, headers: { 'Content-Type': 'application/json', 'X-Pi-Request': '1', ...init?.headers },
  });
  if (!response.ok) {
    let detail = '无法连接到服务，请检查本地服务是否正在运行。';
    try { detail = (await response.json()).detail ?? detail; } catch { /* Keep safe fallback. */ }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export function mergeActivities(current: Activity[], incoming: Activity[]): Activity[] {
  const entries = new Map(current.map(item => [item.event_id, item]));
  incoming.forEach(item => entries.set(item.event_id, item));
  return [...entries.values()].sort((a, b) => a.event_id - b.event_id).slice(-256);
}

export function mergePreview(current: Preview | null, incoming: Preview | null): Preview | null {
  if (current && incoming && current.run_id === incoming.run_id && current.revision > incoming.revision) return current;
  return incoming;
}

export const statusLabels = {
  running: '正在运行', completed: '已完成', failed: '运行失败', cancelled: '已停止', needs_recovery: '需要核对',
  awaiting_approval: '等待审批',
};

export interface TokenTotals { input_tokens: number | null; output_tokens: number | null; total_tokens: number | null; recorded_calls: number; unknown_calls: number; pending_calls: number }
export interface UsageView { server_epoch: string; revision: number; session_id: string | null; overall: TokenTotals; session: TokenTotals }

export function mergeUsage(current: UsageView | null, incoming: UsageView): UsageView {
  return current && current.server_epoch === incoming.server_epoch && current.session_id === incoming.session_id && current.revision > incoming.revision ? current : incoming;
}
