"""
Open Charvis - Capability tools
===============================
The tools that make it feel like an assistant you can actually work with:
write and fix code, analyse files, plan a job, break down a problem.

These sit on top of :mod:`opencharvis.reasoning` and the existing dev
tools, and deliberately reuse their static analysis rather than inventing
a second opinion about the same code.
"""

from __future__ import annotations

import ast
import json
import re
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import PATHS
from ..logger import log_warn
from ..reasoning import get_reasoner
from ..security import get_security
from ..utils import human_size, truncate
from . import tool

SEC = get_security()

# Checklists used when no model is connected to write a bespoke plan.
PLAN_TEMPLATES = {
    "build": [
        "Write down what 'done' looks like",
        "List the moving parts and pick the smallest first slice",
        "Build that slice only",
        "Run it and confirm it does what you asked",
        "Then take the next slice",
    ],
    "debug": [
        "Reproduce the problem reliably",
        "Capture the exact error message",
        "Narrow it down: which line, which input",
        "Form one hypothesis and test it",
        "Fix, re-run, confirm the original case no longer happens",
    ],
    "analyse": [
        "State the question in one sentence",
        "Gather real data, not assumptions",
        "Break the question into parts you can answer separately",
        "Look for what would change your mind",
        "Write the conclusion and the uncertainty together",
    ],
    "decide": [
        "Write down the options",
        "Name what actually matters here",
        "Weigh each option against those criteria",
        "Check the cost of being wrong either way",
        "Decide, and record what would reverse it",
    ],
    "learn": [
        "Pick one sub-topic to start with",
        "Find one good source, not ten bad ones",
        "Read it and write three lines about it in your own words",
        "Explain it back to yourself",
        "Apply it to one real thing",
    ],
    "write": [
        "Decide the audience and what they already believe",
        "Pick the one thing you want them to remember",
        "Draft the shape: opening, three points, close",
        "Write it badly, then cut it in half",
        "Read it aloud and fix what sounds wrong",
    ],
    "general": [
        "Say exactly what outcome you want",
        "Identify what is missing right now",
        "Do the smallest useful piece",
        "Check it worked",
        "Repeat",
    ],
}


# ==========================================================================
# Reasoning
# ==========================================================================


@tool("reason.think", "Think through a problem step by step and show the working",
      capabilities=["chat"], risk=0.05, tags=["reason", "think"])
def reason_think(goal: str, verbose: bool = False) -> Dict[str, Any]:
    """
    The visible-reasoning entry point.

    Returns the plan, every step taken, what was found at each step, an
    honest confidence, and - importantly - what it is unsure about.
    """
    reasoning = get_reasoner().think(goal, verbose=verbose)
    return {
        "ok": True,
        "goal": reasoning.goal,
        "shape": reasoning.shape,
        "steps": [s.to_dict() for s in reasoning.steps],
        "answer": reasoning.answer,
        "confidence": round(reasoning.confidence, 3),
        "caveats": reasoning.caveats,
        "rendered": reasoning.render(verbose=verbose),
    }


@tool("reason.plan", "Break a goal into concrete ordered steps",
      capabilities=["chat"], risk=0.03, tags=["reason", "plan"])
def reason_plan(goal: str) -> Dict[str, Any]:
    """Decompose without executing anything - useful before committing."""
    reasoning = get_reasoner().think(goal)
    return {
        "ok": True,
        "goal": goal,
        "shape": reasoning.shape,
        "plan": [
            {"n": i, **s.to_dict()}
            for i, s in enumerate(reasoning.steps, 1)
        ],
        "caveats": reasoning.caveats,
        "next": "say 'do it' and I will run the plan",
    }


@tool("reason.compare", "Weigh two or more options against each other",
      capabilities=["chat", "net.fetch"], risk=0.05, tags=["reason", "decide"])
