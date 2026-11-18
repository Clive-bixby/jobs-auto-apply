import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import type { Job, JobStatus, Status } from '../types';
import { Empty, Notice, Pill, Score, Spinner } from '../components/ui';

interface Props {
  status: Status | null;
  refreshKey: number;
  onChanged: () => Promise<void>;
}

type Filter = 'pending' | 'approved' | 'rejected' | 'all';

export default function Review({ status, refreshKey, onChanged }: Props) {
  const [filter, setFilter] = useState<Filter>('pending');
  const [platform, setPlatform] = useState('all');
  const [query, setQuery] = useState('');
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [detail, setDetail] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const params = new URLSearchParams({ status_filter: filter, platform });
      if (query.trim()) params.set('q', query.trim());
      const data = await api.get<{ items: Job[] }>(`/api/jobs?${params.toString()}`);
      setJobs(data.items);
      setSelected((prev) => {
        const live = new Set(data.items.map((j) => j.job_key));
        return new Set([...prev].filter((key) => live.has(key)));
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setJobs([]);
    }
  }, [filter, platform, query]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const decide = async (keys: string[], next: JobStatus) => {
    if (keys.length === 0) return;
    setWorking(true);
    setError(null);
    try {
      await api.post('/api/jobs/decision', { job_keys: keys, status: next });
      setDetail(null);
      await load();
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setWorking(false);
    }
  };

  const toggle = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const allVisibleSelected = useMemo(
    () => (jobs?.length ?? 0) > 0 && selected.size === jobs?.length,
    [jobs, selected],
  );

  const toggleAll = () => {
    if (!jobs) return;
    setSelected(allVisibleSelected ? new Set() : new Set(jobs.map((job) => job.job_key)));
  };

  const approvedCount = status?.counts.approved ?? 0;

  return (
    <div className="stack">
      {error ? <Notice kind="error">{error}</Notice> : null}

      <div className="toolbar">
        <div className="segmented">
          {(['pending', 'approved', 'rejected', 'all'] as Filter[]).map((value) => (
            <button
              key={value}
              type="button"
              className={`seg${filter === value ? ' active' : ''}`}
              onClick={() => setFilter(value)}
            >
              {value === 'all' ? 'All' : value.charAt(0).toUpperCase() + value.slice(1)}
            </button>
          ))}
        </div>

        <select value={platform} onChange={(event) => setPlatform(event.target.value)}>
          <option value="all">All platforms</option>
          {(status ? Object.keys(status.by_platform) : []).map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>

        <input
          type="search"
          placeholder="Search title, company or description…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />

        <div className="toolbar-spacer" />

        <span className="muted small">
          {selected.size > 0 ? `${selected.size} selected · ` : ''}
          {jobs?.length ?? 0} shown
        </span>

        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => decide([...selected], 'rejected')}
          disabled={selected.size === 0 || working}
        >
          Reject
        </button>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => decide([...selected], 'approved')}
          disabled={selected.size === 0 || working}
        >
          Approve {selected.size || ''}
        </button>
      </div>

      {jobs === null ? (
        <Spinner label="Loading the review queue…" />
      ) : jobs.length === 0 ? (
        <Empty>
          No jobs match this filter. Run a discovery pass from the top bar to collect candidates.
        </Empty>
      ) : (
        <div className="panel table-panel">
          <table className="table">
            <thead>
              <tr>
                <th className="check">
                  <input type="checkbox" checked={allVisibleSelected} onChange={toggleAll} />
                </th>
                <th>Role</th>
                <th>Company</th>
                <th>Platform</th>
                <th className="score-col">Match</th>
                <th>Status</th>
                <th className="actions-col">Decision</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.job_key} className={selected.has(job.job_key) ? 'row-selected' : ''}>
                  <td className="check">
                    <input
                      type="checkbox"
                      checked={selected.has(job.job_key)}
                      onChange={() => toggle(job.job_key)}
                    />
                  </td>
                  <td className="role-cell">
                    <button type="button" className="link" onClick={() => setDetail(job)}>
                      {job.title}
                    </button>
                    <div className="cell-sub">
                      {job.salary_display || job.score_reason || '—'}
                    </div>
                  </td>
                  <td>{job.company || <span className="muted">—</span>}</td>
                  <td>
                    <Pill value={job.platform} />
                  </td>
                  <td className="score-col">
                    <Score value={job.score} />
                  </td>
                  <td>
                    <Pill value={job.status} />
                  </td>
                  <td className="actions-col">
                    <div className="row-buttons">
                      {job.status !== 'approved' ? (
                        <button
                          type="button"
                          className="btn btn-mini btn-primary"
                          onClick={() => decide([job.job_key], 'approved')}
                          disabled={working}
                        >
                          Approve
                        </button>
                      ) : null}
                      {job.status !== 'rejected' ? (
                        <button
                          type="button"
                          className="btn btn-mini btn-ghost"
                          onClick={() => decide([job.job_key], 'rejected')}
                          disabled={working}
                        >
                          Reject
                        </button>
                      ) : null}
                      {job.status !== 'pending' ? (
                        <button
                          type="button"
                          className="btn btn-mini btn-ghost"
                          onClick={() => decide([job.job_key], 'pending')}
                          disabled={working}
                        >
                          Reset
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="muted small">
        {approvedCount} approved job{approvedCount === 1 ? '' : 's'} ready. Use “Apply approved” in
        the top bar to run the bot's existing submission workflow — it reads this queue directly.
      </p>

      {detail ? (
        <div className="drawer-backdrop" onClick={() => setDetail(null)}>
          <aside className="drawer" onClick={(event) => event.stopPropagation()}>
            <header className="drawer-head">
              <div>
                <h2>{detail.title}</h2>
                <p className="muted small">
                  {detail.company || 'Unknown company'} · {detail.platform} ·{' '}
                  <span className="mono">{detail.job_key.split(':')[1]}</span>
                </p>
              </div>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDetail(null)}>
                Close
              </button>
            </header>

            <div className="drawer-score">
              <Score value={detail.score} />
              <span className="muted small">{detail.score_reason}</span>
            </div>

            <dl className="facts tight">
              <div>
                <dt>Salary</dt>
                <dd>{detail.salary_display || '—'}</dd>
              </div>
              <div>
                <dt>Salary eligible</dt>
                <dd>
                  {detail.salary_eligible === null
                    ? 'unknown'
                    : detail.salary_eligible
                      ? 'yes'
                      : `no — ${detail.salary_reason}`}
                </dd>
              </div>
              <div>
                <dt>Resume used</dt>
                <dd className="mono">{detail.resume}</dd>
              </div>
              <div>
                <dt>Location blocked</dt>
                <dd>{detail.location_blocked ? 'yes' : 'no'}</dd>
              </div>
              <div>
                <dt>Score</dt>
                <dd>
                  profile {detail.profile_score.toFixed(1)} · salary{' '}
                  {detail.salary_score.toFixed(1)}
                </dd>
              </div>
            </dl>

            <section className="drawer-section">
              <h3>Cover note</h3>
              {detail.cover_letter ? (
                <pre className="prose">{detail.cover_letter}</pre>
              ) : (
                <p className="muted">
                  No cover note stored for this job. It is generated during enrichment; re-run
                  discovery to refresh.
                </p>
              )}
            </section>

            <section className="drawer-section">
              <h3>Job description</h3>
              {detail.jd ? (
                <pre className="prose">{detail.jd}</pre>
              ) : (
                <p className="muted">No job description captured.</p>
              )}
            </section>

            <footer className="drawer-foot">
              {detail.url ? (
                <a className="btn btn-ghost btn-sm" href={detail.url} target="_blank" rel="noopener">
                  Open posting
                </a>
              ) : null}
              <div className="toolbar-spacer" />
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => decide([detail.job_key], 'rejected')}
                disabled={working}
              >
                Reject
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => decide([detail.job_key], 'approved')}
                disabled={working || detail.status === 'approved'}
              >
                {detail.status === 'approved' ? 'Already approved' : 'Approve for submission'}
              </button>
            </footer>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
