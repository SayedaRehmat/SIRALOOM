import Link from "next/link";
import { ReactNode } from "react";
import { Brand } from "./brand";

export function SiteShell({ children }: { children: ReactNode }) {
  return <><header className="site-header"><Brand /><nav aria-label="Primary navigation"><Link href="/about">About</Link><Link href="/services">Services</Link><Link href="/contact">Contact</Link></nav><div className="header-actions"><Link className="text-link" href="/login">Sign in</Link><Link className="button small" href="/signup">Create account</Link></div></header>{children}<footer className="site-footer"><Brand /><p>Genomic intelligence infrastructure for evidence-aware laboratory workflows.</p><div><Link href="/privacy">Privacy</Link><Link href="/terms">Terms</Link></div></footer></>;
}
