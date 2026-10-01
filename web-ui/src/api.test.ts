import { describe, expect, it } from 'vitest';
import { mergeActivities, mergePreview, type Activity, type Preview } from './api';

const event = (id: number): Activity => ({ event_id: id, session_id: 's', run_id: 'r', phase: 'before_tool', tool_name: 'read', outcome: null, created_at: '' });

describe('activity reconciliation', () => {
  it('deduplicates reconnect delivery and keeps arrival order by event identity', () => {
    expect(mergeActivities([event(2), event(1)], [event(2), event(3)]).map(x => x.event_id)).toEqual([1, 2, 3]);
  });
  it('bounds memory even with a long-running subscription', () => {
    const result = mergeActivities([], Array.from({ length: 1000 }, (_, i) => event(i)));
    expect(result).toHaveLength(256);
    expect(result[0].event_id).toBe(744);
  });
});

describe('stream preview reconciliation', () => {
  const preview = (revision: number, status: Preview['status'] = 'streaming'): Preview => ({ run_id: 'run', message_id: 'message', revision, text: status === 'discarded' ? '' : 'partial', status, truncated: false });
  it('ignores a stale snapshot after a newer streaming event', () => {
    expect(mergePreview(preview(3), preview(2))?.revision).toBe(3);
  });
  it('clears failed attempts and accepts a new attempt or terminal snapshot', () => {
    expect(mergePreview(preview(3), preview(4, 'discarded'))?.text).toBe('');
    expect(mergePreview(preview(4, 'discarded'), preview(5))?.revision).toBe(5);
    expect(mergePreview(preview(5), null)).toBeNull();
  });
});
