export const API_BASE = "http://localhost:8000/api";
export const WS_BASE  = "ws://localhost:8000/ws";

export const TIRE_COLORS = {
  SOFT:         { bg: "bg-red-600",    text: "text-white",  hex: "#dc2626", label: "S" },
  MEDIUM:       { bg: "bg-yellow-400", text: "text-black",  hex: "#ca8a04", label: "M" },
  HARD:         { bg: "bg-gray-200",   text: "text-black",  hex: "#d1d5db", label: "H" },
  INTERMEDIATE: { bg: "bg-green-600",  text: "text-white",  hex: "#16a34a", label: "I" },
  WET:          { bg: "bg-blue-600",   text: "text-white",  hex: "#2563eb", label: "W" },
  UNKNOWN:      { bg: "bg-gray-600",   text: "text-gray-300", hex: "#4b5563", label: "?" },
};

export const TEAM_COLORS = {
  "Red Bull Racing":       "#1e3a5f",
  "Red Bull":              "#1e3a5f",
  "Ferrari":               "#e8002d",
  "Scuderia Ferrari":      "#e8002d",
  "Mercedes":              "#00d2be",
  "Mercedes AMG":          "#00d2be",
  "McLaren":               "#ff8000",
  "McLaren F1 Team":       "#ff8000",
  "Aston Martin":          "#006f62",
  "Aston Martin F1 Team":  "#006f62",
  "Alpine":                "#0090ff",
  "Alpine F1 Team":        "#0090ff",
  "Williams":              "#005aff",
  "Williams Racing":       "#005aff",
  "AlphaTauri":            "#2b4562",
  "Scuderia AlphaTauri":   "#2b4562",
  "RB":                    "#2b4562",
  "Visa Cash App RB":      "#2b4562",
  "Alfa Romeo":            "#900000",
  "Alfa Romeo F1 Team":    "#900000",
  "Kick Sauber":           "#00e701",
  "Haas":                  "#b6babd",
  "Haas F1 Team":          "#b6babd",
  "Racing Point":          "#f596c8",
  "Force India":           "#ff80c7",
  "Renault":               "#ffd800",
  "Toro Rosso":            "#469bff",
  "Lotus":                 "#1e6500",
};

export const TEAM_COLOR_FALLBACK = "#555";

export function getTeamColor(teamName) {
  if (!teamName) return TEAM_COLOR_FALLBACK;
  if (TEAM_COLORS[teamName]) return TEAM_COLORS[teamName];
  const lower = teamName.toLowerCase();
  for (const [key, val] of Object.entries(TEAM_COLORS)) {
    if (lower.includes(key.toLowerCase().split(" ")[0])) return val;
  }
  return TEAM_COLOR_FALLBACK;
}

export const SPEED_OPTIONS = [
  { label: "2×",  value: 2  },
  { label: "5×",  value: 5  },
  { label: "10×", value: 10 },
];
