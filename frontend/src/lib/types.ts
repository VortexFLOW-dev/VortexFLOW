// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

export interface User {
  id: string
  email: string
  name: string
  role: 'admin' | 'editor' | 'viewer'
  auth_method: string
  is_active: boolean
  created_at: string
  must_change_password?: boolean
}

export interface AuthMethods {
  local: boolean
  azure: boolean
  oidc: boolean
  oidc_display_name: string
  saml: boolean
  saml_display_name: string
  ldap: boolean
  app_name: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface Instance {
  id: string
  label: string
  api_url: string
  config_push_mode: 'local' | 'agent'
  config_dir: string | null
  agent_url: string | null
  data_dir: string | null
  expire_metrics_secs: number | null
  is_active: boolean
  fleet_id: string | null
  role: 'agent' | 'aggregator'
  tls_verify: boolean
  tls_ca_cert: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface Fleet {
  id: string
  name: string
  description: string | null
  is_default: boolean
  generation: number
  // Per-fleet Vector version target ("" / null = inherit the global default).
  desired_vector_version: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface FleetWithInstances extends Fleet {
  instances: InstanceInFleet[]
}

export interface InstanceInFleet {
  id: string
  label: string
  api_url: string
  role: 'agent' | 'aggregator'
  is_active: boolean
  config_push_mode: 'local' | 'agent'
  applied_generation: number | null
  agent_last_seen: string | null
  agent_status: string | null
}

export interface InstanceHealth {
  instance_id: string
  reachable: boolean
  vector_version: string | null
  uptime_seconds: number | null
  error: string | null
}


export interface TransformStage {
  id: string
  fleet_id: string
  name: string
  mode: 'inline' | 'library'
  source_vrl: string | null
  transform_id: string | null
  inputs: string[]
  created_at: string
  updated_at: string
}

export interface VrlTransform {
  id: string
  name: string
  description: string | null
  source_vrl: string
  created_at: string
  updated_at: string
}

export interface ApiError {
  detail: string
}

export interface SystemHealth {
  api: boolean
  db: boolean
  redis: boolean
  vm: boolean
}

export interface InstanceMetrics {
  events_in_per_sec: number
  events_out_per_sec: number
  errors_per_sec: number
  bytes_in_per_sec?: number
  bytes_out_per_sec?: number
  discarded_per_sec?: number
  buffer_events?: number
  sink_failed_per_sec?: number
}

export interface DashboardInstance {
  id: string
  label: string
  api_url: string
  role: 'agent' | 'aggregator'
  fleet_id: string | null
  config_push_mode: 'local' | 'agent'
  applied_generation: number | null
  agent_status: string | null
  vector_version: string | null
  metrics: InstanceMetrics
}

export interface DashboardFleet {
  id: string
  name: string
  is_default: boolean
  generation: number
  instance_count: number
  // events/sec over the last hour, oldest→newest; aligned across fleets for the
  // stacked throughput hero. May be empty when VM has no series for the fleet.
  throughput_series: number[]
  instances: DashboardInstance[]
}

export interface LeaderMetrics {
  load1: number | null
  mem_pct: number | null
}

export interface DashboardSummary {
  system: SystemHealth
  leader: LeaderMetrics | null
  desired_vector_version: string
  fleets: DashboardFleet[]
  unassigned_instances: number
  total_instances: number
}

export interface FleetEvent {
  id: string
  kind: string
  severity: 'info' | 'warning' | 'critical'
  title: string
  body: string | null
  resource_type: string | null
  resource_id: string | null
  created_at: string
  acknowledged_at: string | null
  resolved_at: string | null
}

export interface EventListResponse {
  events: FleetEvent[]
  unacknowledged: number
}

export type ChannelType = 'webhook' | 'slack' | 'teams' | 'email'

export interface NotificationChannel {
  id: string
  type: ChannelType
  name: string
  enabled: boolean
  config: Record<string, unknown>
  has_secret: boolean
  min_severity: 'warning' | 'critical'
  notify_on_resolve: boolean
  last_success_at: string | null
  last_attempt_at: string | null
  last_error: string | null
  created_at: string
}

export interface ChannelInput {
  type: ChannelType
  name: string
  enabled: boolean
  config: Record<string, unknown>
  secret: Record<string, unknown>
  min_severity: 'warning' | 'critical'
  notify_on_resolve: boolean
}

export type FleetState = 'healthy' | 'degraded' | 'offline' | 'unknown' | 'inactive'

export interface FleetInstanceMetrics {
  events_in_per_sec: number
  events_out_per_sec: number
  errors_per_sec: number
  bytes_in_per_sec?: number
  bytes_out_per_sec?: number
  discarded_per_sec?: number
  buffer_events?: number
  sink_failed_per_sec?: number
}

export interface FleetInstance {
  id: string
  label: string
  api_url: string
  host: string
  config_push_mode: 'local' | 'agent'
  role: 'agent' | 'aggregator'
  fleet_id: string | null
  is_active: boolean
  vector_version: string | null
  version_drift: boolean
  agent_status: string | null
  agent_last_seen: string | null
  fleet_generation: number | null
  applied_generation: number | null
  config_synced: boolean | null
  status: { state: FleetState; reason: string }
  metrics: FleetInstanceMetrics
}

export interface FleetResponse {
  instances: FleetInstance[]
  fleets: Record<string, { name: string; generation: number; is_default: boolean }>
  desired_vector_version: string
}

export type NodeHealth = 'healthy' | 'degraded' | 'offline' | 'unknown'

export interface RouteBranch {
  name: string
  condition: string
  sink_ids: string[]
}

export interface Route {
  id: string
  fleet_id: string
  name: string
  description: string | null
  branches: RouteBranch[]
  source_ids: string[]
  passthrough_sink_ids: string[]
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface Component {
  id: string
  fleet_id: string
  kind: 'source' | 'sink'
  name: string
  component_type: string
  config: Record<string, unknown>
  inputs: string[]
  /** TLS cert-store references: { identity?: certId, ca?: certId }. */
  cert_refs: Record<string, string>
  created_by: string | null
  created_at: string
  updated_at: string
}
