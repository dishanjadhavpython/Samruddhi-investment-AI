import { useEffect, useState } from "react";
import { useApi } from "./http";
import { ProjectionAssumptions } from "./projection";

// Fetched once per page load and shared: the assumptions only change with a deploy
let cached: ProjectionAssumptions | null = null;
let inflight: Promise<ProjectionAssumptions> | null = null;

/**
 * The retirement projection's assumptions from the API — the same values the
 * Retirement agent uses, so the page and the report can't disagree.
 * Null until loaded; pages show a skeleton rather than guessing.
 */
export function useProjectionAssumptions(): { assumptions: ProjectionAssumptions | null; error: string | null } {
  const api = useApi();
  const [assumptions, setAssumptions] = useState<ProjectionAssumptions | null>(cached);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (cached) return;
    inflight ??= api<ProjectionAssumptions>("/api/projection/assumptions");
    let live = true;
    inflight
      .then((value) => {
        cached = value;
        if (live) setAssumptions(value);
      })
      .catch((err) => {
        inflight = null;
        if (live) setError(err instanceof Error ? err.message : "Couldn't load the projection assumptions.");
      });
    return () => {
      live = false;
    };
  }, [api]);

  return { assumptions, error };
}
