#!/usr/bin/env bash

set -euo pipefail

BASE_PORT=8010
WITH_WEB=0
HOST="0.0.0.0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-web)
      WITH_WEB=1
      shift
      ;;
    --base-port)
      BASE_PORT="${2:-8010}"
      shift 2
      ;;
    --host)
      HOST="${2:-0.0.0.0}"
      shift 2
      ;;
    *)
      echo "Argumento no reconocido: $1" >&2
      echo "Uso: $0 [--with-web] [--base-port 8010] [--host 0.0.0.0]" >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICES_DIR="${REPO_ROOT}/services"
RUNTIME_DIR="${REPO_ROOT}/.runtime"
LOG_DIR="${RUNTIME_DIR}/logs"
PID_DIR="${RUNTIME_DIR}/pids"

mkdir -p "${LOG_DIR}" "${PID_DIR}"

if [[ ! -d "${SERVICES_DIR}" ]]; then
  echo "No existe la carpeta services/: ${SERVICES_DIR}" >&2
  exit 1
fi

mapfile -t SERVICE_DIRS < <(
  find "${SERVICES_DIR}" -mindepth 1 -maxdepth 1 -type d | sort
)

declare -a SERVICES=()
for service_path in "${SERVICE_DIRS[@]}"; do
  service_name="$(basename "${service_path}")"
  if [[ -f "${service_path}/app.py" ]]; then
    SERVICES+=("${service_name}")
  fi
done

if [[ ${#SERVICES[@]} -eq 0 ]]; then
  echo "No se encontraron microservicios en services/ con app.py"
  exit 0
fi

declare -A KNOWN_PORTS=(
  ["execution_service"]=8010
  ["market_data_service"]=8020
  ["ai_filter_service"]=8030
  ["signal_engine"]=8040
  ["news_service"]=8050
)

declare -A ASSIGNED_PORTS=()
next_dynamic_port="${BASE_PORT}"

for service_name in "${SERVICES[@]}"; do
  if [[ -n "${KNOWN_PORTS[$service_name]:-}" ]]; then
    ASSIGNED_PORTS["${service_name}"]="${KNOWN_PORTS[$service_name]}"
    continue
  fi

  while printf '%s\n' "${ASSIGNED_PORTS[@]}" | grep -qx "${next_dynamic_port}"; do
    next_dynamic_port=$((next_dynamic_port + 10))
  done

  ASSIGNED_PORTS["${service_name}"]="${next_dynamic_port}"
  next_dynamic_port=$((next_dynamic_port + 10))
done

is_running() {
  local pid_file="$1"
  if [[ ! -f "${pid_file}" ]]; then
    return 1
  fi

  local pid
  pid="$(cat "${pid_file}")"
  if [[ -z "${pid}" ]]; then
    return 1
  fi

  kill -0 "${pid}" 2>/dev/null
}

launch_service() {
  local name="$1"
  local module="$2"
  local port="$3"

  local pid_file="${PID_DIR}/${name}.pid"
  local log_file="${LOG_DIR}/${name}.log"

  if is_running "${pid_file}"; then
    local existing_pid
    existing_pid="$(cat "${pid_file}")"
    printf '%-22s %-8s %-8s %s\n' "${name}" "${port}" "running" "pid=${existing_pid}"
    return
  fi

  (
    cd "${REPO_ROOT}"
    nohup python3 -m uvicorn "${module}" --host "${HOST}" --port "${port}" \
      >"${log_file}" 2>&1 &
    echo $! > "${pid_file}"
  )

  local pid
  pid="$(cat "${pid_file}")"
  printf '%-22s %-8s %-8s %s\n' "${name}" "${port}" "started" "pid=${pid}"
}

echo
printf '%-22s %-8s %-8s %s\n' "service" "port" "status" "detail"
printf '%-22s %-8s %-8s %s\n' "----------------------" "--------" "--------" "------------------------------"

for service_name in "${SERVICES[@]}"; do
  launch_service "${service_name}" "services.${service_name}.app:app" "${ASSIGNED_PORTS[$service_name]}"
done

if [[ "${WITH_WEB}" -eq 1 ]]; then
  launch_service "dashboard_web" "bot_trading_news.service:app" "8000"
fi

echo
echo "Logs: ${LOG_DIR}"
echo "PIDs: ${PID_DIR}"
echo
echo "Tip:"
echo "Agrega EXECUTION_SERVICE_URL=http://127.0.0.1:8010 en .env para que la app use execution_service."
echo "Tambien podes agregar NEWS_SERVICE_URL=http://127.0.0.1:8050, AI_FILTER_SERVICE_URL=http://127.0.0.1:8030, MARKET_DATA_SERVICE_URL=http://127.0.0.1:8020 y SIGNAL_ENGINE_URL=http://127.0.0.1:8040."
