"""
email_interface/router.py — Request routing logic.

Parses incoming email subject lines and routes to the correct system:
  RESEARCH: [ticker]  -> agentic-research-assistant (full multi-tool research brief)
  QUERY: [question]   -> CapitalContext RAG (semantic search + grounded answer)

Both return a dict: {mode, query, response, cost_estimate, elapsed, error}
"""

import subprocess
import sys
import time
import json
from pathlib import Path

from email_interface.config import (
    PREFIX_RESEARCH, PREFIX_QUERY,
    AGENTIC_ROOT, PROJECT_ROOT,
)


def parse_subject(subject: str) -> tuple[str, str] | tuple[None, None]:
    """
    Parses an email subject into (mode, query).

    Returns ("RESEARCH", ticker), ("QUERY", question), or (None, None).
    Matching is case-insensitive. Extra whitespace is stripped.
    """
    s = subject.strip()
    upper = s.upper()

    if upper.startswith(PREFIX_RESEARCH):
        query = s[len(PREFIX_RESEARCH):].strip()
        return ("RESEARCH", query) if query else (None, None)
    elif upper.startswith(PREFIX_QUERY):
        query = s[len(PREFIX_QUERY):].strip()
        return ("QUERY", query) if query else (None, None)

    return (None, None)


def run_research(ticker: str) -> dict:
    """
    Runs the agentic research assistant for a given ticker.
    Calls the agentic project's graph.py via subprocess in its own venv.

    Returns a dict with: response (final_brief markdown), cost, elapsed, error
    """
    t0 = time.time()

    agentic_python = AGENTIC_ROOT / "venv" / "Scripts" / "python.exe"
    if not agentic_python.exists():
        agentic_python = AGENTIC_ROOT / "venv" / "bin" / "python"

    runner_script = AGENTIC_ROOT / "_email_runner.py"

    # Write a tiny runner script that accepts ticker as argv[1] and prints JSON
    runner_code = '''\
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

from agent.graph import run

ticker = sys.argv[1]
state  = run(ticker)

cost = (
    (state["input_tokens"]  / 1000) * 0.00025 +
    (state["output_tokens"] / 1000) * 0.00125
)

print(json.dumps({
    "final_brief":    state.get("final_brief") or "",
    "input_tokens":   state.get("input_tokens", 0),
    "output_tokens":  state.get("output_tokens", 0),
    "iteration_count": state.get("iteration_count", 0),
    "cost":           round(cost, 5),
}))
'''
    runner_script.write_text(runner_code, encoding="utf-8")

    try:
        proc = subprocess.run(
            [str(agentic_python), str(runner_script), ticker.upper().strip()],
            capture_output=True,
            text=True,
            timeout=300,   # 5-minute hard cap
            cwd=str(AGENTIC_ROOT),
        )

        if proc.returncode != 0:
            return {
                "mode": "RESEARCH",
                "query": ticker,
                "response": None,
                "cost": 0,
                "elapsed": round(time.time() - t0, 1),
                "error": f"Agent subprocess failed: {proc.stderr[-500:]}",
            }

        # Parse last line of stdout as JSON (runner prints only JSON)
        output_lines = [l.strip() for l in proc.stdout.strip().splitlines() if l.strip()]
        data = json.loads(output_lines[-1])

        return {
            "mode":    "RESEARCH",
            "query":   ticker,
            "response": data["final_brief"],
            "cost":     data["cost"],
            "elapsed":  round(time.time() - t0, 1),
            "tokens":   {"in": data["input_tokens"], "out": data["output_tokens"]},
            "iterations": data["iteration_count"],
            "error":    None,
        }

    except subprocess.TimeoutExpired:
        return {
            "mode": "RESEARCH", "query": ticker, "response": None,
            "cost": 0, "elapsed": 300,
            "error": "Agent timed out after 5 minutes.",
        }
    except Exception as e:
        return {
            "mode": "RESEARCH", "query": ticker, "response": None,
            "cost": 0, "elapsed": round(time.time() - t0, 1),
            "error": str(e),
        }


def run_query(question: str, mode: str = "Q&A with citations") -> dict:
    """
    Runs the CapitalContext RAG pipeline for a question.

    Returns a dict with: response text, sources, cost, elapsed, error
    """
    t0 = time.time()

    try:
        # Import inline so this module is importable even before sys.path is set
        import sys
        sys.path.insert(0, str(PROJECT_ROOT))
        from rag import query as rag_query

        result = rag_query(question=question, mode=mode)
        elapsed = round(time.time() - t0, 1)

        # Rough cost estimate for RAG query (Haiku pricing)
        # Actual token count not directly available here without instrumenting rag.py
        cost_estimate = 0.001   # ~1 cent ballpark for a typical RAG response

        return {
            "mode":     "QUERY",
            "query":    question,
            "response": result.get("response"),
            "sources":  result.get("sources", []),
            "cost":     cost_estimate,
            "elapsed":  elapsed,
            "error":    result.get("error"),
        }

    except Exception as e:
        return {
            "mode": "QUERY", "query": question, "response": None,
            "sources": [], "cost": 0,
            "elapsed": round(time.time() - t0, 1),
            "error": str(e),
        }


def route(mode: str, query: str) -> dict:
    """Dispatch to the correct backend based on mode."""
    if mode == "RESEARCH":
        return run_research(query)
    elif mode == "QUERY":
        return run_query(query)
    else:
        return {"mode": mode, "query": query, "response": None,
                "cost": 0, "elapsed": 0, "error": f"Unknown mode: {mode}"}
