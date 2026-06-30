// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { GENERATED_SOURCES, GENERATED_SINKS } from './catalog.generated'
import { schemaToCatalog } from './catalogGen'

export type FieldType = 'string' | 'number' | 'boolean' | 'array' | 'select' | 'textarea'

export interface CatalogField {
  key: string
  label: string
  type: FieldType
  required?: boolean
  default?: string | number | boolean
  placeholder?: string
  hint?: string
  options?: Array<{ value: string; label: string }>
  /** Optional section header. Fields sharing a group render under one heading. */
  group?: string
  /** True when this field came from the schema-driven generator, not curation. */
  generated?: boolean
}

/**
 * True when a component config key names a credential. Mirrors the backend
 * `is_secret_key` in `app/services/secrets.py` — the backend is the security
 * source of truth (it encrypts + masks these); this drives password-input UX so
 * the two stay in sync. Keep both lists aligned.
 */
const _SECRET_RE =
  /password|passwd|secret|token|api_?key|access_key|private_key|credential|sas_?key|license_key|auth_?key|passphrase|key_pass|connection_string|shared_key|nkey/i
const _NOT_SECRET_LEAVES = new Set([
  'key',
  'key_field',
  'partition_key',
  'group_key',
  'routing_key',
  'message_key',
  'dedupe_key',
  'secret_name',
])
export function isSecretKey(dotkey: string): boolean {
  const leaf = (dotkey.split('.').pop() ?? dotkey).toLowerCase()
  if (_NOT_SECRET_LEAVES.has(leaf)) return false
  if (/(_file|_field|_path)$/i.test(dotkey)) return false
  return _SECRET_RE.test(dotkey)
}

export interface CatalogComponent {
  type: string
  name: string
  description: string
  category: string
  fields: CatalogField[]
  /** True when this component was auto-generated from the Vector JSON Schema. */
  generated?: boolean
}

export const CATEGORIES = [
  'File & System',
  'Containers',
  'Network',
  'Messaging',
  'Cloud',
  'Metrics',
  'Observability',
  'Analytics',
  'Pipeline',
] as const

// ─── Sources ──────────────────────────────────────────────────────────────────

