"""PDF (Typst) and plain-text rendering (SPEC §7).

Flow: CV dict -> display-ready dict -> data/out/cv.json -> `typst compile`.
The .txt export is generated straight from the same dict for ATS web forms.
"""
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend import config

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class RenderError(Exception):
    pass


def fmt_month(ym: Optional[str]) -> str:
    """'2022-04' -> 'Apr 2022'; tolerates '2022' and ''."""
    if not ym:
        return ""
    parts = str(ym).split("-")
    year = parts[0]
    if len(parts) > 1 and parts[1].isdigit() and 1 <= int(parts[1]) <= 12:
        return f"{MONTHS[int(parts[1]) - 1]} {year}"
    return year


def date_range(start: Optional[str], end: Optional[str]) -> str:
    s, e = fmt_month(start), (fmt_month(end) if end else "Present")
    return f"{s} – {e}" if s else (e if end else "")


def build_render_data(cv: Dict[str, Any]) -> Dict[str, Any]:
    contact_bits = [cv["basics"][k] for k in ("email", "phone", "location")
                    if cv["basics"][k]]
    contact_bits += [l["url"] for l in cv["basics"]["links"] if l["url"]]
    data = json.loads(json.dumps(cv))  # deep copy
    data["contact_line"] = "  |  ".join(contact_bits)
    for e in data["experience"]:
        e["dates"] = date_range(e["start"], e["end"])
    for e in data["education"]:
        e["dates"] = date_range(e["start"], e["end"])
    for c in data["certifications"]:
        c["date"] = fmt_month(c["date"])
    return data


def render_pdf(cv: Dict[str, Any], out_name: str = "cv") -> Path:
    if not config.TYPST_BIN:
        raise RenderError("Typst binary not found. Expected it in tools/typst "
                          "(or on PATH via `brew install typst`).")
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = config.OUT_DIR / f"{out_name}.json"
    pdf_path = config.OUT_DIR / f"{out_name}.pdf"
    json_path.write_text(json.dumps(build_render_data(cv), ensure_ascii=False))

    # --root = project root so the template can address /data/out/cv.json
    rel_json = "/" + str(json_path.relative_to(config.PROJECT_ROOT))
    cmd = [config.TYPST_BIN, "compile",
           "--root", str(config.PROJECT_ROOT),
           "--input", f"data={rel_json}",
           str(config.TYPST_DIR / "cv.typ"), str(pdf_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RenderError(f"typst compile failed:\n{proc.stderr.strip()}")
    return pdf_path


def render_txt(cv: Dict[str, Any], out_name: str = "cv") -> Path:
    """Plain-text export for paste-into-form ATS portals."""
    d = build_render_data(cv)
    lines: List[str] = []

    def header(t: str):
        lines.extend(["", t.upper(), "-" * len(t)])

    lines.append(d["basics"]["name"])
    if d["basics"]["title"]:
        lines.append(d["basics"]["title"])
    if d["contact_line"]:
        lines.append(d["contact_line"].replace("  |  ", " | "))

    if d["summary"]:
        header("Summary")
        lines.append(d["summary"])

    if d["experience"]:
        header("Experience")
        for e in d["experience"]:
            role = ", ".join(x for x in (e["title"], e["company"]) if x)
            if e["location"]:
                role += f" — {e['location']}"
            lines.append(f"{role} ({e['dates']})" if e["dates"] else role)
            lines.extend(f"* {b['text']}" for b in e["bullets"])
            lines.append("")
        lines.pop()

    if d["education"]:
        header("Education")
        for e in d["education"]:
            row = ", ".join(x for x in (e["degree"], e["institution"]) if x)
            if e["dates"]:
                row += f" ({e['dates']})"
            lines.append(row)
            if e["details"]:
                lines.append(f"  {e['details']}")

    if d["skills"]:
        header("Skills")
        for s in d["skills"]:
            prefix = f"{s['group']}: " if s["group"] else ""
            lines.append(prefix + ", ".join(s["items"]))

    if d["projects"]:
        header("Projects")
        for p in d["projects"]:
            lines.append(p["name"] + (f" — {p['url']}" if p["url"] else ""))
            lines.extend(f"* {b['text']}" for b in p["bullets"])

    if d["certifications"]:
        header("Certifications")
        for c in d["certifications"]:
            row = ", ".join(x for x in (c["name"], c["issuer"]) if x)
            if c["date"]:
                row += f" ({c['date']})"
            lines.append(row)

    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    txt_path = config.OUT_DIR / f"{out_name}.txt"
    txt_path.write_text("\n".join(lines).strip() + "\n")
    return txt_path
