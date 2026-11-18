import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Job, Status } from '../types';
import { Empty, Pill, Score, Stat, duration, timeAgo } from '../components/ui';

interface Props {
  status: Status | null;
  onStartDiscovery: () => void;
  onStartApply: () => void;
  busy: boolean;
}

export default function Overview({ status, onStartDiscovery, onStartApply, busy }: Props) {
  if (!status) return <Empty>Loading dashboard…</Empty>;

  const { counts, by_platform, automation, config } = status;
  const platforms = Object.values(by_platform);
  const current = automation.current;

  return (
    <div className="stack">
      <section className="stats">
        <Stat label="Awaiting review" value={counts.pending} hint="discovered, not decided" />
        <Stat
          label="Approved"
          value={counts.approved}
          hint="queued for submission"
        />
        <Stat
          label="Applied (total)"
          value={counts.applied}
          hint="verified in history · add your own under Applications"
        />
        <Stat
          label="Needs attention"
          value={counts.failures + counts.questions}
          hint={`${counts.failures} failures · ${counts.questions} questions`}
        />
      </section>

      <div className="grid-2">
        <section className="panel">
          <div className="panel-head">
            <h2>Automation</h2>
            <span className={`badge ${automation.paused ? 'badge-warn' : 'badge-ok'}`}>
              {automation.paused ? 'paused' : automation.busy ? 'running' : 'ready'}
            </span>
          </div>

          {current ? (
            <div className="current-run">
              <div className="current-run-head">
                <strong>
                  {current.kind === 'discovery' ? 'Discovering jobs' : 'Submitting approved jobs'}
                </strong>
                <span className="muted">{duration(current.started_at, null)} elapsed</span>
              </div>
              <p className="muted small">
                {current.platform === 'all' ? 'All enabled platforms' : current.platform} · started{' '}
                {timeAgo(current.started_at)}
              </p>
              <p className="muted small">
                A headed browser window is driving this run — leave it running. Progress appears in
                Activity &amp; logs.
              </p>
            </div>
          ) : (
            <>
              <p className="muted">
                Discovery collects, enriches and scores jobs into the review queue without
                submitting anything. Submissions only ever run for jobs you approved.
              </p>
              <div className="row-actions">
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={onStartDiscovery}
                  disabled={busy}
                >
                  Start discovery
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={onStartApply}
                  disabled={busy || counts.approved === 0}
                >
                  Apply {counts.approved} approved
                </button>
              </div>
            </>
          )}

          <dl className="facts">
            <div>
              <dt>Submission mode</dt>
              <dd>
                {automation.apply_mode === 'inherit'
                  ? `config.yaml (${config.resume ? 'live' : '—'})`
                  : automation.apply_mode === 'dry'
                    ? 'Dry run (no submissions)'
                    : 'Live submissions'}
              </dd>
            </div>
            <div>
              <dt>Per-platform limit</dt>
              <dd>{automation.discovery_limit} jobs</dd>
            </div>
            <div>
              <dt>Salary floor</dt>
              <dd>₹{config.min_inr_salary_lpa}L</dd>
            </div>
            <div>
              <dt>One job per company</dt>
              <dd>{config.one_job_per_company ? 'yes' : 'no'}</dd>
            </div>
          </dl>
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>Platforms</h2>
            <span className="muted small">
              {platforms.filter((p) => p.enabled).length} enabled
            </span>
          </div>
          <table className="table compact">
            <thead>
              <tr>
                <th>Platform</th>
                <th className="num">Pending</th>
                <th className="num">Approved</th>
                <th className="num">Rejected</th>
              </tr>
            </thead>
            <tbody>
              {platforms.map((platform) => (
                <tr key={platform.label}>
                  <td>
                    <span className="platform-name">
                      {platform.label}
                      {platform.enabled ? null : <span className="tag">off</span>}
                    </span>
                  </td>
                  <td className="num">{platform.pending}</td>
                  <td className="num">{platform.approved}</td>
                  <td className="num">{platform.rejected}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2>Recent runs</h2>
        </div>
        {automation.runs.length === 0 ? (
          <Empty>No runs yet. Start a discovery run to fill the review queue.</Empty>
        ) : (
          <table className="table compact">
            <thead>
              <tr>
                <th>When</th>
                <th>Run</th>
                <th>Platform</th>
                <th>Status</th>
                <th className="num">Discovered</th>
                <th className="num">Applied</th>
                <th>Took</th>
              </tr>
            </thead>
            <tbody>
              {automation.runs.map((record) => (
                <tr key={record.id}>
                  <td className="muted">{timeAgo(record.started_at)}</td>
                  <td>{record.kind === 'discovery' ? 'Discovery' : 'Apply approved'}</td>
                  <td className="muted">{record.platform}</td>
                  <td>
                    <Pill value={record.status} />
                    {record.error ? <div className="cell-sub">{record.error}</div> : null}
                  </td>
                  <td className="num">{record.discovered || '—'}</td>
                  <td className="num">{record.applied || '—'}</td>
                  <td className="muted">{duration(record.started_at, record.finished_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Top matches waiting for you</h2>
        </div>
        <TopMatches />
      </section>
    </div>
  );
}

function TopMatches() {
  const [jobs, setJobs] = useState<Job[] | null>(null);

  useEffect(() => {
    let live = true;
    api
      .get<{ items: Job[] }>('/api/jobs?status_filter=pending')
      .then((data) => {
        if (live) setJobs(data.items.slice(0, 5));
      })
      .catch(() => {
        if (live) setJobs([]);
      });
    return () => {
      live = false;
    };
  }, []);

  if (jobs === null) return <Empty>Loading…</Empty>;
  if (jobs.length === 0) return <Empty>Nothing pending — start a discovery run.</Empty>;

  return (
    <ul className="match-list">
      {jobs.map((job) => (
        <li key={job.job_key}>
          <div className="match-main">
            <span className="match-title">{job.title}</span>
            <span className="muted small">
              {job.company || 'Unknown company'} · {job.platform}
            </span>
          </div>
          <Score value={job.score} />
        </li>
      ))}
    </ul>
  );
}
