import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorText } from "../api";
import { homeFor, useAuth } from "../auth";

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
    <div className="pad">
      {error ? (
        <p className="error">
          {error} <a href="/login">Back to sign-in</a>
        </p>
      ) : (
        <p className="muted">Signing you in…</p>
      )}
    </div>
  );
}
