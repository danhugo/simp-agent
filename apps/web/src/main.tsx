import { createRoot } from "react-dom/client";
import App from "./App";
import "@fontsource-variable/nunito";  // headings only (see --font-display); body stays the system font
import "./styles.css";

createRoot(document.getElementById("root")!).render(<App />);

// Optional error reporting: only when VITE_SENTRY_DSN is set at build time (loaded lazily, errors only, no PII)
const dsn = import.meta.env.VITE_SENTRY_DSN;
if (dsn) import("@sentry/browser").then((S) => S.init({ dsn, tracesSampleRate: 0,
  integrations: (all) => all.filter((i) => i.name !== "BrowserTracing" && i.name !== "Replay") }));
