import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../api';
import { Notice } from './ui';

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

const PLATFORM_OPTIONS = [
  'manual',
  'naukri',
  'hirist',
  'instahyre',
  'wellfound',
  'uplers',
  'linkedin',
  'indeed',
  'other',
];

const today = () => new Date().toISOString().slice(0, 10);

const emptyForm = () => ({
  title: '',
  company: '',
  url: '',
  platform: 'manual',
  applied_at: today(),
  note: '',
});

/** Drawer for logging a job you applied to outside this bot. */
export default function LogApplicationForm({ open, onClose, onSaved }: Props) {
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  if (!open) return null;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form.title.trim()) {
      setError('A job title is required.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.post('/api/applications/manual', {
        title: form.title.trim(),
        company: form.company.trim(),
        url: form.url.trim(),
        platform: form.platform,
        applied_at: form.applied_at || null,
        note: form.note.trim(),
      });
      setForm(emptyForm());
      setSaving(false);
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSaving(false);
    }
  };

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(event) => event.stopPropagation()}>
        <header className="drawer-head">
          <div>
            <h2>Log an application made outside this bot</h2>
            <p className="muted small">
              Goes into <code>data/applied_jobs.json</code> — the same history the bot writes — so
              it shows up in the table and the CSV/HTML export. Nothing is submitted.
            </p>
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            Close
          </button>
        </header>

        {error ? <Notice kind="error">{error}</Notice> : null}

        <form onSubmit={submit}>
          <div className="form-grid">
            <label className="field field-wide">
              <span className="field-label">Job title *</span>
              <input
                type="text"
                value={form.title}
                onChange={(event) => setForm({ ...form, title: event.target.value })}
                placeholder="Full Stack Developer"
                required
                autoFocus
              />
            </label>

            <label className="field">
              <span className="field-label">Company</span>
              <input
                type="text"
                value={form.company}
                onChange={(event) => setForm({ ...form, company: event.target.value })}
                placeholder="Acme Corp"
              />
            </label>

            <label className="field">
              <span className="field-label">Where you applied</span>
              <select
                value={form.platform}
                onChange={(event) => setForm({ ...form, platform: event.target.value })}
              >
                {PLATFORM_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option === 'manual' ? 'Manual / other' : option}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span className="field-label">Date applied</span>
              <input
                type="date"
                value={form.applied_at}
                onChange={(event) => setForm({ ...form, applied_at: event.target.value })}
              />
            </label>

            <label className="field">
              <span className="field-label">Job URL</span>
              <input
                type="text"
                value={form.url}
                onChange={(event) => setForm({ ...form, url: event.target.value })}
                placeholder="https://…"
              />
            </label>

            <label className="field field-wide">
              <span className="field-label">Note</span>
              <input
                type="text"
                value={form.note}
                onChange={(event) => setForm({ ...form, note: event.target.value })}
                placeholder="Referred by…, recruiter said…, response pending…"
              />
            </label>
          </div>

          <div className="drawer-foot">
            <div className="toolbar-spacer" />
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={saving}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? 'Saving…' : 'Add to history'}
            </button>
          </div>
        </form>
      </aside>
    </div>
  );
}
