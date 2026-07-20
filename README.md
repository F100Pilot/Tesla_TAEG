# Verificador de TAEG — Tesla Model 3 (Portugal) 🚗⚡

Aplicação simples que, **todos os dias**, verifica no site da Tesla Portugal se
existe alguma **promoção de financiamento a crédito** (TAEG / TAN 0% / campanhas
sem juros) para a compra de um **Model 3**. Quando deteta uma promoção nova — ou
uma mudança nas condições — envia-te um **email**.

Corre num **container LXC no Proxmox** (ou noutra máquina em casa), agendado uma
vez por dia.

---

> ℹ️ **Porque não corre no GitHub/cloud?** A Tesla bloqueia (HTTP 403) os pedidos
> vindos de IPs de datacenter (GitHub Actions, VPS, Cloudflare, etc.). Só passam
> IPs **residenciais**. Por isso a forma gratuita e fiável é correr a partir de
> casa (o teu Proxmox), onde o IP é residencial. A partir de casa, a página é
> aberta num **browser headless (Chromium)** para executar o JavaScript e ler os
> valores. *(Alternativa: manter no GitHub Actions com um plano **pago** de
> proxies residenciais — ver o fim deste ficheiro.)*

## Como funciona

1. Uma vez por dia, um *timer* do systemd corre o script [`check_tesla_taeg.py`](check_tesla_taeg.py).
2. O script abre as páginas do Model 3 (Tesla PT) num Chromium headless e procura:
   - valores de **TAEG** e **TAN**;
   - palavras de campanha: *"TAN 0%"*, *"sem juros"*, *"campanha"*, *"promoção"*,
     *"condições especiais"*, *"taxa reduzida"*, etc.
3. Guarda uma "impressão digital" do resultado em [`state.json`](state.json).
4. **Só te envia email quando há uma promoção e algo mudou** desde a última
   verificação — para não receberes email repetido todos os dias.

> ⚠️ É uma ferramenta de apoio/alerta. **Confirma sempre as condições reais
> diretamente no site oficial da Tesla** antes de qualquer decisão.

---

## Instalação no Proxmox (container LXC)

### 1. Criar o container (na consola do host Proxmox)

Cria um container **Debian 12**. Pela interface web do Proxmox (*Create CT*) ou
pela linha de comandos do host (ajusta o `--storage`, `--bridge` e a password):

```bash
# Descarregar o template Debian 12, se ainda não o tiveres
pveam update && pveam download local debian-12-standard_12.7-1_amd64.tar.zst

# Criar o container (ID 200 como exemplo). DHCP na tua rede = IP residencial.
pct create 200 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname tesla-taeg \
  --cores 2 --memory 1024 --swap 512 \
  --rootfs local-lvm:8 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --features nesting=1 \
  --unprivileged 1 \
  --password

pct start 200
pct enter 200      # entra no container como root
```

> O `--features nesting=1` ajuda o Chromium a arrancar dentro do LXC.

### 2. Instalar a aplicação (dentro do container)

```bash
apt-get update && apt-get install -y curl
curl -fsSL https://raw.githubusercontent.com/F100Pilot/Tesla_TAEG/main/deploy/install.sh -o install.sh
bash install.sh
```

O script instala tudo (Python, Chromium, dependências), agenda a verificação
**diária às 20:00** e cria o ficheiro de credenciais.

### 3. Pôr as credenciais do Gmail

```bash
nano /etc/tesla-taeg.env      # define GMAIL_USER e GMAIL_APP_PASSWORD
```

(Como obter a App Password: ver a secção do Gmail mais abaixo.)

### 4. Testar

```bash
systemctl start tesla-taeg.service           # corre já uma verificação
journalctl -u tesla-taeg.service -n 60 --no-pager   # ver o resultado
systemctl list-timers tesla-taeg.timer       # ver quando corre a seguir
```

Para **mudar a hora**, edita `OnCalendar` em
`/etc/systemd/system/tesla-taeg.timer` e corre `systemctl daemon-reload`.

