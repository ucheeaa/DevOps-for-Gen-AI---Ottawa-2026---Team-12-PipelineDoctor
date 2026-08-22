import React, { useEffect, useState } from 'react';
import { getEvents } from '../api';

const STATUS_CONFIG = {
  auto_fixed:        { label: 'AutoFixed',       bg: '#064e3b', color: '#34d399' },
  awaiting_approval: { label: 'Awaiting',         bg: '#78350f', color: '#fbbf24' },
  pass_no_remedy:    { label: 'Pass',             bg: '#1e3a5f', color: '#60a5fa' },
  fix_failed:        { label: 'Fix Failed',       bg: '#7f1d1d', color: '#f87171' },
  unknown:           { label: 'Unknown',          bg: '#1e293b', color: '#94a3b8' },
};

export default function ResultsTab() {
  const [events, setEvents] = useState([]);

  useEffect(() => {
    const load = () => getEvents().then(r => setEvents(r.data.events || [])).catch(() => {});
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <div>
      <h2 style={{ marginBottom: 16, fontSize: 16, color: '#e2e8f0' }}>
        Results — All Pipeline Events
      </h2>

      {events.length === 0 && (
        <p style={{ color: '#64748b', fontSize: 14 }}>No events yet.</p>
      )}

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ color: '#64748b', borderBottom: '1px solid #334155', textAlign: 'left' }}>
            {['Pipeline', 'Source', 'Stage', 'Error', 'Status', 'Fix ID', 'Time'].map(h => (
              <th key={h} style={{ padding: '8px 12px', fontWeight: 600 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {events.map(item => {
            const ev = item.event || {};
            const res = item.result || {};
            const status = res.status || 'unknown';
            const conf = STATUS_CONFIG[status] || STATUS_CONFIG.unknown;
            const fix = res.fix;
            return (
              <tr key={ev.event_id} style={{ borderBottom: '1px solid #1e293b' }}>
                <td style={{ padding: '10px 12px', fontWeight: 600 }}>#{ev.pipeline_id}</td>
                <td style={{ padding: '10px 12px', color: '#94a3b8' }}>{ev.source}</td>
                <td style={{ padding: '10px 12px' }}>{ev.stage}</td>
                <td style={{ padding: '10px 12px', color: '#fca5a5', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {ev.error || '—'}
                </td>
                <td style={{ padding: '10px 12px' }}>
                  <span style={{
                    background: conf.bg, color: conf.color,
                    padding: '3px 10px', borderRadius: 99, fontWeight: 600, fontSize: 11,
                  }}>
                    {conf.label}
                  </span>
                </td>
                <td style={{ padding: '10px 12px' }}>
                  {fix ? (
                    <code style={{ background: '#0f172a', padding: '1px 6px', borderRadius: 4, color: '#7dd3fc', fontSize: 11 }}>
                      {fix.fix_id}
                    </code>
                  ) : '—'}
                </td>
                <td style={{ padding: '10px 12px', color: '#475569', fontSize: 11 }}>
                  {item.ingested_at ? new Date(item.ingested_at).toLocaleTimeString() : '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
