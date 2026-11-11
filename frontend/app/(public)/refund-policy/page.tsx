"use client";
import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";

export default function RefundPolicy() {
  return (
    <SiteShell>
      <main className="content-page public-content legal">
        <p className="eyebrow">BILLING &amp; CUSTOMER SUPPORT</p>
        <h1>Refund policy</h1>
        <p className="lead">Effective November 11, 2026</p>

        <section>
          <h2>14-day refund period</h2>
          <p>
            You may request a refund for a SIRALOOM software subscription within
            14 calendar days of the payment date. This policy covers access to
            SIRALOOM's genomic workflow, variant interpretation, case management,
            evidence review and reporting software, according to your selected plan.
          </p>
        </section>

        <section>
          <h2>How to request a refund</h2>
          <p>
            SIRALOOM payments are processed by Paddle, our Merchant of Record.
            To request a refund, visit <a href="https://paddle.net" target="_blank" rel="noreferrer">Paddle Buyer Support</a>,
            find your transaction and submit your request within the 14-day period.
            Include your order reference and checkout email. Paddle handles payment
            and refund processing under its <a href="https://www.paddle.com/legal/refund-policy" target="_blank" rel="noreferrer">refund policy</a>.
          </p>
        </section>

        <section>
          <h2>Subscription cancellation</h2>
          <p>
            You can cancel a subscription using the subscription-management link
            in your Paddle receipt. Cancellation stops future renewals; it does
            not automatically refund a previous payment. Submit a separate refund
            request within the 14-day period if you want a payment reviewed.
          </p>
        </section>

        <section>
          <h2>Technical support and contact</h2>
          <p>
            If a technical issue prevents you from accessing the service, contact
            SIRALOOM at <a href="mailto:siralooms@gmail.com">siralooms@gmail.com</a> or
            <a href="tel:+923211906738"> +92 321 1906738</a>.
          </p>
        </section>

        <p className="quiet">
          This policy does not limit any mandatory consumer rights that apply
          in your country. See our <Link href="/terms">Terms of Service</Link> and{" "}
          <Link href="/privacy">Privacy Policy</Link>.
        </p>
      </main>
    </SiteShell>
  );
}
