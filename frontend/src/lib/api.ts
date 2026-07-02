// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import axios, { type AxiosError } from 'axios'
import type {
  ChannelInput,
  DashboardSummary,
  EventListResponse,
  Fleet,
  FleetResponse,
  FleetWithInstances,
  Instance,
  NotificationChannel,
  TransformStage,
} from '@/lib/types'

const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

// Attach access token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Auto-refresh on 401
let _refreshing = false
let _refreshQueue: Array<(token: string) => void> = []

api.interceptors.response.use(
  (res) => res,
  async (err: AxiosError) => {
    const original = err.config as typeof err.config & { _retry?: boolean }
    if (err.response?.status !== 401 || original?._retry) {
      return Promise.reject(err)
    }
    original._retry = true

    if (_refreshing) {
      return new Promise((resolve) => {
        _refreshQueue.push((token) => {
          if (original?.headers) original.headers.Authorization = `Bearer ${token}`
          resolve(api(original!))
        })
      })
    }

    _refreshing = true
    try {
      const refreshToken = localStorage.getItem('refresh_token')
      if (!refreshToken) throw new Error('No refresh token')

      const { data } = await axios.post<{ access_token: string; refresh_token: string }>(
        '/api/v1/auth/refresh',
        { refresh_token: refreshToken }
      )
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)

      _refreshQueue.forEach((cb) => cb(data.access_token))
      _refreshQueue = []

      if (original?.headers) original.headers.Authorization = `Bearer ${data.access_token}`
      return api(original!)
    } catch {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      window.location.href = '/login'
      return Promise.reject(err)
    } finally {
      _refreshing = false
    }
  }
)

export const authApi = {
  methods: () => api.get('/auth/methods'),
  login: (email: string, password: string) =>
    api.post('/auth/login', { email, password }),
  logout: (refreshToken?: string | null) =>
    api.post('/auth/logout', refreshToken ? { refresh_token: refreshToken } : {}),
  me: () => api.get('/auth/me'),
  changePassword: (current_password: string, new_password: string) =>
    api.post('/auth/change-password', { current_password, new_password }),
}

export const usersApi = {
  list: () => api.get('/users'),
  create: (data: { email: string; name: string; role: string; password?: string }) =>
    api.post('/users', data),
  update: (id: string, data: { name?: string; role?: string; is_active?: boolean }) =>
    api.patch(`/users/${id}`, data),
  resetPassword: (id: string, new_password?: string) =>
    api.post<{ generated: boolean; password: string | null }>(`/users/${id}/reset-password`, {
      new_password: new_password || null,
    }),
  delete: (id: string) => api.delete(`/users/${id}`),
}

export interface ApiTokenMeta {
  id: string
  token_id: string
  name: string
  created_at: string | null
  last_used_at: string | null
  expires_at: string | null
}

export const catalogApi = {
  // Raw Vector generate-schema JSON; the X-Vector-Version header carries the
  // version. force=true bypasses the backend + browser cache.
  schema: (force = false) =>
    api.get('/catalog/schema', { params: force ? { force: true } : undefined }),
  refresh: () => api.post<{ available: boolean; vector_version: string | null }>(
    '/catalog/refresh',
  ),
}

export const tokensApi = {
  list: () => api.get<ApiTokenMeta[]>('/tokens'),
  create: (name: string, expires_in_days: number | null) =>
    api.post<ApiTokenMeta & { token: string }>('/tokens', { name, expires_in_days }),
  revoke: (id: string) => api.delete(`/tokens/${id}`),
}

export const instancesApi = {
  list: () => api.get<Instance[]>('/instances'),
  fleet: () => api.get<FleetResponse>('/instances/fleet'),
  create: (data: object) => api.post('/instances', data),
  update: (id: string, data: object) => api.patch(`/instances/${id}`, data),
  delete: (id: string) => api.delete(`/instances/${id}`),
  health: (id: string) => api.get(`/instances/${id}/health`),
  topology: (id: string) => api.get(`/instances/${id}/topology`),
}


