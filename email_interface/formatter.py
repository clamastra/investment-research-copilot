"""
email_interface/formatter.py — HTML email formatter.

Converts raw agent/RAG output into clean HTML emails with:
  - Bold section headers
  - Bullet points for lists
  - Source citation table
  - Run metadata footer
"""

import html
import re
from datetime import datetime, timezone


def _md_to_html(text: str) -> str:
    """
    Minimal Markdown-to-HTML conversion for research brief output.
    Handles: headers (##/###), bold (**), bullet lists, horizontal rules, line breaks.
    Does NOT handle tables or nested structures (not needed for brief format).
    """
    if not text:
        return ""

    lines = text.split("\n")
    out = []
    in_ul = False

    for line in lines:
        stripped = line.rstrip()

        # Horizontal rule
        if re.match(r"^---+$", stripped):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append("<hr style='border:none;border-top:1px solid #CBD5E0;margin:12px 0;'>")
            continue

        # h2
        if stripped.startswith("## "):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            content = html.escape(stripped[3:])
            out.append(f"<h2 style='color:#1B6CA8;font-size:1rem;margin:16px 0 6px;border-bottom:1px solid #E2E8F0;padding-bottom:4px;'>{content}</h2>")
            continue

        # h3
        if stripped.startswith("### "):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            content = html.escape(stripped[4:])
            out.append(f"<h3 style='color:#2D3748;font-size:0.9rem;margin:12px 0 4px;'>{content}</h3>")
            continue

        # Bullet list item
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_ul:
                out.append("<ul style='margin:4px 0 8px 18px;padding:0;'>")
                in_ul = True
            content = _inline_md(stripped[2:])
            out.append(f"<li style='margin-bottom:3px;'>{content}</li>")
            continue

        # Numbered list item
        if re.match(r"^\d+\.\s", stripped):
            if not in_ul:
                out.append("<ul style='margin:4px 0 8px 18px;padding:0;list-style-type:decimal;'>")
                in_ul = True
            content = _inline_md(re.sub(r"^\d+\.\s", "", stripped))
            out.append(f"<li style='margin-bottom:3px;'>{content}</li>")
            continue

        # Close list if we hit a non-list line
        if in_ul:
            out.append("</ul>")
            in_ul = False

        # Empty line → paragraph break
        if not stripped:
            out.append("<br>")
            continue

        # Regular paragraph
        out.append(f"<p style='margin:4px 0;'>{_inline_md(stripped)}</p>")

    if in_ul:
        out.append("</ul>")

    return "\n".join(out)


def _inline_md(text: str) -> str:
    """Handle bold (**), italic (*), and inline code (`) within a line."""
    text = html.escape(text)
    # Bold: **text**
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic: *text* (not already consumed by bold)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Inline code: `text`
    text = re.sub(r"`(.+?)`", r"<code style='background:#EDF2F7;padding:1px 4px;border-radius:3px;font-size:0.85em;'>\1</code>", text)
    return text


def _source_table(sources: list[dict]) -> str:
    """Renders a compact source citation table."""
    if not sources:
        return ""

    rows = ""
    for i, s in enumerate(sources[:10], 1):   # cap at 10 sources for email length
        src  = html.escape(str(s.get("source", "Unknown")))
        page = html.escape(str(s.get("page", "?")))
        cls  = html.escape(str(s.get("asset_class", "")))
        dist = s.get("distance", "")
        dist_str = f"{dist:.3f}" if isinstance(dist, float) else str(dist)
        rows += (
            f"<tr style='border-bottom:1px solid #E2E8F0;'>"
            f"<td style='padding:4px 8px;color:#718096;'>{i}</td>"
            f"<td style='padding:4px 8px;font-weight:600;'>{src}</td>"
            f"<td style='padding:4px 8px;'>p.{page}</td>"
            f"<td style='padding:4px 8px;color:#4A5568;'>{cls}</td>"
            f"<td style='padding:4px 8px;color:#A0AEC0;'>{dist_str}</td>"
            f"</tr>"
        )

    return f"""
<h3 style='color:#2D3748;font-size:0.85rem;margin:16px 0 6px;'>{len(sources)} Source Passage(s) Retrieved</h3>
<table style='border-collapse:collapse;width:100%;font-size:0.8rem;'>
  <thead>
    <tr style='background:#EDF2F7;'>
      <th style='padding:4px 8px;text-align:left;'>#</th>
      <th style='padding:4px 8px;text-align:left;'>Document</th>
      <th style='padding:4px 8px;text-align:left;'>Page</th>
      <th style='padding:4px 8px;text-align:left;'>Asset Class</th>
      <th style='padding:4px 8px;text-align:left;'>Distance</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
"""


def build_confirmation_email(mode: str, query: str) -> str:
    """HTML body for the immediate confirmation reply."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mode_desc = "full agentic research brief" if mode == "RESEARCH" else "RAG document query"
    return f"""
