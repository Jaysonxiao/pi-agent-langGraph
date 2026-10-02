import { describe, expect, it } from 'vitest';
import { mergeActivities, mergePreview, mergeUsage, type Activity, type Preview, type UsageView } from './api';

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

describe('usage reconciliation', () => {
  const usage = (revision: number, session_id = 'one', server_epoch = 'server'): UsageView => ({ revision, session_id, server_epoch, overall: { input_tokens: 0, output_tokens: 0, total_tokens: 0, recorded_calls: 0, unknown_calls: 0, pending_calls: 0 }, session: { input_tokens: null, output_tokens: null, total_tokens: null, recorded_calls: 1, unknown_calls: 1, pending_calls: 0 } });
  it('does not replace a newer streaming update with an older polling result', () => {
    expect(mergeUsage(usage(4), usage(3)).revision).toBe(4);
    expect(mergeUsage(usage(4), usage(5)).revision).toBe(5);
  });
  it('accepts a switched session or a restarted service', () => {
    expect(mergeUsage(usage(4), usage(3, 'two')).session_id).toBe('two');
    expect(mergeUsage(usage(4), usage(1, 'one', 'new')).server_epoch).toBe('new');
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
