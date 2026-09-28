/** Samruddhi mark: a sun rising over the horizon line. */
export function LogoMark({ size = 36, className = "" }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" className={className} aria-hidden="true">
      <rect width="36" height="36" rx="11" fill="#121212" />
      <path d="M8.5 23.5 A9.5 9.5 0 0 1 27.5 23.5 Z" fill="#ffc62b" />
      <rect x="7" y="25.5" width="22" height="2.6" rx="1.3" fill="#ffc62b" />
    </svg>
  );
}

export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`font-display text-[17px] font-semibold tracking-[-0.03em] text-ink ${className}`}>
      Samruddhi<span className="ml-1 rounded-md bg-accent px-1.5 py-0.5 align-middle text-[11px] font-bold tracking-normal text-accent-ink">AI</span>
    </span>
  );
}
