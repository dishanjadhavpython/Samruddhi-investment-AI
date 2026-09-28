import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";

type Theme = "light" | "dark";

interface Preferences {
  theme: Theme;
  privacy: boolean;
  /** Calm mode hides day-to-day price changes; on by default. */
  calm: boolean;
  toggleTheme: () => void;
  togglePrivacy: () => void;
  toggleCalm: () => void;
}

export const THEME_KEY = "samruddhi-theme";
export const PRIVACY_KEY = "samruddhi-privacy";
export const CALM_KEY = "samruddhi-calm";

const PreferencesContext = createContext<Preferences | null>(null);

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Private mode / blocked storage: the preference just won't persist
  }
}

/**
 * Theme and privacy mode. Both are stamped on <html> as data attributes (the
 * inline script in _document.tsx does the same before first paint), so CSS
 * handles the visuals and React only tracks the value for toggle icons.
 */
export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>("light");
  const [privacy, setPrivacy] = useState(false);
  const [calm, setCalm] = useState(true);

  useEffect(() => {
    const root = document.documentElement;
    setTheme(root.dataset.theme === "dark" ? "dark" : "light");
    setPrivacy(root.dataset.privacy === "on");
    setCalm(readStorage(CALM_KEY) !== "off");

    // Follow the OS setting until the user picks a theme explicitly
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (event: MediaQueryListEvent) => {
      if (readStorage(THEME_KEY)) return;
      const next: Theme = event.matches ? "dark" : "light";
      root.dataset.theme = next;
      setTheme(next);
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      document.querySelector('meta[name="theme-color"]')?.setAttribute("content", next === "dark" ? "#0a0a0b" : "#e6e6ea");
      writeStorage(THEME_KEY, next);
      return next;
    });
  }, []);

  const togglePrivacy = useCallback(() => {
    setPrivacy((current) => {
      const next = !current;
      document.documentElement.dataset.privacy = next ? "on" : "off";
      writeStorage(PRIVACY_KEY, next ? "on" : "off");
      return next;
    });
  }, []);

  const toggleCalm = useCallback(() => {
    setCalm((current) => {
      const next = !current;
      writeStorage(CALM_KEY, next ? "on" : "off");
      return next;
    });
  }, []);

  return (
    <PreferencesContext.Provider value={{ theme, privacy, calm, toggleTheme, togglePrivacy, toggleCalm }}>
      {children}
    </PreferencesContext.Provider>
  );
}

export function usePreferences(): Preferences {
  const ctx = useContext(PreferencesContext);
  if (!ctx) throw new Error("usePreferences must be used inside PreferencesProvider");
  return ctx;
}
