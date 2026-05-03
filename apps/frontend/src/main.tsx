import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";

// i18n init — must run before any component renders so the first
// paint already has translations. Import for side-effect; module
// guard inside prevents re-init on HMR.
import "./i18n";
import { createQueryClient } from "./lib/queryClient";
import { router } from "./routes/router";
import "./index.css";

// Font assets — Inter Variable (sans, all weights via variable axis)
// + JetBrains Mono (mono 400/700). The body font stack in
// styles/tokens.css and the tailwind fontFamily.sans/mono chains
// reference these families; without these side-effect imports the
// browser silently falls back to Segoe UI / system-ui and the typography
// portion of the visual lock is a no-op.
import "@fontsource-variable/inter";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/700.css";

// IMPORTANT — always instantiate via createQueryClient(), never by
// constructing the QueryClient class directly. The factory installs:
//   - queryCache.onError for 401 → flip ['me'] to null (route gate
//     picks this up and redirects)
//   - retry: false default (opt-in per-query retry only)
//   - refetchOnWindowFocus: false (avoid surprise refetch storms)
// See src/lib/queryClient.ts. The static guard in
// src/__tests__/main-wiring.test.ts keeps this locked.
const queryClient = createQueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
);
