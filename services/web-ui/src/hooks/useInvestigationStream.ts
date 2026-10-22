import { useEffect, useReducer } from 'react';
import { api } from '../api';
import { initialStreamState, streamReducer, type StreamState } from '../lib/investigationStream';

/** Connect to an investigation's SSE stream (or the demo replay) and reduce its events. */
export function useInvestigationStream(id: string | null): StreamState {
  const [state, dispatch] = useReducer(streamReducer, initialStreamState);

  useEffect(() => {
    if (!id) {
      dispatch({ type: 'reset' });
      return undefined;
    }
    dispatch({ type: 'connect' });
    return api.openEvents(id, {
      onStep: (step) => dispatch({ type: 'step', step }),
      onReport: (data) => dispatch({ type: 'report', data }),
      onError: (data) => dispatch({ type: 'error', data }),
      onConnectionLost: (message) => dispatch({ type: 'connection_lost', message }),
    });
  }, [id]);

  return state;
}
