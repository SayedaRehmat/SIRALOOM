import Link from "next/link";

export function Brand({ compact = false }: { compact?: boolean }) {
  return <Link href="/" className="brand" aria-label="SIRALOOM home">
    <span>SIRALOOM</span>
  </Link>;
}