<div style='font-family:Arial,sans-serif;max-width:640px;color:#2D3748;font-size:0.9rem;'>
  <div style='background:#EBF8FF;border-left:4px solid #3182CE;padding:12px 16px;border-radius:4px;margin-bottom:16px;'>
    <strong>Request received</strong> &mdash; processing your {mode_desc}.
  </div>
  <p><strong>Mode:</strong> {html.escape(mode)}</p>
  <p><strong>Query:</strong> {html.escape(query)}</p>
  <p><strong>Received at:</strong> {ts}</p>
  <p>Expect a response in approximately 1&ndash;3 minutes. If you don&rsquo;t hear back within 10 minutes, the laptop may be offline or the polling script may have stopped.</p>
  <hr style='border:none;border-top:1px solid #E2E8F0;margin:16px 0;'>
  <p style='color:#A0AEC0;font-size:0.75rem;'>CapitalContext &mdash; Institutional Investment Document Intelligence</p>
</div>
"""


def build_response_email(result: dict) -> str:
    """HTML body for the full research/query response email."""
    mode    = result.get("mode", "")
    query   = result.get("query", "")
    elapsed = result.get("elapsed", 0)
    cost    = result.get("cost", 0)
    error   = result.get("error")
    ts      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    header_color = "#1B6CA8" if mode == "RESEARCH" else "#2D6A4F"
    mode_label   = "Research Brief" if mode == "RESEARCH" else "Document Query"

    # Metadata chips
    meta_parts = [f"<strong>Query:</strong> {html.escape(str(query))}"]
    if elapsed:
        meta_parts.append(f"<strong>Time:</strong> {elapsed}s")
    if cost:
        meta_parts.append(f"<strong>Est. cost:</strong> ${cost:.4f}")
    if result.get("iterations"):
        meta_parts.append(f"<strong>Iterations:</strong> {result['iterations']}")
    if result.get("tokens"):
        t = result["tokens"]
        meta_parts.append(f"<strong>Tokens:</strong> {t['in']:,} in / {t['out']:,} out")
    meta_html = " &nbsp;|&nbsp; ".join(meta_parts)

    # Error case
    if error:
        body = f"""
<div style='background:#FFF5F5;border-left:4px solid #FC8181;padding:12px 16px;border-radius:4px;'>
  <strong>Processing failed</strong><br>
  <span style='color:#C53030;font-size:0.85rem;'>{html.escape(str(error))}</span>
</div>
<p style='font-size:0.85rem;color:#718096;margin-top:12px;'>
  Check that the ticker symbol is valid, your API key is active, and the laptop is connected.
  You can retry by sending the same email again.
</p>
"""
    else:
        response_text = result.get("response") or ""
        sources       = result.get("sources", [])

        response_html = _md_to_html(response_text)
        sources_html  = _source_table(sources) if sources else ""

        body = f"""
<div style='background:#F7FAFC;border-left:4px solid {header_color};border-radius:6px;padding:16px 20px;line-height:1.7;font-size:0.88rem;'>
{response_html}
</div>
{sources_html}
"""

    return f"""
<div style='font-family:Arial,sans-serif;max-width:680px;color:#2D3748;font-size:0.9rem;'>

  <div style='background:{header_color};color:white;padding:10px 16px;border-radius:6px 6px 0 0;margin-bottom:0;'>
    <strong>CapitalContext &mdash; {html.escape(mode_label)}</strong>
  </div>

  <div style='background:#EDF2F7;padding:8px 16px;font-size:0.8rem;border-radius:0 0 4px 4px;margin-bottom:16px;'>
    {meta_html} &nbsp;|&nbsp; <strong>Completed:</strong> {ts}
  </div>

  {body}

  <hr style='border:none;border-top:1px solid #E2E8F0;margin:20px 0 12px;'>
  <p style='color:#A0AEC0;font-size:0.75rem;margin:0;'>
    CapitalContext &mdash; Institutional Investment Document Intelligence<br>
    Sources: Yahoo Finance, DuckDuckGo, SEC EDGAR (public data only) &mdash; Personal use only
  </p>
</div>
"""


def build_error_email(subject: str, error_msg: str) -> str:
    """HTML body for a processing error notification."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""
<div style='font-family:Arial,sans-serif;max-width:640px;color:#2D3748;font-size:0.9rem;'>
  <div style='background:#FFF5F5;border-left:4px solid #FC8181;padding:12px 16px;border-radius:4px;margin-bottom:16px;'>
    <strong>Processing error</strong>
  </div>
  <p><strong>Original subject:</strong> {html.escape(subject)}</p>
  <p><strong>Error:</strong> {html.escape(error_msg)}</p>
  <p><strong>Time:</strong> {ts}</p>
  <p style='font-size:0.85rem;color:#718096;'>
    If the subject line format is unexpected, remember to use:<br>
    <code>RESEARCH: AAPL</code> or <code>QUERY: What are the risks of PIMCO Income?</code>
  </p>
</div>
"""
