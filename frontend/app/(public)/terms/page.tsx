"use client";
import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";

export default function Terms() {
  return (
    <SiteShell>
      <main className="content-page public-content legal">
        <p className="eyebrow">LEGAL</p>
        <h1>Terms of Service</h1>
        <p className="lead">Effective November 11, 2026</p>
        <section>
          <h2>Using SIRALOOM</h2>
          <p>
            SIRALOOM provides software for genomic laboratory workflows,
            variant interpretation, evidence review, case management and
            reporting, as included in your plan or deployment agreement. By
            accessing the service, you agree to these terms and applicable law.
          </p>
        </section>
        <section>
          <h2>Accounts and laboratory responsibilities</h2>
          <p>
            You must provide accurate account information, protect your
            credentials and use the service only with proper authorisation.
            Organisations are responsible for their users, access permissions,
            lawful collection and submission of data, and the security of their
            own devices and infrastructure.
          </p>
          <p>
            The laboratory and its qualified professionals remain responsible
            for checking results, applying appropriate validation and quality
            procedures, making clinical decisions, and approving or issuing
            reports. SIRALOOM is decision-support software; it does not replace
            professional judgement or applicable clinical, laboratory or
            regulatory requirements.
          </p>
        </section>
        <section>
          <h2>Subscriptions and payments</h2>
          <p>
            Plan features, fees and billing periods are shown at checkout or in
            your written agreement. Paddle is the Merchant of Record for
            purchases made through SIRALOOM checkout and handles payment
            processing. Refunds and cancellation are explained in our{" "}
            <Link href="/refund-policy">Refund Policy</Link>.
          </p>
        </section>
        <section>
          <h2>Acceptable use and service changes</h2>
          <p>
            You must not misuse the service, attempt unauthorised access,
            interfere with its operation, or use it unlawfully. Features,
            integrations and availability may change as the product develops.
            Any deployment-specific commitments are governed by the applicable
            written agreement.
          </p>
        </section>
        <section>
          <h2>Contact</h2>
          <p>
            For questions about these terms or SIRALOOM support, email{" "}
            <a href="mailto:siralooms@gmail.com">siralooms@gmail.com</a> or call{" "}
            <a href="tel:+923211906738">+92 321 1906738</a>.
          </p>
        </section>
        <p className="quiet">
          See our <Link href="/privacy">Privacy Policy</Link> for information
          about data handling and our <Link href="/refund-policy">Refund Policy</Link>
          for refund requests.
        </p>
      </main>
    </SiteShell>
  );
}
