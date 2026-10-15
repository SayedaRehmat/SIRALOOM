export function sessionDestination(options: {
  ok: boolean;
  status: number;
  sessionState?: string | null;
  fallbackWhenUnprovisioned?: string;
  redirectWhenProvisioned?: string | null;
}): string;
