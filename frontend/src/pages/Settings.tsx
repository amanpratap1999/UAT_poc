import { Settings as SettingsIcon } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { useAuth } from "@/hooks/use-auth";

export default function Settings() {
  const { user } = useAuth();

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-ink-100">
          Settings
        </h1>
        <p className="mt-1 text-sm text-ink-400">
          Account and workspace configuration
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 max-w-2xl">
        {/* Account info */}
        <Card>
          <CardHeader>
            <CardTitle>Account</CardTitle>
            <SettingsIcon size={14} className="text-ink-600" aria-hidden="true" />
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-3">
              <div>
                <p className="data-label mb-0.5">Username</p>
                <p className="font-mono text-sm text-ink-100">{user?.username ?? "—"}</p>
              </div>
              <div>
                <p className="data-label mb-0.5">Role</p>
                <p className="font-mono text-sm text-ink-100">{user?.role ?? "—"}</p>
              </div>
              <div>
                <p className="data-label mb-0.5">Tenant</p>
                <p className="font-mono text-xs text-ink-400">{user?.tenant_id ?? "—"}</p>
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
            <div className="flex flex-col gap-3">
              <div>
                <p className="data-label mb-0.5">API Base URL</p>
                <p className="font-mono text-xs text-ink-400">
                  {import.meta.env.VITE_API_BASE_URL || "(via proxy)"}
                </p>
              </div>
              <div>
                <p className="data-label mb-0.5">Auth Method</p>
                <p className="font-mono text-xs text-ink-400">JWT Bearer (OAuth2 password)</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
