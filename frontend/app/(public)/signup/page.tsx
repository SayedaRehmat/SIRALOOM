"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AuthForm } from "../../../components/auth-form";
import { Brand } from "../../../components/brand";
import { useLanguage } from "../../../lib/i18n";

export default function Signup() {
  const { t } = useLanguage();
  const [isOrganizationSignup, setIsOrganizationSignup] = useState(false);

  useEffect(() => {
    setIsOrganizationSignup(new URLSearchParams(window.location.search).get("mode") === "organization");
  }, []);

  return (
    <main className="auth-page">
      <Brand />
      <AuthForm mode="signup" trial={!isOrganizationSignup} />
      <p className="text-muted">
        {isOrganizationSignup
          ? <Link href="/signup">{t("auth.startFreeTrial")} →</Link>
          : <Link href="/signup?mode=organization">{t("auth.orgSwitch")} →</Link>}
      </p>
    </main>
  );
}
