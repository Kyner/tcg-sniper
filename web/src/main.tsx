// Ponto de entrada do Vite: monta o app em <div id="raiz"> e carrega o CSS (Tailwind + DaisyUI).
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./estilo.css";

createRoot(document.getElementById("raiz")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
