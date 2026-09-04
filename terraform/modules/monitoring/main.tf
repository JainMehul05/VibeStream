# =============================================================================
# VibeStream Monitoring Module
# =============================================================================
# Complete observability stack for the self-hosted VibeStream deployment.
#
# Components:
# - Prometheus + Grafana + AlertManager
# - Loki for log aggregation
# - Jaeger for distributed tracing
# - Kiali for Istio service-mesh observability
# - Custom VibeStream Grafana dashboards
# - Backend ServiceMonitor
# - Backend Prometheus alerts
# =============================================================================


# =============================================================================
# Monitoring Namespace
# =============================================================================

resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = "monitoring"

    labels = {
      name        = "monitoring"
      environment = var.environment
    }
  }
}


# =============================================================================
# Prometheus + Grafana + AlertManager
# =============================================================================

resource "helm_release" "kube_prometheus_stack" {
  count = var.prometheus_enabled ? 1 : 0

  name       = "kube-prometheus-stack"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"
  version    = "55.0.0"
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [
    templatefile("${path.module}/values/prometheus-stack.yaml", {
      environment             = var.environment
      grafana_admin_password  = var.grafana_admin_password
      prometheus_retention    = var.prometheus_retention
      prometheus_storage_size = var.prometheus_storage_size
      alertmanager_enabled    = var.alertmanager_enabled
      slack_webhook_url       = var.slack_webhook_url
      pagerduty_service_key   = var.pagerduty_service_key
    })
  ]

  timeout = 600

  set {
    name  = "prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues"
    value = "false"
  }

  set {
    name  = "prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues"
    value = "false"
  }
}


# =============================================================================
# Loki — Log Aggregation
# =============================================================================

resource "helm_release" "loki" {
  count = var.loki_enabled ? 1 : 0

  name       = "loki"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "loki-stack"
  version    = "2.9.11"
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [
    templatefile("${path.module}/values/loki.yaml", {
      environment = var.environment
    })
  ]

  timeout = 600
}


# =============================================================================
# Jaeger — Distributed Tracing
# =============================================================================

resource "helm_release" "jaeger" {
  count = var.jaeger_enabled ? 1 : 0

  name       = "jaeger"
  repository = "https://jaegertracing.github.io/helm-charts"
  chart      = "jaeger"
  version    = "0.71.0"
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [
    templatefile("${path.module}/values/jaeger.yaml", {
      environment = var.environment
    })
  ]

  timeout = 600
}


# =============================================================================
# Kiali — Istio Service Mesh Observability
# =============================================================================

resource "helm_release" "kiali" {
  count = var.kiali_enabled ? 1 : 0

  name       = "kiali-server"
  repository = "https://kiali.org/helm-charts"
  chart      = "kiali-server"
  version    = "1.79.0"
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [
    templatefile("${path.module}/values/kiali.yaml", {
      environment = var.environment
    })
  ]

  timeout = 600

  depends_on = [
    helm_release.kube_prometheus_stack
  ]
}


# =============================================================================
# Grafana Dashboards
# =============================================================================
# Custom VibeStream dashboards:
#
# - Inference
# - Platform overview
# - PostgreSQL / RDS
# =============================================================================

resource "kubernetes_config_map" "grafana_dashboards" {
  metadata {
    name      = "grafana-custom-dashboards"
    namespace = kubernetes_namespace.monitoring.metadata[0].name

    labels = {
      grafana_dashboard = "1"
    }
  }

  data = {
    "vibestream-inference.json" = file(
      "${path.module}/dashboards/vibestream-inference.json"
    )

    "vibestream-overview.json" = file(
      "${path.module}/dashboards/vibestream-overview.json"
    )

    "vibestream-postgres.json" = file(
      "${path.module}/dashboards/vibestream-postgres.json"
    )
  }
}


# =============================================================================
# VibeStream Backend ServiceMonitor
# =============================================================================
# Allows Prometheus to scrape backend metrics from:
#
#   /metrics
#
# The backend Kubernetes Service must expose a port named "metrics".
# =============================================================================

