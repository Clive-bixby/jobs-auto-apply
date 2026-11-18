import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import type { ApplyMode, PlatformInfo, PreferencesResponse, Status } from '../types';
import { Empty, Notice, Pill, Spinner } from '../components/ui';

interface Props {
  status: Status | null;
  refreshKey: number;
  onChanged: () => Promise<void>;
}

const MODE_LABEL: Record<ApplyMode, string> = {
  inherit: 'Follow config.yaml',
  dry: 'Force dry run (no submissions)',
  live: 'Force live submissions',
};

export default function Settings({ status, refreshKey, onChanged }: Props) {
  const [prefs, setPrefs] = useState<PreferencesResponse | null>(null);
  const [platforms, setPlatforms] = useState<Record<string, PlatformInfo> | null>(null);
  const [draft, setDraft] = useState<PreferencesResponse['preferences'] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [prefData, platformData] = await Promise.all([
        api.get<PreferencesResponse>('/api/preferences'),
        api.get<{ platforms: Record<string, PlatformInfo> }>('/api/platforms'),
      ]);
      setPrefs(prefData);
      setDraft(prefData.preferences);
      setPlatforms(platformData.platforms);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.put('/api/preferences', {
        paused: draft.paused,
        apply_mode: draft.apply_mode,
        discovery_limit: draft.discovery_limit,
        platforms: draft.platforms,
      });
      setSaved(true);
      await load();
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  if (!prefs || !draft || !platforms) {
    return error ? <Notice kind="error">{error}</Notice> : <Spinner label="Loading preferences…" />;
  }

  const updatePlatform = (name: string, patch: Partial<{ enabled: boolean | null; keywords: string }>) => {
    setDraft({
      ...draft,
      platforms: {
        ...draft.platforms,
        [name]: { ...(draft.platforms[name] ?? { enabled: null, keywords: '' }), ...patch },
      },
    });
  };

  return (
    <div className="stack">
      {error ? <Notice kind="error">{error}</Notice> : null}
      {saved ? <Notice kind="info">Preferences saved.</Notice> : null}

      <Notice kind="info">{prefs.note}</Notice>

      <div className="grid-2">
        <section className="panel">
          <div className="panel-head">
            <h2>Automation</h2>
          </div>

          <label className="field">
            <span className="field-label">State</span>
            <div className="segmented">
              <button
                type="button"
                className={`seg${draft.paused ? '' : ' active'}`}
                onClick={() => setDraft({ ...draft, paused: false })}
              >
                Running
              </button>
              <button
                type="button"
                className={`seg${draft.paused ? ' active' : ''}`}
                onClick={() => setDraft({ ...draft, paused: true })}
              >
                Paused
              </button>
            </div>
            <span className="field-hint">
              Paused blocks new discovery and apply runs started from this dashboard.
            </span>
          </label>

          <label className="field">
            <span className="field-label">Submission mode</span>
            <select
              value={draft.apply_mode}
              onChange={(event) =>
                setDraft({ ...draft, apply_mode: event.target.value as ApplyMode })
              }
            >
              {prefs.apply_modes.map((mode) => (
                <option key={mode} value={mode}>
                  {MODE_LABEL[mode]}
                </option>
              ))}
            </select>
            <span className="field-hint">
              <code>config.yaml</code> currently has{' '}
              <code>dry_run: {String(prefs.config_dry_run)}</code>.
            </span>
          </label>

          <label className="field">
            <span className="field-label">Per-platform limit</span>
            <input
              type="number"
              min={1}
              max={200}
              value={draft.discovery_limit}
              onChange={(event) =>
                setDraft({ ...draft, discovery_limit: Number(event.target.value) || 1 })
              }
            />
            <span className="field-hint">
              Discovery target and per-platform apply batch. <code>config.yaml</code> uses{' '}
              {prefs.config_jobs_per_platform === 0
                ? 'unlimited'
                : prefs.config_jobs_per_platform}
              .
            </span>
          </label>

          <div className="row-actions">
            <button type="button" className="btn btn-primary" onClick={save} disabled={saving}>
              {saving ? 'Saving…' : 'Save preferences'}
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setDraft(prefs.preferences)}
              disabled={saving}
            >
              Discard changes
            </button>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>Effective configuration</h2>
          </div>
          {status ? (
            <dl className="facts tight">
              <div>
                <dt>Resume</dt>
                <dd className="mono">
                  {status.config.resume}
                  {status.config.resume_exists ? '' : ' (missing!)'}
                </dd>
              </div>
              <div>
                <dt>Email set</dt>
                <dd>{status.config.email ? 'yes' : 'no — set user.email in config.yaml'}</dd>
              </div>
              <div>
                <dt>Review queue</dt>
                <dd className="mono">{status.config.review_dir}</dd>
              </div>
              <div>
                <dt>Salary floor</dt>
                <dd>₹{status.config.min_inr_salary_lpa}L</dd>
              </div>
              <div>
                <dt>One job per company</dt>
                <dd>{status.config.one_job_per_company ? 'yes' : 'no'}</dd>
              </div>
              <div>
                <dt>Parallel platforms</dt>
                <dd>{status.config.parallel_platforms ? 'yes' : 'no'}</dd>
              </div>
              <div>
                <dt>Approval gate</dt>
                <dd>
                  <Pill value="enforced" /> the dashboard only submits approved jobs
                </dd>
              </div>
            </dl>
          ) : (
            <Empty>Loading configuration…</Empty>
          )}
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2>Target platforms</h2>
          <span className="muted small">
            {Object.values(platforms).filter((p) => p.enabled).length} enabled
          </span>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>Platform</th>
              <th>Enabled</th>
              <th>Search terms</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {Object.values(platforms).map((platform) => {
              const entry = draft.platforms[platform.name] ?? { enabled: null, keywords: '' };
              return (
                <tr key={platform.name}>
                  <td>
                    <div className="strong">{platform.label}</div>
                    <div className="cell-sub">
                      config.yaml: {platform.config_enabled ? 'enabled' : 'disabled'}
                    </div>
                  </td>
                  <td>
                    <select
                      value={entry.enabled === null ? 'inherit' : entry.enabled ? 'on' : 'off'}
                      onChange={(event) =>
                        updatePlatform(platform.name, {
                          enabled:
                            event.target.value === 'inherit'
                              ? null
                              : event.target.value === 'on',
                        })
                      }
                    >
                      <option value="inherit">Inherit</option>
                      <option value="on">Enabled</option>
                      <option value="off">Disabled</option>
                    </select>
                  </td>
                  <td>
                    {platform.keywords_editable ? (
                      <input
                        type="text"
                        value={entry.keywords || platform.keywords}
                        placeholder={platform.keywords || 'comma-separated'}
                        onChange={(event) =>
                          updatePlatform(platform.name, { keywords: event.target.value })
                        }
                      />
                    ) : (
                      <span className="muted small">configured in config.yaml</span>
                    )}
                  </td>
                  <td className="muted small">
                    {platform.search_urls.length > 0
                      ? `${platform.search_urls.length} search URL(s)`
                      : platform.feed_count > 0
                        ? `${platform.feed_count} feed(s)`
                        : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="muted small">
          Keyword overrides apply to discovery runs started here. Clear the field to keep
          <code> config.yaml</code>'s value.
        </p>
      </section>
    </div>
  );
}
