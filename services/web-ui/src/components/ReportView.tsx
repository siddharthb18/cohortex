import type { Claim, Report } from '../api/types';
import { ConfidenceBadge } from './Badges';
import { ClaimText } from './ClaimText';
import { AlertIcon, DownloadIcon } from './icons';

interface Props {
  report: Report;
  markdown: string | null;
  investigationId: string;
}

function ClaimList({
  claims,
  investigationId,
  section,
  className,
}: {
  claims: Claim[];
  investigationId: string;
  section: string;
  className?: string;
}) {
  return (
    <ul className={`claims ${className ?? ''}`}>
      {claims.map((claim, i) => (
        <li key={i}>
          <ClaimText claim={claim} investigationId={investigationId} claimKey={`${section}:${i}`} />
        </li>
      ))}
    </ul>
  );
}

function downloadMarkdown(markdown: string, id: string) {
  const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `cohortex-investigation-${id}.md`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ReportView({ report, markdown, investigationId }: Props) {
  return (
    <article className="panel report" aria-labelledby="report-title" data-testid="report">
      <h2 id="report-title" className="sr-only">
        Report
      </h2>

      <section className="report-section" aria-labelledby="sec-summary">
        <h2 id="sec-summary">Summary</h2>
        {report.summary.length > 0 ? (
          <ClaimList
            claims={report.summary}
            investigationId={investigationId}
            section="summary"
            className="summary-claims"
          />
        ) : (
          <p className="secondary">
            No claim passed the evidence check strongly enough for the summary.
          </p>
        )}
      </section>

      {report.findings.length > 0 && (
        <section className="report-section" aria-labelledby="sec-findings">
          <h2 id="sec-findings">
            Findings <span className="count">{report.findings.length}</span>
          </h2>
          <ClaimList
            claims={report.findings}
            investigationId={investigationId}
            section="findings"
            className="findings"
          />
        </section>
      )}

      {report.hypotheses.length > 0 && (
        <section className="report-section" aria-labelledby="sec-hypotheses">
          <h2 id="sec-hypotheses">
            Hypotheses <span className="count">{report.hypotheses.length}</span>
          </h2>
          <ul className="hypotheses">
            {report.hypotheses.map((h, i) => (
              <li key={i} className="hypothesis">
                <div className="hypothesis-head">
                  <p className="hypothesis-statement">{h.statement}</p>
                  <ConfidenceBadge confidence={h.confidence} />
                </div>
                {h.support.length > 0 && (
                  <ClaimList
                    claims={h.support}
                    investigationId={investigationId}
                    section={`hypothesis:${i}`}
                  />
                )}
                <p className="confirm">
                  <b>How to confirm:</b> {h.how_to_confirm}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {report.recommended_actions.length > 0 && (
        <section className="report-section" aria-labelledby="sec-actions">
          <h2 id="sec-actions">Recommended actions</h2>
          <ol className="plain-list actions-list">
            {report.recommended_actions.map((action, i) => (
              <li key={i}>{action}</li>
            ))}
          </ol>
        </section>
      )}

      {report.limitations.length > 0 && (
        <section className="report-section" aria-labelledby="sec-limitations">
          <h2 id="sec-limitations">Limitations</h2>
          <ul className="plain-list secondary">
            {report.limitations.map((limitation, i) => (
              <li key={i}>{limitation}</li>
            ))}
          </ul>
        </section>
      )}

      {report.unverified.length > 0 && (
        <section
          className="report-section unverified"
          aria-labelledby="sec-unverified"
          data-testid="unverified"
        >
          <h2 id="sec-unverified">
            Unverified <span className="count">{report.unverified.length}</span>
          </h2>
          <p className="secondary" style={{ fontSize: '0.8125rem', marginBottom: 12 }}>
            These claims failed the evidence check and are kept out of the summary.
          </p>
          <ul className="claims">
            {report.unverified.map((claim, i) => (
              <li key={i}>
                <span className="failed-label">
                  <AlertIcon size={12} /> Failed evidence check
                </span>
                <ClaimText
                  claim={claim}
                  investigationId={investigationId}
                  claimKey={`unverified:${i}`}
                />
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="report-footer">
        <span>
          {report.mode === 'orchestrated' ? 'Orchestrated' : 'Single-agent'} mode, model{' '}
          <span className="mono">{report.model_id}</span>
        </span>
        {markdown && (
          <button
            type="button"
            className="button button-small"
            onClick={() => downloadMarkdown(markdown, investigationId)}
          >
            <DownloadIcon size={14} /> Download Markdown
          </button>
        )}
      </div>
    </article>
  );
}
