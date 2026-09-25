import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, refreshSession, setAccessToken, type Me } from "./api";
import { setLanguage } from "./i18n";

interface AuthState {
  me: Me | null;
  loading: boolean;
  signIn: (accessToken: string) => Promise<Me>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // A returning visitor still has the refresh cookie: resume silently.
    refreshSession()
      .then(async (ok) => {
        if (!ok) return;
        const current = await api<Me>("/me");
        setLanguage(current.locale);
        setMe(current);
      })
      .catch(() => null)
      .finally(() => setLoading(false));
  }, []);

  const signIn = useCallback(async (accessToken: string) => {
    setAccessToken(accessToken);
    const current = await api<Me>("/me");
    setLanguage(current.locale);
    setMe(current);
    return current;
  }, []);

  const signOut = useCallback(async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => null);
    setAccessToken(null);
    setMe(null);
  }, []);

  return (
    <AuthContext.Provider value={{ me, loading, signIn, signOut }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const state = useContext(AuthContext);
  if (!state) throw new Error("useAuth outside AuthProvider");
  return state;
}

export function homeFor(me: Me): string {
  if (me.role === "worker") return "/passport";
  if (me.role === "pm") return "/console";
  return "/ops";
}
