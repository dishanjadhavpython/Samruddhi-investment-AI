import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

// WebGL only exists in the browser; keep the shader out of the static export's HTML
const Warp = dynamic(() => import("@paper-design/shaders-react").then((m) => m.Warp), {
  ssr: false,
});

/** Brand Warp: the charcoal checks from the design brief, with purple swapped for haldi yellow. */
export const WARP_COLORS = ["#121212", "#ffc62b", "#121212", "#f5a300"];

interface WarpBackdropProps {
  className?: string;
  /** 1 is the brief's pace; drop it for calm surfaces, raise it while agents are working */
  speed?: number;
  colors?: string[];
  shapeScale?: number;
  swirl?: number;
}

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(media.matches);
    const onChange = (event: MediaQueryListEvent) => setReduced(event.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

/**
 * Absolutely-positioned Warp gradient that fills its (relative) parent. The
 * charcoal base colour doubles as the fallback before WebGL paints, so the
 * card never flashes white.
 */
export function WarpBackdrop({ className = "", speed = 1, colors = WARP_COLORS, shapeScale = 0.1, swirl = 0.8 }: WarpBackdropProps) {
  const reducedMotion = usePrefersReducedMotion();

  return (
    <div className={`pointer-events-none absolute inset-0 overflow-hidden bg-[#121212] ${className}`} aria-hidden="true">
      <Warp
        style={{ width: "100%", height: "100%" }}
        colors={colors}
        proportion={0.45}
        softness={1}
        distortion={0.25}
        swirl={swirl}
        swirlIterations={10}
        shape="checks"
        shapeScale={shapeScale}
        speed={reducedMotion ? 0 : speed}
      />
    </div>
  );
}
