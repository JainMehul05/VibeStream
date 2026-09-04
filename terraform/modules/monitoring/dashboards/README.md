# Grafana dashboards

Each `*.json` file in this directory is a Grafana dashboard exported via
`Dashboard settings → JSON Model`. The monitoring module mounts them
into the Grafana ConfigMap so they appear under the **VibeStream** folder
on next reconciliation.

## Files

| File                  | What it shows                                                  |
| --------------------- | -------------------------------------------------------------- |
| `VibeStream-overview.json` | RED metrics (request rate, error rate, duration) per service  |
| `VibeStream-inference.json` | Modal inference latency, cold-start frequency, degraded rate |
| `VibeStream-postgres.json`  | RDS CPU, connections, free storage, replication lag           |

## Adding a new dashboard

1. Build it in Grafana → export JSON.
2. Drop the JSON file in this directory.
3. `terraform apply` — the monitoring module re-mounts the ConfigMap
   and Grafana auto-discovers.

## Common variables

Every VibeStream dashboard expects these template variables (declared in
the JSON):

| Variable        | Source                                                 |
| --------------- | ------------------------------------------------------ |
| `$datasource`   | Prometheus data source                                 |
| `$namespace`    | label selector on `kube_pod_info.namespace`            |
| `$service`      | label selector on `app.kubernetes.io/name`             |
| `$interval`     | rate window (`$__rate_interval` recommended)            |
