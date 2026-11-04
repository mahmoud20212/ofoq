import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

type Theme = "dark" | "light";
const ThemeContext = createContext<{ theme: Theme; toggleTheme: () => void } | null>(null);

export function AccountTheme({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    try { return localStorage.getItem("ofoq-theme") === "light" ? "light" : "dark"; }
    catch { return "dark"; }
  });
  useEffect(() => {
    // PatternFly renders toast notifications in a portal attached to body.
    document.documentElement.dataset.accountTheme = theme;
    try { localStorage.setItem("ofoq-theme", theme); } catch { /* Storage may be unavailable. */ }
    return () => { delete document.documentElement.dataset.accountTheme; };
  }, [theme]);
  return (
    <ThemeContext.Provider value={{ theme, toggleTheme: () => setTheme(current => current === "dark" ? "light" : "dark") }}>
      <div className="account-theme" data-theme={theme} dir="rtl" lang="ar">{children}</div>
    </ThemeContext.Provider>
  );
}

export function useAccountTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("AccountTheme is required");
  return context;
}
