import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./app/App";
import { PortalProvider } from "./app/PortalContext";
import "./app.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PortalProvider>
      <App />
    </PortalProvider>
  </StrictMode>,
);
