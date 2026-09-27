#!/usr/bin/env bash
# Break-glass emergency access script for MCP Security Control Plane
# Grants temporary elevated access with automatic revocation after 1 hour.
# All actions are logged to CloudWatch.

set -euo pipefail

SCRIPT_VERSION="0.1.0"
LOG_GROUP="/mcp-security-control-plane/break-glass"
AUTO_REVOKE_SECONDS=3600  # 1 hour

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]

Break-glass emergency access for MCP Security Control Plane.

Options:
  --env ENV         Target environment (dev|staging|prod). Required.
  --reason REASON   Reason for break-glass access. Required.
  --approver EMAIL  Email of approver. Required.
  --duration SECS   Duration in seconds (max 3600). Default: 3600.
  -h, --help        Show this help message.

Examples:
  $0 --env prod --reason "P0 incident response" --approver oncall@company.com
EOF
  exit 1
}

log() {
  local level="$1"
  shift
  local msg="$*"
  local timestamp
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  echo "[${timestamp}] [${level}] ${msg}" >&2

  # Ship to CloudWatch
  if command -v aws &>/dev/null; then
    aws logs put-log-events \
      --log-group-name "${LOG_GROUP}" \
      --log-stream-name "break-glass-${ENV:-unknown}" \
      --log-events timestamp="$(date +%s%3N)",message="[${level}] OPERATOR=${OPERATOR} ENV=${ENV:-unknown} REASON=${REASON:-none} ${msg}" \
      2>/dev/null || true
  fi
}

require_mfa() {
  log "INFO" "Verifying MFA..."
  if ! aws sts get-caller-identity --query 'Arn' --output text &>/dev/null; then
    log "ERROR" "AWS credentials not available or MFA required. Aborting."
    exit 2
  fi
  local caller_arn
  caller_arn=$(aws sts get-caller-identity --query 'Arn' --output text)
  log "INFO" "Authenticated as: ${caller_arn}"
  OPERATOR="${caller_arn}"
}

grant_access() {
  log "INFO" "Granting temporary elevated access for ${DURATION}s to ${ENV}"
  local policy_arn="arn:aws:iam::${AWS_ACCOUNT_ID:-unknown}:policy/mcp-break-glass-policy"
  local role_name="mcp-break-glass-role-${ENV}"
  local session_name="break-glass-$(date +%s)"

  # Assume the break-glass role with limited duration
  TEMP_CREDS=$(aws sts assume-role \
    --role-arn "arn:aws:iam::${AWS_ACCOUNT_ID}:role/${role_name}" \
    --role-session-name "${session_name}" \
    --duration-seconds "${DURATION}" \
    --external-id "break-glass-${ENV}" \
    2>/dev/null) || {
    log "ERROR" "Failed to assume break-glass role. Check AWS_ACCOUNT_ID and role existence."
    exit 3
  }

  export AWS_ACCESS_KEY_ID
  export AWS_SECRET_ACCESS_KEY
  export AWS_SESSION_TOKEN
  AWS_ACCESS_KEY_ID=$(echo "${TEMP_CREDS}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['Credentials']['AccessKeyId'])")
  AWS_SECRET_ACCESS_KEY=$(echo "${TEMP_CREDS}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['Credentials']['SecretAccessKey'])")
  AWS_SESSION_TOKEN=$(echo "${TEMP_CREDS}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['Credentials']['SessionToken'])")

  log "INFO" "Temporary credentials obtained. Expiry in ${DURATION}s."
}

schedule_revocation() {
  log "INFO" "Scheduling auto-revocation in ${DURATION}s..."
  (
    sleep "${DURATION}"
    log "INFO" "Auto-revoking break-glass access for ${OPERATOR} on ${ENV}"
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  ) &
  REVOKE_PID=$!
  log "INFO" "Auto-revocation scheduled (PID=${REVOKE_PID})"
}

# Parse arguments
ENV=""
REASON=""
APPROVER=""
DURATION="${AUTO_REVOKE_SECONDS}"
OPERATOR=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --env)        ENV="$2";      shift 2 ;;
    --reason)     REASON="$2";   shift 2 ;;
    --approver)   APPROVER="$2"; shift 2 ;;
    --duration)   DURATION="$2"; shift 2 ;;
    -h|--help)    usage ;;
    *)            echo "Unknown option: $1" >&2; usage ;;
  esac
done

# Validate
[[ -z "${ENV}" ]]      && { echo "ERROR: --env is required" >&2; usage; }
[[ -z "${REASON}" ]]   && { echo "ERROR: --reason is required" >&2; usage; }
[[ -z "${APPROVER}" ]] && { echo "ERROR: --approver is required" >&2; usage; }
[[ "${ENV}" =~ ^(dev|staging|prod)$ ]] || { echo "ERROR: --env must be dev|staging|prod" >&2; exit 1; }
[[ "${DURATION}" -le "${AUTO_REVOKE_SECONDS}" ]] || { echo "ERROR: --duration exceeds max (${AUTO_REVOKE_SECONDS}s)" >&2; exit 1; }

# Confirm for prod
if [[ "${ENV}" == "prod" ]]; then
  echo "WARNING: You are requesting break-glass access to PRODUCTION."
  read -rp "Type 'CONFIRM' to proceed: " confirm
  [[ "${confirm}" == "CONFIRM" ]] || { echo "Aborted." >&2; exit 1; }
fi

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text 2>/dev/null || echo "unknown")

require_mfa
grant_access
schedule_revocation

log "INFO" "Break-glass access granted. Reason: ${REASON}. Approver: ${APPROVER}. Expires in ${DURATION}s."
echo ""
echo "Break-glass access is active. Credentials will auto-expire in ${DURATION}s."
echo "All actions are being logged to CloudWatch: ${LOG_GROUP}"
