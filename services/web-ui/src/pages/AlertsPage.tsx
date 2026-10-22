import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import type { SuggestedAlert } from '../api/types';
import { EmptyState, ErrorNotice, SkeletonRows } from '../components/Feedback';
import { AlertIcon } from '../components/icons';
import { SOURCES } from '../config';
import { formatDateTime, formatPct, formatPValue, formatRatio } from '../lib/format';
import { buildPath } from '../router';
import { Link } from '../components/Link';

function investigateHref(alert: SuggestedAlert): string {
  return buildPath(['investigate'], {
    q: alert.suggested_question,
    source: alert.source,
    models: alert.model,
    from: alert.window_start,
    to: alert.window_end,
  });
}

export function AlertsPage() {
  const alerts = useQuery({ queryKey: ['alerts'], queryFn: () => api.suggestedAlerts() });

  return (
    <div className="section-gap">
      <div className="page-header">
        <div>
          <h1>Alerts</h1>
          <p>
            Cohorts whose failure rate shifted against the prior 90 days. Each alert comes with a
            suggested question; Investigate opens it ready to run.
          </p>
        </div>
      </div>
      <section className="panel" aria-label="Open alerts">
        {alerts.isPending ? (
          <SkeletonRows rows={4} />
        ) : alerts.isError ? (
          <div className="panel-pad">
            <ErrorNotice error={alerts.error} title="Could not load alerts." />
          </div>
        ) : alerts.data.length === 0 ? (
          <EmptyState title="No open alerts">
            Alerts appear here when change detection flags a cohort whose failure rate moved beyond
            its recent baseline.
          </EmptyState>
        ) : (
          <ul className="alert-list" data-testid="alert-list">
            {alerts.data.map((alert) => (
              <li key={alert.alert_id} className="alert-row">
                <div>
                  <div className="alert-title">
                    <h2>{alert.model}</h2>
                    <span className={`badge ${alert.status === 'open' ? 'badge-warn' : ''}`}>
                      <AlertIcon size={12} /> {alert.status === 'open' ? 'Open' : 'Resolved'}
                    </span>
                    {alert.source && (
                      <span className="muted" style={{ fontSize: '0.8125rem' }}>
                        {SOURCES[alert.source].label} {SOURCES[alert.source].media}
                      </span>
                    )}
                  </div>
                  <div className="alert-figures">
                    <span>
                      AFR <b>{formatPct(alert.baseline_afr)}</b> to{' '}
                      <b>{formatPct(alert.current_afr)}</b>
                    </span>
                    <span>
                      Rate ratio <b>{formatRatio(alert.rate_ratio)}</b>
                    </span>
                    <span>
                      p = <b>{formatPValue(alert.p_value)}</b>
                    </span>
                    <span>
                      Window {alert.window_start} to {alert.window_end}
                    </span>
                    {alert.opened_at && <span>Opened {formatDateTime(alert.opened_at)}</span>}
                  </div>
                  <p className="alert-question">{alert.suggested_question}</p>
                </div>
                <Link
                  to={investigateHref(alert)}
                  className="button button-primary"
                  aria-label={`Investigate ${alert.model}`}
                >
                  Investigate
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
