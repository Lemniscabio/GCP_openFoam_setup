import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import App from "./App.tsx";
import { SignInGate } from "./components/SignInGate";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SignInGate>
      <App />
    </SignInGate>
  </StrictMode>,
);
