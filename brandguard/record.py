"""Printable approval record. Everything user-supplied is HTML-escaped."""
from __future__ import annotations

import datetime as dt
from html import escape as e

STATUS = {"draft": "Draft", "in_review": "In review", "changes_requested": "Changes requested", "approved": "Approved"}
DECISION = {"open": "Not decided", "accepted": "Fix accepted", "edited": "Edited by a person", "dismissed": "Dismissed"}
CLAIM = {"supported": "Supported by an approved fact", "contradicted": "Contradicts an approved fact",
         "no_approved_source": "No approved source"}


def _when(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return dt.datetime.fromisoformat(iso).strftime("%d %b %Y, %H:%M UTC")
    except ValueError:
        return iso


def render(d: dict, viewer: str) -> str:
    c = d["content"]
    approved = c["status"] == "approved"
    findings = d["findings"]
    done = [f for f in findings if f["decision"] != "open"]
    rows = "".join(
        f"""<tr><td>{e(f['category'])}<br><span class="m">{e(f['severity'])} / {e(f['confidence'])}{' / AI' if f['ai_generated'] else ''}</span></td>
        <td><b>{e(f['issue'])}</b><br><span class="m">Flagged: {e(f['span_text'])}</span></td>
        <td><code>{e(f['source_id'])}</code> {e(f['source_quote'])}</td>
        <td>{e(DECISION.get(f['decision'], f['decision']))}{('<br><span class="m">' + e(f['decision_reason']) + '</span>') if f['decision_reason'] else ''}
        {('<br><span class="m">by ' + e(f['decided_by_name']) + '</span>') if f.get('decided_by_name') else ''}</td></tr>"""
        for f in findings)
    applied = "".join(
        f"<li><code>{e(f['source_id'])}</code> {e(f['issue'])} <span class='m'>({e(DECISION.get(f['decision'], f['decision']))}"
        f"{', by ' + e(f['decided_by_name']) if f.get('decided_by_name') else ''})</span></li>" for f in d["history"])
    claims = "".join(f"<tr><td>{e(x['text'])}</td><td>{e(CLAIM.get(x['status'], x['status']))}"
                     f"{' (' + e(x['source_id']) + ')' if x['source_id'] else ''}</td></tr>" for x in d["claims"])
    comments = "".join(f"<li><b>{e(m['author'])}</b> ({e(m['role'])}), {e(_when(m['created_at']))}: {e(m['body'])}</li>"
                       for m in d["comments"])
    audit = "".join(f"<tr><td>{e(_when(a['created_at']))}</td><td>{e(a['who'] or 'system')}</td><td>{e(a['action'])}</td>"
                    f"<td>{e(a['detail'])}</td></tr>" for a in reversed(d["audit"]))
    images = "".join(f"<li>{e(i.get('name', ''))}: alt text {e(i.get('alt') or '(missing)')}</li>" for i in d["images"])
    banner = (f"Approved by <b>{e(c['approved_by'] or 'unknown')}</b> on {e(_when(c['approved_at']))}" if approved
              else f"<b>Not approved.</b> Status: {e(STATUS.get(c['status'], c['status']))}. This is a snapshot, not a clearance.")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Approval record: {e(c['title'])}</title><link rel="stylesheet" href="/static/record.css"></head><body>
<div class="brand"><img src="/static/brandguard-mark.svg" alt=""><span>BrandGuard</span></div>
<p class="m">BrandGuard approval record. Synthetic demo data. Generated {e(_when(dt.datetime.now(dt.timezone.utc).isoformat()))} for {e(viewer)}.</p>
<h1>{e(c['title'])}</h1><p class="m">Author: {e(c['author'])}. Version {c['current_version']}.</p>
<div class="banner {'ok' if approved else 'no'}">{banner}</div><button id="print">Print or save as PDF</button><script src="/static/print.js"></script>
<h2>Final text</h2><pre>{e(d['body'])}</pre>{('<h2>Images</h2><ul>' + images + '</ul>') if images else ''}
<h2>Findings ({len(done)} of {len(findings)} decided)</h2>
{('<table><tr><th>Type</th><th>Issue</th><th>Source (approved guideline or fact)</th><th>Decision</th></tr>' + rows + '</table>') if rows else '<p>No findings in this version.</p>'}
{('<h2>Changes applied in earlier versions</h2><ul>' + applied + '</ul>') if applied else ''}
{('<h2>Claim check</h2><table><tr><th>Sentence</th><th>Result</th></tr>' + claims + '</table>') if claims else ''}
{('<h2>Discussion</h2><ul>' + comments + '</ul>') if comments else ''}
{('<h2>Audit trail</h2><table><tr><th>When</th><th>Who</th><th>Action</th><th>Detail</th></tr>' + audit + '</table>') if audit else ''}
<p class="m">AI-generated suggestions are labelled "AI" and were decided by a person. Nothing is applied automatically.</p></body></html>"""