const CURATED_SOURCES: CatalogComponent[] = [
  {
    type: 'file',
    name: 'File',
    description: 'Tail one or more files on the local filesystem.',
    category: 'File & System',
    fields: [
      {
        key: 'include',
        label: 'Include paths',
        type: 'array',
        required: true,
        placeholder: '/var/log/app/*.log',
        hint: 'One glob pattern per line.',
      },
      {
        key: 'exclude',
        label: 'Exclude paths',
        type: 'array',
        placeholder: '/var/log/app/*.gz',
        hint: 'Patterns to exclude (optional).',
      },
      {
        key: 'read_from',
        label: 'Read from',
        type: 'select',
        default: 'beginning',
        options: [
          { value: 'beginning', label: 'Beginning' },
          { value: 'end', label: 'End (tail)' },
        ],
      },
      {
        key: 'multiline.mode',
        label: 'Multiline mode',
        type: 'select',
        default: '',
        options: [
          { value: '', label: 'Disabled' },
          { value: 'continue_through', label: 'Continue through' },
          { value: 'halt_before', label: 'Halt before' },
          { value: 'halt_with', label: 'Halt with' },
        ],
        hint: 'Aggregate log lines that span multiple lines.',
      },
    ],
  },
  {
    type: 'stdin',
    name: 'Standard Input',
    description: 'Read lines from standard input (stdin). Useful for piped input.',
    category: 'File & System',
    fields: [
      {
        key: 'host_key',
        label: 'Host key field',
        type: 'string',
        default: 'host',
        hint: 'Field name to store the hostname.',
      },
    ],
  },
  {
    type: 'journald',
    name: 'systemd Journal',
    description: 'Collect log entries from the systemd journal.',
    category: 'File & System',
    fields: [
      {
        key: 'units',
        label: 'Units (filter)',
        type: 'array',
        placeholder: 'nginx.service',
        hint: 'Limit to specific systemd units. Leave empty to collect all.',
      },
      {
        key: 'include_matches',
        label: 'Include matches',
        type: 'textarea',
        placeholder: '_SYSTEMD_UNIT=nginx.service',
        hint: 'Journal field match filters, one per line.',
      },
      {
        key: 'since_now',
        label: 'Start from now',
        type: 'boolean',
        default: false,
        hint: 'If true, only collect entries logged after Vector starts.',
      },
    ],
  },
  {
    type: 'docker_logs',
    name: 'Docker Logs',
    description: 'Collect logs from Docker containers via the Docker API.',
    category: 'Containers',
    fields: [
      {
        key: 'include_containers',
        label: 'Include containers',
        type: 'array',
        placeholder: 'my-app',
        hint: 'Container names or IDs to include. Leave empty for all.',
      },
      {
        key: 'exclude_containers',
        label: 'Exclude containers',
        type: 'array',
        placeholder: 'vector',
        hint: 'Container names or IDs to exclude.',
      },
      {
        key: 'docker_host',
        label: 'Docker host',
        type: 'string',
        default: 'unix:///var/run/docker.sock',
        hint: 'Docker socket or API URL.',
      },
    ],
  },
  {
    type: 'kubernetes_logs',
    name: 'Kubernetes Logs',
    description: 'Collect logs from Kubernetes pods. Typically runs as a DaemonSet.',
    category: 'Containers',
    fields: [
      {
        key: 'extra_label_selector',
        label: 'Label selector',
        type: 'string',
        placeholder: 'app=frontend',
        hint: 'Kubernetes label selector to filter pods.',
      },
      {
        key: 'extra_namespace_label_selector',
        label: 'Namespace selector',
        type: 'string',
        placeholder: 'environment=production',
        hint: 'Filter pods by namespace label.',
      },
      {
        key: 'self_node_name',
        label: 'Node name env var',
        type: 'string',
        default: '${NODE_NAME}',
        hint: 'Environment variable holding the current node name.',
      },
    ],
  },
  {
    type: 'syslog',
    name: 'Syslog',
    description: 'Listen for syslog messages over UDP, TCP, or Unix socket.',
    category: 'Network',
    fields: [
      {
        key: 'mode',
        label: 'Mode',
        type: 'select',
        required: true,
        default: 'udp',
        options: [
          { value: 'udp', label: 'UDP' },
          { value: 'tcp', label: 'TCP' },
          { value: 'unix', label: 'Unix socket' },
        ],
      },
      {
        key: 'address',
        label: 'Listen address',
        type: 'string',
        default: '0.0.0.0:514',
        placeholder: '0.0.0.0:514',
      },
      {
        key: 'max_length',
        label: 'Max message length (bytes)',
        type: 'number',
        default: 102400,
      },
    ],
  },
  {
    type: 'socket',
    name: 'TCP / UDP Socket',
    description: 'Listen for events on a TCP or UDP socket.',
    category: 'Network',
    fields: [
      {
        key: 'mode',
        label: 'Mode',
        type: 'select',
        required: true,
        default: 'tcp',
        options: [
          { value: 'tcp', label: 'TCP' },
          { value: 'udp', label: 'UDP' },
          { value: 'unix', label: 'Unix stream' },
        ],
      },
      {
        key: 'address',
        label: 'Listen address',
        type: 'string',
        required: true,
        default: '0.0.0.0:9000',
        placeholder: '0.0.0.0:9000',
      },
    ],
  },
  {
    type: 'http_server',
    name: 'HTTP Server',
    description: 'Accept log events over HTTP. Accepts POST requests with a JSON body.',
    category: 'Network',
    fields: [
      {
        key: 'address',
        label: 'Listen address',
        type: 'string',
        required: true,
        default: '0.0.0.0:8080',
        placeholder: '0.0.0.0:8080',
      },
      {
        key: 'path',
        label: 'HTTP path',
        type: 'string',
        default: '/',
        placeholder: '/logs',
      },
      {
        key: 'encoding.codec',
        label: 'Encoding',
        type: 'select',
        default: 'json',
        options: [
          { value: 'json', label: 'JSON' },
          { value: 'ndjson', label: 'NDJSON' },
          { value: 'text', label: 'Plain text' },
        ],
      },
    ],
  },
  {
    type: 'kafka',
    name: 'Apache Kafka',
    description: 'Consume messages from one or more Kafka topics.',
    category: 'Messaging',
    fields: [
      {
        key: 'bootstrap_servers',
        label: 'Bootstrap servers',
        type: 'string',
        required: true,
        placeholder: 'broker1:9092,broker2:9092',
      },
      {
        key: 'topics',
        label: 'Topics',
        type: 'array',
        required: true,
        placeholder: 'logs.production',
        hint: 'One topic name per line.',
      },
      {
        key: 'group_id',
        label: 'Consumer group ID',
        type: 'string',
        required: true,
        default: 'vector',
      },
      {
        key: 'auto_offset_reset',
        label: 'Auto offset reset',
        type: 'select',
        default: 'earliest',
        options: [
          { value: 'earliest', label: 'Earliest' },
          { value: 'latest', label: 'Latest' },
        ],
      },
    ],
  },
  {
    type: 'nats',
    name: 'NATS',
    description: 'Subscribe to subjects on a NATS server.',
    category: 'Messaging',
    fields: [
      {
        key: 'url',
        label: 'NATS URL',
        type: 'string',
        required: true,
        default: 'nats://localhost:4222',
        placeholder: 'nats://localhost:4222',
      },
      {
        key: 'subject',
        label: 'Subject',
        type: 'string',
        required: true,
        placeholder: 'logs.>',
      },
      {
        key: 'queue',
        label: 'Queue group',
        type: 'string',
        placeholder: 'vector-consumers',
        hint: 'Optional NATS queue group for load balancing.',
      },
    ],
  },
  {
    type: 'redis',
    name: 'Redis',
    description: 'Read events from a Redis list or channel.',
    category: 'Messaging',
    fields: [
      {
        key: 'url',
        label: 'Redis URL',
        type: 'string',
        required: true,
        default: 'redis://localhost:6379',
        placeholder: 'redis://localhost:6379',
      },
      {
        key: 'key',
        label: 'List / channel key',
        type: 'string',
        required: true,
        placeholder: 'vector-logs',
      },
      {
        key: 'data_type',
        label: 'Data type',
        type: 'select',
        default: 'list',
        options: [
          { value: 'list', label: 'List (BLPOP)' },
          { value: 'channel', label: 'Pub/Sub channel' },
        ],
      },
    ],
  },
  {
    type: 'aws_s3',
    name: 'Amazon S3',
    description: 'Receive S3 event notifications via SQS and download the objects.',
    category: 'Cloud',
    fields: [
      {
        key: 'region',
        label: 'AWS region',
        type: 'string',
        required: true,
        placeholder: 'us-east-1',
      },
      {
        key: 'sqs.queue_url',
        label: 'SQS queue URL',
        type: 'string',
        required: true,
        placeholder: 'https://sqs.us-east-1.amazonaws.com/123456789/my-queue',
      },
    ],
  },
  {
    type: 'gcp_pubsub',
    name: 'GCP Pub/Sub',
    description: 'Subscribe to a Google Cloud Pub/Sub subscription.',
    category: 'Cloud',
    fields: [
      {
        key: 'project',
        label: 'GCP project ID',
        type: 'string',
        required: true,
        placeholder: 'my-project',
      },
      {
        key: 'subscription',
        label: 'Subscription name',
        type: 'string',
        required: true,
        placeholder: 'my-subscription',
      },
    ],
  },
  {
    type: 'prometheus_scrape',
    name: 'Prometheus Scrape',
    description: 'Scrape metrics from Prometheus /metrics endpoints.',
    category: 'Metrics',
    fields: [
      {
        key: 'endpoints',
        label: 'Endpoints',
        type: 'array',
        required: true,
        placeholder: 'http://localhost:9090/metrics',
        hint: 'One URL per line.',
      },
      {
        key: 'scrape_interval_secs',
        label: 'Scrape interval (seconds)',
        type: 'number',
        default: 15,
      },
    ],
  },
  {
    type: 'internal_metrics',
    name: 'Vector Internal Metrics',
    description: "Emit Vector's own internal performance metrics.",
    category: 'Metrics',
    fields: [
      {
        key: 'scrape_interval_secs',
        label: 'Scrape interval (seconds)',
        type: 'number',
        default: 5,
      },
    ],
  },
  {
    type: 'splunk_hec',
    name: 'Splunk HEC',
    description: 'Receive events from the Splunk HTTP Event Collector protocol.',
    category: 'Observability',
    fields: [
      {
        key: 'address',
        label: 'Listen address',
        type: 'string',
        default: '0.0.0.0:8088',
        placeholder: '0.0.0.0:8088',
      },
      {
        key: 'valid_tokens',
        label: 'Valid HEC tokens',
        type: 'array',
        placeholder: 'my-splunk-token',
        hint: 'One token per line. Leave empty to accept any token.',
      },
    ],
  },
  {
    type: 'vector',
    name: 'Vector (receive)',
    description: 'Receive events forwarded from another Vector instance.',
    category: 'Pipeline',
    fields: [
      {
        key: 'address',
        label: 'Listen address',
        type: 'string',
        required: true,
        default: '0.0.0.0:9000',
        placeholder: '0.0.0.0:9000',
      },
      {
        key: 'version',
        label: 'Protocol version',
        type: 'select',
        default: '2',
        options: [
          { value: '2', label: 'v2 (recommended)' },
          { value: '1', label: 'v1 (legacy)' },
        ],
      },
    ],
  },
]

