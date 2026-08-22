import React, { useEffect, useState } from 'react';
import { getEvents } from '../api';

const STATUS_COLOR = {
  auto_fixed:        '#34d399',
  awaiting_approval: '#fbbf24',
  pass_no_remedy:    '#60a5fa',
  fix_failed:        '#f87171',
  unknown:           '#94a3b8',
};

const ACTION_ICON = {
  received_event:       '📥',
  failure_parsed:       '🔍',
  starting_diagnosis:   '🧠',
  rag_retrieved:        '📚',
  diagnosis_complete:   '✅',
  generating_fix:       '🔧',
  fix_proposed:         '💡',
  applying_auto_fix:    '⚡',
  auto_fix_result:      '🚀',
  requesting_human_approval: '🙋',
  clean_pass:           '✔️',
};

export default function ObservabilityTab() {
  const [events, setEvents] = useState([]);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    const load = () =>
      getEvents().then(r => {
        setEvents(r.data.events || []);
      }).catch(() => {});
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);

  const selectedEvent = selected ? events.find(e => e.event?.event_id === selected) : null;

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
      {/* Event list */}
      <div>
        <h2 style={{ marginBottom: 12, fontSize: 16, color: '#e2e8f0' }}>Recent Pipeline Events</h2>
        {events.length === 0 && (
          <p style={{ color: '#64748b', fontSize: 14 }}>
            No events yet. Use the Demo Panel above to trigger one.
          </p>
        )}
        {events.map(item => {
          const ev = item.event || {};
          const res = item.result || {};
          const status = res.status || 'unknown';
          const isSelected = selected === ev.event_id;
          return (
            <div
              key={ev.event_id}
              onClick={() => setSelected(isSelected ? null : ev.event_id)}
              style={{
                background: isSelected ? '#1e293b' : '#151f2e',
                border: `1px solid ${isSelected ? '#38bdf8' : '#334155'}`,
                borderRadius: 8, padding: '12px 16px', marginBottom: 10,
                cursor: 'pointer',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 600, fontSize: 14 }}>
                  Pipeline #{ev.pipeline_id}
                  <span style={{ marginLeft: 8, fontSize: 12, color: '#64748b' }}>{ev.source}</span>
                </span>
                <span style={{
                  fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 99,
                  background: STATUS_COLOR[status] + '22', color: STATUS_COLOR[status],
                }}>
                  {status.replace(/_/g, ' ').toUpperCase()}
                </span>
              </div>
              <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>
                {ev.stage} — {(ev.error || 'No error').slice(0, 80)}
              </div>
            </div>
          );
        })}
      </div>

      {/* Action trace panel */}
      <div>
        <h2 style={{ marginBottom: 12, fontSize: 16, color: '#e2e8f0' }}>
          {selectedEvent ? `Action Trace — ${selectedEvent.event?.event_id}` : 'Agent Action Trace'}
        </h2>
        {!selectedEvent ? (
          <p style={{ color: '#64748b', fontSize: 14 }}>Select an event to see the agent action trace.</p>
        ) : (
          <div>
            {(selectedEvent.result?.actions || []).map((action, i) => (
              <div key={i} style={{
                display: 'flex', gap: 12, alignItems: 'flex-start',
                background: '#1e293b', borderRadius: 8, padding: '10px 14px',
                marginBottom: 8, border: '1px solid #334155',
              }}>
                <span style={{ fontSize: 18, minWidth: 24 }}>
                  {ACTION_ICON[action.action] || '▶'}
                </span>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>
                    {action.action.replace(/_/g, ' ')}
                  </div>
                  <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>
                    {Object.entries(action)
                      .filter(([k]) => !['action', 'timestamp'].includes(k))
                      .map(([k, v]) => `${k}: ${String(v).slice(0, 60)}`)
                      .join(' · ')}
                  </div>
                  <div style={{ fontSize: 10, color: '#475569', marginTop: 2 }}>
                    {action.timestamp}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
