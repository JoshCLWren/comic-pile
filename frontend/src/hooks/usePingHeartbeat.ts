import { useEffect, useRef } from "react";

const HEARTBEAT_INTERVAL_MS = 240_000; // 4 minutes – balances cold-start mitigation with Vercel monthly execution quotas

export function usePingHeartbeat() {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Only start the heartbeat if the page is currently visible.
    // This prevents burning execution quotas when the tab is backgrounded/minimized.
    if (document.visibilityState === "visible") {
      startHeartbeat();
    }

    const visibilityChange = () => {
      if (document.visibilityState === "visible") {
        startHeartbeat();
      } else {
        stopHeartbeat();
      }
    };

    const stopHeartbeat = () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };

    const startHeartbeat = () => {
      // Clear any existing interval to avoid duplicates
      stopHeartbeat();
      intervalRef.current = setInterval(async () => {
        if (document.visibilityState === "visible") {
          try {
            await fetch("/api/ping", { method: "GET", cache: "no-store" });
          } catch (_err) {
            // Silently swallow fetch errors – the ping is best-effort only.
          }
        }
      }, HEARTBEAT_INTERVAL_MS);
    };

    startHeartbeat();

    return () => {
      stopHeartbeat();
      document.removeEventListener("visibilitychange", visibilityChange);
    };
  }, []); // empty deps – interval is managed entirely inside the effect
}