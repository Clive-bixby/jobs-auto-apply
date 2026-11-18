import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';
import type { Status } from './types';
import { Notice, Pill, duration, timeAgo } from './components/ui';
import Overview from './views/Overview';
import Review from './views/Review';
import Applications from './views/Applications';
import Activity from './views/Activity';
import Settings from './views/Settings';
import LogApplicationForm from './components/LogApplicationForm';

type View = 'overview' | 'review' | 'applications' | 'activity' | 'settings';

// The bundle actually loaded by this page. Changes on every build, so a stale
// cached tab is obvious at a glance.
const BUILD_ID = (() => {
  const src = document.querySelector('script[type="module"]')?.getAttribute('src') ?? '';
  return src.split('/').pop() ?? '';
})();

const NAV: { id: View; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'review', label: 'Review queue' },
  { id: 'applications', label: 'Applications' },
  { id: 'activity', label: 'Activity & logs' },
  { id: 'settings', label: 'Preferences' },
];

export default function App() {
  const [view, setView] = useState<View>('overview');
  const [status, setStatus] = useState<Status | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [flash, setFlash] = useState<{ kind: 'error' | 'info'; text: string } | null>(null);
  const [action, setAction] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [logOpen, setLogOpen] = useState(false);
  const wasBusy = useRef(false);

  const load = useCallback(async () => {
    try {
      setStatus(await api.get<Status>('/api/status'));
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(timer);
  }, [load]);

  const busy = status?.automation.busy ?? false;

  useEffect(() => {
    if (wasBusy.current && !busy) setRefreshKey((k) => k + 1);
    wasBusy.current = busy;
  }, [busy]);

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setAction(label);
    setFlash(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setFlash({ kind: 'error', text: err instanceof Error ? err.message : String(err) });
    } finally {
      setAction(null);
    }
  };

  const startDiscovery = () =>
    run('discovery', () => api.post('/api/control/discovery', { platform: 'all' }));

  const startApply = () =>
    run('apply', () => api.post('/api/control/apply', { platform: 'all' }));

  const stopRun = () => run('stop', () => api.post('/api/control/stop'));

  const togglePause = () =>
    run('pause', () =>
      api.post('/api/control/pause', { paused: !(status?.automation.paused ?? false) }),
    );

  const approved = status?.counts.approved ?? 0;
  const dryRun = status?.automation.effective_dry_run ?? true;
  const current = status?.automation.current ?? null;
  const paused = status?.automation.paused ?? false;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">JA</span>
          <div>
            <div className="brand-name">Jobs Auto-Apply</div>
            <div className="brand-sub">Control dashboard</div>
          </div>
        </div>

        <nav className="nav">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item${view === item.id ? ' active' : ''}`}
              onClick={() => setView(item.id)}
            >
              <span>{item.label}</span>
              {item.id === 'review' && status ? (
                <span className="nav-badge">{status.counts.pending}</span>
              ) : null}
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="side-state">
            <span className={`dot${paused ? ' dot-warn' : busy ? ' dot-live' : ' dot-ok'}`} />
            {paused ? 'Paused' : busy ? 'Run in progress' : 'Idle'}
          </div>
          <div className="side-note">
            Same config, sessions and history as <code>main.py</code>.
          </div>
          {status ? (
            <div className="side-note">
              Resume: <code>{status.config.resume}</code>
              {status.config.resume_exists ? '' : ' (missing)'}
            </div>
          ) : null}
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="topbar-title">
            <h1>{NAV.find((n) => n.id === view)?.label}</h1>
            <p className="topbar-sub">
              {paused
                ? 'Automation is paused — resume to start discovery or submissions.'
                : 'Discovery only collects and scores jobs. Nothing is submitted without your approval.'}
            </p>
          </div>

          <div className="topbar-actions">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setLogOpen(true)}
              title="Log a job you applied to outside this bot"
            >
              + Log application
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={togglePause}
              disabled={action !== null}
            >
              {paused ? 'Resume automation' : 'Pause automation'}
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={startDiscovery}
              disabled={busy || paused || action !== null}
              title="Collect, enrich and score new jobs into the review queue"
            >
              {action === 'discovery' ? 'Starting…' : 'Discover jobs'}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={startApply}
              disabled={busy || paused || action !== null || approved === 0}
              title={
                approved === 0
                  ? 'Approve at least one job first'
                  : 'Submit applications for approved jobs only'
              }
            >
              {action === 'apply' ? 'Starting…' : `Apply approved${approved ? ` (${approved})` : ''}`}
            </button>
          </div>
        </header>

        {loadError ? (
          <Notice kind="error">
            Could not reach the dashboard API: {loadError}. Is <code>python main.py web</code>{' '}
            running?
          </Notice>
        ) : null}

        {flash ? <Notice kind={flash.kind}>{flash.text}</Notice> : null}

        {status?.blockers?.length && !busy ? (
          <div className="notice notice-error blocker-block">
            <strong>A run cannot start yet.</strong>
            <ul className="blocker-list">
              {status.blockers.map((blocker) => (
                <li key={blocker.code}>
                  <span>{blocker.message}</span>
                  <span className="blocker-fix">{blocker.fix}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {dryRun ? (
          <Notice kind="warn">
            <strong>Dry run is ON.</strong> Approved jobs will be scored and listed, but no
            application will be submitted. Change this under Preferences → Submission mode.
          </Notice>
        ) : null}

        {current ? (
          <div className="runbar">
            <span className="dot dot-live" />
            <span>
              {current.kind === 'discovery' ? 'Discovering' : 'Applying'} ·{' '}
              {current.platform === 'all' ? 'all platforms' : current.platform}
            </span>
            <span className="runbar-time">{duration(current.started_at, null)}</span>
            <button type="button" className="btn btn-danger btn-sm" onClick={stopRun}>
              Stop run
            </button>
          </div>
        ) : null}

        <div className="content">
          {view === 'overview' ? (
            <Overview
              status={status}
              onStartDiscovery={startDiscovery}
              onStartApply={startApply}
              busy={busy || paused || action !== null}
            />
          ) : null}
          {view === 'review' ? (
            <Review status={status} refreshKey={refreshKey} onChanged={load} />
          ) : null}
          {view === 'applications' ? (
            <Applications
              status={status}
              refreshKey={refreshKey}
              onChanged={load}
              onLog={() => setLogOpen(true)}
            />
          ) : null}
          {view === 'activity' ? <Activity status={status} refreshKey={refreshKey} /> : null}
          {view === 'settings' ? (
            <Settings status={status} refreshKey={refreshKey} onChanged={load} />
          ) : null}
        </div>

        <footer className="foot">
          {status?.automation.runs?.length ? (
            <span>Last run {timeAgo(status.automation.runs[0].started_at)}</span>
          ) : (
            <span>No runs yet</span>
          )}
          <span className="foot-sep">·</span>
          <span>
            Review queue: <code>{status?.config.review_dir ?? 'data/review'}</code>
          </span>
          {status?.automation.require_review ? (
            <>
              <span className="foot-sep">·</span>
              <Pill value="manual approval required" />
            </>
          ) : null}
          {BUILD_ID ? (
            <>
              <span className="foot-sep">·</span>
              <span className="mono" title="Loaded UI bundle — refresh if this is not the newest build">
                UI {BUILD_ID}
              </span>
            </>
          ) : null}
        </footer>

        <LogApplicationForm
          open={logOpen}
          onClose={() => setLogOpen(false)}
          onSaved={() => {
            void load();
            setRefreshKey((key) => key + 1);
          }}
        />
      </main>
    </div>
  );
}
