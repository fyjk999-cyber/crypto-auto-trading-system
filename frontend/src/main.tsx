import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AIFirstDecisionConsole } from "./components/AIFirstDecisionConsole";
import { MarketIntelligenceDock } from "./components/MarketIntelligenceDock";
import "./app.css";

const root = document.getElementById("root");

if (!root) throw new Error("Missing #root element");

createRoot(root).render(
  <StrictMode>
    <App />
    <MarketIntelligenceDock />
    <AIFirstDecisionConsole />
  </StrictMode>,
);
