import type { Session } from './api';

export interface WorkspaceGroup { key: string; workspace: string | null; title: string; sessions: Session[] }

export function groupSessions(sessions: Session[], search = ''): WorkspaceGroup[] {
  const query = search.trim().toLowerCase();
  const groups = new Map<string, WorkspaceGroup>();
  for (const session of sessions) {
    const workspace = session.workspace_known === false ? null : session.workspace;
    const title = workspace?.split(/[\\/]/).filter(Boolean).pop() || workspace || '历史 / 未标记';
    if (query && !session.title.toLowerCase().includes(query) && !(workspace ?? title).toLowerCase().includes(query)) continue;
    const key = workspace === null ? 'legacy' : `workspace:${workspace}`;
    const group = groups.get(key) ?? { key, workspace, title, sessions: [] };
    group.sessions.push(session);
    groups.set(key, group);
  }
  const recent = (session: Session) => Date.parse(session.updated_at) || 0;
  for (const group of groups.values()) group.sessions.sort((a, b) => recent(b) - recent(a) || b.session_id.localeCompare(a.session_id));
  return [...groups.values()].sort((a, b) => recent(b.sessions[0]) - recent(a.sessions[0]) || a.key.localeCompare(b.key));
}