// ─── Sinks ────────────────────────────────────────────────────────────────────

const RAW_SINKS: CatalogComponent[] = [
  {
    type: 'file',
    name: 'File',
    description: 'Write events to files on the local filesystem.',
    category: 'File & System',
    fields: [
      {
        key: 'path',
        label: 'File path template',
        type: 'string',
        required: true,
        placeholder: '/var/log/vector/{{ host }}.log',
        hint: 'Supports handlebars templates using event fields.',
      },
      {
        key: 'encoding.codec',
        label: 'Encoding',
        type: 'select',
        default: 'json',
        options: [
          { value: 'json', label: 'JSON' },
          { value: 'text', label: 'Plain text (.message field)' },
          { value: 'logfmt', label: 'logfmt' },
        ],
      },
      {
        key: 'compression',
        label: 'Compression',
        type: 'select',
        default: 'none',
        options: [
          { value: 'none', label: 'None' },
          { value: 'gzip', label: 'gzip' },
          { value: 'zstd', label: 'zstd' },
        ],
      },
    ],
  },
  {
    type: 'console',
    name: 'Console',
    description: 'Print events to stdout or stderr.',
    category: 'File & System',
    fields: [
      {
        key: 'target',
        label: 'Target',
        type: 'select',
        default: 'stdout',
        options: [
          { value: 'stdout', label: 'stdout' },
          { value: 'stderr', label: 'stderr' },
        ],
      },
      {
        key: 'encoding.codec',
        label: 'Encoding',
        type: 'select',
        default: 'json',
        options: [
          { value: 'json', label: 'JSON' },
          { value: 'text', label: 'Plain text' },
          { value: 'logfmt', label: 'logfmt' },
        ],
      },
    ],
  },
  {
    type: 'http',
    name: 'HTTP',
    description: 'Send events to an HTTP endpoint via POST.',
    category: 'Network',
    fields: [
      {
        key: 'uri',
        label: 'Endpoint URL',
        type: 'string',
        required: true,
        placeholder: 'https://ingest.example.com/logs',
      },
      {
        key: 'method',
        label: 'HTTP method',
        type: 'select',
        default: 'post',
        options: [
          { value: 'post', label: 'POST' },
          { value: 'put', label: 'PUT' },
          { value: 'patch', label: 'PATCH' },
        ],
      },
      {
        key: 'encoding.codec',
        label: 'Encoding',
        type: 'select',
        default: 'json',
        options: [
          { value: 'json', label: 'JSON' },
          { value: 'ndjson', label: 'NDJSON' },
          { value: 'text', label: 'Plain text' },
        ],
      },
      {
        key: 'auth.strategy',
        label: 'Auth strategy',
        type: 'select',
        default: '',
        options: [
          { value: '', label: 'None' },
          { value: 'basic', label: 'Basic auth' },
          { value: 'bearer', label: 'Bearer token' },
        ],
      },
    ],
  },
  {
    type: 'kafka',
    name: 'Apache Kafka',
    description: 'Publish events to a Kafka topic.',
    category: 'Messaging',
    fields: [
      {
        key: 'bootstrap_servers',
        label: 'Bootstrap servers',
        type: 'string',
        required: true,
        placeholder: 'broker1:9092,broker2:9092',
      },
      {
        key: 'topic',
        label: 'Topic',
        type: 'string',
        required: true,
        placeholder: 'logs.production',
      },
      {
        key: 'encoding.codec',
        label: 'Encoding',
        type: 'select',
        default: 'json',
        options: [
          { value: 'json', label: 'JSON' },
          { value: 'text', label: 'Plain text' },
        ],
      },
      {
        key: 'compression',
        label: 'Compression',
        type: 'select',
        default: 'none',
        options: [
          { value: 'none', label: 'None' },
          { value: 'gzip', label: 'gzip' },
          { value: 'lz4', label: 'lz4' },
          { value: 'snappy', label: 'snappy' },
        ],
      },
    ],
  },
  {
    type: 'nats',
    name: 'NATS',
    description: 'Publish events to a NATS subject.',
    category: 'Messaging',
    fields: [
      {
        key: 'url',
        label: 'NATS URL',
        type: 'string',
        required: true,
        default: 'nats://localhost:4222',
        placeholder: 'nats://localhost:4222',
      },
      {
        key: 'subject',
        label: 'Subject',
        type: 'string',
        required: true,
        placeholder: 'logs.output',
      },
      {
        key: 'encoding.codec',
        label: 'Encoding',
        type: 'select',
        default: 'json',
        options: [
          { value: 'json', label: 'JSON' },
          { value: 'text', label: 'Plain text' },
        ],
      },
    ],
  },
  {
    type: 'redis',
    name: 'Redis',
    description: 'Push events to a Redis list or publish to a channel.',
    category: 'Messaging',
    fields: [
      {
        key: 'url',
        label: 'Redis URL',
        type: 'string',
        required: true,
        default: 'redis://localhost:6379',
        placeholder: 'redis://localhost:6379',
      },
      {
        key: 'key',
        label: 'List / channel key',
        type: 'string',
        required: true,
        placeholder: 'vector-output',
      },
      {
        key: 'data_type',
        label: 'Data type',
        type: 'select',
        default: 'list',
        options: [
          { value: 'list', label: 'List (RPUSH)' },
          { value: 'channel', label: 'Pub/Sub channel (PUBLISH)' },
        ],
      },
    ],
  },
  {
    type: 'aws_s3',
    name: 'Amazon S3',
    description: 'Write event batches to Amazon S3 objects.',
    category: 'Cloud',
    fields: [
      {
        key: 'bucket',
        label: 'S3 bucket',
        type: 'string',
        required: true,
        placeholder: 'my-log-archive',
      },
      {
        key: 'region',
        label: 'AWS region',
        type: 'string',
        required: true,
        placeholder: 'us-east-1',
      },
      {
        key: 'key_prefix',
        label: 'Key prefix',
        type: 'string',
        default: 'logs/',
        placeholder: 'logs/{{ host }}/',
        hint: 'Supports handlebars templates.',
      },
      {
        key: 'encoding.codec',
        label: 'Encoding',
        type: 'select',
        default: 'json',
        options: [
          { value: 'json', label: 'JSON' },
          { value: 'ndjson', label: 'NDJSON' },
          { value: 'text', label: 'Plain text' },
        ],
      },
      {
        key: 'compression',
        label: 'Compression',
        type: 'select',
        default: 'gzip',
        options: [
          { value: 'none', label: 'None' },
          { value: 'gzip', label: 'gzip' },
          { value: 'zstd', label: 'zstd' },
        ],
      },
    ],
  },
  {
    type: 'aws_cloudwatch_logs',
    name: 'CloudWatch Logs',
    description: 'Send log events to Amazon CloudWatch Logs.',
    category: 'Cloud',
    fields: [
      {
        key: 'region',
        label: 'AWS region',
        type: 'string',
        required: true,
        placeholder: 'us-east-1',
      },
      {
        key: 'group_name',
        label: 'Log group name',
        type: 'string',
        required: true,
        placeholder: '/app/production',
      },
      {
        key: 'stream_name',
        label: 'Log stream name',
        type: 'string',
        required: true,
        placeholder: '{{ host }}',
        hint: 'Supports handlebars templates.',
      },
      {
        key: 'encoding.codec',
        label: 'Encoding',
        type: 'select',
        default: 'json',
        options: [
          { value: 'json', label: 'JSON' },
          { value: 'text', label: 'Plain text' },
        ],
      },
    ],
  },
  {
    type: 'gcp_cloud_storage',
    name: 'GCS',
    description: 'Write event batches to Google Cloud Storage.',
    category: 'Cloud',
    fields: [
      {
        key: 'bucket',
        label: 'GCS bucket',
        type: 'string',
        required: true,
        placeholder: 'my-log-archive',
      },
      {
        key: 'key_prefix',
        label: 'Key prefix',
        type: 'string',
        default: 'logs/',
        placeholder: 'logs/',
      },
      {
        key: 'encoding.codec',
        label: 'Encoding',
        type: 'select',
        default: 'ndjson',
        options: [
          { value: 'json', label: 'JSON' },
          { value: 'ndjson', label: 'NDJSON' },
          { value: 'text', label: 'Plain text' },
        ],
      },
    ],
  },
  {
    type: 'azure_blob',
    name: 'Azure Blob Storage',
    description: 'Write event batches to Azure Blob Storage.',
    category: 'Cloud',
    fields: [
      {
        key: 'connection_string',
        label: 'Connection string',
        type: 'string',
        required: true,
        placeholder: 'DefaultEndpointsProtocol=https;AccountName=...',
        hint: 'Azure Storage connection string.',
      },
      {
        key: 'container_name',
        label: 'Container name',
        type: 'string',
        required: true,
        placeholder: 'logs',
      },
      {
        key: 'blob_prefix',
        label: 'Blob prefix',
        type: 'string',
        default: 'vector/',
        placeholder: 'vector/',
      },
      {
        key: 'encoding.codec',
        label: 'Encoding',
        type: 'select',
        default: 'ndjson',
        options: [
          { value: 'json', label: 'JSON' },
          { value: 'ndjson', label: 'NDJSON' },
          { value: 'text', label: 'Plain text' },
        ],
      },
    ],
  },
  {
    type: 'elasticsearch',
    name: 'Elasticsearch',
    description: 'Index events into Elasticsearch or OpenSearch.',
    category: 'Analytics',
    fields: [
      {
        key: 'endpoints',
        label: 'Endpoints',
        type: 'array',
        required: true,
        placeholder: 'http://localhost:9200',
        hint: 'One URL per line.',
      },
      {
        key: 'index',
        label: 'Index',
        type: 'string',
        default: 'vector-%Y.%m.%d',
        placeholder: 'vector-%Y.%m.%d',
        hint: 'Supports strftime date formatting.',
      },
      {
        key: 'auth.strategy',
        label: 'Auth strategy',
        type: 'select',
        default: 'none',
        options: [
          { value: 'none', label: 'None' },
          { value: 'basic', label: 'Basic auth' },
          { value: 'aws', label: 'AWS SigV4' },
        ],
      },
      {
        key: 'tls.verify_certificate',
        label: 'Verify TLS',
        type: 'boolean',
        default: true,
      },
    ],
  },
  {
    type: 'loki',
    name: 'Grafana Loki',
    description: 'Push log streams to Grafana Loki.',
    category: 'Observability',
    fields: [
      {
        key: 'endpoint',
        label: 'Loki endpoint',
        type: 'string',
        required: true,
        default: 'http://localhost:3100',
        placeholder: 'http://localhost:3100',
      },
      {
        key: 'labels',
        label: 'Labels',
        type: 'textarea',
        placeholder: 'host = "{{ host }}"\napp = "myapp"',
        hint: 'Key = value pairs, one per line. Values support templates.',
      },
      {
        key: 'encoding.codec',
        label: 'Encoding',
        type: 'select',
        default: 'json',
        options: [
          { value: 'json', label: 'JSON' },
          { value: 'text', label: 'Plain text (.message)' },
          { value: 'logfmt', label: 'logfmt' },
        ],
      },
      {
        key: 'auth.strategy',
        label: 'Auth',
        type: 'select',
        default: '',
        options: [
          { value: '', label: 'None' },
          { value: 'basic', label: 'Basic auth' },
          { value: 'bearer', label: 'Bearer token' },
        ],
      },
    ],
  },
  {
    type: 'clickhouse',
    name: 'ClickHouse',
    description: 'Insert events into a ClickHouse table.',
    category: 'Analytics',
    fields: [
      {
        key: 'endpoint',
        label: 'ClickHouse HTTP URL',
        type: 'string',
        required: true,
        default: 'http://localhost:8123',
        placeholder: 'http://localhost:8123',
      },
      {
        key: 'table',
        label: 'Table name',
        type: 'string',
        required: true,
        placeholder: 'logs',
      },
      {
        key: 'database',
        label: 'Database',
        type: 'string',
        default: 'default',
        placeholder: 'default',
      },
      {
        key: 'compression',
        label: 'Compression',
        type: 'select',
        default: 'gzip',
        options: [
          { value: 'none', label: 'None' },
          { value: 'gzip', label: 'gzip' },
        ],
      },
    ],
  },
  {
    type: 'prometheus_remote_write',
    name: 'Prometheus Remote Write',
    description: 'Send metrics to any Prometheus remote_write compatible endpoint (VictoriaMetrics, Thanos, Cortex…).',
    category: 'Metrics',
    fields: [
      {
        key: 'endpoint',
        label: 'Remote write endpoint',
        type: 'string',
        required: true,
        placeholder: 'http://localhost:8428/api/v1/write',
      },
      {
        key: 'auth.strategy',
        label: 'Auth',
        type: 'select',
        default: '',
        options: [
          { value: '', label: 'None' },
          { value: 'basic', label: 'Basic auth' },
          { value: 'bearer', label: 'Bearer token' },
        ],
      },
    ],
  },
  {
    type: 'prometheus_exporter',
    name: 'Prometheus Exporter',
    description: 'Expose metrics on an HTTP endpoint for Prometheus to scrape.',
    category: 'Metrics',
    fields: [
      {
        key: 'address',
        label: 'Listen address',
        type: 'string',
        default: '0.0.0.0:9598',
        placeholder: '0.0.0.0:9598',
      },
    ],
  },
  {
    type: 'splunk_hec_logs',
    name: 'Splunk HEC',
    description: 'Send logs to Splunk via the HTTP Event Collector.',
    category: 'Observability',
    fields: [
      {
        key: 'endpoint',
        label: 'Splunk HEC endpoint',
        type: 'string',
        required: true,
        placeholder: 'https://splunk.example.com:8088',
      },
      {
        key: 'token',
        label: 'HEC token',
        type: 'string',
        required: true,
        placeholder: 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
      },
      {
        key: 'default_token',
        label: 'Index',
        type: 'string',
        placeholder: 'main',
        hint: 'Splunk index to write to (optional).',
      },
      {
        key: 'tls.verify_certificate',
        label: 'Verify TLS',
        type: 'boolean',
        default: true,
      },
    ],
  },
  {
    type: 'datadog_logs',
    name: 'Datadog Logs',
    description: 'Send logs to the Datadog Logs API.',
    category: 'Observability',
    fields: [
      {
        key: 'default_api_key',
        label: 'API key',
        type: 'string',
        required: true,
        placeholder: 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
      },
      {
        key: 'site',
        label: 'Datadog site',
        type: 'select',
        default: 'datadoghq.com',
        options: [
          { value: 'datadoghq.com', label: 'US1 (datadoghq.com)' },
          { value: 'us3.datadoghq.com', label: 'US3' },
          { value: 'us5.datadoghq.com', label: 'US5' },
          { value: 'datadoghq.eu', label: 'EU (datadoghq.eu)' },
        ],
      },
      {
        key: 'encoding.codec',
        label: 'Encoding',
        type: 'select',
        default: 'json',
        options: [
          { value: 'json', label: 'JSON' },
          { value: 'text', label: 'Plain text' },
        ],
      },
    ],
  },
  {
    type: 'new_relic',
    name: 'New Relic',
    description: 'Send logs, metrics, or traces to New Relic.',
    category: 'Observability',
    fields: [
      {
        key: 'license_key',
        label: 'License key',
        type: 'string',
        required: true,
        placeholder: 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
      },
      {
        key: 'api',
        label: 'API endpoint',
        type: 'select',
        default: 'logs',
        options: [
          { value: 'logs', label: 'Logs' },
          { value: 'metrics', label: 'Metrics' },
          { value: 'events', label: 'Events' },
          { value: 'traces', label: 'Traces' },
        ],
      },
      {
        key: 'region',
        label: 'Region',
        type: 'select',
        default: 'us',
        options: [
          { value: 'us', label: 'US' },
          { value: 'eu', label: 'EU' },
        ],
      },
    ],
  },
  {
    type: 'vector',
    name: 'Vector (forward)',
    description: 'Forward events to another Vector instance.',
    category: 'Pipeline',
    fields: [
      {
        key: 'address',
        label: 'Target address',
        type: 'string',
        required: true,
        placeholder: 'aggregator.internal:9000',
      },
      {
        key: 'version',
        label: 'Protocol version',
        type: 'select',
        default: '2',
        options: [
          { value: '2', label: 'v2 (recommended)' },
          { value: '1', label: 'v1 (legacy)' },
        ],
      },
      {
        key: 'compression',
        label: 'Compression',
        type: 'boolean',
        default: true,
        hint: 'Enable zstd compression on the wire.',
      },
    ],
  },
]

