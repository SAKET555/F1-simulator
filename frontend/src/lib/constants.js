export const API_BASE = "http://localhost:8000/api";
export const WS_BASE  = "ws://localhost:8000/ws";

export const TIRE_COLORS = {
  SOFT:         { bg: "bg-red-600",    text: "text-white",  label: "S" },
  MEDIUM:       { bg: "bg-yellow-400", text: "text-black",  label: "M" },
  HARD:         { bg: "bg-gray-200",   text: "text-black",  label: "H" },
  INTERMEDIATE: { bg: "bg-green-600",  text: "text-white",  label: "I" },
  WET:          { bg: "bg-blue-600",   text: "text-white",  label: "W" },
  UNKNOWN:      { bg: "bg-gray-600",   text: "text-gray-300", label: "?" },
};

export const SPEED_OPTIONS = [
  { label: "2×",  value: 2  },
  { label: "5×",  value: 5  },
  { label: "10×", value: 10 },
];
