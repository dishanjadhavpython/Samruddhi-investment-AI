import { useAuth } from "@clerk/nextjs";
import { useCallback } from "react";
import { showToast } from "../components/Toast";
import { API_URL } from "./config";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/**
 * Authenticated JSON fetch against the FastAPI backend. Surfaces session
 * expiry and rate limiting once, as toasts, so pages only handle their own errors.
 */
export function useApi() {
  const { getToken } = useAuth();

  return useCallback(
    async <T = unknown>(path: string, init: RequestInit = {}): Promise<T> => {
      const token = await getToken();
      if (!token) throw new ApiError("You are signed out.", 401);

      const response = await fetch(`${API_URL}${path}`, {
        ...init,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(init.body ? { "Content-Type": "application/json" } : {}),
          ...init.headers,
        },
      });

      if (response.status === 401) {
        showToast("error", "Your session expired. Sign in again to continue.");
        throw new ApiError("Session expired", 401);
      }
      if (response.status === 429) {
        showToast("error", "Too many requests — wait a few seconds and try again.");
        throw new ApiError("Rate limited", 429);
      }
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new ApiError(body.detail || `Request failed (${response.status})`, response.status);
      }
      return response.json() as Promise<T>;
    },
    [getToken],
  );
}
