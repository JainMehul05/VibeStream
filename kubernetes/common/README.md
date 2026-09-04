# Shared Kubernetes resources

Cluster-wide resources used by every VibeStream deployment (dev / staging /
production). Apply these before the per-app manifests in the parent
`kubernetes/` directory.

```
common/
├── namespace.yaml          VibeStream + VibeStream-staging namespaces w/ PSA labels
├── networkpolicy.yaml      default-deny + explicit allow lists
├── ingress.yaml            ingress-nginx + cert-manager (Let's Encrypt) routes
└── serviceaccount.yaml     non-mounted SAs for frontend + backend (IRSA-ready)
```

## Apply order

```bash
kubectl apply -f common/namespace.yaml
kubectl apply -f common/serviceaccount.yaml -n VibeStream
kubectl apply -f common/networkpolicy.yaml -n VibeStream
kubectl apply -f common/ingress.yaml -n VibeStream
```

## Pre-flight

* Ingress requires an installed `ingress-nginx` controller and a
  `cert-manager` ClusterIssuer named `letsencrypt-prod`.
* Network policies require a CNI that supports them (Calico, Cilium, or
  AWS VPC CNI with the policy add-on enabled).
* Pod Security Admission labels on the namespace enforce the
  `restricted` profile — pods must drop all capabilities, run as
  non-root and have read-only root filesystems. The shipping manifests
  in this repo already comply.

## Notes

* Change `VibeStream.example.com` / `api.VibeStream.example.com` to your real
  hostnames in `ingress.yaml`.
* For EKS + IRSA, uncomment and set `eks.amazonaws.com/role-arn` on the
  backend ServiceAccount.
