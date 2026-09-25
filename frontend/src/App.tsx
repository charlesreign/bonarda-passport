import { Briefcase, IdentificationCard, Scales, SignOut } from "@phosphor-icons/react";
import { lazy, Suspense, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, type Role } from "./api";
import { homeFor, useAuth } from "./auth";
import { LANGUAGES, setLanguage, type Language } from "./i18n";
import Login from "./pages/Login";
import Verify from "./pages/Verify";
import { Loading } from "./ui";

// Spec §7.8: route-level bundles, so the freelancer's passport never loads the
// console or governance code (and stays inside its 150 KB budget).
const Passport = lazy(() => import("./pages/Passport"));
const Console = lazy(() => import("./pages/Console"));
const ProjectPage = lazy(() => import("./pages/ProjectPage"));
const Ops = lazy(() => import("./pages/Ops"));

function Guard({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { me, loading } = useAuth();
  if (loading) return <Loading />;
  if (!me) return <Navigate to="/login" replace />;
  if (!roles.includes(me.role)) return <Navigate to={homeFor(me)} replace />;
  return <Suspense fallback={<Loading lines={4} />}>{children}</Suspense>;
}

function LanguageSwitch() {
  const { t, i18n } = useTranslation();
  const { me } = useAuth();
  function choose(language: Language) {
    setLanguage(language);
    // Signed-in users keep the choice on their account (emails use it too).
    if (me && me.locale !== language) void api("/me", { method: "PATCH", body: { locale: language } });
  }
  return (
    <div className="lang-switch" role="group" aria-label={t("nav.language")}>
      {LANGUAGES.map((language) => (
        <button
          key={language}
          className="lang"
          aria-pressed={i18n.language === language}
          onClick={() => choose(language)}
          lang={language}
        >
          {language.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

function Header() {
  const { t } = useTranslation();
  const { me, signOut } = useAuth();
  return (
    <header className="topbar">
      <Link to="/" className="brand" aria-label={t("nav.home")}>
        <span className="brand-mark" aria-hidden="true">
          B
        </span>
        <span>
          Bonarda Works
          <small>{t("nav.product")}</small>
        </span>
      </Link>
      {me && (
        <nav className="topnav" aria-label={t("nav.main")}>
          {me.role === "worker" && (
            <NavLink to="/passport">
              <IdentificationCard size={20} aria-hidden="true" />
              <span className="label">{t("nav.passport")}</span>
            </NavLink>
          )}
          {me.role === "pm" && (
            <NavLink to="/console">
              <Briefcase size={20} aria-hidden="true" />
              <span className="label">{t("nav.staffing")}</span>
            </NavLink>
          )}
          {(me.role === "people_ops" || me.role === "admin") && (
            <NavLink to="/ops">
              <Scales size={20} aria-hidden="true" />
              <span className="label">{t("nav.governance")}</span>
            </NavLink>
          )}
        </nav>
      )}
      <div className="who">
        <LanguageSwitch />
        {me && (
          <>
            <div className="who-id">
              <strong>{me.email}</strong>
              <span>{t(`roles.${me.role}`)}</span>
            </div>
            <button className="secondary icon-btn" onClick={() => void signOut()} aria-label={t("nav.signOut")}>
              <SignOut size={20} aria-hidden="true" />
            </button>
          </>
        )}
      </div>
    </header>
  );
}

function Home() {
  const { me, loading } = useAuth();
  if (loading) return <Loading />;
  return <Navigate to={me ? homeFor(me) : "/login"} replace />;
}

export default function App() {
  const { t, i18n } = useTranslation();
  return (
    <>
      <a href="#main" className="skip-link">
        {t("nav.skip")}
      </a>
      <Header />
      {/* Re-mount on language change so every formatted date and label follows. */}
      <main id="main" tabIndex={-1} key={i18n.language}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/auth/verify" element={<Verify />} />
          <Route
            path="/passport"
            element={
              <Guard roles={["worker"]}>
                <Passport />
              </Guard>
            }
          />
          <Route
            path="/console"
            element={
              <Guard roles={["pm"]}>
                <Console />
              </Guard>
            }
          />
          <Route
            path="/console/projects/:projectId"
            element={
              <Guard roles={["pm"]}>
                <ProjectPage />
              </Guard>
            }
          />
          <Route
            path="/ops"
            element={
              <Guard roles={["people_ops", "admin"]}>
                <Ops />
              </Guard>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </>
  );
}
