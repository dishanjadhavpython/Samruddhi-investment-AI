import { Eye, EyeOff, MoonStar, SunMedium } from "lucide-react";
import { usePreferences } from "../lib/preferences";

export default function ThemeToggle({ className = "" }: { className?: string }) {
  const { theme, toggleTheme } = usePreferences();
  const isDark = theme === "dark";
  return (
    <button
      type="button"
      onClick={toggleTheme}
      className={`sm-icon-btn ${className}`}
      aria-label={`Switch to ${isDark ? "light" : "dark"} theme`}
      title={`Switch to ${isDark ? "light" : "dark"} theme`}
    >
      {isDark ? <SunMedium className="h-[18px] w-[18px]" strokeWidth={2} /> : <MoonStar className="h-[18px] w-[18px]" strokeWidth={2} />}
    </button>
  );
}

export function PrivacyToggle({ className = "" }: { className?: string }) {
  const { privacy, togglePrivacy } = usePreferences();
  return (
    <button
      type="button"
      onClick={togglePrivacy}
      className={`sm-icon-btn ${className}`}
      aria-pressed={privacy}
      aria-label={privacy ? "Show amounts" : "Hide amounts"}
      title={privacy ? "Show amounts" : "Hide amounts"}
    >
      {privacy ? <EyeOff className="h-[18px] w-[18px]" strokeWidth={2} /> : <Eye className="h-[18px] w-[18px]" strokeWidth={2} />}
    </button>
  );
}
