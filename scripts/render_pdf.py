#!/usr/bin/env python3
"""Cross-platform HTML -> PDF renderer with automatic backend detection.

Backends tried in order:
  1. WeasyPrint (pip install weasyprint)     — best CSS paged-media support
  2. Headless Chrome / Chromium / Edge        — closest to what you see in a browser
  3. wkhtmltopdf                              — lightweight fallback

If none is available the HTML is still written and an actionable error is
returned; the pipeline never silently produces a broken PDF.

Usage:
  python3 render_pdf.py input.html output.pdf
  python3 render_pdf.py --check
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/usr/bin/microsoft-edge",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
]


def available_backends():
    out = []
    try:
        import weasyprint  # noqa: F401
        out.append("weasyprint")
    except Exception:
        pass
    for c in CHROME_CANDIDATES:
        if Path(c).exists() or shutil.which(c):
            out.append("chrome:%s" % c)
            break
    if shutil.which("wkhtmltopdf"):
        out.append("wkhtmltopdf")
    return out


def to_pdf(html_path, pdf_path, timeout=180):
    html_path, pdf_path = Path(html_path).resolve(), Path(pdf_path).resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    errors = []

    try:
        from weasyprint import HTML
        HTML(filename=str(html_path)).write_pdf(str(pdf_path))
        if pdf_path.stat().st_size > 1000:
            return True, "weasyprint"
    except ImportError:
        errors.append("weasyprint: not installed")
    except Exception as ex:
        errors.append("weasyprint: %s" % str(ex)[:160])

    for c in CHROME_CANDIDATES:
        exe = c if Path(c).exists() else shutil.which(c)
        if not exe:
            continue
        cmd = [exe, "--headless=new", "--disable-gpu", "--no-sandbox",
               "--no-pdf-header-footer", "--disable-extensions",
               "--virtual-time-budget=8000",
               "--print-to-pdf=%s" % pdf_path, "file://%s" % html_path]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if pdf_path.exists() and pdf_path.stat().st_size > 1000:
                return True, "chrome"
            errors.append("chrome: rc=%s %s" % (r.returncode, (r.stderr or "")[-160:]))
        except Exception as ex:
            errors.append("chrome: %s" % str(ex)[:160])
        break

    wk = shutil.which("wkhtmltopdf")
    if wk:
        try:
            r = subprocess.run([wk, "--quiet", "--encoding", "utf-8",
                                str(html_path), str(pdf_path)],
                               capture_output=True, text=True, timeout=timeout)
            if pdf_path.exists() and pdf_path.stat().st_size > 1000:
                return True, "wkhtmltopdf"
            errors.append("wkhtmltopdf: %s" % (r.stderr or "")[-160:])
        except Exception as ex:
            errors.append("wkhtmltopdf: %s" % str(ex)[:160])

    return False, " | ".join(errors) or "no PDF backend available"


def main():
    if "--check" in sys.argv:
        b = available_backends()
        print("Available backends:", b or "NONE")
        if not b:
            print("Install one:  pip install weasyprint   (or install Chrome / wkhtmltopdf)")
            sys.exit(1)
        return
    if len(sys.argv) < 3:
        sys.exit("Usage: render_pdf.py input.html output.pdf | render_pdf.py --check")
    ok, msg = to_pdf(sys.argv[1], sys.argv[2])
    print(("OK [%s] -> %s" % (msg, sys.argv[2])) if ok else ("FAILED: %s" % msg))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