// ─── Shared sink reliability knobs ──────────────────────────────────────────────
// Buffering, end-to-end acknowledgements, and healthchecks apply to every Vector
// sink. They are the difference between losing data on a crash/restart and not,
// so they are surfaced on every destination rather than per-sink. Stored as
// dot-notation keys that the render engine expands into nested Vector tables.
const SINK_RELIABILITY_FIELDS: CatalogField[] = [
  {
    key: 'buffer.max_events',
    label: 'Buffer max events',
    type: 'number',
    default: 500,
    group: 'Reliability',
    hint: 'In-flight events held in the memory buffer before the when-full policy applies. (Disk buffers arrive with instance data_dir support.)',
  },
  {
    key: 'buffer.when_full',
    label: 'When buffer is full',
    type: 'select',
    default: 'block',
    group: 'Reliability',
    options: [
      { value: 'block', label: 'Block — apply backpressure upstream' },
      { value: 'drop_newest', label: 'Drop newest — shed load' },
    ],
    hint: 'Block preserves data by slowing the source; drop_newest sheds events.',
  },
  {
    key: 'acknowledgements.enabled',
    label: 'End-to-end acknowledgements',
    type: 'boolean',
    default: false,
    group: 'Reliability',
    hint: 'Hold the source ack until this sink confirms delivery — prevents data loss on crash for capable sources.',
  },
  {
    key: 'healthcheck.enabled',
    label: 'Healthcheck on boot',
    type: 'boolean',
    default: true,
    group: 'Reliability',
    hint: 'Vector verifies the sink is reachable when the config loads.',
  },
]

