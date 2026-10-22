import type { AnchorHTMLAttributes, ReactNode } from 'react';
import { hrefFor } from '../router';

interface LinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> {
  to: string;
  children: ReactNode;
}

export function Link({ to, children, ...rest }: LinkProps) {
  return (
    <a href={hrefFor(to)} {...rest}>
      {children}
    </a>
  );
}