Para **atualizar** o código mais tarde: volta a correr `bash install.sh` (faz
`git pull` e reinstala).

---

## Credenciais do Gmail

O email é enviado através do Gmail. Precisas de uma **App Password**.

1. A conta Gmail precisa de ter a **verificação em 2 passos** ativada:
   <https://myaccount.google.com/security>
2. Vai a <https://myaccount.google.com/apppasswords>
3. Cria uma password de app (ex.: nome "Tesla TAEG"). Vais receber um código de
   **16 letras** (ex.: `abcd efgh ijkl mnop`).
4. Cola essa password em `/etc/tesla-taeg.env` (variável `GMAIL_APP_PASSWORD`),
   **sem espaços**.

---

## Correr à mão / testar (em qualquer máquina)

```bash
pip install -r requirements.txt
python -m playwright install --with-deps chromium

export GMAIL_USER="pflm.bet@gmail.com"
export GMAIL_APP_PASSWORD="abcdefghijklmnop"   # App Password sem espaços

python check_tesla_taeg.py            # verificação normal (email só se mudar)
python check_tesla_taeg.py --force    # envia email com o estado atual
python check_tesla_taeg.py --dry-run  # não envia email; só mostra o resultado
```

> Tem de ser a partir de um **IP residencial** (casa). De um IP de datacenter a
> Tesla devolve 403.

---

## Personalização

Abre [`check_tesla_taeg.py`](check_tesla_taeg.py):

- **`URLS`** — páginas verificadas. Podes adicionar/remover URLs da Tesla PT.
- **`PROMO_KEYWORDS`** — expressões que sinalizam uma campanha.
- Hora da verificação: `OnCalendar` em `deploy/tesla-taeg.timer`
  (ou, no container, `/etc/systemd/system/tesla-taeg.timer`).

---

## Ficheiros

| Ficheiro | Descrição |
|----------|-----------|
| `check_tesla_taeg.py` | Script principal (browser headless + deteção + email). |
| `deploy/install.sh` | Instalador para o container LXC (Proxmox). |
| `deploy/tesla-taeg.service` / `.timer` | Serviço + agendamento diário (systemd). |
| `deploy/tesla-taeg.env.example` | Modelo do ficheiro de credenciais. |
| `requirements.txt` | Dependências Python. |
| `state.json` | Estado da última verificação (criado/atualizado automaticamente). |
| `.github/workflows/daily-taeg-check.yml` | Execução manual na cloud (opcional; requer proxy pago). |

---

## Opcional — correr na cloud (GitHub Actions) com proxy pago

Se preferires não depender de uma máquina em casa, podes correr no GitHub Actions
usando um serviço de scraping com **proxies residenciais pagos** (o plano
gratuito **não** chega — a Tesla exige IPs residenciais):

1. Subscreve um plano pago em [ScraperAPI](https://www.scraperapi.com/) (ou
   [ZenRows](https://www.zenrows.com/) / [ScrapingBee](https://www.scrapingbee.com/)).
2. Em **Settings → Secrets and variables → Actions**, adiciona os secrets
   `SCRAPERAPI_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD` (e `NOTIFY_EMAIL`, opcional).
3. Reativa o agendamento em
   [`.github/workflows/daily-taeg-check.yml`](.github/workflows/daily-taeg-check.yml)
   (adiciona de volta o bloco `schedule:`), ou corre manualmente em **Actions →
   Run workflow**.

Quando `SCRAPERAPI_KEY` está definida, o script usa a API (com proxies
residenciais). Sem ela, usa o browser headless local.

---

## Notas técnicas

- A Tesla renderiza o conteúdo por JavaScript, por isso usamos um Chromium
  headless (Playwright). O script procura os termos no HTML renderizado (texto
  visível + JSON embebido). Se a Tesla mudar a estrutura das páginas e deixares
  de receber alertas, pode ser necessário atualizar as `URLS` ou os
  `PROMO_KEYWORDS`.
- Nenhuma credencial fica no código — ficam em `/etc/tesla-taeg.env` (fora do git)
  ou nos *secrets* do GitHub.
