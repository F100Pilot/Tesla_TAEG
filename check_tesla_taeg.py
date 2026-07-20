#!/usr/bin/env python3
"""Verificador diário de promoções de TAEG / financiamento do Tesla Model 3 em Portugal.

Abre as páginas públicas da Tesla Portugal num browser real (Chromium via
Playwright — necessário porque a Tesla bloqueia pedidos HTTP simples com um
403), procura menções a financiamento a crédito (TAEG, TAN, 0%, campanha, sem
juros, etc.) e envia um email quando é detetada uma promoção nova ou quando os
detalhes mudam face à última verificação.

Uso:
    python check_tesla_taeg.py            # verificação normal (email só se mudar)
    python check_tesla_taeg.py --force    # envia email com o estado atual, mesmo sem mudanças
    python check_tesla_taeg.py --dry-run  # não envia email, apenas imprime o resultado

Configuração por variáveis de ambiente (ver README.md):
    GMAIL_USER          -> conta Gmail que envia (ex: pflm.bet@gmail.com)
    GMAIL_APP_PASSWORD  -> App Password de 16 caracteres do Gmail
    NOTIFY_EMAIL        -> destinatário (por omissão = GMAIL_USER)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import smtplib
import ssl
import sys
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuração
# --------------------------------------------------------------------------- #

# Páginas da Tesla Portugal onde costumam aparecer condições de financiamento.
URLS = [
    "https://www.tesla.com/pt_PT/model3/design",
    "https://www.tesla.com/pt_PT/model3",
]

STATE_FILE = Path(__file__).with_name("state.json")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Palavras/expressões que indiciam uma PROMOÇÃO de financiamento (não apenas a
# divulgação legal normal). Se alguma destas aparecer, consideramos que há campanha.
PROMO_KEYWORDS = [
    r"tan\s*(?:de\s*)?0\s*%",
    r"0\s*%\s*(?:de\s*)?(?:tan|juros)",
    r"sem\s*juros",
    r"campanha",
    r"promo(?:ção|ções|cional)",
    r"oferta\s*de\s*financiamento",
    r"condições\s*especiais",
    r"taxa\s*reduzida",
]

# Padrões para extrair valores concretos.
RE_TAEG = re.compile(r"TAEG[^0-9%]{0,30}?([0-9]+(?:[.,][0-9]+)?)\s*%", re.IGNORECASE)
RE_TAN = re.compile(r"\bTAN\b[^0-9%]{0,30}?([0-9]+(?:[.,][0-9]+)?)\s*%", re.IGNORECASE)
RE_PROMO = re.compile("|".join(PROMO_KEYWORDS), re.IGNORECASE)

NAV_TIMEOUT = 60_000  # ms


# --------------------------------------------------------------------------- #
# Scraping / render com Playwright
# --------------------------------------------------------------------------- #

def render(url: str) -> tuple[str, str] | None:
    """Abre `url` num Chromium headless e devolve (texto_visivel, html).

    Devolve None se a página não puder ser carregada.
    """
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="pt-PT",
            timezone_id="Europe/Lisbon",
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            status = resp.status if resp else "?"
            print(f"  HTTP {status} — {url}")

            # Aceitar banner de cookies, se existir (não é crítico).
            for label in ("Aceitar todos", "Aceitar", "Accept all", "Accept"):
                try:
                    btn = page.get_by_role("button", name=re.compile(label, re.IGNORECASE))
                    if btn.count():
                        btn.first.click(timeout=3000)
                        break
                except Exception:  # noqa: BLE001
                    pass

            # Dar tempo ao JavaScript para carregar preços/financiamento.
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PWTimeout:
                pass

            # Tentar abrir detalhes de financiamento/pagamentos, se houver link.
            for label in ("Financiamento", "financ", "pagament", "Como são calculados"):
                try:
                    el = page.get_by_text(re.compile(label, re.IGNORECASE))
                    if el.count():
                        el.first.click(timeout=2500)
                        page.wait_for_timeout(1500)
                        break
                except Exception:  # noqa: BLE001
                    pass

            html = page.content()
            text = page.evaluate("() => document.body ? document.body.innerText : ''")
            return text or "", html or ""
        except PWTimeout:
            print(f"  [erro] Timeout ao carregar {url}", file=sys.stderr)
            return None
        except Exception as exc:  # noqa: BLE001
            print(f"  [erro] Falha ao carregar {url}: {exc}", file=sys.stderr)
            return None
        finally:
            context.close()
            browser.close()


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def snippet_around(text: str, index: int, radius: int = 110) -> str:
    start = max(0, index - radius)
    end = min(len(text), index + radius)
    return collapse_whitespace(text[start:end]).strip()


def analyse(url: str, text: str, html: str) -> dict:
    """Analisa o conteúdo renderizado de uma página à procura de sinais de TAEG."""
    visible = collapse_whitespace(text)
    full = collapse_whitespace(html)  # apanha também JSON/atributos embebidos

    # Valores: procurar primeiro no texto visível, depois no HTML completo.
    taeg_values = sorted(
        {m.group(1).replace(",", ".") for m in RE_TAEG.finditer(visible)}
        or {m.group(1).replace(",", ".") for m in RE_TAEG.finditer(full)}
    )
    tan_values = sorted(
        {m.group(1).replace(",", ".") for m in RE_TAN.finditer(visible)}
        or {m.group(1).replace(",", ".") for m in RE_TAN.finditer(full)}
    )

    promo_hits = []
    for m in RE_PROMO.finditer(visible):
        promo_hits.append(snippet_around(visible, m.start()))
    seen = set()
    promo_hits = [s for s in promo_hits if not (s in seen or seen.add(s))]

    mentions_financing = bool(
        re.search(r"financiamento|crédito|credito|TAEG|\bTAN\b", visible, re.IGNORECASE)
    )
    has_promo = bool(promo_hits) or "0" in tan_values or "0.0" in tan_values

    print(
        f"  → financiamento={mentions_financing} TAEG={taeg_values or '—'} "
        f"TAN={tan_values or '—'} promo={has_promo} (texto: {len(visible)} chars)"
    )

    return {
        "url": url,
        "mentions_financing": mentions_financing,
        "taeg_values": taeg_values,
        "tan_values": tan_values,
        "promo_snippets": promo_hits[:8],
        "has_promo": has_promo,
    }


def run_checks() -> dict:
    """Corre a análise em todas as URLs e devolve um relatório agregado."""
    pages = []
    for url in URLS:
        print(f"A verificar: {url}")
        rendered = render(url)
        if rendered is None:
            pages.append({"url": url, "error": "não acessível", "has_promo": False})
            continue
        text, html = rendered
        pages.append(analyse(url, text, html))

    any_promo = any(p.get("has_promo") for p in pages)
    all_taeg = sorted({v for p in pages for v in p.get("taeg_values", [])})
    all_tan = sorted({v for p in pages for v in p.get("tan_values", [])})

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "promotion_detected": any_promo,
        "taeg_values": all_taeg,
        "tan_values": all_tan,
        "pages": pages,
    }


def signature(report: dict) -> str:
    """Assinatura estável do 'conteúdo relevante' para detetar mudanças."""
    relevant = {
        "promotion_detected": report["promotion_detected"],
        "taeg_values": report["taeg_values"],
        "tan_values": report["tan_values"],
        "promo": sorted(
            {s for p in report["pages"] for s in p.get("promo_snippets", [])}
        ),
    }
    blob = json.dumps(relevant, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Estado
# --------------------------------------------------------------------------- #

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# Email
# --------------------------------------------------------------------------- #

def build_email_body(report: dict) -> str:
    lines = []
    if report["promotion_detected"]:
        lines.append("✅ Foi detetada uma POSSÍVEL promoção de financiamento no Tesla Model 3 (Portugal).")
    else:
        lines.append("ℹ️ Estado do financiamento do Tesla Model 3 (Portugal) — sem promoção clara detetada.")
    lines.append("")
    lines.append(f"Verificado em (UTC): {report['checked_at']}")
    if report["taeg_values"]:
        lines.append(f"Valores de TAEG encontrados: {', '.join(v + '%' for v in report['taeg_values'])}")
    if report["tan_values"]:
        lines.append(f"Valores de TAN encontrados: {', '.join(v + '%' for v in report['tan_values'])}")
    lines.append("")

    for page in report["pages"]:
        lines.append(f"— {page['url']}")
        if page.get("error"):
            lines.append(f"    (não foi possível aceder: {page['error']})")
            continue
        if page.get("taeg_values"):
            lines.append(f"    TAEG: {', '.join(v + '%' for v in page['taeg_values'])}")
        if page.get("tan_values"):
            lines.append(f"    TAN: {', '.join(v + '%' for v in page['tan_values'])}")
        if page.get("has_promo"):
            lines.append("    ⭐ Sinais de promoção nesta página.")
        for snip in page.get("promo_snippets", []):
            lines.append(f"    • ...{snip}...")
        if not page.get("promo_snippets") and not page.get("has_promo"):
            lines.append("    (sem sinais de campanha)")
    lines.append("")
    lines.append("Confirma sempre as condições diretamente no site oficial da Tesla:")
    lines.append("https://www.tesla.com/pt_PT/model3")
    lines.append("")
    lines.append("— Verificador automático de TAEG (GitHub Actions)")
    return "\n".join(lines)


def send_email(subject: str, body: str) -> bool:
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("NOTIFY_EMAIL") or user

    if not user or not password:
        print(
            "[aviso] GMAIL_USER / GMAIL_APP_PASSWORD não definidos — email não enviado.",
            file=sys.stderr,
        )
        return False

    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = recipient

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(user, password)
            server.sendmail(user, [recipient], msg.as_string())
        print(f"Email enviado para {recipient}.")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[erro] Falha ao enviar email: {exc}", file=sys.stderr)
        return False


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Enviar email mesmo sem mudanças.")
    parser.add_argument("--dry-run", action="store_true", help="Não enviar email; só imprimir.")
    args = parser.parse_args()

    report = run_checks()
    sig = signature(report)

    print("\n" + "=" * 60)
    print(build_email_body(report))
    print("=" * 60 + "\n")

    prev = load_state()
    changed = prev.get("signature") != sig
    first_run = "signature" not in prev

    should_notify = args.force or (report["promotion_detected"] and changed)

    if args.dry_run:
        print("[dry-run] Email NÃO enviado.")
    elif should_notify:
        if report["promotion_detected"]:
            subject = "🚗 Tesla Model 3 PT — possível promoção de TAEG detetada!"
        else:
            subject = "Tesla Model 3 PT — estado do financiamento (forçado)"
        send_email(subject, build_email_body(report))
    else:
        reason = "sem promoção" if not report["promotion_detected"] else "sem mudanças desde a última verificação"
        print(f"Sem notificação ({reason}).")

    new_state = {
        "signature": sig,
        "last_checked": report["checked_at"],
        "promotion_detected": report["promotion_detected"],
        "taeg_values": report["taeg_values"],
        "tan_values": report["tan_values"],
        "last_report": report,
        "history": (prev.get("history", []) + [
            {
                "checked_at": report["checked_at"],
                "promotion_detected": report["promotion_detected"],
                "taeg_values": report["taeg_values"],
                "tan_values": report["tan_values"],
                "changed": changed and not first_run,
            }
        ])[-30:],
    }
    save_state(new_state)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write("## Verificador TAEG — Tesla Model 3 (PT)\n\n")
            fh.write(f"- **Promoção detetada:** {'✅ Sim' if report['promotion_detected'] else '❌ Não'}\n")
            fh.write(f"- **TAEG:** {', '.join(v + '%' for v in report['taeg_values']) or '—'}\n")
            fh.write(f"- **TAN:** {', '.join(v + '%' for v in report['tan_values']) or '—'}\n")
            fh.write(f"- **Notificação enviada:** {'Sim' if should_notify and not args.dry_run else 'Não'}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
