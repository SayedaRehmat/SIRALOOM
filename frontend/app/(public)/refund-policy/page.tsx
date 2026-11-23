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
          <h2>When a refund may be considered</h2>
          <p>
            You may submit a refund request within 14 calendar days of a
            transaction for review. This is a request period, not an automatic
            money-back guarantee. Refunds are assessed case by case and are
            subject to Paddle's refund policy and applicable law. Paddle may
            approve a full or partial refund or decline a discretionary request.
          </p>
          <p>Relevant circumstances may include:</p>
          <ul>
            <li>A duplicate payment or an incorrect charge.</li>
            <li>
              A material technical defect or service-access failure that
              prevents you from using the subscription as described and that
              cannot be resolved after you report it to SIRALOOM and allow a
              reasonable opportunity for support.
            </li>
            <li>
              An accidental or mistaken transaction, or another exceptional
              circumstance supported by relevant details.
            </li>
          </ul>
          <p>
            In reviewing a request, Paddle may consider the reason for the
            request, the nature of the subscription, the extent of service use
            or consumption, transaction details and any applicable contractual
            or legal requirements.
          </p>
        </section>

        <section>
          <h2>When a discretionary refund is not normally available</h2>
          <p>
            To the extent permitted by law, a refund is not normally granted
            solely because you change your mind, do not use the subscription,
            no longer need the service, or did not cancel before a renewal
            charge. Extensive use of the service may also be taken into account
            when a discretionary refund is reviewed. These conditions do not
            restrict refunds or remedies required by applicable law, including
            rights relating to a service that is faulty or not provided as
            described.
          </p>
        </section>

        <section>
          <h2>How to request a refund</h2>
          <p>
            SIRALOOM payments are processed by Paddle, our Merchant of Record.
            Submit your request through{" "}
            <a href="https://paddle.net" target="_blank" rel="noreferrer">
              Paddle Buyer Support
            </a>{" "}
            or the support link in your Paddle receipt. Include your order
            reference, checkout email and a brief explanation of the issue.
            For a technical or access problem, contact SIRALOOM first at{" "}
            <a href="mailto:siralooms@gmail.com">siralooms@gmail.com</a> so we
            can investigate and try to resolve it. Paddle handles payment and
            refund decisions under its{" "}
            <a
              href="https://www.paddle.com/legal/refund-policy"
              target="_blank"
              rel="noreferrer"
            >
              refund policy
            </a>
            .
          </p>
        </section>

        <section>
          <h2>Subscription cancellation</h2>
          <p>
            You can cancel a subscription using the subscription-management
            link in your Paddle receipt. Cancellation prevents future renewals
            and normally takes effect at the end of the current billing period.
            It does not automatically refund a previous payment. If you want a
            payment reviewed, submit a separate refund request to Paddle.
          </p>
        </section>

        <section>
          <h2>Technical support and contact</h2>
          <p>
            If a technical issue prevents you from accessing the service,
            contact SIRALOOM at{" "}
            <a href="mailto:siralooms@gmail.com">siralooms@gmail.com</a> or
            <a href="tel:+923211906738"> +92 321 1906738</a>.
          </p>
        </section>

        <p className="quiet">
          This policy does not limit any mandatory consumer rights that apply
          in your country. Paddle's policy and applicable law may provide
          additional rights or remedies. See our{" "}
          <Link href="/terms">Terms of Service</Link> and{" "}
          <Link href="/privacy">Privacy Policy</Link>.
        </p>
      </main>
    </SiteShell>
  );
}
