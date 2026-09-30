"use client";

import { AuthForm } from "../../../components/auth-form";
import { Brand } from "../../../components/brand";
import { useLanguage } from "../../../lib/i18n";

export default function Login() {
  const { t } = useLanguage();
  return (
    <main className="auth-page siraloom-auth">
      <div className="auth-brand"><Brand /></div>
      <div className="auth-context">
        <span>01</span>
        <p>{t("auth.workspaceContext")}</p>
      </div>
      <AuthForm mode="login" />
    </main>
  );
}
