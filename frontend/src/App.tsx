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

function Guard({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { me, loading } = useAuth();
  if (loading) return <p className="muted pad">Loading…</p>;
  if (!me) return <Navigate to="/login" replace />;
  if (!roles.includes(me.role)) return <Navigate to={homeFor(me)} replace />;
  return <>{children}</>;
}

function Header() {
  const { me, signOut } = useAuth();
  return (
    <header className="topbar">
      <Link to="/" className="brand">
        Bonarda <span>Works</span>
      </Link>
      {me && (
        <nav>
          {me.role === "worker" && <NavLink to="/passport">My passport</NavLink>}
          {me.role === "pm" && <NavLink to="/console">Staffing</NavLink>}
          {(me.role === "people_ops" || me.role === "admin") && <NavLink to="/ops">Governance</NavLink>}
        </nav>
      )}
      {me && (
        <div className="who">
          <span>
            {me.email} · <b>{me.role.replace("_", " ")}</b>
          </span>
          <button className="ghost" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      )}
    </header>
  );
}

function Home() {
  const { me, loading } = useAuth();
  if (loading) return <p className="muted pad">Loading…</p>;
  return <Navigate to={me ? homeFor(me) : "/login"} replace />;
}

export default function App() {
  return (
    <>
      <Header />
      <main>
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
