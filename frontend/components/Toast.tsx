import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, CircleAlert, Info, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

type ToastType = "success" | "error" | "info";

interface ToastAction {
  label: string;
  href: string;
}

export interface ToastMessage {
  id: string;
  type: ToastType;
  message: string;
  duration?: number;
  action?: ToastAction;
}

const iconByType = {
  success: CheckCircle2,
  error: CircleAlert,
  info: Info,
};

const toneByType = {
  success: "text-good",
  error: "text-bad",
  info: "text-accent-text",
};

function Toast({ toast, onClose }: { toast: ToastMessage; onClose: (id: string) => void }) {
  useEffect(() => {
    const timer = setTimeout(() => onClose(toast.id), toast.duration ?? (toast.action ? 7000 : 4000));
    return () => clearTimeout(timer);
  }, [toast, onClose]);

  const Icon = iconByType[toast.type];

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -12, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: 24, transition: { duration: 0.15 } }}
      transition={{ type: "spring", stiffness: 420, damping: 32 }}
      role={toast.type === "error" ? "alert" : "status"}
      className="pointer-events-auto flex items-start gap-3 rounded-2xl border border-line bg-surface px-4 py-3 text-ink shadow-[var(--shadow-pop)]"
    >
      <Icon className={`mt-0.5 h-[18px] w-[18px] shrink-0 ${toneByType[toast.type]}`} strokeWidth={2} />
      <div className="min-w-0 flex-1">
        <p className="text-[13.5px] leading-5">{toast.message}</p>
        {toast.action && (
          <Link
            href={toast.action.href}
            onClick={() => onClose(toast.id)}
            className="mt-1.5 inline-block text-[13px] font-semibold underline decoration-accent decoration-2 underline-offset-4"
          >
            {toast.action.label}
          </Link>
        )}
      </div>
      <button onClick={() => onClose(toast.id)} className="sm-icon-btn -mr-1 -mt-1 h-7 w-7" aria-label="Dismiss notification">
        <X className="h-4 w-4" strokeWidth={2} />
      </button>
    </motion.div>
  );
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  useEffect(() => {
    const handleToast = (event: CustomEvent<Omit<ToastMessage, "id">>) => {
      setToasts((prev) => [...prev.slice(-3), { ...event.detail, id: `${Date.now()}-${Math.random()}` }]);
    };
    window.addEventListener("toast", handleToast as EventListener);
    return () => window.removeEventListener("toast", handleToast as EventListener);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  return (
    <div className="pointer-events-none fixed right-4 top-4 z-[70] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2">
      <AnimatePresence initial={false}>
        {toasts.map((toast) => (
          <Toast key={toast.id} toast={toast} onClose={removeToast} />
        ))}
      </AnimatePresence>
    </div>
  );
}

export function showToast(
  type: ToastType,
  message: string,
  options?: number | { duration?: number; action?: ToastAction },
) {
  const opts = typeof options === "number" ? { duration: options } : options ?? {};
  window.dispatchEvent(new CustomEvent("toast", { detail: { type, message, ...opts } }));
}
