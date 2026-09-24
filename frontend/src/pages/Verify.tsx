import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorText } from "../api";
import { homeFor, useAuth } from "../auth";
import { Card, ErrorNote, Loading } from "../ui";

/** Magic-link landing page: the token arrives in the URL fragment. */
export default function Verify() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // tokens are single-use; StrictMode runs effects twice
    started.current = true;
    const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (!token) {
      setError("This link is incomplete. Request a new one.");
      return;
    }
    api<{ access_token: string }>("/auth/magic-link/verify", { method: "POST", body: { token } })
      .then((t) => signIn(t.access_token))
      .then((me) => navigate(homeFor(me), { replace: true }))
      .catch((e) => setError(errorText(e)));
  }, [navigate, signIn]);

  return (
    <div style={{ maxWidth: 480, margin: "48px auto" }}>
      <Card title={error ? "We couldn't sign you in" : "Signing you in…"}>
        {error ? (
          <div className="stack">
            <ErrorNote error={error} />
            <Link to="/login">Back to sign-in</Link>
          </div>
        ) : (
          <Loading lines={2} />
        )}
      </Card>
    </div>
  );
}
