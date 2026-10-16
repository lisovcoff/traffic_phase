"""Self-contained HTML consumer of product_result and the common query contract."""
import json
from pathlib import Path

from app.core.product_result import build_product_result
from app.core.state_contract import physical_estimate, prepare_logical_query


def build_report_payload(result, *, history_source='accepted'):
    product = build_product_result(result, history_source=history_source)
    query = prepare_logical_query(result, history_source=history_source)
    states = []
    for start, end, _ in query.segments:
        logical = query.at(start)
        states.append(dict(start=start, end=end, logical_phase=logical.to_dict()))
    for start, end, _ in query.abstention_intervals:
        states.append(dict(start=start, end=end, logical_phase=query.at(start).to_dict()))
    states.sort(key=lambda row: row['start'])
    missing = query.at(-1)
    # Do not ship legacy GREEN/RED proposals or raw event arrays into the UI.
    return dict(schema=product['schema'], phase_count=product['phase_count'],
                input_scope=product['input_scope'],
                period_s=product['period_s'], approaches=product['approaches'],
                unassigned_movements=product['unassigned_movements'], history=product['history'],
                query_timebase=product['query_timebase'], intervals=states,
                fallback_logical_phase=missing.to_dict(),
                physical_section=physical_estimate('UNKNOWN').to_dict(),
                invariant_sha256=product['invariant_sha256'],
                trajectory_count=result.get('trajectory_count'), event_count=result.get('event_count'),
                validation_status='2D.1 FAIL; physical reconstruction unvalidated')


def render_product_html(result, *, history_source='accepted'):
    payload = build_report_payload(result, history_source=history_source)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode('utf-8')) > 8 * 1024 * 1024:
        raise ValueError('HTML_PAYLOAD_BYTE_BUDGET_EXCEEDED')
    # Literal backslash escapes prevent closing the script element via an input label.
    encoded = encoded.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    template = Path(__file__).resolve().parents[1]/'static/v9_offline_report.html'
    return template.read_text(encoding='utf-8').replace('__PRODUCT_DATA__', encoded)
