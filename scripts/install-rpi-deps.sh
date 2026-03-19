#!/usr/bin/env bash

set -euo pipefail

VENV_DIR=".venv"
SYSTEM_ONLY=0
SKIP_APT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --system-only)
      SYSTEM_ONLY=1
      shift
      ;;
    --skip-apt)
      SKIP_APT=1
      shift
      ;;
    --venv-dir)
      VENV_DIR="${2:-.venv}"
      shift 2
      ;;
    *)
      echo "Argumento no reconocido: $1" >&2
      echo "Uso: $0 [--system-only] [--skip-apt] [--venv-dir .venv]" >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

echo
echo "==> Instalando dependencias para Raspberry Pi 4"
echo "Repo: ${REPO_ROOT}"

if [[ "${SKIP_APT}" -eq 0 ]]; then
  if ! command -v sudo >/dev/null 2>&1; then
    echo "sudo no esta disponible. Instala paquetes base manualmente o ejecuta como root." >&2
    exit 1
  fi

  echo
  echo "==> Instalando paquetes del sistema"
  sudo apt-get update
  sudo apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    git \
    build-essential \
    libffi-dev \
    libssl-dev
fi

if [[ "${SYSTEM_ONLY}" -eq 1 ]]; then
  echo
  echo "Instalacion de sistema completa. Se omitio la parte Python/venv por --system-only."
  exit 0
fi

echo
echo "==> Creando entorno virtual en ${VENV_DIR}"
python3 -m venv "${VENV_DIR}"

VENV_PYTHON="${REPO_ROOT}/${VENV_DIR}/bin/python"
VENV_PIP="${REPO_ROOT}/${VENV_DIR}/bin/pip"

echo
echo "==> Actualizando pip/setuptools/wheel"
"${VENV_PYTHON}" -m pip install --upgrade pip setuptools wheel

echo
echo "==> Instalando dependencias Python"
"${VENV_PIP}" install -r requirements.txt

echo
echo "Instalacion lista."
echo
echo "Activar entorno:"
echo "source ${VENV_DIR}/bin/activate"
echo
echo "Levantar microservicios:"
echo "./scripts/start-microservices-rpi.sh"
echo
echo "Levantar tambien la web:"
echo "./scripts/start-microservices-rpi.sh --with-web"