resource "kubernetes_manifest" "backend_service_monitor" {
  manifest = {
    apiVersion = "monitoring.coreos.com/v1"
    kind       = "ServiceMonitor"

    metadata = {
      name      = "vibestream-backend"
      namespace = "vibestream-production"

      labels = {
        app       = "vibestream"
        component = "backend"
      }
    }

    spec = {
      selector = {
        matchLabels = {
          app       = "vibestream"
          component = "backend"
        }
      }

      endpoints = [
        {
          port     = "metrics"
          path     = "/metrics"
          interval = "30s"
        }
      ]
    }
  }

  depends_on = [
    helm_release.kube_prometheus_stack
  ]
}


# =============================================================================
# VibeStream Backend Prometheus Alerts
# =============================================================================

resource "kubernetes_manifest" "backend_alerts" {
  manifest = {
    apiVersion = "monitoring.coreos.com/v1"
    kind       = "PrometheusRule"

    metadata = {
      name      = "vibestream-backend-alerts"
      namespace = kubernetes_namespace.monitoring.metadata[0].name

      labels = {
        prometheus = "kube-prometheus"
      }
    }

    spec = {
      groups = [
        {
          name = "vibestream-backend"

          rules = [
            # -----------------------------------------------------------------
            # High HTTP Error Rate
            # -----------------------------------------------------------------

            {
              alert = "VibeStreamBackendHighErrorRate"

              expr = "rate(http_requests_total{job=\"vibestream-backend\",status=~\"5..\"}[5m]) > 0.05"

              for = "5m"

              labels = {
                severity = "critical"
              }

              annotations = {
                summary = "High VibeStream backend error rate detected"

                description = "The VibeStream backend HTTP 5xx error rate has exceeded the configured threshold for the last 5 minutes."
              }
            },


            # -----------------------------------------------------------------
            # High Request Latency
            # -----------------------------------------------------------------

            {
              alert = "VibeStreamBackendHighLatency"

              expr = "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 2"

              for = "5m"

              labels = {
                severity = "warning"
              }

              annotations = {
                summary = "High VibeStream backend latency detected"

                description = "The VibeStream backend P95 request latency has exceeded 2 seconds for the last 5 minutes."
              }
            },


            # -----------------------------------------------------------------
            # Pod Crash Loop
            # -----------------------------------------------------------------

            {
              alert = "VibeStreamBackendPodCrashLooping"

              expr = "rate(kube_pod_container_status_restarts_total{namespace=\"vibestream-production\"}[15m]) > 0"

              for = "5m"

              labels = {
                severity = "critical"
              }

              annotations = {
                summary = "VibeStream backend pod is crash looping"

                description = "A VibeStream backend pod in the production namespace is repeatedly restarting."
              }
            },


            # -----------------------------------------------------------------
            # High Memory Usage
            # -----------------------------------------------------------------

            {
              alert = "VibeStreamBackendHighMemoryUsage"

              expr = "container_memory_usage_bytes{namespace=\"vibestream-production\"} / container_spec_memory_limit_bytes{namespace=\"vibestream-production\"} > 0.9"

              for = "5m"

              labels = {
                severity = "warning"
              }

              annotations = {
                summary = "High VibeStream backend memory usage"

                description = "A VibeStream backend container is using more than 90% of its configured memory limit."
              }
            },


            # -----------------------------------------------------------------
            # High CPU Usage
            # -----------------------------------------------------------------

            {
              alert = "VibeStreamBackendHighCPUUsage"

              expr = "rate(container_cpu_usage_seconds_total{namespace=\"vibestream-production\"}[5m]) > 0.8"

              for = "10m"

              labels = {
                severity = "warning"
              }

              annotations = {
                summary = "High VibeStream backend CPU usage"

                description = "A VibeStream backend container is consuming high CPU for the configured evaluation period."
              }
            }
          ]
        }
      ]
    }
  }

  depends_on = [
    helm_release.kube_prometheus_stack
  ]
}