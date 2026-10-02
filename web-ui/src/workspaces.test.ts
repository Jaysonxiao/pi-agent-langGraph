import { describe, expect, it } from 'vitest';
import type { Session } from './api';
import { groupSessions } from './workspaces';

function session(id: string, workspace: string, day: number, known = true): Session {
  return { session_id: id, workspace, workspace_known: known, title: `任务 ${id}`, archived: false, created_at: '', updated_at: `2026-10-0${day}T00:00:00Z` };
}

describe('workspace session grouping', () => {
  const sessions = [session('old', '/one/app', 1), session('win', 'C:\\work\\app', 2), session('new', '/one/app', 3), session('legacy', '/fallback', 4, false)];
  it('uses full paths and orders groups and sessions by their latest activity', () => {
    const groups = groupSessions(sessions);
    expect(groups.map(group => [group.workspace, group.title, group.sessions.map(item => item.session_id)])).toEqual([
      [null, '历史 / 未标记', ['legacy']], ['/one/app', 'app', ['new', 'old']], ['C:\\work\\app', 'app', ['win']],
    ]);
  });
  it('searches both session titles and workspace paths without treating fallback as provenance', () => {
    expect(groupSessions(sessions, ' /ONE/ ').flatMap(group => group.sessions.map(item => item.session_id))).toEqual(['new', 'old']);
    expect(groupSessions(sessions, '任务 win')[0].workspace).toBe('C:\\work\\app');
    expect(groupSessions(sessions, 'fallback')).toEqual([]);
    expect(groupSessions(sessions, '未标记')[0].sessions[0].session_id).toBe('legacy');
  });
  it('groups an archived result set and accepts old API payloads', () => {
    const oldPayload = { ...sessions[0], workspace_known: undefined, archived: true };
    expect(groupSessions([oldPayload])[0].workspace).toBe('/one/app');
    expect(groupSessions([])).toEqual([]);
  });
});