def reason_compare(a: str, b: str, criteria: str = "") -> Dict[str, Any]:
    """
    A structured comparison. The criteria come from you if you give them,
    otherwise the reasoner proposes sensible ones and says so.
    """
    from . import web_tools

    axes = [c.strip() for c in criteria.split(",") if c.strip()] or [
        "cost", "effort", "speed", "risk", "reversibility",
    ]
    facts = {}
    for label, subject in (("A", a), ("B", b)):
        found = web_tools.web_search(f"{subject} review", limit=2)
        facts[label] = [r["title"] for r in found.get("results", [])[:2]]

    reasoning = get_reasoner().think(
        f"Compare these and recommend one:\n{a}\nvs\n{b}\n"
        f"Weigh them on: {', '.join(axes)}.",
        verbose=True,
    )
    return {
        "ok": True,
        "a": a,
        "b": b,
        "criteria": axes,
        "criteria_source": "you" if criteria else "proposed by me - say so if they are wrong",
        "found": facts,
        "recommendation": reasoning.answer,
        "confidence": round(reasoning.confidence, 3),
        "caveats": reasoning.caveats,
    }


# ==========================================================================
# Coding
# ==========================================================================


def _extract_code(text: str) -> Tuple[str, str]:
    """
    Pull a code block out of text. Returns (code, language).

    Text that already parses as Python is returned untouched. The indented
    heuristic is only a last resort - applied to real pasted code it strips
    the leading whitespace and produces something that no longer compiles,
    which silently turned every review into "clean".
    """
    fenced = re.search(r"```([\w+-]*)\s*\n?(.*?)```", text, re.S)
    if fenced:
        return fenced.group(2).strip(), (fenced.group(1) or "").lower()

    stripped = (text or "").strip()
    if stripped:
        try:
            ast.parse(stripped)
            return stripped, ""
        except SyntaxError:
            pass

    indented = re.search(r"(?:^|\n)((?:[ \t]+.*\n?){2,})", text)
    if indented:
        return indented.group(1), ""
    return stripped, ""


@tool("code.write", "Write working code for a described task",
      capabilities=["chat", "code.run", "files.write"], risk=0.25,
      tags=["code", "write"])
def code_write(task: str, language: str = "python", test_it: bool = True) -> Dict[str, Any]:
    """
    Generate code, and - when the tools are installed - actually run it to
    confirm it does not just look right.

    A generated program that has never been executed is a guess with
    syntax highlighting.
    """
    from . import dev_tools

    available = {d["language"]: d for d in dev_tools.dev_languages()}
    if language not in available or not available[language]["ready"]:
        ready = [k for k, v in available.items() if v["ready"]]
        return {
            "ok": False,
            "error": f"{language} is not installed on this machine",
            "available": ready,
            "hint": f"write the {language} yourself and paste it, or use one of {ready}",
        }

    prompt = (
        f"Write a complete, runnable {language} program that does this:\n{task}\n\n"
        "Rules: no explanations inside the code, no placeholders, it must run "
        "as-is with no arguments, and print something so I can verify it works."
    )
    reply = get_reasoner().llm.complete(prompt, system=(
        "You write clean, correct, runnable code. Return one code block only."
    ))

    code, detected = _extract_code(reply.text or "")
    if not code:
        return {"ok": False, "error": "no code produced", "raw": truncate(reply.text or "", 400)}

    language = detected or language
    result = {
        "ok": True,
        "language": language,
        "task": task,
        "code": code,
        "lines": len(code.splitlines()),
        "verified": False,
    }

    if test_it and language == "python":
        lint = dev_tools.dev_lint(code, "python")
        result["syntax_ok"] = bool(lint.get("ok"))
        if not lint.get("ok"):
            result["syntax_error"] = lint.get("message")
        run = dev_tools.dev_run(code, language="python", timeout=20)
        if run.get("ok"):
            result["verified"] = True
            result["output"] = truncate(run.get("stdout", ""), 800)
        else:
            result["verified"] = False
            result["run_error"] = truncate(
                str(run.get("error") or run.get("stderr") or "did not complete"), 400
            )
            result["note"] = "I ran it and it failed - the code above is my best attempt, not a working program"

    return result


@tool("code.review", "Review code for bugs, risks and improvements",
      capabilities=["chat"], risk=0.10, tags=["code", "review"])
