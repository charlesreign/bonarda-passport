import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Role } from "../api";
import { homeFor, useAuth } from "../auth";
import { Card, ErrorNote } from "../ui";

interface DemoAccount {
  id: string;
  email: string;
  role: Role;
  name: string;
}

const ROLE_ORDER: [Role, string][] = [
  ["pm", "Project managers"],
  ["people_ops", "People Ops"],
  ["worker", "Freelancers"],
  ["admin", "Admin"],
  ["finance", "Finance"],
];

export default function Login() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");

  const accounts = useQuery({
    queryKey: ["demo-accounts"],
    queryFn: () => api<DemoAccount[]>("/demo/accounts"),
    retry: false,
  });

  const demoLogin = useMutation({
    mutationFn: async (userId: string) => {
      const token = await api<{ access_token: string }>("/demo/login", {
        method: "POST",
        body: { user_id: userId },
      });
      return signIn(token.access_token);
    },
    onSuccess: (me) => navigate(homeFor(me)),
  });

  const magicLink = useMutation({
    mutationFn: () => api("/auth/magic-link", { method: "POST", body: { email } }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    magicLink.mutate();
  }

  return (
    <div className="login">
      <div className="hero">
        <h1>One passport for every engagement.</h1>
        <p>
          Freelancers keep one record across projects. Project managers reactivate people they
          trust in minutes, and meet qualified people they have not worked with yet.
        </p>
      </div>
      <div className="login-grid">
        <Card title="Freelancer sign-in">
          <form onSubmit={submit} className="stack">
            <label>
              Email
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="kofi@example.com"
              />
            </label>
            <button disabled={magicLink.isPending}>Email me a sign-in link</button>
            {magicLink.isSuccess && (
              <p className="ok">
                If that address has a passport, a link is on its way. In the demo, open{" "}
                <a href="http://localhost:8025" target="_blank" rel="noreferrer">
                  Mailpit
                </a>
                .
              </p>
            )}
            <ErrorNote error={magicLink.error} />
          </form>
        </Card>
        <Card title="Demo accounts">
          {accounts.isError && (
            <p className="muted">Demo sign-in is off. Staff sign in through the company IdP.</p>
          )}
          {accounts.data &&
            ROLE_ORDER.map(([role, label]) => {
              const group = accounts.data.filter((a) => a.role === role);
              if (group.length === 0) return null;
              return (
                <div key={role} className="demo-group">
                  <h3>{label}</h3>
                  <div className="chips">
                    {group.map((a) => (
                      <button
                        key={a.id}
                        className="chip"
                        onClick={() => demoLogin.mutate(a.id)}
                        title={a.email}
                      >
                        {a.name}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          <ErrorNote error={demoLogin.error} />
        </Card>
      </div>
    </div>
  );
}
