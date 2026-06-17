# Enclave on k3s

The k3s port of the `docker-compose.bd790i.yml` stack: the Cortex Console
(`enclave-api`) plus its vLLM GPU backend (`enclave-vllm`), running in the
homelab cluster instead of as host containers.

## Topology

```
            Traefik ingress  (enclave.lab.local)
                    │
                    ▼
        ┌──────────────────────┐        ┌──────────────────────────┐
        │  enclave-api  :8001   │ ─────▶ │  enclave-vllm  :8000      │
        │  (Console + REST)     │  HTTP  │  Qwen3-8B-NVFP4           │
        │  runtimeClass nvidia  │        │  limits.nvidia.com/gpu: 1 │
        │  utility (NVML only)  │        │  runtimeClass nvidia      │
        └──────────────────────┘        └──────────────────────────┘
                    │                              │
        hostPath /app/data                 hostPath /models
        (enclave-bd790i-data)              (enclave-vllm-models)
```

Both pods are pinned to **bd790i** (`nodeSelector: nvidia.com/gpu.present`):
it is the only GPU node, holds the locally-imported `enclave-api` image, and
holds the reused docker-volume data dirs.

## Prerequisites

1. GPU schedulable on bd790i — done via `dot-files/config/k3s/gpu`
   (RuntimeClass `nvidia` + device plugin; `nvidia.com/gpu: 1` advertised).
2. The API image present in bd790i's containerd (it was never pushed to a
   registry — it's a local compose build):

   ```bash
   docker save enclave-api:bd790i | sudo k3s ctr images import -
   # verify:
   sudo k3s ctr images ls | grep enclave-api
   ```

## Deploy

```bash
kubectl apply -f deploy/k3s/
kubectl -n enclave rollout status deploy/enclave-vllm   # first start loads the model
kubectl -n enclave rollout status deploy/enclave-api
```

## Access

Add a DNS record so `enclave.lab.local` → a Traefik node IP (e.g. Pi-hole
`address=/enclave.lab.local/192.168.1.109`), then open
<http://enclave.lab.local>. Admin auto-sign-in uses the baked dev key; rotate
via `/api/keys` before exposing beyond the LAN.

Quick check without DNS:

```bash
kubectl -n enclave port-forward svc/enclave-api 8001:8001
curl -s localhost:8001/health
```

## Notes / caveats

- **One GPU unit.** vLLM holds it; the API gets NVML visibility only. Don't add
  `nvidia.com/gpu` to the API or it won't schedule.
- **Ollama fallback** points at `192.168.1.104:11434` but host Ollama binds
  loopback only — set `Environment=OLLAMA_HOST=0.0.0.0:11434` on the host
  `ollama.service` to make the fallback reachable from the pod. vLLM is primary.
- **Data reuse via hostPath** ties the pods to bd790i. To go node-agnostic
  later, copy the volume dirs into `local-path` PVCs and swap the `hostPath`
  volumes for `persistentVolumeClaim`s.
- **Re-importing the image** after a rebuild: `docker save … | sudo k3s ctr
  images import -`, then `kubectl -n enclave rollout restart deploy/enclave-api`.
