"use client";
import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";

export default function Privacy() {
  return (
    <SiteShell>
      <main className="content-page public-content legal">
        <p className="eyebrow">LEGAL</p>
        <h1>Privacy Policy</h1>
        <p className="lead">Effective November 11, 2026</p>
        <section>
          <h2>Information handled by SIRALOOM</h2>
          <p>
            Depending on your use and deployment, SIRALOOM may process account
            and organisation details, user and access records, support
            communications, and technical activity logs. The platform may also
            process files and records submitted by a laboratory, including VCF
            files, genomic and clinical information, case records, evidence
            assessments and reports. Such information may include sensitive
            personal or health data.
          </p>
        </section>
        <section>
          <h2>How information is used</h2>
          <p>
            Information is used to provide and operate the software, manage
            accounts and permissions, support laboratory workflows, maintain
            security and auditability, respond to support requests, and meet
            applicable legal obligations.
          </p>
        </section>
        <section>
          <h2>Laboratory and customer responsibilities</h2>
          <p>
            The organisation using SIRALOOM is responsible for having the
            necessary legal basis and permissions to submit personal, genomic
            or clinical data, and for deciding who may access it. Users should
            not upload information they are not authorised to share.
          </p>
          <p>
            In a customer-managed deployment, the organisation is responsible
            for its own hosting environment, infrastructure access, backups
            and operational controls. Data handling in hosted deployments
            depends on the service arrangement and applicable agreements.
          </p>
        </section>
        <section>
          <h2>Service providers and payments</h2>
          <p>
            SIRALOOM may use service providers needed to operate and support
            the service, subject to the applicable arrangements. Payments made
            through SIRALOOM checkout are processed by Paddle as Merchant of
            Record. Paddle handles payment information under its own{" "}
            <a href="https://www.paddle.com/legal/privacy" target="_blank" rel="noreferrer">
              Privacy Policy
            </a>.
            Do not send full payment-card details to SIRALOOM by email.
          </p>
        </section>
        <section>
          <h2>Retention and privacy enquiries</h2>
          <p>
            Retention and deletion depend on the deployment, customer
            configuration, applicable agreement and legal requirements.
            Organisations should contact their SIRALOOM administrator about
            access to or removal of laboratory records. For privacy questions,
            contact <a href="mailto:siralooms@gmail.com">siralooms@gmail.com</a>.
          </p>
        </section>
        <p className="quiet">
          See our <Link href="/terms">Terms of Service</Link> and{" "}
          <Link href="/refund-policy">Refund Policy</Link>.
        </p>
      </main>
    </SiteShell>
  );
}
