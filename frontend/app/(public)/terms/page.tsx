"use client";

import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";

export default function Terms() {
  return (
    <SiteShell>
      <main className="content-page public-content legal">
        <p className="eyebrow">TERMS</p>
        <h1>Terms of Service</h1>
        <p className="lead">Effective November 10, 2026</p>

        <section>
          <h2>Use of SIRALOOM</h2>
          <p>SIRALOOM provides software for genomic laboratory workflows, evidence review and decision support. You must use the platform lawfully and only for purposes for which you are authorised.</p>
          <p>SIRALOOM is not a substitute for laboratory validation, qualified professional interpretation, clinical judgement or applicable regulatory requirements. Laboratories remain responsible for reviewing outputs and authorising clinical reports.</p>
        </section>

        <section>
          <h2>Accounts and organisational responsibility</h2>
          <p>You are responsible for maintaining the confidentiality of your account credentials and for ensuring that users in your organisation have appropriate access. Your organisation is responsible for the lawful submission and governance of data it uploads.</p>
        </section>

        <section>
          <h2>Payments and refunds</h2>
          <p>Our order process is conducted by our online reseller Paddle.com. Paddle.com is the Merchant of Record for all our orders. Paddle provides all customer service inquiries and handles returns.</p>
          <p>Purchases, refund eligibility and subscription cancellation are subject to Paddle's <a href="https://www.paddle.com/legal/refund-policy" target="_blank" rel="noreferrer">Refund Policy</a> and applicable law. See our <Link href="/refund-policy">Refund Policy</Link> for details.</p>
        </section>

        <section>
          <h2>Service changes</h2>
          <p>Features, availability and supported integrations may change as the platform develops. We may update these terms when necessary and will publish the current version on this page.</p>
        </section>

        <p className="quiet">For information about personal data and payment processing, see our <Link href="/privacy">Privacy Policy</Link>.</p>
      </main>
    </SiteShell>
  );
}
