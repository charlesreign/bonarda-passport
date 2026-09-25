import { ArrowsClockwise, EnvelopeSimple, Scales, UsersThree } from "@phosphor-icons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Trans, useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api, type DemoAccount, type Role } from "../api";
import { homeFor, useAuth } from "../auth";
import { Avatar, Card, ErrorNote, InfoNote, Loading, SuccessNote } from "../ui";

const ROLE_ORDER: Role[] = ["pm", "people_ops", "worker", "admin", "finance"];

const PILLARS = [
  { icon: ArrowsClockwise, key: "reactivate" },
  { icon: UsersThree, key: "firstShot" },
  { icon: Scales, key: "standing" },
] as const;

function displayName(account: DemoAccount): string {
  return account.name.includes("@") ? account.name.split("@")[0] : account.name;
}

export default function Login() {
  const { t } = useTranslation();
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
          <h1>{t("login.title")}</h1>
          <p className="lead">{t("login.lead")}</p>
        </div>
        <ul className="pillars">
          {PILLARS.map(({ icon: Icon, key }) => (
            <li key={key}>
              <Icon size={24} weight="duotone" aria-hidden="true" />
              <div>
                <strong>{t(`login.pillars.${key}.title`)}</strong>
                <span>{t(`login.pillars.${key}.text`)}</span>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <div className="login-grid">
        <Card
          title={t("login.freelancer.title")}
          subtitle={t("login.freelancer.subtitle")}
          icon={<EnvelopeSimple size={20} aria-hidden="true" />}
        >
          <form onSubmit={submit} className="stack">
            <label className="field" htmlFor="email">
              {t("login.freelancer.email")}
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
              {magicLink.isPending ? t("login.freelancer.sending") : t("login.freelancer.send")}
            </button>
            {magicLink.isSuccess && (
              <SuccessNote>
                <Trans
                  i18nKey="login.freelancer.sent"
                  components={{ mailpit: <a href="http://localhost:8025" target="_blank" rel="noreferrer" /> }}
                />
              </SuccessNote>
            )}
            <ErrorNote error={magicLink.error} />
          </form>
        </Card>

        <Card title={t("login.demo.title")} subtitle={t("login.demo.subtitle")}>
          {accounts.isLoading && <Loading />}
          {accounts.isError && <InfoNote>{t("login.demo.off")}</InfoNote>}
          {accounts.data &&
            ROLE_ORDER.map((role) => {
              const group = accounts.data.filter((a) => a.role === role);
              if (group.length === 0) return null;
              return (
                <div key={role} className="demo-group">
                  <h3>{t(`login.demo.groups.${role}`)}</h3>
                  <div className="account-grid">
                    {group.map((a) => (
                      <button
                        key={a.id}
                        className="account-chip"
                        onClick={() => demoLogin.mutate(a.id)}
                        disabled={demoLogin.isPending}
                        aria-label={t("login.demo.signInAs", { name: displayName(a), role: t(`roles.${role}`) })}
                      >
                        <Avatar name={displayName(a)} />
                        {displayName(a)}
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
