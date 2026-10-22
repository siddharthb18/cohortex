import { lazy, Suspense, useEffect } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError } from './api';
import { EvidenceProvider } from './components/EvidenceDrawer';
import { EmptyState, SkeletonRows } from './components/Feedback';
import { Layout } from './components/Layout';
import { AlertsPage } from './pages/AlertsPage';
import { EvalsPage } from './pages/EvalsPage';
import { FleetPage } from './pages/FleetPage';
import { InvestigatePage } from './pages/InvestigatePage';
import { useRoute, type Route } from './router';
import { Link } from './components/Link';

// Charts (Recharts) are only needed on the Cohort page; keep them out of the first load.
const CohortPage = lazy(() =>
  import('./pages/CohortPage').then((m) => ({ default: m.CohortPage })),
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      // Retry once on network or server errors, never on 4xx.
      retry: (count, error) =>
        count < 1 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
    },
  },
});

const TITLES: Record<string, string> = {
  investigate: 'Investigate',
  fleet: 'Fleet',
  cohort: 'Cohort',
  alerts: 'Alerts',
  evals: 'Evals',
};

function Page({ route }: { route: Route }) {
  const first = route.segments[0] ?? 'investigate';
  switch (first) {
    case 'investigate':
      return <InvestigatePage route={route} />;
    case 'fleet':
      return <FleetPage route={route} />;
    case 'cohort':
      return route.segments.length >= 3 ? (
        <Suspense fallback={<SkeletonRows rows={6} />}>
          <CohortPage key={route.path} route={route} />
        </Suspense>
      ) : (
        <FleetPage route={route} />
      );
    case 'alerts':
      return <AlertsPage />;
    case 'evals':
      return <EvalsPage />;
    default:
      return (
        <EmptyState title="Page not found">
          <Link to="/investigate">Go to Investigate</Link>
        </EmptyState>
      );
  }
}

export function App() {
  const route = useRoute();
  const first = route.segments[0] ?? 'investigate';

  useEffect(() => {
    const section = TITLES[first];
    const detail = first === 'cohort' ? route.segments[2] : undefined;
    const name = detail ?? section;
    document.title = name ? `${name} | Cohortex` : 'Cohortex';
  }, [first, route.segments]);

  return (
    <QueryClientProvider client={queryClient}>
      <EvidenceProvider>
        <Layout>
          <Page route={route} />
        </Layout>
      </EvidenceProvider>
    </QueryClientProvider>
  );
}
