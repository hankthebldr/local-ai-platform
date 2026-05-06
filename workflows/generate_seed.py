#!/usr/bin/env python3
"""
Seed Data Generator — Creates realistic seed payloads for XSIAM workflow testing.

Reads mock log files from workflows/mock_data/ and packages them into
JSON seed objects ready for workflow execution.

Usage:
    python workflows/generate_seed.py --source panos     > seed_panos.json
    python workflows/generate_seed.py --source windows   > seed_windows.json
    python workflows/generate_seed.py --source okta      > seed_okta.json
    python workflows/generate_seed.py --source all       > seed_all.json

    # Pipe directly into workflow CLI:
    python cli/workflow.py run workflows/xsiam-normalization-pipeline.yaml \
      --seed "$(python workflows/generate_seed.py --source panos)"
"""

import argparse
import json
import os
import sys

MOCK_DIR = os.path.join(os.path.dirname(__file__), "mock_data")


# ── Source Definitions ────────────────────────────────────────────────────

SOURCES = {
    "panos": {
        "vendor_name": "Palo Alto Networks",
        "product_name": "PAN-OS Firewall",
        "log_type": "TRAFFIC",
        "log_format": "csv_syslog",
        "log_file": "panos_traffic.log",
        "ingestion_method": "syslog_tcp",
        "xdm_dataset": "palo_alto_networks_firewall_raw",
        "constraints": "XDM v3, TRAFFIC logs only (not THREAT/URL/SYSTEM), field positions are 0-indexed CSV",
        "expected_event_types": ["NETWORK"],
        "expected_xdm_fields": [
            "xdm.event.type", "xdm.event.outcome", "xdm.event.original_event_type",
            "xdm.source.ipv4", "xdm.source.port", "xdm.source.zone", "xdm.source.user.username",
            "xdm.source.sent_bytes", "xdm.source.sent_packets",
            "xdm.target.ipv4", "xdm.target.port", "xdm.target.zone",
            "xdm.target.sent_bytes", "xdm.target.sent_packets",
            "xdm.network.session_id", "xdm.network.rule", "xdm.network.application_protocol",
            "xdm.network.ip_protocol",
            "xdm.observer.vendor", "xdm.observer.product", "xdm.observer.unique_identifier",
        ],
        "enum_mappings": {
            "xdm.event.outcome": {"allow": "SUCCESS", "deny": "FAILURE", "drop": "FAILURE", "reset-both": "FAILURE"},
            "xdm.network.ip_protocol": "uppercase(protocol)",
        },
        "stitching_keys": ["session_id", "source_ip+destination_ip+source_port+destination_port+protocol"],
        "detection_use_cases": [
            "Outbound traffic to known-bad IPs",
            "Denied RDP (3389) from DMZ to Datacenter",
            "High-volume data exfiltration (bytes_sent > threshold)",
            "Lateral movement via SMB (445) between internal zones",
            "Tor exit node traffic (185.220.x.x)",
        ],
        "mitre_techniques": ["T1071.001", "T1021.001", "T1048.003", "T1090.003"],
    },
    "windows": {
        "vendor_name": "Microsoft",
        "product_name": "Windows Security",
        "log_type": "Security Event Log",
        "log_format": "xml_evtx",
        "log_file": "windows_security.xml",
        "ingestion_method": "xdr_agent",
        "xdm_dataset": "microsoft_windows_raw",
        "constraints": "XDM v3, events 4624/4625/4688 only, XML via Cortex XDR agent",
        "expected_event_types": ["AUTHENTICATION", "PROCESS"],
        "expected_xdm_fields": [
            "xdm.event.type", "xdm.event.id", "xdm.event.outcome", "xdm.event.description",
            "xdm.source.ipv4", "xdm.source.port", "xdm.source.host.hostname",
            "xdm.source.user.username", "xdm.source.user.domain",
            "xdm.source.process.name", "xdm.source.process.pid",
            "xdm.target.user.username", "xdm.target.user.domain", "xdm.target.user.identifier",
            "xdm.target.host.hostname",
            "xdm.target.process.name", "xdm.target.process.command_line",
            "xdm.auth.auth_method",
            "xdm.observer.vendor", "xdm.observer.product", "xdm.observer.name",
        ],
        "enum_mappings": {
            "xdm.event.outcome": {"4624": "SUCCESS", "4625": "FAILURE"},
            "xdm.event.type": {"4624": "AUTHENTICATION", "4625": "AUTHENTICATION", "4688": "PROCESS"},
            "xdm.auth.auth_method": {
                "2": "INTERACTIVE", "3": "NETWORK", "4": "BATCH", "5": "SERVICE",
                "7": "UNLOCK", "8": "NETWORK_CLEARTEXT", "9": "NEW_CREDENTIALS",
                "10": "REMOTE_INTERACTIVE", "11": "CACHED_INTERACTIVE",
            },
        },
        "stitching_keys": ["TargetUserSid", "TargetLogonId", "IpAddress+WorkstationName"],
        "detection_use_cases": [
            "Brute force (>10 4625 events from same IP in 10 min)",
            "Successful login after brute force (4625s then 4624 from same IP)",
            "Lateral movement via RDP (LogonType=10 from internal IP to multiple hosts)",
            "Suspicious process creation (cmd/powershell spawned by Office app)",
            "Pass-the-hash (LogonType=3 with NTLM from unusual workstation)",
        ],
        "mitre_techniques": ["T1110.001", "T1021.001", "T1059.001", "T1550.002"],
    },
    "okta": {
        "vendor_name": "Okta",
        "product_name": "Identity Cloud",
        "log_type": "System Log",
        "log_format": "json_api",
        "log_file": "okta_system_log.json",
        "ingestion_method": "http_collector",
        "xdm_dataset": "okta_raw",
        "constraints": "XDM v3, System Log API v1, session/auth/MFA events",
        "expected_event_types": ["AUTHENTICATION"],
        "expected_xdm_fields": [
            "xdm.event.type", "xdm.event.id", "xdm.event.outcome", "xdm.event.description",
            "xdm.event.original_event_type",
            "xdm.source.ipv4", "xdm.source.user.username", "xdm.source.user.identifier",
            "xdm.source.host.os",
            "xdm.target.user.username", "xdm.target.user.identifier",
            "xdm.target.resource.type", "xdm.target.resource.name",
            "xdm.auth.auth_method", "xdm.auth.mfa.method", "xdm.auth.mfa.is_successful",
            "xdm.network.http.browser",
            "xdm.observer.vendor", "xdm.observer.product",
        ],
        "enum_mappings": {
            "xdm.event.outcome": "direct_map (Okta uses SUCCESS/FAILURE/SKIPPED natively)",
            "xdm.auth.mfa.is_successful": "conditional on eventType contains 'mfa' AND outcome.result",
        },
        "stitching_keys": ["actor.id", "client.ipAddress", "authenticationContext.externalSessionId"],
        "detection_use_cases": [
            "Brute force (multiple FAILURE outcomes from same IP)",
            "Account lockout (user.account.lock event)",
            "MFA fatigue attack (many MFA push events in short window)",
            "Impossible travel (same user, different geolocations within threshold)",
            "Credential stuffing (many FAILURE outcomes for different users from same IP)",
        ],
        "mitre_techniques": ["T1110.004", "T1621", "T1078.004"],
    },
}


