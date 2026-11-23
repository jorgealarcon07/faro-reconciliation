"""Localized labels for the offline report."""

import json
import re
from html import escape

COPY = {
    "text_title": ("Faro · Conciliación", "Faro · Payment reconciliation"),
    "text_brand": ("Faro · Operaciones de pagos", "Faro · Payment operations"),
    "text_heading": ("Conciliación y excepciones", "Reconciliation and exceptions"),
    "text_units": ("@@CASE@@ · COP · unidades menores", "@@CASE@@ · COP · minor units"),
    "text_notice": (
        "Datos sintéticos. La diferencia de cobertura de una factura requiere contexto comercial.",
        "Synthetic data. An invoice coverage gap requires commercial context.",
    ),
    "text_views": ("Vistas de conciliación", "Reconciliation views"),
    "text_payouts": ("Abonos", "Payouts"),
    "text_queue": ("Cola de excepciones", "Exception queue"),
    "text_trace": ("Trazabilidad", "Audit trail"),
    "text_lot_state": ("Estado de los lotes", "Payout batch status"),
    "text_state": ("Estado", "Status"),
    "text_all": ("Todos", "All"),
    "text_reconciled": ("Conciliado", "Reconciled"),
    "text_exception": ("Excepción", "Exception"),
    "text_provisional": ("Provisional", "Provisional"),
    "text_payout_csv": ("Descargar abonos CSV", "Download payouts CSV"),
    "text_invoice_csv": ("Descargar cobertura CSV", "Download invoice coverage CSV"),
    "text_open_issues": ("Excepciones abiertas", "Open exceptions"),
    "text_priority": (
        "Prioridad por antigüedad y magnitud de la diferencia. La resolución requiere "
        "evidencia aplicada.",
        "Prioritized by age and discrepancy size. Resolving an exception requires "
        "evidence of an applied correction.",
    ),
    "text_queue_csv": ("Descargar cola CSV", "Download exception queue CSV"),
    "text_movements": ("Movimientos que explican el abono", "Transactions behind this payout"),
    "text_deliveries": ("Entregas recibidas", "Event deliveries received"),
    "text_audit": ("Auditoría y evidencia de resolución", "Audit and resolution evidence"),
    "text_license": ("Simulación CC0 ·", "CC0 simulation ·"),
    "text_json": ("Datos y trazabilidad JSON", "Download data and audit trail JSON"),
    "js_locale": ("es-CO", "en-US"),
    "js_reconciled": ("Conciliado", "Reconciled"),
    "js_exception": ("Excepción", "Exception"),
    "js_provisional": ("Provisional", "Provisional"),
    "js_empty": ("Sin registros", "No records"),
    "js_audited": ("Entregas auditadas", "Audited deliveries"),
    "js_matches": ("Lotes conciliados", "Reconciled batches"),
    "js_open": ("Excepciones abiertas", "Open exceptions"),
    "js_duplicates": ("Entregas repetidas", "Repeated deliveries"),
    "js_payout": ("Abono", "Payout"),
    "js_state": ("Estado", "Status"),
    "js_expected": ("Esperado", "Expected"),
    "js_declared": ("Declarado", "Declared"),
    "js_difference": ("Diferencia", "Difference"),
    "js_of": (" de ", " of "),
    "js_filtered": (
        " lotes filtrados. El CSV incluye todos los lotes.",
        " matching batches shown. The CSV includes every batch.",
    ),
    "js_reason": ("Motivo", "Reason"),
    "js_reference": ("Referencia", "Reference"),
    "js_first_seen": ("Primera detección UTC", "First detected (UTC)"),
    "js_payout_prefix": ("Abono ", "Payout "),
    "js_no_focus": ("Abono sin detalle", "No payout details"),
    "js_expected_suffix": (" esperado · ", " expected · "),
    "js_declared_suffix": (" declarado", " declared"),
    "js_cli": (
        "Consulta la CLI para abrir otro lote.",
        "Use the CLI to inspect a different batch.",
    ),
    "js_type": ("Tipo", "Type"),
    "js_effect": ("Efecto", "Effect"),
    "js_signed": ("Importe firmado", "Signed amount"),
    "js_position": ("Posición", "Position"),
    "js_event": ("Evento", "Event"),
    "js_received": ("Recepción UTC", "Received (UTC)"),
    "js_action": ("Acción", "Action"),
    "js_role": ("Rol", "Role"),
    "js_evidence": ("Evidencia", "Evidence"),
    "js_capture": ("Captura", "Capture"),
    "js_refund": ("Devolución", "Refund"),
    "js_fee": ("Comisión", "Fee"),
    "js_projection": ("Recálculo", "Recalculation"),
    "js_resolution": ("Resolución", "Resolution"),
    "js_event_payload_conflict": ("Conflicto de contenido del evento", "Conflicting event payload"),
    "js_missing_declared_effect": ("Falta un movimiento declarado", "Declared effect is missing"),
    "js_missing_invoice": ("Falta la factura", "Invoice is missing"),
    "js_payout_mismatch": ("El abono no cuadra", "Payout does not match"),
    "js_refunds_exceed_capture": (
        "Las devoluciones exceden la captura",
        "Refunds exceed the capture",
    ),
    "js_recomputed": (
        "Recalculado a partir de entregas inmutables",
        "Recomputed from immutable receipts",
    ),
    "js_demo_resolution": (
        "La declaración revisada coincide con captura, devolución y comisión.",
        "The revised declaration matches the capture, refund and fee.",
    ),
}


REPORT_FILES = {"es": "index.html", "en": "index.en.html"}


def labels(language):
    if language not in REPORT_FILES:
        raise ValueError(f"Unsupported report language: {language}")
    column = 0 if language == "es" else 1
    return {key: pair[column] for key, pair in COPY.items()}


def localize(template, language):
    copy = labels(language)
    alternate = "en" if language == "es" else "es"
    html = {
        **{key: escape(value) for key, value in copy.items()},
        "lang": language,
        "other_lang": alternate,
        "other_file": REPORT_FILES[alternate],
        "other_label": "English" if alternate == "en" else "Español",
    }
    js_copy = {key: value for key, value in copy.items() if key.startswith("js_")}
    html["js_copy"] = json.dumps(js_copy, ensure_ascii=False).replace("<", r"\u003c")

    return re.sub(r"@@([a-z_]+)@@", lambda match: html[match[1]], template)
