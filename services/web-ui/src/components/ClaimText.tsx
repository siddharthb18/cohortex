import { useMemo } from 'react';
import type { Claim, NumberRef } from '../api/types';
import { linkClaimNumbers } from '../lib/claimNumbers';
import { formatRefValue } from '../lib/format';
import { useEvidence } from './evidenceContext';

interface Props {
  claim: Claim;
  investigationId: string;
  /** Stable id for this claim within the report, used for trigger keys. */
  claimKey: string;
}

/** A claim's text with every cited number rendered as a button that opens its evidence (FR-UI-6). */
export function ClaimText({ claim, investigationId, claimKey }: Props) {
  const { segments, unplaced } = useMemo(() => linkClaimNumbers(claim), [claim]);

  return (
    <span className="claim">
      {segments.map((segment, i) =>
        segment.kind === 'text' ? (
          <span key={i}>{segment.text}</span>
        ) : (
          <NumberLink
            key={i}
            label={segment.text}
            numberRef={segment.ref}
            investigationId={investigationId}
            claimText={claim.text}
            triggerKey={`${claimKey}:${segment.refIndex}`}
          />
        ),
      )}
      {unplaced.length > 0 && (
        <span className="extra-refs">
          {unplaced.map(({ ref, refIndex }) => (
            <NumberLink
              key={refIndex}
              label={formatRefValue(ref)}
              numberRef={ref}
              investigationId={investigationId}
              claimText={claim.text}
              triggerKey={`${claimKey}:${refIndex}`}
            />
          ))}
        </span>
      )}
      {claim.passage_ids.length > 0 && (
        <span className="passages">[{claim.passage_ids.join(', ')}]</span>
      )}
    </span>
  );
}

function NumberLink({
  label,
  numberRef,
  investigationId,
  claimText,
  triggerKey,
}: {
  label: string;
  numberRef: NumberRef;
  investigationId: string;
  claimText: string;
  triggerKey: string;
}) {
  const evidence = useEvidence();
  const expanded = evidence.current?.key === triggerKey;
  return (
    <button
      type="button"
      className="num-link"
      aria-haspopup="dialog"
      aria-expanded={expanded}
      title={`Evidence ${numberRef.evidence_id}, field ${numberRef.field}`}
      data-evidence-id={numberRef.evidence_id}
      onClick={(event) =>
        evidence.open(
          {
            investigationId,
            evidenceId: numberRef.evidence_id,
            ref: numberRef,
            claimText,
            key: triggerKey,
          },
          event.currentTarget,
        )
      }
    >
      {label}
      <span className="sr-only">, show evidence</span>
    </button>
  );
}
