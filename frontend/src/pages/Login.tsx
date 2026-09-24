import { ArrowsClockwise, EnvelopeSimple, Scales, UsersThree } from "@phosphor-icons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Role } from "../api";
import { homeFor, useAuth } from "../auth";
import { Avatar, Card, ErrorNote, InfoNote, Loading, SuccessNote } from "../ui";

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

const PILLARS = [
  {
    icon: ArrowsClockwise,
    title: "Reactivate in minutes",
    text: "Terms prefill from the last engagement. One confirmation sends the contract.",
  },
  {
    icon: UsersThree,
    title: "A fair first shot",
    text: "Every staffing page shows qualified people who have had little recent work.",
  },
  {
    icon: Scales,
    title: "Standing you can explain",
    text: "Tiers come from versioned rules. Freelancers see why, and can dispute any record.",
  },
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
      <section className="hero">
        <div>
          <p className="eyebrow">Bonarda Works</p>
          <h1>One passport for every engagement.</h1>
          <p className="lead">
            Freelancers keep one record across projects. Project managers bring back people they
            trust, and meet qualified people they have not worked with yet.
          </p>
        </div>
        <ul className="pillars">
          {PILLARS.map(({ icon: Icon, title, text }) => (
            <li key={title}>
              <Icon size={24} weight="duotone" aria-hidden="true" />
              <div>
                <strong>{title}</strong>
                <span>{text}</span>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <div className="login-grid">
        <Card
          title="Freelancer sign-in"
          subtitle="No password: we email you a single-use link."
          icon={<EnvelopeSimple size={20} aria-hidden="true" />}
        >
          <form onSubmit={submit} className="stack">
            <label className="field" htmlFor="email">
              Email address
              <input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="kofi@example.com"
              />
            </label>
            <button disabled={magicLink.isPending}>
              {magicLink.isPending ? "Sending…" : "Email me a sign-in link"}
            </button>
            {magicLink.isSuccess && (
              <SuccessNote>
                If that address has a passport, a link is on its way. In the demo, open{" "}
                <a href="http://localhost:8025" target="_blank" rel="noreferrer">
                  Mailpit
                </a>
                .
              </SuccessNote>
            )}
            <ErrorNote error={magicLink.error} />
          </form>
        </Card>

        <Card title="Demo accounts" subtitle="Sign in as anyone in the seeded dataset.">
          {accounts.isLoading && <Loading />}
          {accounts.isError && (
            <InfoNote>Demo sign-in is off. Staff sign in through the company identity provider.</InfoNote>
          )}
          {accounts.data &&
            ROLE_ORDER.map(([role, label]) => {
              const group = accounts.data.filter((a) => a.role === role);
              if (group.length === 0) return null;
              return (
                <div key={role} className="demo-group">
                  <h3>{label}</h3>
                  <div className="account-grid">
                    {group.map((a) => (
                      <button
                        key={a.id}
                        className="account-chip"
                        onClick={() => demoLogin.mutate(a.id)}
                        disabled={demoLogin.isPending}
                        aria-label={`Sign in as ${a.name} (${label})`}
                      >
                        <Avatar name={a.name.includes("@") ? a.name.split("@")[0] : a.name} />
                        {a.name.includes("@") ? a.name.split("@")[0] : a.name}
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
