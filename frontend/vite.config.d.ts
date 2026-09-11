export declare function resolveProxyTarget(env: Record<string, string | undefined>): string;
export declare function getViteServerConfig(env: Record<string, string | undefined>): {
    port: number;
    host: boolean;
    proxy: {
        "/api": {
            target: string;
            changeOrigin: boolean;
            secure: boolean;
        };
    };
};
declare const _default: import("vite").UserConfigFnObject;
export default _default;