def code_review(code: str, language: str = "python") -> Dict[str, Any]:
    """A critique based on the actual code, not on impressions of it."""
    from . import dev_tools

    code = _extract_code(code)[0] or code
    report = dev_tools.dev_inspect(code, language)

    findings: List[Dict[str, Any]] = []
    severity = {"high": 0, "medium": 0, "low": 0}

    if language == "python" and report.get("ok"):
        for point in report.get("risk_points", []):
            level = "high" if any(w in point["issue"] for w in ("eval", "exec", "shell", "deserial")) else "medium"
            severity[level] += 1
            findings.append({"line": point["line"], "issue": point["issue"],
                             "code": point["code"], "severity": level})

        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                findings.append({"line": node.lineno, "issue": "bare except swallows every error",
                                 "severity": "medium"})
                severity["medium"] += 1
        names = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for name in set(names):
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                    has_doc = ast.get_docstring(node) is not None
                    has_body = any(
                        not isinstance(s, (ast.Pass, ast.Expr)) for s in node.body
                    )
                    if not has_body:
                        findings.append({"line": node.lineno,
                                         "issue": f"'{name}' has no implementation",
                                         "severity": "high"})
                        severity["high"] += 1
                    elif not has_doc and node.body:
                        findings.append({"line": node.lineno,
                                         "issue": f"'{name}' has no docstring",
                                         "severity": "low"})
                        severity["low"] += 1

    complexity = report.get("branching_complexity", 0)
    if isinstance(complexity, int) and complexity > 40:
        findings.append({"line": 0, "issue": f"high branching complexity ({complexity}) - hard to test",
                         "severity": "medium"})
        severity["medium"] += 1

    verdict = "clean" if not findings else (
        "needs work" if severity["high"] else "minor issues only"
    )
    return {
        "ok": True,
        "verdict": verdict,
        "findings": findings,
        "severity": severity,
        "lines": report.get("lines", len(code.splitlines())),
        "functions": len(report.get("functions", [])),
        "classes": len(report.get("classes", [])),
        "summary": (
            f"{report.get('lines', 0)} lines, "
            f"{len(report.get('functions', []))} functions, "
            f"complexity {complexity}. "
            + ("Nothing flagged." if not findings
               else f"{severity['high']} high, {severity['medium']} medium, {severity['low']} low.")
        ),
    }


@tool("code.explain", "Explain what a piece of code does, line by line",
      capabilities=["chat"], risk=0.03, tags=["code", "explain"])
def code_explain(code: str, language: str = "python") -> Dict[str, Any]:
    code = _extract_code(code)[0] or code
    from . import dev_tools

    report = dev_tools.dev_inspect(code, language)
    structure = []
    if language == "python" and report.get("ok"):
        structure = [
            {"name": f["name"], "line": f["line"],
             "args": f["args"], "async": f["async"]}
            for f in report.get("functions", [])
        ]
    reply = get_reasoner().llm.complete(
        f"Explain this {language} code to someone who can code but does not know "
        f"this codebase. Be concrete.\n\n```{language}\n{code}\n```",
        system="You explain code clearly. Lead with what it does overall, then detail.",
    )
    return {
        "ok": True,
        "explanation": reply.text,
        "structure": structure,
        "imports": report.get("imports", []),
        "lines": report.get("lines", len(code.splitlines())),
        "risk_points": report.get("risk_points", []),
    }


@tool("code.test", "Generate a test file for a function and run it",
      capabilities=["code.run", "files.write"], risk=0.30,
      tags=["code", "test"], confirm=True)
