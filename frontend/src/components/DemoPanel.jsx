import React, { useState } from 'react';
import { submitEvent } from '../api';

// Pre-built payloads matching sanyapeter/Dummy_Pipeline sample_failures/
const SCENARIOS = [
  {
    label: 'missing_dep',
    description: 'Missing boto3 dependency (auto-fix)',
    color: '#34d399',
    payload: {
      event_id: null, // will be generated
      pipeline_id: '124',
      source: 'github_actions',
      status: 'FAILED',
      stage: 'BUILD',
      error: "ModuleNotFoundError: No module named 'boto3'",
      commit: 'a82f31c',
      changed_files: ['requirements.txt', 'app.py'],
      category: 'direct_failure',
      risky: false,
    },
  },
  {
    label: 'failing_test',
    description: 'Assertion error in tests (escalate)',
    color: '#fbbf24',
    payload: {
      pipeline_id: '125',
      source: 'github_actions',
      status: 'FAILED',
      stage: 'TEST',
      error: 'AssertionError: assert add(2, 2) == 5, expected 5',
      commit: 'b91e42d',
      changed_files: ['tests/test_app.py'],
      category: 'direct_failure',
      risky: false,
    },
  },
  {
    label: 'bad_config',
    description: 'Missing DATABASE_URL secret (escalate)',
    color: '#f97316',
    payload: {
      pipeline_id: '126',
      source: 'jenkins',
      status: 'FAILED',
      stage: 'DEPLOY',
      error: "KeyError: 'DATABASE_URL'",
      commit: 'c40a91f',
      changed_files: ['app.py'],
      category: 'direct_failure',
      risky: true,
      risk_reason: 'deploy-time configuration/secret missing in target environment',
    },
  },
  {
    label: 'slow_deploy',
    description: 'Health check timeout (escalate)',
    color: '#a78bfa',
    payload: {
      pipeline_id: '127',
      source: 'github_actions',
      status: 'FAILED',
      stage: 'DEPLOY',
      error: 'DEPLOY FAILED: health check timeout after 5s (simulated 300s SLA)',
      commit: 'd29bc50',
      changed_files: [],
      category: 'direct_failure',
      risky: false,
    },
  },
  {
    label: 'risky_iam_change',
    description: 'Passed but wildcard IAM detected (flag)',
    color: '#f87171',
    payload: {
      pipeline_id: '128',
      source: 'github_actions',
      status: 'PASSED',
      stage: 'DEPLOY',
      error: null,
      commit: 'e28f014',
      changed_files: ['terraform/main.tf'],
      category: 'risky_change',
      risky: true,
      risk_reason: "IAM policy uses wildcard Action 'iam:*' and Resource '*'; security group open to 0.0.0.0/0",
    },
  },
  {
    label: 'clean_pass',
    description: 'Clean pipeline pass (no action)',
    color: '#60a5fa',
    payload: {
      pipeline_id: '129',
      source: 'github_actions',
      status: 'PASSED',
      stage: 'DEPLOY',
      error: null,
      commit: 'f99aa01',
      changed_files: ['README.md'],
      category: 'direct_failure',
      risky: false,
    },
  },
];

export default function DemoPanel() {
  const [loading, setLoading] = useState(null);
  const [last, setLast]       = useState(null);

  const trigger = async (scenario) => {
    setLoading(scenario.label);
    try {
      const r = await submitEvent(scenario.payload);
      setLast({ label: scenario.label, event_id: r.data.event_id });
    } catch (e) {
      setLast({ label: scenario.label, error: true });
    } finally {
      setLoading(null);
    }
  };

  return (
    <div style={{
      background: '#1e293b', borderBottom: '1px solid #334155',
      padding: '14px 24px',
    }}>
      <div style={{ fontSize: 12, color: '#64748b', marginBottom: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        Demo — Trigger a Scenario
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {SCENARIOS.map(s => (
          <button
            key={s.label}
            onClick={() => trigger(s)}
            disabled={loading === s.label}
            title={s.description}
            style={{
              background: s.color + '18',
              border: `1px solid ${s.color}44`,
              color: s.color,
              borderRadius: 6, padding: '6px 14px',
              fontSize: 12, fontWeight: 600, cursor: 'pointer',
              opacity: loading && loading !== s.label ? 0.5 : 1,
            }}
          >
            {loading === s.label ? '...' : s.label}
          </button>
        ))}
        {last && (
          <span style={{ fontSize: 12, color: last.error ? '#f87171' : '#34d399', marginLeft: 8 }}>
            {last.error ? `${last.label} failed` : `${last.label} submitted (${last.event_id})`}
          </span>
        )}
      </div>
    </div>
  );
}
