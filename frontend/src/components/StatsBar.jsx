import React, { useEffect, useState } from 'react';
import { getStats } from '../api';

const card = {
  background: '#1e293b', borderRadius: 10, padding: '16px 24px',
  display: 'flex', flexDirection: 'column', gap: 4, minWidth: 140,
  border: '1px solid #334155',
};

const STAT_CONFIG = [
  { key: 'total_events',       label: 'Total Events',       color: '#94a3b8' },
  { key: 'auto_fixed',         label: 'Auto Fixed',         color: '#34d399' },
  { key: 'awaiting_approval',  label: 'Awaiting Approval',  color: '#fbbf24' },
  { key: 'pass_no_remedy',     label: 'Healthy Passes',     color: '#60a5fa' },
  { key: 'fix_failed',         label: 'Fix Failed',         color: '#f87171' },
  { key: 'pending_approvals',  label: 'Pending Approvals',  color: '#a78bfa' },
];

export default function StatsBar() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    const load = () => getStats().then(r => setStats(r.data)).catch(() => {});
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  if (!stats) return null;

  return (
    <div style={{ display: 'flex', gap: 12, padding: '16px 24px', flexWrap: 'wrap', background: '#0f172a' }}>
      {STAT_CONFIG.map(({ key, label, color }) => (
        <div key={key} style={card}>
          <span style={{ fontSize: 28, fontWeight: 700, color }}>{stats[key] ?? 0}</span>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>{label}</span>
        </div>
      ))}
    </div>
  );
}
