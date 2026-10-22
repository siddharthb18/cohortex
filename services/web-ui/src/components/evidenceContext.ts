import { createContext, useContext } from 'react';
import type { NumberRef } from '../api/types';

export interface EvidenceTarget {
  investigationId: string;
  evidenceId: string;
  /** Present when opened from a number in a claim. */
  ref?: NumberRef;
  claimText?: string;
  /** Identifies the trigger so it can show aria-expanded. */
  key: string;
}

export interface EvidenceContextValue {
  current: EvidenceTarget | null;
  open(target: EvidenceTarget, trigger: HTMLElement | null): void;
  close(): void;
}

export const EvidenceContext = createContext<EvidenceContextValue | null>(null);

export function useEvidence(): EvidenceContextValue {
  const value = useContext(EvidenceContext);
  if (!value) throw new Error('useEvidence must be used inside <EvidenceProvider>');
  return value;
}
