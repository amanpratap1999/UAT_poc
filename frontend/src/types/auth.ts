/** JWT token response from POST /api/v1/token */
export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
}

/** Roles defined in the backend RBAC system */
export type UserRole = "Admin" | "QA Manager" | "QA Engineer" | "Viewer";

/** Decoded user context from JWT claims */
export interface UserContext {
  username: string;
  role: UserRole;
  tenant_id: string;
  user_id: string;
}

/** Role hierarchy — higher index = more permissions */
export const ROLE_HIERARCHY: UserRole[] = [
  "Viewer",
  "QA Engineer",
  "QA Manager",
  "Admin",
];

export function hasRole(userRole: UserRole, requiredRole: UserRole): boolean {
  return ROLE_HIERARCHY.indexOf(userRole) >= ROLE_HIERARCHY.indexOf(requiredRole);
}
