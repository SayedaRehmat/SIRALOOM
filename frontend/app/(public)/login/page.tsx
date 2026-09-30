"use client";

import { AuthForm } from "../../../components/auth-form";
import { Brand } from "../../../components/brand";

export default function Login() {
  return (
    <main className="auth-page siraloom-auth">
      <div className="auth-brand"><Brand /></div>
      <div className="auth-context">
        <span>01</span>
        <p>Genomic laboratory workspace</p>
      </div>
      <AuthForm mode="login" />
    </main>
  );
}
