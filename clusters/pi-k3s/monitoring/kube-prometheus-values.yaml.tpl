# kube-prometheus-stack values for Raspberry Pi 5
# Tuned for limited resources
# NOTE: This is a template file - use `op inject` to render with secrets

# Grafana settings
grafana:
  adminPassword: "op://pi-cluster/grafana/password"
  persistence:
    enabled: true
    size: 1Gi
    storageClassName: local-path
  resources:
    requests:
      cpu: 50m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi
  # Use hostNetwork for easy access
  service:
    type: ClusterIP
    port: 3000

# Prometheus settings
prometheus:
  prometheusSpec:
    retention: 7d
    retentionSize: 2GB
    resources:
      requests:
        cpu: 100m
        memory: 256Mi
      limits:
        cpu: 1000m
        memory: 1Gi
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: local-path
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 5Gi

# Alertmanager - disable for now (can enable later)
alertmanager:
  enabled: false

# Node exporter - lightweight, keep enabled
nodeExporter:
  resources:
    requests:
      cpu: 10m
      memory: 32Mi
    limits:
      cpu: 100m
      memory: 64Mi

# Kube-state-metrics
kubeStateMetrics:
  resources:
    requests:
      cpu: 10m
      memory: 32Mi
    limits:
      cpu: 100m
      memory: 128Mi

# Prometheus operator
prometheusOperator:
  resources:
    requests:
      cpu: 50m
      memory: 64Mi
    limits:
      cpu: 200m
      memory: 256Mi

# Disable components not needed for single-node learning cluster
kubeEtcd:
  enabled: false
kubeScheduler:
  enabled: false
kubeControllerManager:
  enabled: false
kubeProxy:
  enabled: false