export const transformsApi = {
  list: () => api.get('/transforms'),
  get: (id: string) => api.get(`/transforms/${id}`),
  create: (data: object) => api.post('/transforms', data),
  update: (id: string, data: object) => api.patch(`/transforms/${id}`, data),
  delete: (id: string) => api.delete(`/transforms/${id}`),
  test: (data: { vrl: string; event: object; instance_id?: string }) =>
    api.post('/transforms/test', data),
  // Server-side validate/run via the bundled Vector binary — needs no instance.
  validate: (data: { vrl: string; event: object }) =>
    api.post('/transforms/validate', data),
  // AI assistant (BYO-LLM). aiStatus = editor-readable enabled flag for UI gating.
  aiStatus: () => api.get<{ enabled: boolean; provider: string }>('/transforms/ai/status'),
  aiGenerate: (data: {
    intent: string
    event: object
    current_vrl?: string
    max_retries?: number
  }) => api.post('/transforms/ai/generate', data),
}

export const fleetsApi = {
  list: () => api.get<{ fleets: Fleet[]; total: number }>('/fleets'),
  get: (id: string) => api.get<FleetWithInstances>(`/fleets/${id}`),
  create: (data: { name: string; description?: string }) => api.post<Fleet>('/fleets', data),
  update: (
    id: string,
    data: { name?: string; description?: string; desired_vector_version?: string },
  ) => api.patch<Fleet>(`/fleets/${id}`, data),
  delete: (id: string) => api.delete(`/fleets/${id}`),
  deleteImpact: (id: string) =>
    api.get<{
      is_default: boolean
      sources: number
      sinks: number
      routes: number
      stages: number
      instances: string[]
    }>(`/fleets/${id}/delete-impact`),
  addInstance: (fleetId: string, instanceId: string, role: 'agent' | 'aggregator') =>
    api.post(`/fleets/${fleetId}/instances/${instanceId}`, { role }),
  removeInstance: (fleetId: string, instanceId: string) =>
    api.delete(`/fleets/${fleetId}/instances/${instanceId}`),
  generateBootstrapToken: (fleetId: string) =>
    api.post<{ token: string }>(`/fleets/${fleetId}/bootstrap-token`),
  getBootstrapCommand: (fleetId: string) =>
    api.get<{ command: string; token_set: boolean }>(`/fleets/${fleetId}/bootstrap-command`),
  getConfig: (fleetId: string) =>
    api.get<{ yaml: string; warnings: string[]; errors: string[] }>(
      `/fleets/${fleetId}/config`,
    ),
  tapTargets: (fleetId: string) =>
    api.get<{
      targets: Array<{
        resource_id: string
        id: string
        label: string
        kind: 'source' | 'transform' | 'route' | 'route_branch'
        input_ids?: string[]
      }>
    }>(`/fleets/${fleetId}/tap-targets`),
  validate: (fleetId: string) =>
    api.post<{
      status: 'valid' | 'invalid' | 'unavailable'
      output: string
      errors: string[]
      warnings: string[]
    }>(`/fleets/${fleetId}/validate`),
  deploy: (fleetId: string) =>
    api.post<{
      deployed: number
      total: number
      warnings: string[]
      results: Array<{
        instance_id: string
        label: string
        status: 'deployed' | 'skipped' | 'error'
        detail?: string
        path?: string
      }>
    }>(`/fleets/${fleetId}/deploy`),
}

export const dashboardApi = {
  summary: (minutes?: number, metric?: 'events' | 'bytes') =>
    api.get<DashboardSummary>('/dashboard/summary', {
      params: { ...(minutes ? { minutes } : {}), ...(metric ? { metric } : {}) },
    }),
}

export const eventsApi = {
  list: (includeResolved = false) =>
    api.get<EventListResponse>(
      `/events${includeResolved ? '?include_resolved=true' : ''}`,
    ),
  ack: (id: string) => api.post(`/events/${id}/ack`),
  ackAll: () => api.post('/events/ack-all'),
}

export const routesApi = {
  list: (fleetId?: string) =>
    api.get(`/routes${fleetId ? `?fleet_id=${fleetId}` : ''}`),
  get: (id: string) => api.get(`/routes/${id}`),
  create: (data: object) => api.post('/routes', data),
  update: (id: string, data: object) => api.patch(`/routes/${id}`, data),
  delete: (id: string, force = false) =>
    api.delete(`/routes/${id}${force ? '?force=true' : ''}`),
}

