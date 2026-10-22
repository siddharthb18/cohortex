import type { SVGProps } from 'react';

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function base({ size = 16, ...rest }: IconProps) {
  return {
    width: size,
    height: size,
    viewBox: '0 0 16 16',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.6,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
    focusable: false,
    ...rest,
  };
}

/** Cohort mark: three drive platters of different wear, read as a ranked cohort. */
export function LogoMark({ size = 22, ...rest }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden focusable={false} {...rest}>
      <rect x="3" y="4" width="18" height="3.2" rx="1.6" fill="currentColor" />
      <rect x="3" y="10.4" width="13" height="3.2" rx="1.6" fill="currentColor" opacity="0.7" />
      <rect x="3" y="16.8" width="8" height="3.2" rx="1.6" fill="currentColor" opacity="0.45" />
    </svg>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M3.5 8.5l3 3 6-7" />
    </svg>
  );
}

export function XIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  );
}

export function AlertIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M8 2.5l6 10.5H2L8 2.5z" />
      <path d="M8 6.8v2.6M8 11.2v.1" />
    </svg>
  );
}

export function InfoIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="8" cy="8" r="6" />
      <path d="M8 7.2v3.6M8 5.2v.1" />
    </svg>
  );
}

export function SunIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="8" cy="8" r="3" />
      <path d="M8 1.5v1.3M8 13.2v1.3M1.5 8h1.3M13.2 8h1.3M3.4 3.4l.9.9M11.7 11.7l.9.9M3.4 12.6l.9-.9M11.7 4.3l.9-.9" />
    </svg>
  );
}

export function MoonIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M13.5 9.6A5.8 5.8 0 016.4 2.5a5.8 5.8 0 107.1 7.1z" />
    </svg>
  );
}

export function SortIcon({ dir, ...props }: IconProps & { dir: 'asc' | 'desc' | null }) {
  return (
    <svg {...base({ size: 12, ...props })} className="sort-icon">
      {dir === null ? (
        <path d="M5 6l3-3 3 3M5 10l3 3 3-3" />
      ) : dir === 'asc' ? (
        <path d="M4.5 10l3.5-4 3.5 4" />
      ) : (
        <path d="M4.5 6l3.5 4 3.5-4" />
      )}
    </svg>
  );
}

export function ArrowRightIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M3 8h10M9 4l4 4-4 4" />
    </svg>
  );
}

export function DocIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 1.8h5.2L12.5 5v9.2H4z" />
      <path d="M9 1.8V5h3.5M6 8.5h4M6 11h4" />
    </svg>
  );
}

export function DownloadIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M8 2.5v8M4.5 7.5L8 11l3.5-3.5M3 13.5h10" />
    </svg>
  );
}

export function ToolIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M9.6 2.6a3 3 0 00-3.9 3.9L2.5 9.7a1.4 1.4 0 002 2l3.2-3.2a3 3 0 003.9-3.9L9.8 6.4 8.4 6l-.4-1.4 1.6-2z" />
    </svg>
  );
}
