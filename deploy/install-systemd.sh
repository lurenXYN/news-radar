#!/usr/bin/env bash
# Install news-radar as a systemd service on Linux.
#
# Usage:
#   ./deploy/install-systemd.sh
# Optional:
#   INSTALL_DIR=/opt/news-radar HOST=0.0.0.0 PORT=8770 ./deploy/install-systemd.sh
#   INSTALL_DIR="$PWD" ./deploy/install-systemd.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${INSTALL_DIR:-/opt/news-radar}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8770}"
SERVICE_USER="${SERVICE_USER:-$(id -un)}"
UNIT_NAME="news-radar.service"
UNIT_DST="/etc/systemd/system/${UNIT_NAME}"
AS_ROOT=0
if [[ "$(id -u)" -eq 0 ]]; then
  AS_ROOT=1
fi

run_root() {
  if [[ "$AS_ROOT" -eq 1 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

run_as_service_user() {
  local cmd="$1"
  if [[ "$AS_ROOT" -eq 1 ]]; then
    if [[ "$SERVICE_USER" == "root" ]] || [[ "$(id -un)" == "$SERVICE_USER" ]]; then
      bash -lc "$cmd"
    else
      runuser -u "$SERVICE_USER" -- bash -lc "$cmd" 2>/dev/null \
        || su -s /bin/bash "$SERVICE_USER" -c "$cmd"
    fi
  else
    if [[ "$(id -un)" == "$SERVICE_USER" ]]; then
      bash -lc "$cmd"
    else
      sudo -u "$SERVICE_USER" bash -lc "$cmd"
    fi
  fi
}

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found. Use ./start.sh for foreground runs."
  exit 1
fi

if [[ "$AS_ROOT" -eq 0 ]] && ! command -v sudo >/dev/null 2>&1; then
  echo "Need sudo, or re-run as root."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install: apt install -y python3 python3-venv python3-pip"
  exit 1
fi

venv_has_pip() {
  local py="$1"
  [[ -x "$py" ]] && "$py" -m pip --version >/dev/null 2>&1
}

ensure_python_venv() {
  local probe py_ver
  py_ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  probe="$(mktemp -d)"
  if python3 -m venv "$probe/v" >/dev/null 2>&1 && venv_has_pip "$probe/v/bin/python"; then
    rm -rf "$probe"
    return 0
  fi
  rm -rf "$probe"

  echo "python3-venv / ensurepip incomplete."
  if command -v apt-get >/dev/null 2>&1; then
    echo "Installing python${py_ver}-venv python3-venv python3-pip ..."
    run_root apt-get update -y
    run_root apt-get install -y "python${py_ver}-venv" python3-venv python3-pip || \
      run_root apt-get install -y python3-venv python3-pip
  else
    echo "  Debian/Ubuntu: apt install -y python${py_ver}-venv python3-pip"
    exit 1
  fi

  probe="$(mktemp -d)"
  if ! python3 -m venv "$probe/v" >/dev/null 2>&1; then
    rm -rf "$probe"
    echo "Still cannot create venv."
    exit 1
  fi
  if ! venv_has_pip "$probe/v/bin/python"; then
    "$probe/v/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
  fi
  rm -rf "$probe"
}

bootstrap_venv_pip() {
  local py="$INSTALL_DIR/.venv/bin/python"
  if [[ -x "$py" ]] && venv_has_pip "$py"; then
    return 0
  fi
  echo "Bootstrapping pip inside $INSTALL_DIR/.venv ..."
  run_as_service_user "
    set -euo pipefail
    cd '$INSTALL_DIR'
    if [[ ! -x .venv/bin/python ]]; then
      rm -rf .venv
      python3 -m venv .venv
    fi
    if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
      .venv/bin/python -m ensurepip --upgrade || true
    fi
    if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
      curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
      .venv/bin/python /tmp/get-pip.py
      rm -f /tmp/get-pip.py
    fi
    .venv/bin/python -m pip --version
  "
}

ensure_python_venv

if [[ "$ROOT" != "$INSTALL_DIR" ]] && ! command -v rsync >/dev/null 2>&1; then
  echo "rsync not found. Install: apt install -y rsync"
  exit 1
fi

if [[ "$SERVICE_USER" != "root" ]] && ! id "$SERVICE_USER" >/dev/null 2>&1; then
  echo "Service user '$SERVICE_USER' does not exist."
  exit 1
fi

echo "Install dir : ${INSTALL_DIR}"
echo "Service user: ${SERVICE_USER}"
echo "Bind        : ${HOST}:${PORT}"

if [[ "$ROOT" != "$INSTALL_DIR" ]]; then
  echo "Syncing source -> ${INSTALL_DIR} ..."
  run_root mkdir -p "$INSTALL_DIR"
  run_root rsync -a --delete \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude 'data/' \
    --exclude '.git/' \
    "$ROOT/" "$INSTALL_DIR/"
  run_root mkdir -p "$INSTALL_DIR/data"
  if [[ "$SERVICE_USER" != "root" ]]; then
    run_root chown -R "${SERVICE_USER}:${SERVICE_USER}" "$INSTALL_DIR"
  fi
else
  mkdir -p "$INSTALL_DIR/data"
  if [[ "$AS_ROOT" -eq 1 && "$SERVICE_USER" != "root" ]]; then
    run_root chown -R "${SERVICE_USER}:${SERVICE_USER}" "$INSTALL_DIR"
  fi
fi

echo "Creating venv + installing deps..."
if [[ -d "$INSTALL_DIR/.venv" ]]; then
  if [[ ! -x "$INSTALL_DIR/.venv/bin/python" ]] || ! venv_has_pip "$INSTALL_DIR/.venv/bin/python"; then
    run_root rm -rf "$INSTALL_DIR/.venv"
  fi
fi
run_as_service_user "
  set -euo pipefail
  cd '$INSTALL_DIR'
  if [[ ! -x .venv/bin/python ]]; then
    rm -rf .venv
    python3 -m venv .venv
  fi
"
bootstrap_venv_pip
run_as_service_user "
  set -euo pipefail
  cd '$INSTALL_DIR'
  .venv/bin/python -m pip install -q -U pip
  .venv/bin/python -m pip install -q -r requirements.txt
"

TMP_UNIT="$(mktemp)"
sed \
  -e "s|REPLACE_USER|${SERVICE_USER}|g" \
  -e "s|/opt/news-radar|${INSTALL_DIR}|g" \
  -e "s|--host 0.0.0.0 --port 8770|--host ${HOST} --port ${PORT}|g" \
  "$ROOT/deploy/news-radar.service" > "$TMP_UNIT"

echo "Installing unit -> ${UNIT_DST}"
run_root cp "$TMP_UNIT" "$UNIT_DST"
rm -f "$TMP_UNIT"

run_root systemctl daemon-reload
run_root systemctl enable --now "$UNIT_NAME"
run_root systemctl --no-pager --full status "$UNIT_NAME" || true

echo
echo "Done. Open: http://127.0.0.1:${PORT}/"
echo "Logs:     journalctl -u ${UNIT_NAME} -f"
