import React, { useState } from 'react';
import StatsBar from './components/StatsBar';
import ObservabilityTab from './components/ObservabilityTab';
import ApprovalsTab from './components/ApprovalsTab';
import ResultsTab from './components/ResultsTab';
import DemoPanel from './components/DemoPanel';

const TABS = [
  { id: 'observability', label: 'Agent Activity' },
  { id: 'approvals',     label: 'Human Approvals' },
  { id: 'results',       label: 'Results' },
];

const styles = {
  app:     { minHeight: '100vh', background: '#0f172a', color: '#e2e8f0' },
  header:  { background: '#1e293b', borderBottom: '1px solid #334155', padding: '16px 24px', display: 'flex', alignItems: 'center', gap: 12 },
  logo:    { fontSize: 22, fontWeight: 700, color: '#38bdf8', letterSpacing: '-0.5px' },
  sub:     { fontSize: 13, color: '#94a3b8' },
  tabs:    { display: 'flex', gap: 4, padding: '0 24px', background: '#1e293b', borderBottom: '1px solid #334155' },
  tab:     { padding: '12px 20px', cursor: 'pointer', fontSize: 14, fontWeight: 500, border: 'none', background: 'none', color: '#94a3b8', borderBottom: '2px solid transparent' },
  tabActive:{ borderBottom: '2px solid #38bdf8', color: '#38bdf8' },
  body:    { padding: 24 },
};

export default function App() {
  const [activeTab, setActiveTab] = useState('observability');

  return (
    <div style={styles.app}>
      <header style={styles.header}>
        <div>
          <div style={styles.logo}>Pipeline Doctor</div>
          <div style={styles.sub}>AI-powered CI/CD failure diagnosis and auto-fix</div>
        </div>
      </header>

      <StatsBar />

      <DemoPanel />

      <nav style={styles.tabs}>
        {TABS.map(t => (
          <button
            key={t.id}
            style={{ ...styles.tab, ...(activeTab === t.id ? styles.tabActive : {}) }}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main style={styles.body}>
        {activeTab === 'observability' && <ObservabilityTab />}
        {activeTab === 'approvals'     && <ApprovalsTab />}
        {activeTab === 'results'       && <ResultsTab />}
      </main>
    </div>
  );
}