def code_test(code: str, function_name: str = "") -> Dict[str, Any]:
    """Write tests for real code, then run them and report the result."""
    from . import dev_tools

    code = _extract_code(code)[0] or code
    from . import dev_tools as _dt

    report = _dt.dev_inspect(code, "python")
    if not report.get("ok"):
        return {"ok": False, "error": f"the code does not parse: {report.get('error')}"}
    names = [f["name"] for f in report.get("functions", [])]
    if not names:
        return {"ok": False, "error": "no functions found to test"}
    target = function_name or names[0]

    tests = f'''import unittest, importlib.util, sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("subject", Path(__file__).parent / "subject.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


class Test{''.join(w.capitalize() for w in target.split('_'))}(unittest.TestCase):
    def test_exists(self):
        self.assertTrue(hasattr(_mod, "{target}"), "{target} is missing")

    def test_returns_something(self):
        result = getattr(_mod, "{target}")()
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
'''
    folder = PATHS["exports"] / "code"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time())
    (folder / "subject.py").write_text(code, encoding="utf-8")
    test_file = folder / f"test_subject_{stamp}.py"
    test_file.write_text(tests, encoding="utf-8")

    result = dev_tools.dev_run(
        f"import subprocess,sys;"
        f"r=subprocess.run([sys.executable,'-m','unittest','-v','{test_file.name}'],"
        f"capture_output=True,text=True,cwd=r'{folder}');"
        f"print(r.stdout[-1500:]);print(r.stderr[-800:])",
        language="python",
        timeout=90,
    )
    return {
        "ok": True,
        "target": target,
        "test_file": str(test_file),
        "source_saved": str(folder / "subject.py"),
        "passed": "OK" in (result.get("stdout") or ""),
        "output": truncate(result.get("stdout", "") + result.get("stderr", ""), 1500),
    }


# ==========================================================================
# Files and data
# ==========================================================================


def _safe(path: str):
    return SEC.safe_target(
        path, [Path.home(), Path.cwd(), PATHS["exports"], PATHS["home"]]
    )


@tool("file.analyze", "Analyse a file: what it is, what is inside, what stands out",
      capabilities=["files.read"], risk=0.15, tags=["file", "analyse"])
def file_analyze(path: str, question: str = "") -> Dict[str, Any]:
    """
    A real look at a file, not just a dump of it.

    Text files get structure statistics and notable lines; data files get
    column analysis; images get their dimensions.
    """
    guarded = _safe(path)
    if not guarded:
        return {"ok": False, "error": "that path is outside the areas I can read"}
    target = Path(guarded)
    if not target.is_file():
        return {"ok": False, "error": "file not found"}

    stat = target.stat()
    info: Dict[str, Any] = {
        "ok": True,
        "path": str(target),
        "name": target.name,
        "size": human_size(stat.st_size),
        "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
        "extension": target.suffix.lower().lstrip("."),
    }
    suffix = info["extension"]

    if suffix in {"png", "jpg", "jpeg", "gif", "bmp", "webp"}:
        info["kind"] = "image"
        info["pixels"] = _image_size(target)
        if info.get("pixels"):
            info["dimensions"] = "x".join(str(v) for v in info["pixels"])
        return info

    if suffix in {"json"}:
        try:
            data = json.loads(target.read_text(encoding="utf-8", errors="replace"))
            info["kind"] = "json"
            info["top_level"] = (
                list(data)[:20] if isinstance(data, dict)
                else f"array of {len(data)} items"
            )
            info["valid"] = True
        except json.JSONDecodeError as exc:
            info["kind"] = "json"
            info["valid"] = False
            info["error"] = str(exc)
        return info

    if suffix in {"csv", "tsv"}:
        return {**info, **_analyse_tabular(target, suffix)}

    text = target.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    info["kind"] = "text"
    info["lines"] = len(lines)
    info["characters"] = len(text)
    info["words"] = len(text.split())

    if suffix == "py":
        from . import dev_tools

        report = dev_tools.dev_inspect(text)
        if report.get("ok"):
            info["functions"] = [f["name"] for f in report["functions"]]
            info["classes"] = [c["name"] for c in report["classes"]]
            info["complexity"] = report["branching_complexity"]
            info["risk_points"] = report["risk_points"]
    elif suffix in {"md", "txt"}:
        headings = [l.strip() for l in lines if l.strip().startswith("#")]
        info["headings"] = headings[:20]
        longest = max(lines, key=len, default="")
        info["longest_line"] = len(longest)

    if question:
        info["answer"] = get_reasoner().think(
            f"About this file ({target.name}):\n{text[:6000]}\n\nQuestion: {question}"
        ).answer

    return info


