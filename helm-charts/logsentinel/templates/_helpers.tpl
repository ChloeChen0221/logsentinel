{{/* vim: set filetype=mustache: */}}

{{- define "logsentinel.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "logsentinel.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "logsentinel.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
通用 labels
*/}}
{{- define "logsentinel.labels" -}}
helm.sh/chart: {{ include "logsentinel.chart" . }}
app.kubernetes.io/name: {{ include "logsentinel.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
组件 selector labels（component 由调用方传入）
*/}}
{{- define "logsentinel.selectorLabels" -}}
app.kubernetes.io/name: {{ include "logsentinel.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Postgres 主服务名（匹配 bitnami/postgresql subchart 默认模板）
模式：<release>-postgresql
*/}}
{{- define "logsentinel.postgresqlHost" -}}
{{- printf "%s-postgresql" .Release.Name -}}
{{- end -}}

{{/*
Redis master 服务名（匹配 bitnami/redis subchart 默认模板）
模式：<release>-redis-master
*/}}
{{- define "logsentinel.redisHost" -}}
{{- printf "%s-redis-master" .Release.Name -}}
{{- end -}}

{{/*
Loki 服务名（grafana/loki SingleBinary 模式）
模式：<release>-loki
*/}}
{{- define "logsentinel.lokiHost" -}}
{{- printf "%s-loki" .Release.Name -}}
{{- end -}}

{{/*
DATABASE_URL（asyncpg 格式）
*/}}
{{- define "logsentinel.databaseUrl" -}}
{{- printf "postgresql+asyncpg://%s:%s@%s:5432/%s"
    .Values.postgresql.auth.username
    .Values.postgresql.auth.password
    (include "logsentinel.postgresqlHost" .)
    .Values.postgresql.auth.database
-}}
{{- end -}}

{{/*
REDIS_URL
*/}}
{{- define "logsentinel.redisUrl" -}}
{{- printf "redis://%s:6379/0" (include "logsentinel.redisHost" .) -}}
{{- end -}}

{{/*
LOKI_URL
*/}}
{{- define "logsentinel.lokiUrl" -}}
{{- printf "http://%s:3100" (include "logsentinel.lokiHost" .) -}}
{{- end -}}

{{/*
应用容器通用环境变量（DATABASE_URL / REDIS_URL / LOKI_URL）
*/}}
{{- define "logsentinel.commonEnv" -}}
- name: DATABASE_URL
  value: {{ include "logsentinel.databaseUrl" . | quote }}
- name: REDIS_URL
  value: {{ include "logsentinel.redisUrl" . | quote }}
- name: LOKI_URL
  value: {{ include "logsentinel.lokiUrl" . | quote }}
- name: LOG_LEVEL
  value: "INFO"
- name: ENGINE_INTERVAL_SECONDS
  value: "30"
{{- end -}}
