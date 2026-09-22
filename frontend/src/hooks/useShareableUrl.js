import { useEffect } from "react";

export function useShareableUrl({ raceId, lap, onRestore }) {
  useEffect(() => {
    if (!raceId) {
      history.replaceState(null, "", window.location.pathname);
      return;
    }
    const hash = `#race=${encodeURIComponent(raceId)}${lap ? `&lap=${lap}` : ""}`;
    history.replaceState(null, "", hash);
  }, [raceId, lap]);

  useEffect(() => {
    const hash = window.location.hash.slice(1);
    if (!hash) return;
    const params = new URLSearchParams(hash);
    const savedRace = params.get("race");
    const savedLap = params.get("lap");
    if (savedRace && onRestore) {
      onRestore({ raceId: decodeURIComponent(savedRace), lap: savedLap ? parseInt(savedLap) : null });
    }
  }, []);
}

export function copyShareLink() {
  navigator.clipboard.writeText(window.location.href).catch(() => {});
}