export const componentsApi = {
  list: (params?: { fleet_id?: string; kind?: 'source' | 'sink' }) => {
    const q = new URLSearchParams()
    if (params?.fleet_id) q.set('fleet_id', params.fleet_id)
    if (params?.kind) q.set('kind', params.kind)
    const qs = q.toString()
    return api.get(`/components${qs ? `?${qs}` : ''}`)
  },
  get: (id: string) => api.get(`/components/${id}`),
  create: (data: object) => api.post('/components', data),
  update: (id: string, data: object) => api.patch(`/components/${id}`, data),
  delete: (id: string, force = false) =>
    api.delete(`/components/${id}${force ? '?force=true' : ''}`),
}

export const certsApi = {
  list: () => api.get('/certs'),
  parse: (data: { cert_pem: string; key_pem?: string; passphrase?: string }) =>
    api.post('/certs/parse', data),
  upload: (data: {
    label: string
    cert_type: string
    cert_pem: string
    key_pem?: string
    passphrase?: string
    ca_chain_pem?: string
    notes?: string
  }) => api.post('/certs', data),
  patch: (id: string, data: { label?: string; notes?: string }) =>
    api.patch(`/certs/${id}`, data),
  delete: (id: string) => api.delete(`/certs/${id}`),
}

export interface AuditEntry {
  id: string
  created_at: string | null
  user_id: string | null
  user_email: string | null
  action: string
  resource_type: string | null
  resource_id: string | null
  detail: string | null
  ip_address: string | null
}

export type AuditQuery = {
  action?: string
  resource_type?: string
  user_id?: string
  q?: string
  limit?: number
  offset?: number
}

function auditQs(params: AuditQuery): string {
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== '') qs.set(k, String(v))
  })
  const s = qs.toString()
  return s ? `?${s}` : ''
}

export const auditApi = {
  list: (params: AuditQuery = {}) =>
    api.get<{ total: number; entries: AuditEntry[] }>(`/audit${auditQs(params)}`),
  exportCsv: (params: AuditQuery = {}) =>
    api.get(`/audit/export${auditQs(params)}`, { responseType: 'blob' }),
}

export const transformStagesApi = {
  list: (fleetId?: string) =>
    api.get<{ stages: TransformStage[]; total: number }>(
      `/transform-stages${fleetId ? `?fleet_id=${fleetId}` : ''}`,
    ),
  create: (data: object) => api.post<TransformStage>('/transform-stages', data),
  update: (id: string, data: object) =>
    api.patch<TransformStage>(`/transform-stages/${id}`, data),
  delete: (id: string, force = false) =>
    api.delete(`/transform-stages/${id}${force ? '?force=true' : ''}`),
}

export const recoveryApi = {
  status: () => api.get<{ available: boolean }>('/recovery'),
  use: (token: string, new_password: string) =>
    api.post('/recovery', { token, new_password }),
}

export const notificationsApi = {
  list: () => api.get<NotificationChannel[]>('/notifications/channels'),
  create: (data: ChannelInput) =>
    api.post<NotificationChannel>('/notifications/channels', data),
  update: (id: string, data: Partial<ChannelInput>) =>
    api.patch<NotificationChannel>(`/notifications/channels/${id}`, data),
  delete: (id: string) => api.delete(`/notifications/channels/${id}`),
  test: (id: string) => api.post(`/notifications/channels/${id}/test`),
}

export const settingsApi = {
  getGeneral: () => api.get('/settings/general'),
  putGeneral: (data: object) => api.put('/settings/general', data),
  getNotifications: () => api.get('/settings/notifications'),
  putNotifications: (data: object) => api.put('/settings/notifications', data),
  getTls: () => api.get('/settings/tls'),
  putTls: (data: object) => api.put('/settings/tls', data),
  applyTls: () => api.post('/settings/tls/apply'),
  getAzure: () => api.get('/settings/sso/azure'),
  putAzure: (data: object) => api.put('/settings/sso/azure', data),
  getOidc: () => api.get('/settings/sso/oidc'),
  putOidc: (data: object) => api.put('/settings/sso/oidc', data),
  getSaml: () => api.get('/settings/sso/saml'),
  putSaml: (data: object) => api.put('/settings/sso/saml', data),
  getLdap: () => api.get('/settings/sso/ldap'),
  putLdap: (data: object) => api.put('/settings/sso/ldap', data),
  getAi: () => api.get('/settings/ai'),
  putAi: (data: object) => api.put('/settings/ai', data),
  testAi: () => api.post('/settings/ai/test'),
}

export default api
