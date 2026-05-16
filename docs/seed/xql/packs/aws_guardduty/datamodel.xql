// AWS GuardDuty -- XDM Data Model Rule
// Dataset: aws_guardduty_generic_alert_raw
// Vendor: Amazon | Product: GuardDuty
//
// Maps AWS GuardDuty findings to the Cortex XDM schema across all six
// action types (AWS_API_CALL, NETWORK_CONNECTION, DNS_REQUEST,
// KUBERNETES_API_CALL, PORT_PROBE, RDS_LOGIN_ATTEMPT) plus actionless
// findings (AttackSequence, MalwareProtection).
//
// Documentation: aws_guardduty_xdm_model_rule_documentation.md
//
// SPDX-FileCopyrightText: GoCortexIO
// SPDX-License-Identifier: AGPL-3.0-or-later

[MODEL: dataset = aws_guardduty_generic_alert_raw ]

// -- Stage 1: Initialise root-level aliases ---------------------------------
// Normalise the Resource and Service JSON objects to support both PascalCase
// and camelCase field naming conventions from the XSIAM parser.
alter
    finding_resource = coalesce(Resource, resource),
    finding_service = coalesce(Service, service)

// -- Stage 2: Extract action-specific sub-objects ---------------------------
| alter
    finding_process = coalesce(finding_service -> RuntimeDetails.Process{}, finding_service -> runtimeDetails.process{}),
    finding_runtime_context = coalesce(finding_service -> RuntimeDetails.Context{}, finding_service -> runtimeDetails.context{}),
    finding_network = coalesce(finding_service -> Action.NetworkConnectionAction{}, finding_service -> action.networkConnectionAction{}),
    finding_aws_api = coalesce(finding_service -> Action.AwsApiCallAction{}, finding_service -> action.awsApiCallAction{}),
    finding_k8s_api = coalesce(finding_service -> Action.KubernetesApiCallAction{}, finding_service -> action.kubernetesApiCallAction{}),
    finding_rds_login = coalesce(finding_service -> Action.RdsLoginAttemptAction{}, finding_service -> action.rdsLoginAttemptAction{})

