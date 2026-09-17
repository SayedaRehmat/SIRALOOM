import Link from "next/link";
import { AuthForm } from "../../../components/auth-form";
import { Brand } from "../../../components/brand";

export default async function Signup({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const isOrganizationSignup = params?.mode === "organization";

  return (
    <main className="auth-page">
      <Brand />
      <AuthForm mode="signup" trial={!isOrganizationSignup} />
      <p className="text-muted">
        {isOrganizationSignup ? (
          <Link href="/signup">Start a free trial instead →</Link>
        ) : (
          <Link href="/signup?mode=organization">
            Setting up a production laboratory account instead? →
          </Link>
        )}
      </p>
    </main>
  );
}
