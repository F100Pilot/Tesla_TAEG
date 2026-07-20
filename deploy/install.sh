#!/usr/bin/env bash
#
# Instalador do Verificador de TAEG num container LXC Debian 12 (Proxmox).
# Corre este script DENTRO do container, como root.
#
#   bash install.sh
#
# O que faz:
#   - instala Python, git, xvfb e as dependências do Chromium;
#   - clona (ou atualiza) o repositório em /opt/tesla-taeg;
#   - cria um virtualenv e instala requisitos + Chromium stealth (patchright);
#   - instala o serviço + timer do systemd (verificação diária às 20:00);
#   - cria /etc/tesla-taeg.env a partir do exemplo (tens de o editar depois).
#
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/F100Pilot/Tesla_TAEG.git}"
APP_DIR="/opt/tesla-taeg"
ENV_FILE="/etc/tesla-taeg.env"
TZ_REGION="Europe/Lisbon"

echo ">> A definir o fuso horário para ${TZ_REGION}..."
timedatectl set-timezone "${TZ_REGION}" 2>/dev/null || ln -sf "/usr/share/zoneinfo/${TZ_REGION}" /etc/localtime || true

echo ">> A instalar pacotes de sistema..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends git python3 python3-venv python3-pip ca-certificates tzdata xvfb

echo ">> A obter o código para ${APP_DIR}..."
if [ -d "${APP_DIR}/.git" ]; then
  git -C "${APP_DIR}" pull --ff-only
else
  git clone --depth 1 "${REPO_URL}" "${APP_DIR}"
fi

echo ">> A criar o virtualenv e a instalar dependências..."
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip -q
"${APP_DIR}/.venv/bin/pip" install -q -r "${APP_DIR}/requirements.txt"

echo ">> A instalar o Chromium stealth (patchright) + dependências do sistema..."
"${APP_DIR}/.venv/bin/python" -m patchright install --with-deps chromium

echo ">> A instalar o serviço e o timer do systemd..."
install -m 644 "${APP_DIR}/deploy/tesla-taeg.service" /etc/systemd/system/tesla-taeg.service
install -m 644 "${APP_DIR}/deploy/tesla-taeg.timer" /etc/systemd/system/tesla-taeg.timer

if [ ! -f "${ENV_FILE}" ]; then
  echo ">> A criar ${ENV_FILE} (EDITA-O com as tuas credenciais do Gmail)."
  install -m 600 "${APP_DIR}/deploy/tesla-taeg.env.example" "${ENV_FILE}"
else
  echo ">> ${ENV_FILE} já existe — não foi alterado."
fi

systemctl daemon-reload
systemctl enable --now tesla-taeg.timer

cat <<EOF

============================================================
Instalação concluída. ✅

FALTA UM PASSO: edita as credenciais do Gmail em:
    ${ENV_FILE}
  (define GMAIL_USER e GMAIL_APP_PASSWORD)

Comandos úteis:
  • Testar já (envia email de teste):
      systemctl start tesla-taeg.service
      journalctl -u tesla-taeg.service -n 50 --no-pager
  • Ver quando corre a seguir:
      systemctl list-timers tesla-taeg.timer
  • Editar a hora:
      /etc/systemd/system/tesla-taeg.timer  (depois: systemctl daemon-reload)
============================================================
EOF