// -- Stage 3: Extract common finding and resource fields --------------------
// Ref: https://docs.aws.amazon.com/guardduty/latest/APIReference/API_Finding.html
// Ref: https://docs.aws.amazon.com/guardduty/latest/APIReference/API_Resource.html
| alter
    // Core finding identifiers
    finding_account_id = coalesce(AccountId, accountId), // The AWS account ID in which the finding was generated.
    finding_arn = coalesce(Arn, arn), // The Amazon Resource Name (ARN) of the finding.
    finding_description = coalesce(Description, description), // The description of the finding.
    finding_id = coalesce(Id, id), // The unique identifier of the finding.
    finding_region = coalesce(Region, region), // The AWS Region where the finding was generated.
    finding_severity = to_float(coalesce(Severity, severity)), // The severity of the finding (1.0-10.0).
    // Keep-in-both anchor: parser.xql stamps `_severity_band` at ingest with
    // the same 3-value bucket (LOW 1.0-3.9, MEDIUM 4.0-6.9, HIGH 7.0-8.9;
    // Critical >=9.0 stays NULL). Parser-stamped rows short-circuit through
    // the column read; legacy / replayed / backfilled rows fall through to
    // the bucketing if-chain below. The MODEL itself drives xdm.alert.severity
    // off the numeric Severity float (which has its own four-band vocabulary
    // including Critical), so this column exists for symmetry with the parser
    // and for downstream consumers that want the bucketed string.
    finding_severity_band = coalesce(
        _severity_band,
        if(to_float(coalesce(Severity, severity)) < 4.0, "LOW",
           to_float(coalesce(Severity, severity)) < 7.0, "MEDIUM",
           to_float(coalesce(Severity, severity)) < 9.0, "HIGH")),
    finding_title = coalesce(Title, title), // The title of the finding.
    finding_type = coalesce(Type, type), // The type of finding (e.g. Recon:EC2/PortProbeEMRUnprotectedPort).

    // Resource metadata
    // Ref: https://docs.aws.amazon.com/guardduty/latest/APIReference/API_Resource.html
    resource_type = coalesce(finding_resource -> ResourceType, finding_resource -> resourceType), // The type of AWS resource (Instance, AccessKey, S3Bucket, EKSCluster, etc.).
    resource_instance_id = coalesce(finding_resource -> InstanceDetails.InstanceId, finding_resource -> instanceDetails.instanceId), // The EC2 instance ID.
    resource_instance_type = coalesce(finding_resource -> InstanceDetails.InstanceType, finding_resource -> instanceDetails.instanceType), // The EC2 instance type (e.g. m5.xlarge).
    resource_username = coalesce(
        finding_resource -> RdsDbUserDetails.User, finding_resource -> rdsDbUserDetails.user, // The database user name used in the anomalous login attempt.
        finding_resource -> AccessKeyDetails.UserName, finding_resource -> accessKeyDetails.userName, // The IAM user name.
        finding_resource -> KubernetesDetails.KubernetesUserDetails.Username, finding_resource -> kubernetesDetails.kubernetesUserDetails.username), // The Kubernetes user name.
    resource_user_id = coalesce(
        finding_resource -> AccessKeyDetails.PrincipalId, finding_resource -> accessKeyDetails.principalId, // The IAM principal ID.
        finding_resource -> KubernetesDetails.KubernetesUserDetails.Uid, finding_resource -> kubernetesDetails.kubernetesUserDetails.uid), // The Kubernetes user UID.
    resource_user_type = coalesce(finding_resource -> AccessKeyDetails.UserType, finding_resource -> accessKeyDetails.userType), // The IAM user type (Root, IAMUser, AssumedRole, etc.).
    resource_user_groups = coalesce(finding_resource -> KubernetesDetails.KubernetesUserDetails.Groups[], finding_resource -> kubernetesDetails.kubernetesUserDetails.groups[]), // The Kubernetes user groups.
    resource_access_key_id = coalesce(finding_resource -> AccessKeyDetails.AccessKeyId, finding_resource -> accessKeyDetails.accessKeyId), // The IAM access key credential identifier (e.g. ASIA5X6DQURZH7S5HCEM).
    resource_iam_instance_profile_arn = coalesce(finding_resource -> InstanceDetails.IamInstanceProfile.Arn, finding_resource -> instanceDetails.iamInstanceProfile.arn), // The IAM instance profile ARN for assumed roles.
    resource_k8s_namespace = coalesce( // The Kubernetes namespace (organisational unit).
        finding_resource -> KubernetesDetails.KubernetesWorkloadDetails.Namespace, finding_resource -> kubernetesDetails.kubernetesWorkloadDetails.namespace),
    resource_k8s_service_account_name = coalesce( // The Kubernetes service account name used by the workload.
        finding_resource -> KubernetesDetails.KubernetesWorkloadDetails.ServiceAccountName, finding_resource -> kubernetesDetails.kubernetesWorkloadDetails.serviceAccountName),
    resource_k8s_workload_type = coalesce( // The Kubernetes workload type (e.g. pods, deployments).
        finding_resource -> KubernetesDetails.KubernetesWorkloadDetails.Type, finding_resource -> kubernetesDetails.kubernetesWorkloadDetails.type),
    resource_rds_db_instance_arn = coalesce( // The ARN of the target RDS database instance.
        finding_resource -> RdsDbInstanceDetails.DbInstanceArn, finding_resource -> rdsDbInstanceDetails.dbInstanceArn),
    resource_rds_db_instance_id = coalesce( // The identifier of the target RDS database instance.
        finding_resource -> RdsDbInstanceDetails.DbInstanceIdentifier, finding_resource -> rdsDbInstanceDetails.dbInstanceIdentifier),
    resource_rdsDbUserDetails_auth_method = coalesce(finding_resource -> RdsDbUserDetails.AuthMethod, finding_resource -> rdsDbUserDetails.authMethod), // The RDS authentication method used.
    resource_rdsDbUserDetails_application = coalesce(finding_resource -> RdsDbUserDetails.Application, finding_resource -> rdsDbUserDetails.application), // The application name used in the RDS login attempt.
    resource_availability_zone = coalesce( // The Availability Zone of the affected resource.
        finding_resource -> InstanceDetails.AvailabilityZone, finding_resource -> instanceDetails.availabilityZone,
        finding_resource -> EcsClusterDetails.InstanceDetails.AvailabilityZone, finding_resource -> ecsClusterDetails.instanceDetails.availabilityZone,
        finding_resource -> EksClusterDetails.InstanceDetails.AvailabilityZone, finding_resource -> eksClusterDetails.instanceDetails.availabilityZone),
    resource_name = coalesce( // The name or identifier of the affected resource, prioritised by resource type.
        finding_resource -> LambdaDetails.FunctionName, finding_resource -> lambdaDetails.functionName, // Lambda function name
        finding_resource -> ContainerDetails.Name, finding_resource -> containerDetails.name, // Container name
        finding_resource -> RdsDbUserDetails.Database, finding_resource -> rdsDbUserDetails.database, // RDS database name
        finding_resource -> EcsClusterDetails.Name, finding_resource -> ecsClusterDetails.name, // ECS cluster name
        finding_resource -> EksClusterDetails.Name, finding_resource -> eksClusterDetails.name, // EKS cluster name
        finding_resource -> InstanceDetails.InstanceId, finding_resource -> instanceDetails.instanceId, // EC2 instance ID (fallback)
        finding_resource -> AccessKeyDetails.UserName, finding_resource -> accessKeyDetails.userName, // IAM user name (fallback)
        arraystring(arraymap(coalesce(finding_resource -> S3BucketDetails[], finding_resource -> s3BucketDetails[]), coalesce("@element" -> Name, "@element" -> name)), ",")), // S3 bucket name(s)

    // Service metadata
    // Ref: https://docs.aws.amazon.com/guardduty/latest/APIReference/API_Service.html
    // Keep-in-both anchor: parser.xql stamps `_action_type` at ingest with
    // the same 8-value vocabulary derived below. See
    // PRIVATE_DOCS/anchor_field_design.md "Defence in depth". Parser-stamped
    // rows short-circuit through the column read; legacy / replayed /
    // backfilled rows fall through to the original PascalCase/camelCase
    // coalesce plus the AttackSequence + MalwareProtection fallbacks for
    // actionless findings.
    service_action_type = coalesce(
        _action_type,
        finding_service -> Action.ActionType, finding_service -> action.actionType, // The GuardDuty finding activity type (AWS_API_CALL, NETWORK_CONNECTION, etc.).
        if(coalesce(Type, type) ~= "^AttackSequence", "AttackSequence"), // Actionless: derived from the finding Type prefix.
        if(coalesce(finding_service -> FeatureName, finding_service -> featureName) ~= "(?i)Malware", "MalwareProtection")), // Actionless: derived from the GuardDuty FeatureName.
    service_detector_id = coalesce(finding_service -> DetectorId, finding_service -> detectorId), // The GuardDuty detector ID.
    service_evidence_threat_intelligence_details = coalesce(finding_service -> Evidence.ThreatIntelligenceDetails[], finding_service -> evidence.threatIntelligenceDetails[]), // Threat intelligence details.

    // Runtime process details (present for Runtime Monitoring findings)
    // Ref: https://docs.aws.amazon.com/guardduty/latest/APIReference/API_ProcessDetails.html
    service_runtime_details_process_pid = to_integer(coalesce(finding_process -> Pid, finding_process -> pid)), // The operating system process ID.
    service_runtime_details_process_uuid = coalesce(finding_process -> Uuid, finding_process -> uuid), // The unique process ID assigned by GuardDuty.
    service_runtime_details_process_parent_uuid = coalesce(finding_process -> ParentUuid, finding_process -> parentUuid), // The unique parent process ID assigned by GuardDuty.
    service_runtime_details_process_name = coalesce(finding_process -> Name, finding_process -> name), // The process name.
    service_runtime_details_process_executable_path = coalesce(finding_process -> ExecutablePath, finding_process -> executablePath), // The absolute path of the process executable.
    service_runtime_details_process_executable_sha256 = coalesce(finding_process -> ExecutableSha256, finding_process -> executableSha256), // The SHA-256 hash of the process executable.
    service_runtime_details_process_user = coalesce(finding_process -> User, finding_process -> user), // The operating system user that executed the process.
    service_runtime_details_process_user_id = coalesce(finding_process -> UserId, finding_process -> userId), // The operating system user ID that executed the process.

    // Runtime context details (present for Runtime Monitoring findings with target/threat context)
    // Ref: https://docs.aws.amazon.com/guardduty/latest/APIReference/API_RuntimeContext.html
    service_runtime_context_target_process_name = coalesce(finding_runtime_context -> TargetProcess.Name, finding_runtime_context -> targetProcess.name), // The name of the target process (e.g. injection victim).
    service_runtime_context_target_process_executable_path = coalesce(finding_runtime_context -> TargetProcess.ExecutablePath, finding_runtime_context -> targetProcess.executablePath), // The executable path of the target process.
    service_runtime_context_target_process_executable_sha256 = coalesce(finding_runtime_context -> TargetProcess.ExecutableSha256, finding_runtime_context -> targetProcess.executableSha256), // The SHA-256 hash of the target process executable.
    service_runtime_context_target_process_pid = to_integer(coalesce(finding_runtime_context -> TargetProcess.Pid, finding_runtime_context -> targetProcess.pid)), // The PID of the target process.
    service_runtime_context_target_process_user = coalesce(finding_runtime_context -> TargetProcess.User, finding_runtime_context -> targetProcess.user), // The OS user that owns the target process.
    service_runtime_context_target_process_user_id = coalesce(finding_runtime_context -> TargetProcess.UserId, finding_runtime_context -> targetProcess.userId), // The OS user ID that owns the target process.
    service_runtime_context_module_name = coalesce(finding_runtime_context -> ModuleName, finding_runtime_context -> moduleName), // The name of the loaded kernel module.
    service_runtime_context_module_file_path = coalesce(finding_runtime_context -> ModuleFilePath, finding_runtime_context -> moduleFilePath), // The file path of the loaded kernel module.
    service_runtime_context_module_sha256 = coalesce(finding_runtime_context -> ModuleSha256, finding_runtime_context -> moduleSha256), // The SHA-256 hash of the loaded kernel module.
    service_runtime_context_tool_name = coalesce(finding_runtime_context -> ToolName, finding_runtime_context -> toolName), // The name of the suspicious tool detected.
    service_runtime_context_threat_file_path = coalesce(finding_runtime_context -> ThreatFilePath, finding_runtime_context -> threatFilePath), // The file path of the detected threat.
    service_runtime_context_script_path = coalesce(finding_runtime_context -> ScriptPath, finding_runtime_context -> scriptPath), // The path of the script executed.
    service_runtime_context_release_agent_path = coalesce(finding_runtime_context -> ReleaseAgentPath, finding_runtime_context -> releaseAgentPath), // The cgroups release agent path used in privilege escalation.

    // Additional service metadata
    service_feature_name = coalesce(finding_service -> FeatureName, finding_service -> featureName), // The GuardDuty feature that detected this finding (RuntimeMonitoring, EbsMalwareProtection, etc.).
    service_resource_role = coalesce(finding_service -> ResourceRole, finding_service -> resourceRole), // Whether the affected resource was the TARGET or ACTOR.

    // Network connection action fields (NETWORK_CONNECTION)
    // Ref: https://docs.aws.amazon.com/guardduty/latest/APIReference/API_NetworkConnectionAction.html
    service_action_network_connection_is_blocked = to_boolean(coalesce(finding_network -> Blocked, finding_network -> blocked)), // Whether the network connection was blocked.
    service_action_network_connection_direction = coalesce(finding_network -> ConnectionDirection, finding_network -> connectionDirection), // INBOUND or OUTBOUND.
    service_action_network_connection_protocol = coalesce(finding_network -> Protocol, finding_network -> protocol), // The network connection protocol (TCP, UDP).
    service_action_network_connection_local_ipv4 = coalesce(finding_network -> LocalIpDetails.IpAddressV4, finding_network -> localIpDetails.ipAddressV4), // The local IPv4 address.
    service_action_network_connection_local_ipv6 = coalesce(finding_network -> LocalIpDetails.IpAddressV6, finding_network -> localIpDetails.ipAddressV6), // The local IPv6 address.
    service_action_network_connection_local_port = coalesce(finding_network -> LocalPortDetails.Port, finding_network -> localPortDetails.port), // The local port number.
    service_action_network_connection_local_port_name = coalesce(finding_network -> LocalPortDetails.PortName, finding_network -> localPortDetails.portName), // The local port name (e.g. HTTP, SMTP).
    service_action_network_connection_remote_asn = coalesce(finding_network -> RemoteIpDetails.Organization.Asn, finding_network -> remoteIpDetails.organization.asn), // The remote ASN.
    service_action_network_connection_remote_asn_org = coalesce(finding_network -> RemoteIpDetails.Organization.AsnOrg, finding_network -> remoteIpDetails.organization.asnOrg), // The organisation that registered the remote ASN.
    service_action_network_connection_remote_asn_isp = coalesce(finding_network -> RemoteIpDetails.Organization.Isp, finding_network -> remoteIpDetails.organization.isp), // The remote ISP.
    service_action_network_connection_remote_asn_isp_org = coalesce(finding_network -> RemoteIpDetails.Organization.Org, finding_network -> remoteIpDetails.organization.org), // The remote ISP organisation name.
    service_action_network_connection_remote_ipv4 = coalesce(finding_network -> RemoteIpDetails.IpAddressV4, finding_network -> remoteIpDetails.ipAddressV4), // The remote IPv4 address.
    service_action_network_connection_remote_ipv6 = coalesce(finding_network -> RemoteIpDetails.IpAddressV6, finding_network -> remoteIpDetails.ipAddressV6), // The remote IPv6 address.
    service_action_network_connection_remote_port = coalesce(finding_network -> RemotePortDetails.Port, finding_network -> remotePortDetails.port), // The remote port number.
    service_action_network_connection_remote_port_name = coalesce(finding_network -> RemotePortDetails.PortName, finding_network -> remotePortDetails.portName), // The remote port name.

    // AWS API call action fields (AWS_API_CALL)
    // Ref: https://docs.aws.amazon.com/guardduty/latest/APIReference/API_AwsApiCallAction.html
    service_action_api_call_user_agent = coalesce( // The user agent string of the API caller.
        finding_aws_api -> UserAgent, finding_aws_api -> userAgent,
        to_json_string(finding_service -> AdditionalInfo.Value) -> userAgent.fullUserAgent,
        to_json_string(finding_service -> additionalInfo.value) -> userAgent.fullUserAgent),
    service_action_api_call_remote_ipv4 = coalesce(finding_aws_api -> RemoteIpDetails.IpAddressV4, finding_aws_api -> remoteIpDetails.ipAddressV4), // The remote IPv4 address of the API caller.
    service_action_api_call_remote_ipv6 = coalesce(finding_aws_api -> RemoteIpDetails.IpAddressV6, finding_aws_api -> remoteIpDetails.ipAddressV6), // The remote IPv6 address of the API caller.
    service_action_api_call_remote_asn = coalesce(finding_aws_api -> RemoteIpDetails.Organization.Asn, finding_aws_api -> remoteIpDetails.organization.asn), // The remote ASN.
    service_action_api_call_remote_asn_org = coalesce(finding_aws_api -> RemoteIpDetails.Organization.AsnOrg, finding_aws_api -> remoteIpDetails.organization.asnOrg), // The organisation that registered the remote ASN.
    service_action_api_call_remote_isp = coalesce(finding_aws_api -> RemoteIpDetails.Organization.Isp, finding_aws_api -> remoteIpDetails.organization.isp), // The remote ISP.
    service_action_api_call_remote_isp_org = coalesce(finding_aws_api -> RemoteIpDetails.Organization.Org, finding_aws_api -> remoteIpDetails.organization.org), // The remote ISP organisation name.
    service_action_api_call_remote_account_id = coalesce(finding_aws_api -> RemoteAccountDetails.AccountId, finding_aws_api -> remoteAccountDetails.accountId), // The AWS account ID of the remote API caller.
    service_action_api_call_error_code = coalesce(finding_aws_api -> ErrorCode, finding_aws_api -> errorCode), // The error code if the API call failed.

    // DNS request action fields (DNS_REQUEST)
    // Ref: https://docs.aws.amazon.com/guardduty/latest/APIReference/API_DnsRequestAction.html
    service_action_dns_request_action_domain = coalesce(finding_service -> Action.DnsRequestAction.Domain, finding_service -> action.dnsRequestAction.domain), // The queried domain name.
    service_action_dns_request_action_protocol = coalesce(finding_service -> Action.DnsRequestAction.Protocol, finding_service -> action.dnsRequestAction.protocol), // The DNS query protocol (UDP/TCP).
    service_action_dns_request_action_blocked = to_boolean(coalesce(finding_service -> Action.DnsRequestAction.Blocked, finding_service -> action.dnsRequestAction.blocked)), // Whether the DNS request was blocked.

    // Kubernetes API call action fields (KUBERNETES_API_CALL)
    // Ref: https://docs.aws.amazon.com/guardduty/latest/APIReference/API_KubernetesApiCallAction.html
    service_action_k8s_api_call_verb = coalesce(finding_k8s_api -> Verb, finding_k8s_api -> verb), // The Kubernetes API request HTTP verb (get, list, create, etc.).
    service_action_k8s_api_call_request_uri = coalesce(finding_k8s_api -> RequestUri, finding_k8s_api -> requestUri), // The Kubernetes API request URI.
    service_action_k8s_api_call_status_code = coalesce(finding_k8s_api -> StatusCode, finding_k8s_api -> statusCode), // The HTTP response status code of the Kubernetes API call.
    service_action_k8s_api_call_user_agent = coalesce(finding_k8s_api -> UserAgent, finding_k8s_api -> userAgent), // The user agent of the Kubernetes API caller.
    service_action_k8s_api_call_resource = coalesce(finding_k8s_api -> Resource, finding_k8s_api -> resource), // The Kubernetes resource component (e.g. pods, deployments).
    service_action_k8s_api_call_resource_name = coalesce(finding_k8s_api -> ResourceName, finding_k8s_api -> resourceName), // The name of the Kubernetes resource.
    service_action_k8s_api_call_sourceIPs = coalesce(finding_k8s_api -> SourceIPs[], finding_k8s_api -> sourceIPs[]), // The source IPs of the Kubernetes API caller (may include proxy IPs).
    service_action_k8s_api_call_remote_ipv4 = coalesce(finding_k8s_api -> RemoteIpDetails.IpAddressV4, finding_k8s_api -> remoteIpDetails.ipAddressV4), // The remote IPv4 address.
    service_action_k8s_api_call_remote_ipv6 = coalesce(finding_k8s_api -> RemoteIpDetails.IpAddressV6, finding_k8s_api -> remoteIpDetails.ipAddressV6), // The remote IPv6 address.
    service_action_k8s_api_call_remote_asn = coalesce(finding_k8s_api -> RemoteIpDetails.Organization.Asn, finding_k8s_api -> remoteIpDetails.organization.asn), // The remote ASN.
    service_action_k8s_api_call_remote_asn_org = coalesce(finding_k8s_api -> RemoteIpDetails.Organization.AsnOrg, finding_k8s_api -> remoteIpDetails.organization.asnOrg), // The organisation that registered the remote ASN.
    service_action_k8s_api_call_remote_isp = coalesce(finding_k8s_api -> RemoteIpDetails.Organization.Isp, finding_k8s_api -> remoteIpDetails.organization.isp), // The remote ISP.
    service_action_k8s_api_call_remote_isp_org = coalesce(finding_k8s_api -> RemoteIpDetails.Organization.Org, finding_k8s_api -> remoteIpDetails.organization.org), // The remote ISP organisation name.

    // Port probe action fields (PORT_PROBE)
    // Ref: https://docs.aws.amazon.com/guardduty/latest/APIReference/API_PortProbeAction.html
    service_action_port_probing_remote_ipv4_addresses = coalesce( // IPv4 addresses of port probe sources.
        arraymap(finding_service -> Action.PortProbeAction.PortProbeDetails[], "@element" -> RemoteIpDetails.IpAddressV4),
        arraymap(finding_service -> action.portProbeAction.portProbeDetails[], "@element" -> remoteIpDetails.ipAddressV4)),
    service_action_port_probing_remote_ipv6_addresses = coalesce( // IPv6 addresses of port probe sources.
        arraymap(finding_service -> Action.PortProbeAction.PortProbeDetails[], "@element" -> RemoteIpDetails.IpAddressV6),
        arraymap(finding_service -> action.portProbeAction.portProbeDetails[], "@element" -> remoteIpDetails.ipAddressV6)),

    // Kubernetes role details
    // Ref: https://docs.aws.amazon.com/guardduty/latest/APIReference/API_KubernetesRoleDetails.html
    service_action_k8s_role_name = coalesce(finding_service -> Action.KubernetesRoleDetails.Name, finding_service -> action.kubernetesRoleDetails.name), // The Kubernetes role name.

    // Kubernetes role binding details
    // Ref: https://docs.aws.amazon.com/guardduty/latest/APIReference/API_KubernetesRoleBindingDetails.html
    service_action_k8s_role_binding_name = coalesce(finding_service -> Action.KubernetesRoleBindingDetails.Name, finding_service -> action.kubernetesRoleBindingDetails.name), // The Kubernetes role binding name.

    // RDS login attempt action fields (RDS_LOGIN_ATTEMPT)
    // Ref: https://docs.aws.amazon.com/guardduty/latest/APIReference/API_RdsLoginAttemptAction.html
    service_action_rds_login_attempt_users = if(finding_rds_login != null, coalesce( // The user name(s) from the RDS login attempt.
        arraystring(arraymap(finding_rds_login -> LoginAttribute[], "@element" -> User), ","),
        arraystring(arraymap(finding_rds_login -> loginAttribute[], "@element" -> user), ","))),
    service_action_rds_login_attempt_applications = if(finding_rds_login != null, coalesce( // The application name(s) from the RDS login attempt.
        arraystring(arraymap(finding_rds_login -> LoginAttribute[], "@element" -> Application), ","),
        arraystring(arraymap(finding_rds_login -> loginAttribute[], "@element" -> application), ","))),
    service_action_rds_login_attempt_remote_ipv4 = coalesce(finding_rds_login -> RemoteIpDetails.IpAddressV4, finding_rds_login -> remoteIpDetails.ipAddressV4), // The remote IPv4 address.
    service_action_rds_login_attempt_remote_ipv6 = coalesce(finding_rds_login -> RemoteIpDetails.IpAddressV6, finding_rds_login -> remoteIpDetails.ipAddressV6), // The remote IPv6 address.
    service_action_rds_login_attempt_remote_asn = coalesce(finding_rds_login -> RemoteIpDetails.Organization.Asn, finding_rds_login -> remoteIpDetails.organization.asn), // The remote ASN.
    service_action_rds_login_attempt_remote_asn_org = coalesce(finding_rds_login -> RemoteIpDetails.Organization.AsnOrg, finding_rds_login -> remoteIpDetails.organization.asnOrg), // The organisation that registered the remote ASN.
    service_action_rds_login_attempt_remote_isp = coalesce(finding_rds_login -> RemoteIpDetails.Organization.Isp, finding_rds_login -> remoteIpDetails.organization.isp), // The remote ISP.
    service_action_rds_login_attempt_remote_isp_org = coalesce(finding_rds_login -> RemoteIpDetails.Organization.Org, finding_rds_login -> remoteIpDetails.organization.org) // The remote ISP organisation name.

