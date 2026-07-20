# Verificador de TAEG — Tesla Model 3 (Portugal) 🚗⚡

Aplicação simples que, **todos os dias**, verifica no site da Tesla Portugal se
existe alguma **promoção de financiamento a crédito** (TAEG / TAN 0% / campanhas
sem juros) para a compra de um **Model 3**. Quando deteta uma promoção nova — ou
uma mudança nas condições — envia-te um **email**.

Corre automaticamente no **GitHub Actions** (não precisas de deixar nenhum
computador ligado).

---

> ℹ️ **Importante:** a Tesla bloqueia (HTTP 403) os pedidos vindos de servidores/datacenters,
> como os do GitHub Actions. Por isso o verificador usa uma **API de scraping**
> (ScraperAPI, com plano gratuito) que faz o pedido a partir de um IP residencial
> e executa o JavaScript da página. Sem essa chave, o verificador só funciona se
> for corrido a partir de um IP residencial (o teu computador).

## Como funciona

1. Uma vez por dia, o GitHub Actions corre o script [`check_tesla_taeg.py`](check_tesla_taeg.py).
2. O script descarrega as páginas públicas do Model 3 na Tesla Portugal (via ScraperAPI) e procura:
   - valores de **TAEG** e **TAN**;
   - palavras de campanha: *"TAN 0%"*, *"sem juros"*, *"campanha"*, *"promoção"*,
     *"condições especiais"*, *"taxa reduzida"*, etc.
3. Guarda uma "impressão digital" do resultado em [`state.json`](state.json).
4. **Só te envia email quando há uma promoção e algo mudou** desde a última
   verificação — para não receberes email repetido todos os dias.

> ⚠️ É uma ferramenta de apoio/alerta. **Confirma sempre as condições reais
> diretamente no site oficial da Tesla** antes de qualquer decisão.

---

## Configuração (uma vez)

O email é enviado através do Gmail. Precisas de criar uma **App Password** e
guardar 2 secrets no repositório.

### 1. Criar uma App Password do Gmail

1. A conta Gmail precisa de ter a **verificação em 2 passos** ativada:
   <https://myaccount.google.com/security>
2. Vai a <https://myaccount.google.com/apppasswords>
3. Cria uma password de app (ex.: nome "Tesla TAEG"). Vais receber um código de
   **16 letras** (ex.: `abcd efgh ijkl mnop`). Copia-o **sem espaços**.

### 2. Criar uma chave da API de scraping (ScraperAPI — grátis)

1. Vai a <https://www.scraperapi.com/> e cria uma conta gratuita.
2. No painel (dashboard) copia a tua **API Key**.
3. O plano gratuito dá 1.000 créditos/mês — mais do que suficiente para uma
   verificação por dia.

> Alternativas equivalentes: [ZenRows](https://www.zenrows.com/),
> [ScrapingBee](https://www.scrapingbee.com/). Se preferires outra, adapta a
> função `fetch()` em [`check_tesla_taeg.py`](check_tesla_taeg.py).

### 3. Adicionar os secrets no GitHub

No repositório: **Settings → Secrets and variables → Actions → New repository secret**

| Nome do secret       | Valor                                             |
|----------------------|---------------------------------------------------|
| `SCRAPERAPI_KEY`     | A API Key do ScraperAPI                           |
| `GMAIL_USER`         | O teu Gmail (ex.: `pflm.bet@gmail.com`)           |
| `GMAIL_APP_PASSWORD` | A App Password de 16 letras (sem espaços)         |
| `NOTIFY_EMAIL`       | *(opcional)* destinatário; por omissão = `GMAIL_USER` |

### 4. Ativar os GitHub Actions

Vai ao separador **Actions** do repositório e, se pedido, confirma que queres
ativar os workflows. Está agendado para correr **todos os dias às 08:00 UTC**.

---

## Testar / correr manualmente

- **No GitHub:** separador **Actions → "Verificação diária TAEG Tesla Model 3"
  → Run workflow**. Podes marcar a opção *"Enviar email mesmo sem mudanças"*
  para forçar um email de teste.

- **No teu computador:**
  ```bash
  pip install -r requirements.txt

  # Configura as variáveis de ambiente
  export SCRAPERAPI_KEY="a_tua_api_key"          # opcional se correres de casa
  export GMAIL_USER="pflm.bet@gmail.com"
  export GMAIL_APP_PASSWORD="abcdefghijklmnop"   # App Password sem espaços

  python check_tesla_taeg.py            # verificação normal
  python check_tesla_taeg.py --force    # envia email com o estado atual
  python check_tesla_taeg.py --dry-run  # não envia email; só mostra o resultado
  ```

---

## Personalização

Abre [`check_tesla_taeg.py`](check_tesla_taeg.py):

- **`URLS`** — páginas verificadas. Podes adicionar/remover URLs da Tesla PT.
- **`PROMO_KEYWORDS`** — expressões que sinalizam uma campanha.
- Horário: edita o `cron` em
  [`.github/workflows/daily-taeg-check.yml`](.github/workflows/daily-taeg-check.yml)
  (está em UTC).

---

## Ficheiros

| Ficheiro | Descrição |
|----------|-----------|
| `check_tesla_taeg.py` | Script principal (scraping + deteção + email). |
| `.github/workflows/daily-taeg-check.yml` | Agendamento diário no GitHub Actions. |
| `requirements.txt` | Dependências Python. |
| `state.json` | Estado da última verificação (criado/atualizado automaticamente). |

---

## Notas técnicas

- O site da Tesla renderiza muito conteúdo por JavaScript. O script procura os
  termos tanto no texto visível como no JSON embebido nas páginas, o que cobre a
  maioria dos casos. Se a Tesla mudar a estrutura das páginas e deixares de
  receber alertas, pode ser necessário atualizar as `URLS` ou os
  `PROMO_KEYWORDS`.
- Nenhuma credencial fica no código — só nos *secrets* do GitHub.
