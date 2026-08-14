import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppLayout } from "@/layouts/AppLayout";
import { FullBleedLayout } from "@/layouts/FullBleedLayout";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { Skeleton } from "@/components/ui/skeleton";

// Lazy-loaded pages
const Login = lazy(() => import("@/pages/Login"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Runs = lazy(() => import("@/pages/Runs"));
const RunDetail = lazy(() => import("@/pages/RunDetail"));
const Findings = lazy(() => import("@/pages/Findings"));
const KnowledgeModel = lazy(() => import("@/pages/KnowledgeModel"));
const Settings = lazy(() => import("@/pages/Settings"));
const NotFound = lazy(() => import("@/pages/NotFound"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      refetchOnWindowFocus: true,
    },
    mutations: {
      retry: 0,
    },
  },
});

function PageFallback() {
  return (
    <div className="flex flex-col gap-4 p-8">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-4 w-96" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Suspense fallback={<PageFallback />}>
          <Routes>
            {/* Public routes */}
            <Route path="/login" element={<Login />} />

            {/* Protected standard layout routes */}
            <Route
              element={
                <ProtectedRoute>
                  <AppLayout />
                </ProtectedRoute>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="runs" element={<Runs />} />
              <Route path="findings" element={<Findings />} />
              <Route path="knowledge" element={<KnowledgeModel />} />
              <Route path="settings" element={<Settings />} />
            </Route>

            {/* Protected full-bleed layout routes (Live Run view) */}
            <Route
              element={
                <ProtectedRoute>
                  <FullBleedLayout />
                </ProtectedRoute>
              }
            >
              <Route path="runs/:runId" element={<RunDetail />} />
            </Route>

            {/* Catch-all */}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
