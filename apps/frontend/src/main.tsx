import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";

import { createQueryClient } from "./lib/queryClient";
import { router } from "./routes/router";
import "./index.css";

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
