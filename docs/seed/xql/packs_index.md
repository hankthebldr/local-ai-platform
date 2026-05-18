<!--
-->

# XQL/XDM corpus — pack index

Auto-derived from `docs/seed/xql/packs/`. Pattern family is heuristic, based on dominant XQL idiom in `datamodel.xql`.

| Pack | Vendor | Product | Dataset | Pattern | Kind | Lines |
|---|---|---|---|---|---|---|
| `apache_tomcat_brokenbank` | ? | ? | `apache_tomcat_raw` | **C** | DM | 102 |
| `aws_guardduty` | ? | ? | `aws_guardduty_generic_alert_raw` | **D** | DM | 387 |
| `cisco_wsa_access_log` | ? | ? | `cisco_websecurityappliance_raw` | **B** | DM | 125 |
| `efficientip_ddi` | ? | ? | `efficientip_raw` | **B** | DM | 638 |
| `extrahop_revealx` | ? | ? | `extrahop_revealx_raw` | **B** | DM | 367 |
| `gocortex_bbwaf` | ? | ? | `gocortex_bbwaf_raw` | **A** | DM | 133 |
| `gocortex_brokenbank_auth` | ? | ? | `gocortex_brokenbank_raw` | **A** | DM | 89 |
| `gocortex_concierge` | ? | ? | `gocortex_concierge_raw` | **A** | DM | 153 |
| `imperva_account_takeover` | ? | ? | `imperva_accounttakeover_raw` | **A** | DM | 103 |
| `imperva_audit_trail` | ? | ? | `imperva_audittrail_raw` | **A** | DM | 94 |
| `microsoft_defender_cloud_apps_alerts` | ? | ? | `microsoftcloudappsecurity_generic_alert_raw` | **A** | DM | 171 |
| `mimecast_siem` | ? | ? | `mimecast_siem_raw` | **A** | DM | 97 |
| `somansa_webkeeper` | ? | ? | `somansa_webkeeper_raw` | **B** | DM | 166 |
| `symantec_endpoint_protection` | ? | ? | `symantec_ep_raw` | **C** | DM | 521 |
| `trend_micro_vision_one_detections` | ? | ? | `trend_micro_vision_one_gc_raw` | **A** | DM | 241 |
| `trend_micro_vision_one_endpoint_activity` | ? | ? | `trend_micro_vision_one_gc_raw` | **A** | DM | 275 |
| `universal_intel_hunt_template` | ? | ? | `hunt` | **-** | Hunt | 294 |

## Pattern family heuristic counts

| Pack | A (json_extract_scalar) | B (arrayindex/split) | C (regextract) | D (arrow) |
|---|---|---|---|---|
| `apache_tomcat_brokenbank` | 0 | 8 | 10 | 0 |
| `aws_guardduty` | 0 | 2 | 0 | 116 |
| `cisco_wsa_access_log` | 0 | 29 | 9 | 0 |
| `efficientip_ddi` | 0 | 68 | 68 | 0 |
| `extrahop_revealx` | 0 | 12 | 0 | 0 |
| `gocortex_bbwaf` | 11 | 0 | 0 | 0 |
| `gocortex_brokenbank_auth` | 9 | 0 | 0 | 0 |
| `gocortex_concierge` | 14 | 0 | 0 | 0 |
| `imperva_account_takeover` | 18 | 0 | 0 | 0 |
| `imperva_audit_trail` | 13 | 4 | 0 | 0 |
| `microsoft_defender_cloud_apps_alerts` | 9 | 5 | 0 | 0 |
| `mimecast_siem` | 0 | 0 | 0 | 0 |
| `somansa_webkeeper` | 0 | 25 | 4 | 0 |
| `symantec_endpoint_protection` | 0 | 72 | 74 | 0 |
| `trend_micro_vision_one_detections` | 14 | 3 | 2 | 0 |
| `trend_micro_vision_one_endpoint_activity` | 4 | 4 | 0 | 0 |
| `universal_intel_hunt_template` | 0 | 0 | 0 | 0 |

## Canonical few-shot exemplars

See `docs/seed/xql/few_shot_examples.json` for full input/output exemplars.

- **Pattern A** (json_extract_scalar) — `packs/imperva_account_takeover/`
- **Pattern B** (split + arrayindex) — `packs/cisco_wsa_access_log/`
- **Pattern C** (regextract) — `packs/efficientip_ddi/`
- **Pattern D** (arrow operator) — `packs/aws_guardduty/`
