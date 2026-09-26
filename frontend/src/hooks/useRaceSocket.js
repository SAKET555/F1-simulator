import { useEffect, useRef, useState, useCallback } from "react";
import { WS_BASE } from "../lib/constants";

/**
 * useRaceSocket(raceId, speed)
 *
 * raceId  – historical race id ("2023-r14"); no connection while null
 * speed   – replay speed multiplier
 */
export function useRaceSocket(raceId, speed = 2) {
  const wsRef      = useRef(null);
  const [raceState,   setRaceState]   = useState(null);
  const [predictions, setPredictions] = useState(null);
  const [status,      setStatus]      = useState("idle");
  const [winner,      setWinner]      = useState(null);
  const [infoMsg,     setInfoMsg]     = useState(null);

  const send = useCallback((obj) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(obj));
    }
  }, []);

  useEffect(() => {
    if (!raceId) return;

    setStatus("connecting");
    setRaceState(null);
    setPredictions(null);
    setWinner(null);
    setInfoMsg(null);

    const ws = new WebSocket(`${WS_BASE}/race/${raceId}?speed=${speed}`);
    wsRef.current = ws;

    ws.onopen = () => setStatus("live");

    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      switch (msg.type) {
        case "race_state":
          setRaceState(msg.payload);
          break;
        case "prediction":
          setPredictions(msg.payload);
          break;
        case "race_end":
          setWinner(msg.payload.winner);
          setStatus("finished");
          break;
        case "info":
          setInfoMsg(msg.payload.message);
          if (!msg.payload.live) setStatus("idle");
          break;
        case "error":
          console.error("WS error:", msg.payload.detail);
          setStatus("error");
          break;
        default:
          break;
      }
    };

    ws.onerror  = () => setStatus("error");
    ws.onclose  = () => {};

    return () => ws.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raceId, speed]);

  const pause          = useCallback(() => send({ type: "pause" }),  [send]);
  const resume         = useCallback(() => send({ type: "resume" }), [send]);
  const setSpeedRemote = useCallback(
    (s) => send({ type: "set_speed", payload: { speed: s } }), [send]
  );

  return { raceState, predictions, status, winner, infoMsg,
           pause, resume, setSpeed: setSpeedRemote };
}
