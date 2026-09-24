import { Briefcase, IdentificationCard, Scales, SignOut } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { Link, NavLink, Navigate, Route, Routes } from "react-router-dom";
import type { Role } from "./api";
import { homeFor, useAuth } from "./auth";
import Console from "./pages/Console";
import Login from "./pages/Login";
import Ops from "./pages/Ops";
import Passport from "./pages/Passport";
import ProjectPage from "./pages/ProjectPage";
import Verify from "./pages/Verify";
import { Loading } from "./ui";

const ROLE_LABEL: Record<Role, string> = {
  pm: "Project manager",
  people_ops: "People Ops",
  finance: "Finance",
  worker: "Freelancer",
  admin: "Admin",
};

function Guard({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { me, loading } = useAuth();
  if (loading) return <Loading />;
  if (!me) return <Navigate to="/login" replace />;
  if (!roles.includes(me.role)) return <Navigate to={homeFor(me)} replace />;
  return <>{children}</>;
}

function Header() {
  const { me, signOut } = useAuth();
  return (
    <header className="topbar">
      <Link to="/" className="brand" aria-label="Bonarda Works home">
        <span className="brand-mark" aria-hidden="true">
          B
        </span>
        <span>
          Bonarda Works
          <small>Freelancer Passport</small>
        </span>
      </Link>
      {me && (
        <nav className="topnav" aria-label="Main">
          {me.role === "worker" && (
            <NavLink to="/passport">
              <IdentificationCard size={20} aria-hidden="true" />
              <span className="label">My passport</span>
            </NavLink>
          )}
          {me.role === "pm" && (
            <NavLink to="/console">
              <Briefcase size={20} aria-hidden="true" />
              <span className="label">Staffing</span>
            </NavLink>
          )}
          {(me.role === "people_ops" || me.role === "admin") && (
            <NavLink to="/ops">
              <Scales size={20} aria-hidden="true" />
              <span className="label">Governance</span>
            </NavLink>
          )}
        </nav>
      )}
      {me && (
        <div className="who">
          <div className="who-id">
            <strong>{me.email}</strong>
            <span>{ROLE_LABEL[me.role]}</span>
          </div>
          <button className="secondary icon-btn" onClick={() => void signOut()} aria-label="Sign out">
            <SignOut size={20} aria-hidden="true" />
          </button>
        </div>
      )}
    </header>
  );
}

function Home() {
  const { me, loading } = useAuth();
  if (loading) return <Loading />;
  return <Navigate to={me ? homeFor(me) : "/login"} replace />;
}

export default function App() {
  return (
    <>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <Header />
      <main id="main" tabIndex={-1}>
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