// -- Stage 4: Post-extraction processing ------------------------------------
// Derive directional flags, normalise HTTP fields, categorise IP addresses
// from Kubernetes API call source IP arrays, and determine network protocol.
| alter
    is_connection_inbound = if(service_action_network_connection_direction != null and service_action_network_connection_direction = "INBOUND"),
    is_connection_outbound = if(service_action_network_connection_direction != null and service_action_network_connection_direction = "OUTBOUND"),
    http_code = to_integer(service_action_k8s_api_call_status_code), // Normalised HTTP status code for XDM_CONST mapping.
    http_verb = service_action_k8s_api_call_verb, // Normalised HTTP verb for XDM_CONST mapping.
    network_protocol = coalesce(service_action_network_connection_protocol, service_action_dns_request_action_protocol),
    k8s_api_call_src_ipv4_addresses = arrayfilter(service_action_k8s_api_call_sourceIPs, "@element" ~= "(?:\d{1,3}\.){3}\d{1,3}"),
    k8s_api_call_src_ipv6_addresses = arrayfilter(service_action_k8s_api_call_sourceIPs, "@element" ~= "(?:[a-fA-F\d]{0,4}\:){1,7}[a-fA-F\d]{0,4}")

// -- Stage 5: Directional IP and port resolution ----------------------------
| alter
    network_application_protocol = if(is_connection_inbound, service_action_network_connection_local_port_name, is_connection_outbound, service_action_network_connection_remote_port_name),
    source_ipv4 = if(is_connection_inbound, service_action_network_connection_remote_ipv4, is_connection_outbound, service_action_network_connection_local_ipv4, coalesce(service_action_api_call_remote_ipv4, service_action_k8s_api_call_remote_ipv4, service_action_rds_login_attempt_remote_ipv4)),
    source_ipv6 = if(is_connection_inbound, service_action_network_connection_remote_ipv6, is_connection_outbound, service_action_network_connection_local_ipv6, coalesce(service_action_api_call_remote_ipv6, service_action_k8s_api_call_remote_ipv6, service_action_rds_login_attempt_remote_ipv6)),
    target_ipv4 = if(is_connection_inbound, service_action_network_connection_local_ipv4, is_connection_outbound, service_action_network_connection_remote_ipv4),
    target_ipv6 = if(is_connection_inbound, service_action_network_connection_local_ipv6, is_connection_outbound, service_action_network_connection_remote_ipv6)

