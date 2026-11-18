import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import type { ApplicationRow, Status } from '../types';
import { Empty, Notice, Pill, Spinner } from '../components/ui';

interface Props {
  status: Status | null;
  refreshKey: number;
  onChanged: () => Promise<void>;
  onLog: () => void;
}

type StatusFilter = 'all' | 'applied' | 'abandoned' | 'deferred';

export default function Applications({ status, refreshKey, onChanged, onLog }: Props) {
  const [rows, setRows] = useState<ApplicationRow[] | null>(null);
  const [platform, setPlatform] = useState('all');
  const [state, setState] = useState<StatusFilter>('all');
  const [query, setQuery] = useState('');
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const params = new URLSearchParams();
      if (platform !== 'all') params.set('platform', platform);
      const data = await api.get<{ items: ApplicationRow[] }>(
        `/api/applications?${params.toString()}`,
      );
      setRows(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setRows([]);
    }
  }, [platform]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const remove = async (key: string) => {
    setError(null);
    try {
      await api.delete(`/api/applications/manual?key=${encodeURIComponent(key)}`);
      await load();
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const visible = (rows ?? []).filter((row) => {
    if (state !== 'all' && row.status !== state) return false;
    const needle = query.trim().toLowerCase();
    if (!needle) return true;
    return `${row.role} ${row.company} ${row.family}`.toLowerCase().includes(needle);
  });

  const appliedCount = visible.filter((row) => row.status === 'applied').length;
  const manualCount = visible.filter((row) => row.manual).length;

  return (
    <div className="stack">
      {error ? <Notice kind="error">{error}</Notice> : null}

      <div className="toolbar">
        <button
          type="button"
          className="btn btn-primary"
          onClick={onLog}
          title="Add an application you submitted outside this bot"
        >
          + Log external application
        </button>

        <select value={platform} onChange={(event) => setPlatform(event.target.value)}>
          <option value="all">All platforms</option>
          {(status ? Object.keys(status.by_platform) : []).map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>

        <select value={state} onChange={(event) => setState(event.target.value as StatusFilter)}>
          <option value="all">All statuses</option>
          <option value="applied">Applied</option>
          <option value="abandoned">Abandoned</option>
          <option value="deferred">Deferred</option>
        </select>

        <input
          type="search"
          placeholder="Search role, company, role family…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />

        <div className="toolbar-spacer" />

        <span className="muted small">
          {appliedCount} applied of {visible.length} shown
          {manualCount ? ` · ${manualCount} logged manually` : ''}
        </span>
      </div>

      {rows === null ? (
        <Spinner label="Loading application history…" />
      ) : visible.length === 0 ? (
        <Empty>
          No application records yet. The bot writes these to <code>data/applied_jobs.json</code>{' '}
          as it submits — or log one you sent yourself with “+ Log external application”.
        </Empty>
      ) : (
        <div className="panel table-panel">
          <table className="table">
            <thead>
              <tr>
                <th>Applied</th>
                <th>Platform</th>
                <th>Role</th>
                <th>Company</th>
                <th>Status</th>
                <th>Note</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map((row, index) => (
                <tr key={`${row.job_key}-${index}`}>
                  <td className="nowrap">
                    <div>{row.applied_at || '—'}</div>
                    <div className="cell-sub">{row.relative}</div>
                  </td>
                  <td>
                    <Pill value={row.platform_key} />
                  </td>
                  <td>
                    <div className="strong">
                      {row.role}
                      {row.manual ? <span className="tag manual-tag">logged</span> : null}
                    </div>
                    <div className="cell-sub">{row.family}</div>
                  </td>
                  <td>
                    <div className="company-cell">
                      <span className="avatar" style={{ background: row.avatar_color }}>
                        {row.initial}
                      </span>
                      {row.company}
                    </div>
                  </td>
                  <td>
                    <Pill value={row.status} />
                  </td>
                  <td className="muted small">{row.reason || '—'}</td>
                  <td>
                    <div className="row-buttons">
                      {row.url ? (
                        <a className="link" href={row.url} target="_blank" rel="noopener">
                          Open
                        </a>
                      ) : null}
                      {row.manual ? (
                        <button
                          type="button"
                          className="link danger"
                          onClick={() => void remove(row.job_key)}
                          title="Remove this manually logged entry"
                        >
                          Delete
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
    </div>
  );
}