def _image_size(path: Path) -> Optional[Tuple[int, int]]:
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.size
    except ImportError:
        pass
    # Read the dimensions straight out of the PNG header.
    try:
        with open(path, "rb") as fh:
            head = fh.read(26)
        if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
            return (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"))
    except OSError:
        pass
    return None


def _analyse_tabular(path: Path, suffix: str) -> Dict[str, Any]:
    delim = "\t" if suffix == "tsv" else ","
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {"kind": "data", "error": str(exc)}
    if not lines:
        return {"kind": "data", "rows": 0}

    header = lines[0].split(delim)
    rows = [l.split(delim) for l in lines[1:] if l.strip()]
    out: Dict[str, Any] = {
        "kind": "data",
        "columns": [h.strip() for h in header],
        "rows": len(rows),
    }

    stats = []
    for index, column in enumerate(header):
        values = [r[index] for r in rows if index < len(r) and r[index].strip()]
        if not values:
            continue
        column_stat: Dict[str, Any] = {
            "name": column.strip(),
            "filled": len(values),
            "empty": len(rows) - len(values),
        }
        numeric = []
        for value in values:
            try:
                numeric.append(float(value))
            except ValueError:
                pass
        if numeric and len(numeric) >= len(values) * 0.8:
            column_stat.update({
                "type": "number",
                "min": min(numeric),
                "max": max(numeric),
                "mean": round(statistics.fmean(numeric), 3),
            })
        else:
            column_stat.update({
                "type": "text",
                "distinct": len(set(values)),
                "most_common": statistics.mode(values) if len(set(values)) < len(values) else "-",
            })
        stats.append(column_stat)

    out["column_stats"] = stats
    out["sample"] = rows[:5]
    return out


@tool("data.summarise", "Summarise a CSV or data file into plain English",
      capabilities=["files.read"], risk=0.15, tags=["data", "analyse"])
def data_summarise(path: str) -> Dict[str, Any]:
    analysis = file_analyze(path)
    if not analysis.get("ok") or analysis.get("kind") != "data":
        return {"ok": False, "error": "that is not a data file I can summarise",
                "detail": analysis}

    stats = analysis.get("column_stats", [])
    numbers = [c for c in stats if c.get("type") == "number"]
    texts = [c for c in stats if c.get("type") == "text"]
    lines = [
        f"{analysis['name']} has {analysis['rows']} rows and "
        f"{len(analysis['columns'])} columns."
    ]
    for column in numbers:
        lines.append(
            f"- {column['name']}: ranges {column['min']} to {column['max']}, "
            f"average {column['mean']}"
        )
    for column in texts:
        lines.append(
            f"- {column['name']}: {column['distinct']} distinct values, "
            f"most common '{truncate(str(column['most_common']), 40)}'"
            + (f", {column['empty']} blanks" if column["empty"] else "")
        )
    gaps = [c for c in stats if c.get("empty", 0) > 0]
    if gaps:
        lines.append(
            "Missing data in: " + ", ".join(
                f"{g['name']} ({g['empty']} blank)" for g in gaps
            )
        )
    return {"ok": True, "summary": "\n".join(lines), "analysis": analysis}


# ==========================================================================
# Planning a job
# ==========================================================================


@tool("job.plan", "Turn a multi-step goal into a checklist you can follow",
      capabilities=["chat"], risk=0.03, tags=["plan", "productivity"])
def job_plan(goal: str, steps: str = "") -> Dict[str, Any]:
    """A working checklist, saved to a file so it survives a restart."""
    if steps:
        items = [s.strip() for s in steps.replace(";", "\n").splitlines() if s.strip()]
    else:
        # Without a model the reasoner produces generic steps, which is a
        # useless checklist. Use shape-aware defaults instead.
        shape = get_reasoner().classify(goal)
        items = PLAN_TEMPLATES.get(shape, PLAN_TEMPLATES["general"])[:]
        # Prepended, not substituted - the template's own first step is
        # usually the one that matters most (reproduce it, find one source).
        items.insert(0, f"Define exactly what '{truncate(goal, 70)}' should produce")

    checklist = "\n".join(f"- [ ] {item}" for item in items)
    folder = PATHS["exports"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"plan-{int(time.time())}.md"
    path.write_text(f"# {goal}\n\n{checklist}\n", encoding="utf-8")

    from ..memory import get_memory

    get_memory().add(f"Plan for '{truncate(goal, 60)}': {' | '.join(items)}",
                     kind="plan", tags=["plan"], importance=0.4, source="job.plan")

    return {"ok": True, "goal": goal, "steps": items,
            "checklist": checklist, "saved": str(path)}