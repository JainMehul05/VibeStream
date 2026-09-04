# vibestream-backend Helm chart

Production-grade Helm chart for the VibeStream Django backend. Supports
blue/green deployment, HPA, PDB, ingress (cert-manager + ingress-nginx),
network policies, custom-metric autoscaling, and ServiceMonitor +
PrometheusRule out-of-the-box.

## Install

```bash
helm upgrade --install VibeStream . \
  --namespace=VibeStream --create-namespace \
  --set image.tag=$(git rev-parse --short HEAD)
```

## Values

Every knob lives in [`values.yaml`](values.yaml). Highlights:

| Key                              | Default                              | Notes                                         |
| -------------------------------- | ------------------------------------ | --------------------------------------------- |
| `image.repository`               | `VibeStream/backend`                    | Override with your registry path              |
| `image.tag`                      | `latest`                             | Pass git SHA in CI                            |
| `replicaCount`                   | `3`                                  | Initial replica count                         |
| `blueGreen.enabled`              | `true`                               | Spin both color Deployments side-by-side      |
| `blueGreen.activeEnvironment`    | `blue`                               | Flip to `green` to swap traffic               |
| `autoscaling.enabled`            | `true`                               | HPA min 3 / max 15, CPU 70 % / mem 80 %        |
| `podDisruptionBudget.minAvailable` | `2`                                | Survives single-AZ outage                     |
| `service.port`                   | `8000`                               | Container port                                |
| `ingress.enabled`                | `true`                               | Creates an ingress-nginx Ingress              |
| `ingress.hosts[0].host`          | `api.VibeStream.com`                    | Replace with your hostname                    |
| `configMap.data`                 | `{NODE_ENV, LOG_LEVEL, DB_HOST, …}`  | Non-secret env                                |
| `secrets.create`                 | `true`                               | Pair with External Secrets in prod            |
| `networkPolicy.enabled`          | `true`                               | Deny by default, allow ingress + egress       |

## Blue/green flip

```bash
# Spin both colors (default).
helm upgrade --install VibeStream . \
  --set blueGreen.enabled=true \
  --set blueGreen.activeEnvironment=blue \
  --set image.tag=v1

# Stage v2 on green.
helm upgrade VibeStream . \
  --reuse-values \
  --set image.tag=v2 \
  --set blueGreen.activeEnvironment=blue \
  --set blueGreen.keepInactive=true

# Flip traffic to green.
helm upgrade VibeStream . \
  --reuse-values \
  --set blueGreen.activeEnvironment=green

# Roll back if anything is off.
helm upgrade VibeStream . \
  --reuse-values \
  --set blueGreen.activeEnvironment=blue
```

## Renders

```bash
helm template VibeStream . | kubectl apply --dry-run=client -f -
```

Produces:

* `Deployment/VibeStream-vibestream-backend-blue`
* `Deployment/VibeStream-vibestream-backend-green`
* `Service/VibeStream-vibestream-backend` (selects `color=<active>`)
* `ServiceAccount/vibestream-backend-sa`
* `ConfigMap/VibeStream-vibestream-backend-config`
* `HorizontalPodAutoscaler/VibeStream-vibestream-backend`
* `PodDisruptionBudget/VibeStream-vibestream-backend`
* `Ingress/VibeStream-vibestream-backend`
* `NetworkPolicy/VibeStream-vibestream-backend`
