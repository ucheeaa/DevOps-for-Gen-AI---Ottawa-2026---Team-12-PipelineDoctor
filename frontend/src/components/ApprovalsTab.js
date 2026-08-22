import React, { useEffect, useState } from 'react';
import { getApprovals, approveFix, denyFix } from '../api';

const RISK_COLOR = { low: '#34d399', medium: '#fbbf24', high: '#f97316', critical: '#f87171' };

export default function ApprovalsTab() {
  const [approvals, setApprovals] = useState([]);
  const [loading, setLoading] = useState({});
  const [notes, setNotes]    = useState({});

  const load = () =>
    getApprovals().then(r => setApprovals(r.data.approvals || [])).catch(() => {});

  useEffect(() => { load(); const id = setInterval(load, 5000); return () => clearInterval(id); }, []);

  const act = (fixId, action) => {
    setLoading(l => ({ ...l, [fixId]: true }));
    const fn = action === 'approve' ? approveFix : denyFix;
    fn(fixId, { approver: 'dashboard-user', notes: notes[fixId] || '' })
      .then(() => load())
      .catch(() => {})
      .finally(() => setLoading(l => ({ ...l, [fixId]: false })));
  };

  const pending = approvals.filter(a => a.status === 'pending');
  const past    = approvals.filter(a => a.status !== 'pending');

  return (
    <div>
      <h2 style={{ marginBottom: 16, fontSize: 16, color: '#e2e8f0' }}>
        Human-in-the-Loop Approvals
        {pending.length > 0 && (
          <span style={{ marginLeft: 10, background: '#fbbf2422', color: '#fbbf24', fontSize: 12, padding: '2px 8px', borderRadius: 99, fontWeight: 600 }}>
            {pending.length} pending
          </span>
        )}
      </h2>

      {pending.length === 0 && (
        <div style={{ color: '#64748b', fontSize: 14, marginBottom: 24 }}>No pending approvals.</div>
      )}

      {pending.map(ap => {
        const fix = ap.fix || {};
        const risk = fix.risk_level || 'high';
        return (
          <div key={ap.fix_id} style={{
            background: '#1e293b', border: '1px solid #334155',
            borderRadius: 10, padding: 20, marginBottom: 16,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
              <div>
                <span style={{ fontWeight: 700, fontSize: 15 }}>Pipeline #{ap.pipeline_id}</span>
                <span style={{ marginLeft: 10, fontSize: 12, color: '#94a3b8' }}>Stage: {ap.stage}</span>
              </div>
              <span style={{
                background: RISK_COLOR[risk] + '22', color: RISK_COLOR[risk],
                fontSize: 12, fontWeight: 700, padding: '3px 10px', borderRadius: 99,
              }}>
                {risk.toUpperCase()} RISK
              </span>
            </div>

            <div style={{ fontSize: 13, marginBottom: 8 }}>
              <strong style={{ color: '#94a3b8' }}>Error:</strong>{' '}
              <span style={{ color: '#fca5a5' }}>{ap.error}</span>
            </div>

            <div style={{ fontSize: 13, marginBottom: 8 }}>
              <strong style={{ color: '#94a3b8' }}>Proposed fix:</strong>{' '}
              {fix.description}
            </div>

            <div style={{ fontSize: 13, marginBottom: 8 }}>
              <strong style={{ color: '#94a3b8' }}>Why approval needed:</strong>{' '}
              <span style={{ color: '#fbbf24' }}>{fix.approval_reason}</span>
            </div>

            {fix.steps && fix.steps.length > 0 && (
              <div style={{ fontSize: 12, marginBottom: 12 }}>
                <strong style={{ color: '#94a3b8', display: 'block', marginBottom: 4 }}>Steps:</strong>
                <ol style={{ paddingLeft: 20, color: '#cbd5e1' }}>
                  {fix.steps.map((s, i) => <li key={i}>{s}</li>)}
                </ol>
              </div>
            )}

            {fix.file_changes && Object.keys(fix.file_changes).length > 0 && (
              <div style={{ fontSize: 12, marginBottom: 12 }}>
                <strong style={{ color: '#94a3b8' }}>Files to change: </strong>
                {Object.keys(fix.file_changes).map(f => (
                  <code key={f} style={{ background: '#0f172a', padding: '1px 6px', borderRadius: 4, marginRight: 6, color: '#7dd3fc' }}>{f}</code>
                ))}
              </div>
            )}

            <textarea
              placeholder="Optional notes..."
              value={notes[ap.fix_id] || ''}
              onChange={e => setNotes(n => ({ ...n, [ap.fix_id]: e.target.value }))}
              style={{
                width: '100%', background: '#0f172a', border: '1px solid #334155',
                borderRadius: 6, padding: '8px 12px', color: '#e2e8f0', fontSize: 13,
                resize: 'vertical', minHeight: 60, marginBottom: 12,
              }}
            />

            <div style={{ display: 'flex', gap: 10 }}>
              <button
                onClick={() => act(ap.fix_id, 'approve')}
                disabled={loading[ap.fix_id]}
                style={{
                  background: '#16a34a', color: '#fff', border: 'none', borderRadius: 6,
                  padding: '8px 20px', fontWeight: 600, cursor: 'pointer', fontSize: 13,
                }}
              >
                {loading[ap.fix_id] ? 'Applying...' : 'Approve & Apply Fix'}
              </button>
              <button
                onClick={() => act(ap.fix_id, 'deny')}
                disabled={loading[ap.fix_id]}
                style={{
                  background: '#991b1b', color: '#fff', border: 'none', borderRadius: 6,
                  padding: '8px 20px', fontWeight: 600, cursor: 'pointer', fontSize: 13,
                }}
              >
                Deny
              </button>
            </div>
          </div>
        );
      })}

      {past.length > 0 && (
        <div style={{ marginTop: 32 }}>
          <h3 style={{ marginBottom: 12, fontSize: 14, color: '#64748b' }}>Past Approvals</h3>
          {past.map(ap => (
            <div key={ap.fix_id} style={{
              background: '#151f2e', border: '1px solid #334155',
              borderRadius: 8, padding: '10px 16px', marginBottom: 8,
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <span style={{ fontSize: 13 }}>Pipeline #{ap.pipeline_id} — {(ap.fix || {}).description}</span>
              <span style={{
                fontSize: 12, fontWeight: 600,
                color: ap.status === 'approved' ? '#34d399' : '#f87171',
              }}>
                {ap.status.toUpperCase()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
