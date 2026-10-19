/// <reference types="vitest/config" />
// Vite (build e servidor de desenvolvimento) e Vitest (testes).
// Em `npm run dev` e `vite preview` (teste ponta a ponta), /api vai para a API local (API_ALVO);
// no container quem faz esse repasse é o Caddy (web/Caddyfile). Mesma origem: sem CORS.
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const alvoApi = process.env.API_ALVO ?? "http://127.0.0.1:8100";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": alvoApi } },
  preview: { proxy: { "/api": alvoApi } },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/teste/configuracao.ts"],
    css: false,
  },
});
