import { Settings as SettingsIcon } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { useAuth } from "@/hooks/use-auth";
import { getApiBaseUrl } from "@/lib/api-client";

export default function Settings() {
  const { user } = useAuth();
  const apiBaseUrl = getApiBaseUrl();

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      <div>
        <h1 className="page-title">Settings</h1>
        <p className="page-subtitle">
          Account and workspace configuration
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 max-w-2xl">
        {/* Account info */}
        <Card>
          <CardHeader>
            <CardTitle>Account</CardTitle>
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink/5 text-muted">
              <SettingsIcon size={15} aria-hidden="true" />
            </span>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-4">
              <div>
                <p className="data-label mb-1">Username</p>
                <p className="rounded-md bg-canvas px-2.5 py-1.5 font-mono text-sm text-ink">{user?.username ?? "—"}</p>
              </div>
              <div>
                <p className="data-label mb-1">Role</p>
                <p className="rounded-md bg-canvas px-2.5 py-1.5 font-mono text-sm text-ink">{user?.role ?? "—"}</p>
              </div>
              <div>
                <p className="data-label mb-1">Tenant</p>
                <p className="rounded-md bg-canvas px-2.5 py-1.5 font-mono text-xs text-body">{user?.tenant_id ?? "—"}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Backend info */}
        <Card>
          <CardHeader>
            <CardTitle>Backend</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-4">
              <div>
                <p className="data-label mb-1">API Base URL</p>
                <p className="rounded-md bg-canvas px-2.5 py-1.5 font-mono text-xs text-body break-all">
                  {apiBaseUrl || "(same-origin / relative proxy)"}
                </p>
              </div>
              <div>
                <p className="data-label mb-1">Auth Method</p>
                <p className="rounded-md bg-canvas px-2.5 py-1.5 font-mono text-xs text-body">
                  JWT Bearer (OAuth2 password)
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
