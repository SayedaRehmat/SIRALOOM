"use client";
import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";
export default function RefundPolicy() {
 return <SiteShell><main className="content-page public-content legal">
  <p className="eyebrow">BILLING &amp; CUSTOMER SUPPORT</p><h1>Refund policy</h1><p className="lead">Effective November 10, 2026</p>
  <section><h2>Payments and refunds</h2>
   <p>All purchases made through SIRALOOM checkout are processed by Paddle.com, our online reseller and Merchant of Record. Paddle handles payment support and refund requests under its <a href="https://www.paddle.com/legal/refund-policy" target="_blank" rel="noreferrer">Refund Policy</a> and applicable consumer protection laws.</p>
   <p>Refund eligibility is assessed under Paddle's policy and applicable law. A request does not guarantee approval. Mandatory consumer rights are not restricted by this policy.</p>
  </section>
  <section><h2>Service issues</h2><p>If a material technical issue prevents access to a purchased service, contact SIRALOOM at <a href="mailto:siralooms@gmail.com">siralooms@gmail.com</a> so we can investigate. If the issue remains unresolved, submit a refund request to Paddle.</p></section>
  <section><h2>Subscriptions and cancellation</h2><p>Where subscriptions are offered, cancel through the subscription-management link in your Paddle receipt or at <a href="https://paddle.net" target="_blank" rel="noreferrer">Paddle Buyer Support</a>. Cancellation stops future renewals and normally takes effect at the end of the current paid period. Cancellation alone does not refund a payment already made.</p></section>
  <section><h2>How to request a refund</h2><p>Visit <a href="https://paddle.net" target="_blank" rel="noreferrer">paddle.net</a> and locate your transaction. Include your order reference and the email used at checkout. Do not send payment-card details by email.</p></section>
  <p className="quiet">Mandatory consumer rights in your country always take precedence over inconsistent terms in this policy. See also our <Link href="/terms">Terms of Service</Link> and <Link href="/privacy">Privacy Policy</Link>.</p>
 </main></SiteShell>;
}