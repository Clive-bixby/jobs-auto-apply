import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import type { FailureRecord, RunRecord, Status } from '../types';
import { Empty, Notice, Pill, Spinner, duration, timeAgo } from '../components/ui';

interface Props {
  status: Status | null;
  refreshKey: number;
}

interface QuestionItem {
  question?: string;
  label?: string;
  [key: string]: unknown;
}

export default function Activity({ status, refreshKey }: Props) {
  const [failures, setFailures] = useState<FailureRecord[] | null>(null);
  const [logs, setLogs] = useState<{ path: string; content: string; files: string[] } | null>(null);
  const [questions, setQuestions] = useState<QuestionItem[]>([]);
  const [selectedRun, setSelectedRun] = useState<RunRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [failureData, logData, questionData] = await Promise.all([
        api.get<{ items: FailureRecord[] }>('/api/failures'),
        api.get<{ path: string; content: string; files: string[] }>('/api/logs?lines=300'),
        api.get<{ items: QuestionItem[] }>('/api/questions'),
      ]);
      setFailures(failureData.items);
      setLogs(logData);
      setQuestions(questionData.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setFailures([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const openRun = async (id: string) => {
    try {
      setSelectedRun(await api.get<RunRecord>(`/api/runs/${id}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const runs = status?.automation.runs ?? [];

  return (
    <div className="stack">
      {error ? <Notice kind="error">{error}</Notice> : null}

      <section className="panel">
        <div className="panel-head">
          <h2>Run history</h2>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void load()}>
            Refresh
          </button>
        </div>
        {runs.length === 0 ? (
          <Empty>No runs recorded yet.</Empty>
        ) : (
          <table className="table compact">
            <thead>
              <tr>
                <th>Started</th>
                <th>Run</th>
                <th>Platform</th>
                <th>Status</th>
                <th className="num">Discovered</th>
                <th className="num">Applied</th>
                <th>Took</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {runs.map((record) => (
                <tr key={record.id}>
                  <td className="nowrap">
                    <div>{timeAgo(record.started_at)}</div>
                    <div className="cell-sub">{record.id}</div>
                  </td>
                  <td>{record.kind === 'discovery' ? 'Discovery' : 'Apply approved'}</td>
                  <td className="muted">{record.platform}</td>
                  <td>
                    <Pill value={record.status} />
                    {record.error ? <div className="cell-sub">{record.error}</div> : null}
                  </td>
                  <td className="num">{record.discovered || '—'}</td>
                  <td className="num">{record.applied || '—'}</td>
                  <td className="muted">{duration(record.started_at, record.finished_at)}</td>
                  <td>
                    <button
                      type="button"
                      className="link"
                      onClick={() => void openRun(record.id)}
                    >
                      Log
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Technical failures</h2>
          <span className="muted small">{failures?.length ?? 0} tracked</span>
        </div>
        {failures === null ? (
          <Spinner />
        ) : failures.length === 0 ? (
          <Empty>No failures recorded.</Empty>
        ) : (
          <table className="table compact">
            <thead>
              <tr>
                <th>Job</th>
                <th>Platform</th>
                <th>Reason</th>
                <th className="num">Attempts</th>
                <th>Last seen</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {failures.map((failure) => (
                <tr key={`${failure.source}-${failure.title}-${failure.last_seen}`}>
                  <td>
                    <div className="strong">{failure.title}</div>
                    <div className="cell-sub">{failure.company || '—'}</div>
                  </td>
                  <td>
                    <Pill value={failure.source} />
                  </td>
                  <td className="muted small">{failure.reason}</td>
                  <td className="num">{failure.count}</td>
                  <td className="muted nowrap">{timeAgo(failure.last_seen)}</td>
                  <td>
                    {failure.url ? (
                      <a className="link" href={failure.url} target="_blank" rel="noopener">
                        Open
                      </a>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Deferred screening questions</h2>
          <span className="muted small">{questions.length} pending</span>
        </div>
        {questions.length === 0 ? (
          <Empty>No deferred questions. The bot answered everything it was confident about.</Empty>
        ) : (
          <>
            <Notice kind="info">
              These need your answer. Answering is a recruiter-facing action, so the dashboard shows
              them read-only — use <code>python main.py answer-questions</code>.
            </Notice>
            <ul className="question-list">
              {questions.slice(0, 20).map((item, index) => (
                <li key={index}>
                  {String(item.question ?? item.label ?? JSON.stringify(item))}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Bot log</h2>
          <span className="muted small mono">{logs?.path ?? ''}</span>
        </div>
        {logs === null ? (
          <Spinner />
        ) : logs.content ? (
          <pre className="log">{logs.content}</pre>
        ) : (
          <Empty>Log file is empty.</Empty>
        )}
      </section>

      {selectedRun ? (
        <div className="drawer-backdrop" onClick={() => setSelectedRun(null)}>
          <aside className="drawer" onClick={(event) => event.stopPropagation()}>
            <header className="drawer-head">
              <div>
                <h2>
                  {selectedRun.kind === 'discovery' ? 'Discovery' : 'Apply approved'} ·{' '}
                  {selectedRun.id}
                </h2>
                <p className="muted small">
                  {selectedRun.platform} · {selectedRun.status} ·{' '}
                  {duration(selectedRun.started_at, selectedRun.finished_at)}
                </p>
              </div>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setSelectedRun(null)}
              >
                Close
              </button>
            </header>
            {selectedRun.error ? <Notice kind="error">{selectedRun.error}</Notice> : null}
            <pre className="log tall">{selectedRun.log || 'No output captured for this run.'}</pre>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
