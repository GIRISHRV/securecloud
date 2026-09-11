export type IconName =
  | "settings"
  | "shield"
  | "grid"
  | "layers"
  | "box"
  | "network"
  | "alert"
  | "arrow"
  | "plus"
  | "refresh"
  | "chevron"
  | "check"
  | "web"
  | "api"
  | "database"
  | "activity"
  | "search"
  | "close"
  | "stop"
  | "trash"
  | "clock";
const paths: Record<IconName, string> = {
  settings:
    "M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1 1-3ZM16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
  shield: "M12 3 21 7v6c0 5-9 9-9 9s-9-4-9-9V7l9-4Zm-4 9 3 3 5-6",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  layers: "m12 3 10 5-10 5L2 8l10-5ZM2 12l10 5 10-5M2 16l10 5 10-5",
  box: "m12 2 9 5v10l-9 5-9-5V7l9-5Zm0 10 9-5M12 12 3 7m9 5v10M7 4.8l9 5",
  network: "M9 3h6v6H9zM2 16h6v6H2zM16 16h6v6h-6zM12 9v4M5 16v-3h14v3",
  alert: "m12 3 10 18H2L12 3Zm0 5v6m0 3v1",
  arrow: "M4 12h16m-6-6 6 6-6 6",
  plus: "M12 5v14M5 12h14",
  refresh: "M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 14 6M4 12a8 8 0 0 0 14 6",
  chevron: "m9 5 7 7-7 7",
  check: "m5 12 4 4L19 6",
  web: "M3 4h18v16H3zM3 9h18M6 6.5h.01M9 6.5h.01",
  api: "m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18",
  database:
    "M20 5c0 2-4 3-8 3S4 7 4 5s4-3 8-3 8 1 8 3ZM4 5v14c0 2 4 3 8 3s8-1 8-3V5M4 12c0 2 4 3 8 3s8-1 8-3",
  activity: "M2 12h5l3-9 4 18 3-9h5",
  search: "M21 21l-6-6M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z",
  close: "m6 6 12 12M6 18 18 6",
  stop: "M5 5h14v14H5z",
  trash: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7",
  clock: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 7v5l3 2",
};
export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
