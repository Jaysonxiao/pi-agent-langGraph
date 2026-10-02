import { useEffect, useState } from 'react';
import { ChevronDown, Folder, MessageSquare } from 'lucide-react';
import type { WorkspaceGroup } from './workspaces';

function savedCollapsed(): Set<string> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem('pi.collapsed-workspaces') ?? '[]');
    return new Set(Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []);
  } catch { return new Set(); }
}

export default function WorkspaceSessions({ groups, selected, searching, select }: {
  groups: WorkspaceGroup[]; selected: string | null; searching: boolean; select: (id: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(savedCollapsed);
  const activeGroup = groups.find(group => group.sessions.some(session => session.session_id === selected))?.key;
  useEffect(() => {
    if (activeGroup) setCollapsed(current => {
      if (!current.has(activeGroup)) return current;
      const next = new Set(current); next.delete(activeGroup); return next;
    });
  }, [selected, activeGroup]);
  useEffect(() => {
    try { localStorage.setItem('pi.collapsed-workspaces', JSON.stringify([...collapsed])); } catch { /* Storage can be disabled. */ }
  }, [collapsed]);
  return groups.map(group => {
    const expanded = searching || !collapsed.has(group.key);
    return <section className="workspace-group" key={group.key} aria-label={group.workspace ?? group.title}>
      <button className="workspace-group-heading" title={group.workspace ?? '旧会话未记录工作区'} aria-expanded={expanded}
        onClick={() => setCollapsed(current => {
          const next = new Set(current); if (next.has(group.key)) next.delete(group.key); else next.add(group.key); return next;
        })}>
        <Folder size={14} /><span>{group.title}</span><small>{group.sessions.length}</small><ChevronDown size={13} className={expanded ? '' : 'collapsed'} />
      </button>
      {expanded && <div className="workspace-group-sessions">{group.sessions.map(item => <button key={item.session_id}
        className={`session-item ${selected === item.session_id ? 'active' : ''}`} onClick={() => select(item.session_id)}>
        <MessageSquare size={15} /><span>{item.title}</span><i />
      </button>)}</div>}
    </section>;
  });
}
