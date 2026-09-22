import { useEffect } from "react";

export function useKeyboardShortcuts({ onPause, onResume, onSpeedChange, paused, enabled = true }) {
  useEffect(() => {
    if (!enabled) return;

    function handleKey(e) {
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.target.tagName === "TEXTAREA") return;

      switch (e.key) {
        case " ":
          e.preventDefault();
          if (paused) onResume?.();
          else onPause?.();
          break;
        case "2":
          onSpeedChange?.(2);
          break;
        case "5":
          onSpeedChange?.(5);
          break;
        case "0":
        case "1":
          onSpeedChange?.(10);
          break;
        default:
          break;
      }
    }

    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [paused, enabled, onPause, onResume, onSpeedChange]);
}
