import type { ReactNode } from 'react';

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const diff = Date.now() - then;
  const mins = Math.round(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return `${Math.round(days / 30)}mo ago`;
}

export function duration(startIso: string, endIso: string | null): string {
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const secs = Math.max(0, Math.round((end - start) / 1000));
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

export function Pill({ value, className }: { value: string; className?: string }) {
  const safe = value.replace(/[^a-z0-9_-]/gi, '').toLowerCase();
  return <span className={`pill pill-${safe}${className ? ` ${className}` : ''}`}>{value}</span>;
}

export function Score({ value }: { value: number }) {
  const tone = value >= 7 ? 'high' : value >= 4 ? 'mid' : 'low';
  return (
    <span className={`score score-${tone}`}>
      <span className="score-value">{value.toFixed(1)}</span>
      <span className="score-track">
        <span className="score-fill" style={{ width: `${Math.min(100, value * 10)}%` }} />
      </span>
    </span>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint ? <div className="stat-hint">{hint}</div> : null}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="spinner-row">
      <span className="spinner" />
      {label ? <span>{label}</span> : null}
    </div>
  );
}

export function Notice({ kind, children }: { kind: 'error' | 'info' | 'warn'; children: ReactNode }) {
  return <div className={`notice notice-${kind}`}>{children}</div>;
}
