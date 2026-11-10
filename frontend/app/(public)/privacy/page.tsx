"use client";
import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";
export default function Privacy() {
 return <SiteShell><main className="content-page public-content legal">
  <p className="eyebrow">PRIVACY</p><h1>Privacy Policy</h1><p className="lead">Effective November 10, 2026</p>
  <section><h2>Data and access</h2><p>SIRALOOM is designed for controlled, organisation-scoped access to genomic workflow records and auditable activity. Organisations using the platform are responsible for ensuring that data submitted to SIRALOOM is collected and shared lawfully, and for configuring user access and retention for their intended use.</p></section>
  <section><h2>Payment information</h2><p>Payments made through SIRALOOM checkout are processed by Paddle.com as Merchant of Record. Payment details are submitted to Paddle and handled under its own privacy policy and buyer terms. SIRALOOM does not ask customers to send full payment-card details by email.</p></section>
  <section><h2>Questions</h2><p>For payment-related privacy questions, contact <a href="https://paddle.net" target="_blank" rel="noreferrer">Paddle Buyer Support</a>. For SIRALOOM privacy and platform questions, email <a href="mailto:siralooms@gmail.com">siralooms@gmail.com</a>.</p></section>
  <p className="quiet">This page describes the current privacy principles and payment arrangement. Organisations must assess their own legal and regulatory obligations before uploading personal or genomic data.</p>
  <p className="quiet">See also our <Link href="/terms">Terms of Service</Link> and <Link href="/refund-policy">Refund Policy</Link>.</p>
 </main></SiteShell>;
}