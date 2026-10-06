import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, clearAccessToken, getAccessToken, SESSION_EXPIRED_EVENT, setAccessToken, type AuthenticatedUser } from "../api/client";

type AuthContextValue = {
  user: AuthenticatedUser | null;
  ready: boolean;
  signingIn: boolean;
  signIn(email: string, password: string): Promise<void>;
  signOut(): void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [ready, setReady] = useState(false);
  const [signingIn, setSigningIn] = useState(false);

  useEffect(() => {
    let current = true;
    const token = getAccessToken();
    if (!token) {
      setReady(true);
      return;
    }

    api
      .me()
      .then((authenticatedUser) => {
        if (current) setUser(authenticatedUser);
      })
      .catch(() => {
        clearAccessToken();
        if (current) setUser(null);
      })
      .finally(() => {
        if (current) setReady(true);
      });

    return () => {
      current = false;
    };
  }, []);

  useEffect(() => {
    const expireSession = () => {
      setUser(null);
      setReady(true);
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, expireSession);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, expireSession);
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    setSigningIn(true);
    try {
      const token = await api.login(email, password);
      setAccessToken(token.access_token);
      const authenticatedUser = await api.me();
      setUser(authenticatedUser);
      setReady(true);
    } catch (cause) {
      clearAccessToken();
      setUser(null);
      throw cause;
    } finally {
      setSigningIn(false);
    }
  }, []);

  const signOut = useCallback(() => {
    clearAccessToken();
    setUser(null);
    setReady(true);
  }, []);

  const value = useMemo(
    () => ({ user, ready, signingIn, signIn, signOut }),
    [user, ready, signingIn, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth precisa estar dentro de AuthProvider.");
  return value;
}
