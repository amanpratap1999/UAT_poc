import { Navigate, useLocation } from "react-router-dom";
import { isAuthenticated } from "@/lib/auth-store";

interface ProtectedRouteProps {
  children: React.ReactNode;
}

/**
 * Route guard — redirects unauthenticated users to /login.
 * Preserves the attempted URL so we can redirect back after login.
 */
export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const location = useLocation();

  if (!isAuthenticated()) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}