// -- Stage 6: Aggregate multi-source IP arrays ------------------------------
// Kubernetes API calls and port probes may report multiple source IPs.
// Merge them with the primary source IP for comprehensive host IP coverage.
| alter
    source_ipv4_addresses = if(array_length(k8s_api_call_src_ipv4_addresses) > 0, k8s_api_call_src_ipv4_addresses, array_length(service_action_port_probing_remote_ipv4_addresses) > 0, service_action_port_probing_remote_ipv4_addresses),
    source_ipv6_addresses = if(array_length(k8s_api_call_src_ipv6_addresses) > 0, k8s_api_call_src_ipv6_addresses, array_length(service_action_port_probing_remote_ipv6_addresses) > 0, service_action_port_probing_remote_ipv6_addresses)
| alter
    all_source_ipv4_addresses = if(array_length(source_ipv4_addresses) > 0 and source_ipv4 != null, arrayconcat(arraycreate(source_ipv4), source_ipv4_addresses), source_ipv4 != null, arraycreate(source_ipv4), source_ipv4_addresses),
    all_source_ipv6_addresses = if(array_length(source_ipv6_addresses) > 0 and source_ipv6 != null, arrayconcat(arraycreate(source_ipv6), source_ipv6_addresses), source_ipv6 != null, arraycreate(source_ipv6), source_ipv6_addresses)