const CURATED_SINKS: CatalogComponent[] = RAW_SINKS.map((sink) => ({
  ...sink,
  fields: [...sink.fields, ...SINK_RELIABILITY_FIELDS],
}))

// ─── Hybrid catalog: curated + generated ────────────────────────────────────────
// Curated entries (~36) are authoritative and hand-tuned. The generated catalog
// (schema-driven, every Vector component type) fills in the long tail. On a type
// collision the curated entry WINS — generated is additive only.
function mergeCatalog(
  curated: CatalogComponent[],
  generated: CatalogComponent[]
): CatalogComponent[] {
  const curatedTypes = new Set(curated.map((c) => c.type))
  const extra = generated
    .filter((c) => !curatedTypes.has(c.type))
    .map((c) => ({ ...c, generated: true }))
  return [...curated, ...extra]
}

export const SOURCES: CatalogComponent[] = mergeCatalog(CURATED_SOURCES, GENERATED_SOURCES)
export const SINKS: CatalogComponent[] = mergeCatalog(CURATED_SINKS, GENERATED_SINKS)

/**
 * Build the hybrid catalog from a LIVE Vector `generate-schema` document — the
 * curated entries stay authoritative, the live schema fills the long tail. Lets
 * the catalog track the deployed Vector at runtime (no rebuild). Callers fall
 * back to the bundled SOURCES/SINKS above when no live schema is available.
 */
