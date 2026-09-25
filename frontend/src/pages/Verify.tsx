import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { homeFor, useAuth } from "../auth";
import { Card, ErrorNote, Loading } from "../ui";

/** Magic-link landing page: the token arrives in the URL fragment. */
export default function Verify() {
  const { t } = useTranslation();
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<unknown>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // tokens are single-use; StrictMode runs effects twice
    started.current = true;
    const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (!token) {
      setError(new Error(t("verify.incomplete")));
      return;
    }
    api<{ access_token: string }>("/auth/magic-link/verify", { method: "POST", body: { token } })
      .then((tokens) => signIn(tokens.access_token))
      .then((me) => navigate(homeFor(me), { replace: true }))
      .catch((e) => setError(e));
  }, [navigate, signIn, t]);

  return (
    <div style={{ maxWidth: 480, margin: "48px auto" }}>
      <Card title={error ? t("verify.failed") : t("verify.signingIn")}>
        {error ? (
          <div className="stack">
            <ErrorNote error={error} />
            <Link to="/login">{t("verify.back")}</Link>
          </div>
        ) : (
          <Loading lines={2} />
        )}
      </Card>
    </div>
  );
}
