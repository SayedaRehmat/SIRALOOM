import Link from "next/link";

export function Brand({ compact = false }: { compact?: boolean }) {
  return <Link href="/" className="brand" aria-label="SIRALOOM home">
    <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
    {!compact && <span>SIRALOOM</span>}
  </Link>;
}
