// Runtime configuration. Only public values belong here: anything read from
// import.meta.env is bundled into the client and visible to every user.

const DEV_PROXY_BASE = '/api'

function resolveApiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim()
  if (configured) return configured.replace(/\/+$/, '')
  return DEV_PROXY_BASE
}

export const API_BASE_URL = resolveApiBaseUrl()

/** Builds a full backend URL, e.g. apiUrl('/ask'). */
export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
}

