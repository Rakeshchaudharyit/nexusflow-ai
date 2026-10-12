"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import * as api from "@/lib/api/auth";

type Status = "loading" | "authenticated" | "anonymous" | "unavailable";
type AuthContextValue = {
  user: api.User | null;
  status: Status;
  signIn: typeof api.login;
  signUp: typeof api.register;
  signOut: () => Promise<void>;
  reload: () => Promise<void>;
  updateUser: (user: api.User) => void;
};
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<api.User | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const revision = useRef(0);
  const channel = useRef<BroadcastChannel | null>(null);
  const updateUser = useCallback((value: api.User) => {
    revision.current += 1;
    setUser(value);
    setStatus("authenticated");
  }, []);
  const reload = useCallback(() => {
    const current = ++revision.current;
    return api
      .refreshSession()
      .then((value) => {
        if (revision.current === current) {
          setUser(value);
          setStatus("authenticated");
        }
      })
      .catch((error: unknown) => {
        if (revision.current === current) {
          setUser(null);
          setStatus(
            error instanceof api.APIError && error.status === 401
              ? "anonymous"
              : "unavailable",
          );
        }
      });
  }, []);
  useEffect(() => {
    void reload();
    if (typeof BroadcastChannel !== "undefined") {
      channel.current = new BroadcastChannel("nexusflow-auth");
      channel.current.onmessage = () => {
        api.clearAccessToken();
        void reload();
      };
    }
    return () => {
      revision.current += 1;
      channel.current?.close();
      channel.current = null;
    };
  }, [reload]);
  const signIn: typeof api.login = async (...args) => {
    const value = await api.login(...args);
    updateUser(value);
    channel.current?.postMessage("session_changed");
    return value;
  };
  const signUp: typeof api.register = async (input) => {
    const value = await api.register(input);
    updateUser(value);
    channel.current?.postMessage("session_changed");
    return value;
  };
  const signOut = async () => {
    await api.logout();
    revision.current += 1;
    setUser(null);
    setStatus("anonymous");
    channel.current?.postMessage("session_changed");
  };
  return (
    <AuthContext.Provider
      value={{ user, status, signIn, signUp, signOut, reload, updateUser }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is required.");
  return value;
}
