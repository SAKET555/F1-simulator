import { useEffect, useState, useRef } from "react";
import { Radio, Volume2 } from "lucide-react";

export default function TeamRadio({ isLive, sessionKey }) {
  const [messages, setMessages] = useState([]);
  const bottomRef = useRef(null);

  useEffect(() => {
    if (!isLive || !sessionKey) return;

    async function poll() {
      try {
        const r = await fetch(`https://api.openf1.org/v1/team_radio?session_key=${sessionKey}`);
        if (r.ok) {
          const data = await r.json();
          setMessages(data.slice(-20));
        }
      } catch {}
    }

    poll();
    const id = setInterval(poll, 10000);
    return () => clearInterval(id);
  }, [isLive, sessionKey]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (!isLive) return (
    <div className="text-xs text-gray-600 p-3">Team radio is available during live race sessions.</div>
  );

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <Radio size={12} className="text-red-400 animate-pulse" />
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">Team Radio</h3>
      </div>
      <div className="overflow-auto max-h-64 space-y-2">
        {messages.length === 0 ? (
          <p className="text-gray-600 text-xs">No radio messages yet</p>
        ) : messages.map((m, i) => (
          <div key={i} className="flex items-start gap-2 text-xs">
            <Volume2 size={10} className="text-gray-500 mt-0.5 flex-shrink-0" />
            <div>
              <span className="text-yellow-400 font-bold mr-1">{m.driver_number || "?"}</span>
              <span className="text-gray-500">{m.date?.slice(11, 19) || ""}</span>
              {m.recording_url && (
                <a href={m.recording_url} target="_blank" rel="noreferrer"
                  className="ml-1 text-blue-400 hover:text-blue-300 text-[10px]">▶ play</a>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