// -- Stage 7: XDM field assignments -----------------------------------------
// Map all extracted and derived fields to the Cortex XDM schema.
// GoCortexIO -- every field below is validated against the XDM reference.

| alter
    // XDM Alert fields -- xdm.alert.*
    // Ref: https://docs-cortex.paloaltonetworks.com/r/Cortex-XDM/XDM-Reference/alert
    xdm.alert.description = finding_description,
    xdm.alert.name = finding_title,
    xdm.alert.original_alert_id = finding_id,
    xdm.alert.risks = if(array_length(service_evidence_threat_intelligence_details) > 0, service_evidence_threat_intelligence_details),
    xdm.alert.severity = if( // GuardDuty severity bands: https://docs.aws.amazon.com/guardduty/latest/ug/guardduty_findings.html#guardduty_findings-severity
        finding_severity >= 9, "Critical",
        finding_severity >= 7 and finding_severity <= 8.9, "High",
        finding_severity >= 4 and finding_severity <= 6.9, "Medium",
        finding_severity >= 1 and finding_severity <= 3.9, "Low",
        finding_severity_band = "HIGH", "High", // Defensive fallback: numeric Severity missing but parser-stamped band present.
        finding_severity_band = "MEDIUM", "Medium",
        finding_severity_band = "LOW", "Low",
        to_string(finding_severity)),
    xdm.alert.subcategory = finding_type,

    // XDM Auth fields -- xdm.auth.*
    xdm.auth.auth_method = resource_rdsDbUserDetails_auth_method,

    // XDM Event fields -- xdm.event.*
    xdm.event.description = finding_description, // XDM Event > description -- the human-readable GuardDuty finding description.
    xdm.event.id = finding_id, // XDM Event > id -- the GuardDuty finding ID (top-level Id field), critical for alert correlation and deduplication.
    xdm.event.type = "ALERT",
    xdm.event.operation_sub_type = service_action_type,
    xdm.event.original_event_type = service_feature_name, // XDM Event > original_event_type -- the GuardDuty detection feature name.
    xdm.event.outcome = if(service_action_network_connection_is_blocked or service_action_dns_request_action_blocked or service_action_api_call_error_code != null, XDM_CONST.OUTCOME_FAILED),
    xdm.event.outcome_reason = service_action_api_call_error_code,

    // XDM Network fields -- xdm.network.*
    // Includes application protocol, DNS, HTTP method/response code, and IP protocol.
    xdm.network.application_protocol = if(network_application_protocol != "Unknown", network_application_protocol),
    xdm.network.dns.dns_question.name = service_action_dns_request_action_domain,
    xdm.network.http.method = if(http_verb = null, http_verb, http_verb = "GET", XDM_CONST.HTTP_METHOD_GET, http_verb = "POST", XDM_CONST.HTTP_METHOD_POST, http_verb = "PUT", XDM_CONST.HTTP_METHOD_PUT, http_verb = "PATCH", XDM_CONST.HTTP_METHOD_PATCH, http_verb = "OPTIONS", XDM_CONST.HTTP_METHOD_OPTIONS, http_verb = "HEAD", XDM_CONST.HTTP_METHOD_HEAD, http_verb = "ACL", XDM_CONST.HTTP_METHOD_ACL, http_verb = "BASELINE_CONTROL", XDM_CONST.HTTP_METHOD_BASELINE_CONTROL, http_verb = "BIND", XDM_CONST.HTTP_METHOD_BIND, http_verb = "CHECKIN", XDM_CONST.HTTP_METHOD_CHECKIN, http_verb = "CHECKOUT", XDM_CONST.HTTP_METHOD_CHECKOUT, http_verb = "CONNECT", XDM_CONST.HTTP_METHOD_CONNECT, http_verb = "COPY", XDM_CONST.HTTP_METHOD_COPY, http_verb = "DELETE", XDM_CONST.HTTP_METHOD_DELETE, http_verb = "LABEL", XDM_CONST.HTTP_METHOD_LABEL, http_verb = "LINK", XDM_CONST.HTTP_METHOD_LINK, http_verb = "LOCK", XDM_CONST.HTTP_METHOD_LOCK, http_verb = "MERGE", XDM_CONST.HTTP_METHOD_MERGE, http_verb = "MKACTIVITY", XDM_CONST.HTTP_METHOD_MKACTIVITY, http_verb = "MKCALENDAR", XDM_CONST.HTTP_METHOD_MKCALENDAR, http_verb = "MKCOL", XDM_CONST.HTTP_METHOD_MKCOL, http_verb = "MKREDIRECTREF", XDM_CONST.HTTP_METHOD_MKREDIRECTREF, http_verb = "MKWORKSPACE", XDM_CONST.HTTP_METHOD_MKWORKSPACE, http_verb = "MOVE", XDM_CONST.HTTP_METHOD_MOVE, http_verb = "ORDERPATCH", XDM_CONST.HTTP_METHOD_ORDERPATCH, http_verb = "PRI", XDM_CONST.HTTP_METHOD_PRI, http_verb = "PROPFIND", XDM_CONST.HTTP_METHOD_PROPFIND, http_verb = "PROPPATCH", XDM_CONST.HTTP_METHOD_PROPPATCH, http_verb = "REBIND", XDM_CONST.HTTP_METHOD_REBIND, http_verb = "REPORT", XDM_CONST.HTTP_METHOD_REPORT, http_verb = "SEARCH", XDM_CONST.HTTP_METHOD_SEARCH, http_verb = "TRACE", XDM_CONST.HTTP_METHOD_TRACE, http_verb = "UNBIND", XDM_CONST.HTTP_METHOD_UNBIND, http_verb = "UNCHECKOUT", XDM_CONST.HTTP_METHOD_UNCHECKOUT, http_verb = "UNLINK", XDM_CONST.HTTP_METHOD_UNLINK, http_verb = "UNLOCK", XDM_CONST.HTTP_METHOD_UNLOCK, http_verb = "UPDATE", XDM_CONST.HTTP_METHOD_UPDATE, http_verb = "UPDATEREDIRECTREF", XDM_CONST.HTTP_METHOD_UPDATEREDIRECTREF, http_verb = "VERSION_CONTROL", XDM_CONST.HTTP_METHOD_VERSION_CONTROL, uppercase(http_verb)),
    xdm.network.http.response_code = if(http_code = null, null, http_code = 200, XDM_CONST.HTTP_RSP_CODE_OK, http_code = 201, XDM_CONST.HTTP_RSP_CODE_CREATED, http_code = 302, XDM_CONST.HTTP_RSP_CODE_FOUND, http_code = 401, XDM_CONST.HTTP_RSP_CODE_UNAUTHORIZED, http_code = 403, XDM_CONST.HTTP_RSP_CODE_FORBIDDEN, http_code = 404, XDM_CONST.HTTP_RSP_CODE_NOT_FOUND, http_code = 500, XDM_CONST.HTTP_RSP_CODE_INTERNAL_SERVER_ERROR, http_code = 501, XDM_CONST.HTTP_RSP_CODE_NOT_IMPLEMENTED, http_code = 502, XDM_CONST.HTTP_RSP_CODE_BAD_GATEWAY, http_code = 503, XDM_CONST.HTTP_RSP_CODE_SERVICE_UNAVAILABLE, http_code = 504, XDM_CONST.HTTP_RSP_CODE_GATEWAY_TIMEOUT, http_code = 505, XDM_CONST.HTTP_RSP_CODE_HTTP_VERSION_NOT_SUPPORTED, http_code = 506, XDM_CONST.HTTP_RSP_CODE_VARIANT_ALSO_NEGOTIATES, http_code = 507, XDM_CONST.HTTP_RSP_CODE_INSUFFICIENT_STORAGE, http_code = 508, XDM_CONST.HTTP_RSP_CODE_LOOP_DETECTED, http_code = 511, XDM_CONST.HTTP_RSP_CODE_NETWORK_AUTHENTICATION_REQUIRED, http_code = 100, XDM_CONST.HTTP_RSP_CODE_CONTINUE, http_code = 101, XDM_CONST.HTTP_RSP_CODE_SWITCHING_PROTOCOLS, http_code = 102, XDM_CONST.HTTP_RSP_CODE_PROCESSING, http_code = 103, XDM_CONST.HTTP_RSP_CODE_EARLY_HINTS, http_code = 202, XDM_CONST.HTTP_RSP_CODE_ACCEPTED, http_code = 203, XDM_CONST.HTTP_RSP_CODE_NON__AUTHORITATIVE_INFORMATION, http_code = 204, XDM_CONST.HTTP_RSP_CODE_NO_CONTENT, http_code = 205, XDM_CONST.HTTP_RSP_CODE_RESET_CONTENT, http_code = 206, XDM_CONST.HTTP_RSP_CODE_PARTIAL_CONTENT, http_code = 207, XDM_CONST.HTTP_RSP_CODE_MULTI__STATUS, http_code = 208, XDM_CONST.HTTP_RSP_CODE_ALREADY_REPORTED, http_code = 226, XDM_CONST.HTTP_RSP_CODE_IM_USED, http_code = 300, XDM_CONST.HTTP_RSP_CODE_MULTIPLE_CHOICES, http_code = 301, XDM_CONST.HTTP_RSP_CODE_MOVED_PERMANENTLY, http_code = 303, XDM_CONST.HTTP_RSP_CODE_SEE_OTHER, http_code = 304, XDM_CONST.HTTP_RSP_CODE_NOT_MODIFIED, http_code = 305, XDM_CONST.HTTP_RSP_CODE_USE_PROXY, http_code = 307, XDM_CONST.HTTP_RSP_CODE_TEMPORARY_REDIRECT, http_code = 308, XDM_CONST.HTTP_RSP_CODE_PERMANENT_REDIRECT, http_code = 400, XDM_CONST.HTTP_RSP_CODE_BAD_REQUEST, http_code = 402, XDM_CONST.HTTP_RSP_CODE_PAYMENT_REQUIRED, http_code = 405, XDM_CONST.HTTP_RSP_CODE_METHOD_NOT_ALLOWED, http_code = 406, XDM_CONST.HTTP_RSP_CODE_NOT_ACCEPTABLE, http_code = 407, XDM_CONST.HTTP_RSP_CODE_PROXY_AUTHENTICATION_REQUIRED, http_code = 408, XDM_CONST.HTTP_RSP_CODE_REQUEST_TIMEOUT, http_code = 409, XDM_CONST.HTTP_RSP_CODE_CONFLICT, http_code = 410, XDM_CONST.HTTP_RSP_CODE_GONE, http_code = 411, XDM_CONST.HTTP_RSP_CODE_LENGTH_REQUIRED, http_code = 412, XDM_CONST.HTTP_RSP_CODE_PRECONDITION_FAILED, http_code = 413, XDM_CONST.HTTP_RSP_CODE_CONTENT_TOO_LARGE, http_code = 414, XDM_CONST.HTTP_RSP_CODE_URI_TOO_LONG, http_code = 415, XDM_CONST.HTTP_RSP_CODE_UNSUPPORTED_MEDIA_TYPE, http_code = 416, XDM_CONST.HTTP_RSP_CODE_RANGE_NOT_SATISFIABLE, http_code = 417, XDM_CONST.HTTP_RSP_CODE_EXPECTATION_FAILED, http_code = 421, XDM_CONST.HTTP_RSP_CODE_MISDIRECTED_REQUEST, http_code = 422, XDM_CONST.HTTP_RSP_CODE_UNPROCESSABLE_CONTENT, http_code = 423, XDM_CONST.HTTP_RSP_CODE_LOCKED, http_code = 424, XDM_CONST.HTTP_RSP_CODE_FAILED_DEPENDENCY, http_code = 425, XDM_CONST.HTTP_RSP_CODE_TOO_EARLY, http_code = 426, XDM_CONST.HTTP_RSP_CODE_UPGRADE_REQUIRED, http_code = 428, XDM_CONST.HTTP_RSP_CODE_PRECONDITION_REQUIRED, http_code = 429, XDM_CONST.HTTP_RSP_CODE_TOO_MANY_REQUESTS, http_code = 431, XDM_CONST.HTTP_RSP_CODE_REQUEST_HEADER_FIELDS_TOO_LARGE, http_code = 451, XDM_CONST.HTTP_RSP_CODE_UNAVAILABLE_FOR_LEGAL_REASONS, service_action_k8s_api_call_status_code),
    xdm.network.http.url = service_action_k8s_api_call_request_uri,
    xdm.network.ip_protocol = if(network_protocol = "UDP", XDM_CONST.IP_PROTOCOL_UDP, network_protocol = "TCP", XDM_CONST.IP_PROTOCOL_TCP),

    // XDM Observer fields -- xdm.observer.*
    // The security product that generated the finding.
    xdm.observer.vendor = "Amazon",
    xdm.observer.product = "GuardDuty",
    xdm.observer.type = service_feature_name, // XDM Observer > type -- the GuardDuty detection feature (RuntimeMonitoring, EbsMalwareProtection, etc.).
    xdm.observer.action = service_resource_role, // XDM Observer > action -- whether the affected resource was TARGET or ACTOR in the finding.
    xdm.observer.unique_identifier = service_detector_id,

    // XDM Source fields -- xdm.source.*
    // The entity that initiated the activity (caller, attacker, probe source).
    xdm.source.application.name = coalesce(resource_rdsDbUserDetails_application, service_action_rds_login_attempt_applications, service_runtime_context_tool_name, service_runtime_context_module_name),
    xdm.source.asn.as_name = if(is_connection_inbound, service_action_network_connection_remote_asn_org, coalesce(service_action_api_call_remote_asn_org, service_action_k8s_api_call_remote_asn_org, service_action_rds_login_attempt_remote_asn_org)),
    xdm.source.asn.as_number = to_integer(if(is_connection_inbound, service_action_network_connection_remote_asn, coalesce(service_action_api_call_remote_asn, service_action_k8s_api_call_remote_asn, service_action_rds_login_attempt_remote_asn))),
    xdm.source.asn.isp = if(is_connection_inbound, coalesce(service_action_network_connection_remote_asn_isp, service_action_network_connection_remote_asn_isp_org), coalesce(service_action_api_call_remote_isp, service_action_api_call_remote_isp_org, service_action_k8s_api_call_remote_isp, service_action_k8s_api_call_remote_isp_org, service_action_rds_login_attempt_remote_isp, service_action_rds_login_attempt_remote_isp_org)),
    xdm.source.cloud.project_id = coalesce(service_action_api_call_remote_account_id, finding_account_id),
    xdm.source.cloud.provider = XDM_CONST.CLOUD_PROVIDER_AWS,
    xdm.source.cloud.region = finding_region,
    xdm.source.cloud.zone = resource_availability_zone,
    xdm.source.host.device_model = resource_instance_type,
    xdm.source.host.hostname = resource_instance_id,
    xdm.source.host.ipv4_addresses = if(array_length(all_source_ipv4_addresses) > 0, all_source_ipv4_addresses),
    xdm.source.host.ipv6_addresses = if(array_length(all_source_ipv6_addresses) > 0, all_source_ipv6_addresses),
    xdm.source.host.ipv4_public_addresses = arrayfilter(all_source_ipv4_addresses, not incidr("@element", "10.0.0.0/8") and not incidr("@element", "172.16.0.0/12") and not incidr("@element", "192.168.0.0/16") and not incidr("@element", "127.0.0.0/8") and not incidr("@element", "169.254.0.0/16") and not incidr("@element", "100.64.0.0/10")),
    xdm.source.ipv4 = coalesce(source_ipv4, arrayindex(all_source_ipv4_addresses, 0)),
    xdm.source.ipv6 = coalesce(source_ipv6, arrayindex(all_source_ipv6_addresses, 0)),
    xdm.source.port = to_integer(if(is_connection_inbound, service_action_network_connection_remote_port, is_connection_outbound, service_action_network_connection_local_port)),
    xdm.source.process.executable.path = service_runtime_details_process_executable_path,
    xdm.source.process.executable.sha256 = service_runtime_details_process_executable_sha256,
    xdm.source.process.identifier = service_runtime_details_process_uuid,
    xdm.source.process.name = service_runtime_details_process_name,
    xdm.source.process.parent_id = service_runtime_details_process_parent_uuid,
    xdm.source.process.pid = service_runtime_details_process_pid, // XDM Source > Process > pid -- the OS-level process ID from GuardDuty Runtime Monitoring.
    xdm.source.user_agent = coalesce(service_action_api_call_user_agent, service_action_k8s_api_call_user_agent),
    xdm.source.user.domain = coalesce(resource_k8s_namespace, finding_account_id), // XDM Source > User > domain -- the organisational boundary: K8s namespace for container findings, AWS account ID for IAM findings.
    xdm.source.user.groups = if(service_action_k8s_role_name != null, arraycreate(service_action_k8s_role_name), resource_user_groups),
    xdm.source.user.identifier = arraystring(arraycreate(resource_user_id, resource_access_key_id, service_runtime_details_process_user_id, service_runtime_context_target_process_user_id), ","), // arraystring on arraycreate handles all-null inputs correctly; the compound 'or' null guard is rejected by the Cortex parser. // XDM Source > User > identifier -- IAM PrincipalId, IAM access key ID, K8s UID, OS user ID, or target process user ID concatenated.
    xdm.source.user.identity_type = if( // XDM Source > User > identity_type -- maps IAM UserType to XDM_CONST.IDENTITY_TYPE_*.
        resource_user_type = "Root", XDM_CONST.IDENTITY_TYPE_BUILTIN, // Root is the built-in AWS account identity.
        resource_user_type = "IAMUser", XDM_CONST.IDENTITY_TYPE_USER, // IAMUser is a human user identity.
        resource_user_type = "AssumedRole", XDM_CONST.IDENTITY_TYPE_MACHINE, // AssumedRole is typically service/automation role assumption.
        resource_user_type = "FederatedUser", XDM_CONST.IDENTITY_TYPE_VIRTUAL, // FederatedUser is an external/virtual federated identity.
        resource_user_type = "AWSAccount", XDM_CONST.IDENTITY_TYPE_MACHINE, // Cross-account access by another AWS account (machine-to-machine).
        resource_user_type = "AWSService", XDM_CONST.IDENTITY_TYPE_MACHINE, // AWS service acting on behalf of the account.
        resource_user_type = "Directory", XDM_CONST.IDENTITY_TYPE_USER, // AWS Directory Service managed user.
        resource_user_type != null, XDM_CONST.IDENTITY_TYPE_UNKNOWN), // Unrecognised IAM user type.
    xdm.source.user.ou = resource_k8s_namespace, // XDM Source > User > ou -- the Kubernetes namespace as the organisational unit of the source user.
    xdm.source.user.roles = arraycreate(coalesce(service_action_k8s_role_binding_name, resource_iam_instance_profile_arn)), // arraycreate(null) is fine; the compound 'or' null guard is rejected by the Cortex parser. // XDM Source > User > roles -- K8s role binding name, or IAM instance profile ARN for assumed roles (array type).
    xdm.source.user.user_type = resource_user_type,
    xdm.source.user.username = coalesce(service_action_rds_login_attempt_users, service_runtime_details_process_user, service_runtime_context_target_process_user, resource_username, resource_k8s_service_account_name), // XDM Source > User > username -- RDS login user, OS process user, runtime context target process user, IAM/K8s user, or K8s service account name (fallback).

    // XDM Target fields -- xdm.target.*
    // The entity that was targeted by the activity.
    xdm.target.asn.as_name = if(is_connection_outbound, service_action_network_connection_remote_asn_org),
    xdm.target.asn.as_number = to_integer(if(is_connection_outbound, service_action_network_connection_remote_asn)),
    xdm.target.asn.isp = if(is_connection_outbound, coalesce(service_action_network_connection_remote_asn_isp, service_action_network_connection_remote_asn_isp_org)),
    xdm.target.cloud.project_id = finding_account_id,
    xdm.target.cloud.provider = XDM_CONST.CLOUD_PROVIDER_AWS,
    xdm.target.cloud.region = finding_region,
    xdm.target.cloud.zone = resource_availability_zone,
    xdm.target.host.ipv4_addresses = if(target_ipv4 != null, arraycreate(target_ipv4)),
    xdm.target.host.ipv6_addresses = if(target_ipv6 != null, arraycreate(target_ipv6)),
    xdm.target.host.ipv4_public_addresses = if(target_ipv4 != null and not incidr(target_ipv4, "10.0.0.0/8") and not incidr(target_ipv4, "172.16.0.0/12") and not incidr(target_ipv4, "192.168.0.0/16") and not incidr(target_ipv4, "127.0.0.0/8") and not incidr(target_ipv4, "169.254.0.0/16") and not incidr(target_ipv4, "100.64.0.0/10"), arraycreate(target_ipv4)),
    xdm.target.ipv4 = target_ipv4,
    xdm.target.ipv6 = target_ipv6,
    xdm.target.port = to_integer(if(is_connection_inbound, service_action_network_connection_local_port, is_connection_outbound, service_action_network_connection_remote_port)),
    xdm.target.file.path = coalesce(service_runtime_context_threat_file_path, service_runtime_context_script_path, service_runtime_context_module_file_path, service_runtime_context_release_agent_path), // XDM Target > File > path -- the threat file, script, kernel module, or cgroups release agent path from RuntimeDetails.Context.
    xdm.target.file.sha256 = service_runtime_context_module_sha256, // XDM Target > File > SHA-256 -- the hash of the loaded kernel module.
    xdm.target.process.executable.path = service_runtime_context_target_process_executable_path, // XDM Target > Process > executable path -- the executable path of the injection/escape target process.
    xdm.target.process.executable.sha256 = service_runtime_context_target_process_executable_sha256, // XDM Target > Process > SHA-256 -- the hash of the target process executable.
    xdm.target.process.name = service_runtime_context_target_process_name, // XDM Target > Process > name -- the name of the injection/escape target process.
    xdm.target.process.pid = service_runtime_context_target_process_pid, // XDM Target > Process > pid -- the PID of the injection/escape target process.
    xdm.target.resource.id = finding_arn,
    xdm.target.resource.name = coalesce(resource_name, service_action_k8s_api_call_resource_name, service_action_k8s_role_binding_name),
    xdm.target.resource.sub_type = resource_k8s_workload_type, // XDM Target > Resource > sub_type -- K8s workload type (pods, deployments, etc.) for container findings.
    xdm.target.resource.type = resource_type,
    xdm.target.resource.value = service_action_k8s_api_call_resource,
    xdm.target.user.identifier = resource_rds_db_instance_arn, // XDM Target > User > identifier -- the RDS DB instance ARN identifying the database targeted in login attempt findings.
    xdm.target.user.username = coalesce(service_action_rds_login_attempt_users, resource_rds_db_instance_id); // XDM Target > User > username -- the database user targeted in RDS login attempts, or the DB instance identifier.
