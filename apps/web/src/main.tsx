import { createRoot } from "react-dom/client";
import App from "./App";
import "@fontsource-variable/nunito";  // headings only (see --font-display); body stays the system font
import "./styles.css";

createRoot(document.getElementById("root")!).render(<App />);
