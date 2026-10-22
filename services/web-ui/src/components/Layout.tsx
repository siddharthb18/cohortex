import { useEffect, useState, type ReactNode } from 'react';
import { IS_DEMO } from '../config';
import { useRoute } from '../router';
import { Link } from './Link';
import { InfoIcon, LogoMark, MoonIcon, SunIcon } from './icons';

type Theme = 'light' | 'dark';
const THEME_KEY = 'cohortex-theme';

function readStoredTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    return value === 'light' || value === 'dark' ? value : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => readStoredTheme() ?? systemTheme());

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const next: Theme = theme === 'dark' ? 'light' : 'dark';
  return (
    <button
      type="button"
      className="icon-button"
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      onClick={() => {
        setTheme(next);
        try {
          window.localStorage.setItem(THEME_KEY, next);
        } catch {
          // Storage can be blocked; the theme still applies for this visit.
        }
      }}
    >
      {theme === 'dark' ? <SunIcon size={18} /> : <MoonIcon size={18} />}
    </button>
  );
}

const NAV = [
  { to: '/investigate', label: 'Investigate', match: ['investigate', ''] },
  { to: '/fleet', label: 'Fleet', match: ['fleet', 'cohort'] },
  { to: '/alerts', label: 'Alerts', match: ['alerts'] },
  { to: '/evals', label: 'Evals', match: ['evals'] },
];

function focusMain() {
  const main = document.getElementById('main');
  main?.focus();
  main?.scrollIntoView();
}

export function Footer() {
  return (
    <footer className="footer">
      <div className="footer-inner">
        <div>
          <p>
            Hard drive data and statistics courtesy of{' '}
            <a href="https://www.backblaze.com/cloud-storage/resources/hard-drive-test-data">
              Backblaze
            </a>
            . The data is free and may not be sold.
          </p>
          <p>
            Alibaba SSD SMART logs from F. Xu, S. Han, P. P. C. Lee, et al.,{' '}
            <cite>
              General Feature Selection for Failure Prediction in Large-scale SSD Deployment
            </cite>
            , DSN 2021 (
            <a href="https://github.com/alibaba-edu/dcbrain/tree/master/ssd_smart_logs">dataset</a>
            ).
          </p>
        </div>
        <p className="footer-tagline">Every number links to its evidence.</p>
      </div>
    </footer>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const route = useRoute();
  const first = route.segments[0] ?? '';

  return (
    <div id="app-shell">
      <button type="button" className="skip-link" onClick={focusMain}>
        Skip to content
      </button>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/investigate" className="brand" aria-label="Cohortex home">
            <LogoMark />
            <span>Cohortex</span>
          </Link>
          <nav className="nav" aria-label="Main">
            {NAV.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                aria-current={item.match.includes(first) ? 'page' : undefined}
              >
                {item.label}
              </Link>
            ))}
          </nav>
          <ThemeToggle />
        </div>
      </header>
      {IS_DEMO && (
        <div className="demo-banner" role="note">
          <div className="demo-banner-inner">
            <InfoIcon />
            <span>Demo: a recorded live investigation over real Backblaze Q2 2026 data</span>
          </div>
        </div>
      )}
      <main id="main" tabIndex={-1}>
        {children}
      </main>
      <Footer />
    </div>
  );
}
