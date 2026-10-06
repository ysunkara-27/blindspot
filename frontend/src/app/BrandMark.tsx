// The Blindspot mark: a cyan ring (the expert outline) on the PACS surround with an amber grease-pencil dot (you).
export function BrandMark({ size = 40, className }: { size?: number; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <rect width="64" height="64" rx="12" fill="#1C1F22" />
      <circle cx="32" cy="32" r="17" fill="none" stroke="#35C9DD" strokeWidth="5" />
      <circle cx="44.5" cy="44.5" r="4.5" fill="#F0A92E" />
    </svg>
  );
}