export function buildCatalogFromSchema(schema: unknown): {
  sources: CatalogComponent[]
  sinks: CatalogComponent[]
} {
  const gen = schemaToCatalog(schema)
  return {
    sources: mergeCatalog(CURATED_SOURCES, gen.sources),
    sinks: mergeCatalog(CURATED_SINKS, gen.sinks),
  }
}

// ─── YAML generation ──────────────────────────────────────────────────────────

const _YAML_RESERVED = /^(null|~|true|false|yes|no|on|off|\.inf|\.nan)$/i

function quoteYamlString(s: string): string {
  if (
    /[:{}\[\],#&*!|>'"$%@`]/.test(s) ||
    s.includes('\n') ||
    /^[-?]/.test(s) ||
    _YAML_RESERVED.test(s) ||
    s === ''
  ) {
    return JSON.stringify(s)
  }
  return s
}

function toYamlValue(value: unknown, indent: number): string {
  const pad = ' '.repeat(indent)
  if (Array.isArray(value)) {
    if (value.length === 0) return '[]'
    return '\n' + value.map((v) => `${pad}- ${quoteYamlString(String(v))}`).join('\n')
  }
  if (typeof value === 'boolean') return String(value)
  if (typeof value === 'number') return String(value)
  if (typeof value === 'string') return quoteYamlString(value)
  return String(value)
}

// Expand dot-notation key "a.b.c" into nested YAML lines at given indent.
function dotKeyToYaml(key: string, value: unknown, baseIndent: number): string[] {
  const parts = key.split('.')
  const lines: string[] = []
  const pad = ' '.repeat(baseIndent)
  if (parts.length === 1) {
    lines.push(`${pad}${key}: ${toYamlValue(value, baseIndent + 2)}`)
  } else {
    // Emit each nesting level, then the leaf value
    for (let i = 0; i < parts.length - 1; i++) {
      lines.push(`${' '.repeat(baseIndent + i * 2)}${parts[i]}:`)
    }
    const leafPad = ' '.repeat(baseIndent + (parts.length - 1) * 2)
    lines.push(`${leafPad}${parts[parts.length - 1]}: ${toYamlValue(value, baseIndent + parts.length * 2)}`)
  }
  return lines
}

/**
 * Coerce raw string form values into properly-typed config values using the
 * catalog field types (array → list, number → number, boolean → bool). Drops
 * empties and values equal to their default. Stored as the component's
 * `config_json` so the backend render engine can emit Vector config without
 * needing the catalog's type metadata.
 */
export function coerceFieldValues(
  component: CatalogComponent,
  values: Record<string, unknown>
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const field of component.fields) {
    const val = values[field.key]
    if (val === undefined || val === null || val === '') continue

    let coerced: unknown = val
    if (field.type === 'array' && typeof val === 'string') {
      coerced = val.split('\n').map((s) => s.trim()).filter(Boolean)
    } else if (field.type === 'number') {
      coerced = Number(val)
    } else if (field.type === 'boolean') {
      coerced = val === true || val === 'true'
    }

    if (coerced === field.default) continue
    if (Array.isArray(coerced) && coerced.length === 0) continue

    out[field.key] = coerced
  }
  return out
}

export function generateYaml(
  kind: 'sources' | 'sinks' | 'transforms',
  component: CatalogComponent,
  values: Record<string, unknown>,
  name: string
): string {
  const safeName = name.replace(/[^a-z0-9_]/gi, '_').toLowerCase() || 'component'
  const flat: Record<string, unknown> = { type: component.type }

  for (const field of component.fields) {
    const val = values[field.key]
    if (val === undefined || val === null || val === '') continue

    let coerced: unknown = val
    if (field.type === 'array' && typeof val === 'string') {
      coerced = val.split('\n').map((s) => s.trim()).filter(Boolean)
    } else if (field.type === 'number') {
      coerced = Number(val)
    } else if (field.type === 'boolean') {
      coerced = val === true || val === 'true'
    }

    if (coerced === field.default) continue
    if (Array.isArray(coerced) && coerced.length === 0) continue

    flat[field.key] = coerced
  }

  // Build YAML — expand dot-notation keys into nested blocks
  const lines: string[] = [`${kind}:`, `  ${safeName}:`]
  for (const [key, value] of Object.entries(flat)) {
    lines.push(...dotKeyToYaml(key, value, 4))
  }
  return lines.join('\n')
}