def load_log_samples(source_key: str) -> str:
    """Load raw log file content"""
    source = SOURCES[source_key]
    log_path = os.path.join(MOCK_DIR, source["log_file"])
    if not os.path.exists(log_path):
        return f"[mock data file not found: {log_path}]"
    with open(log_path) as f:
        return f.read().strip()


def generate_seed(source_key: str) -> dict:
    """Generate a complete seed payload for a single log source"""
    source = SOURCES[source_key]
    return {
        "vendor_name": source["vendor_name"],
        "product_name": source["product_name"],
        "log_type": source["log_type"],
        "log_format": source["log_format"],
        "log_samples": load_log_samples(source_key),
        "ingestion_method": source["ingestion_method"],
        "xdm_dataset": source["xdm_dataset"],
        "constraints": source["constraints"],
        "expected_event_types": source["expected_event_types"],
        "expected_xdm_fields": source["expected_xdm_fields"],
        "known_enum_mappings": source["enum_mappings"],
        "stitching_keys": source["stitching_keys"],
        "detection_use_cases": source["detection_use_cases"],
        "mitre_techniques": source["mitre_techniques"],
    }


def generate_multi_source_seed() -> dict:
    """Generate a combined seed for multi-source normalization"""
    return {
        "sources": [generate_seed(k) for k in SOURCES],
        "environment": {
            "xdm_version": "v3",
            "deployment": "Cortex XSIAM",
            "timezone": "UTC",
            "retention_days": 90,
        },
        "correlation_requirements": [
            "Cross-source brute force detection (firewall + Windows + Okta auth failures)",
            "Lateral movement chain (Okta login → firewall traffic → Windows RDP logon)",
            "Credential compromise (Okta failure → Windows 4625 → Windows 4624 success)",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Generate XSIAM workflow seed data")
    parser.add_argument(
        "--source",
        choices=list(SOURCES.keys()) + ["all"],
        default="panos",
        help="Log source to generate seed for (default: panos)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        default=True,
        help="Pretty-print JSON output (default: true)",
    )
    args = parser.parse_args()

    if args.source == "all":
        seed = generate_multi_source_seed()
    else:
        seed = generate_seed(args.source)

    indent = 2 if args.pretty else None
    json.dump(seed, sys.stdout, indent=indent, default=str)
    print()


if __name__ == "__main__":
    main()
