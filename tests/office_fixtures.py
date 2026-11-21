"""Generate office fixtures and read them through readpage over a local HTTP server."""
import json
import os
import subprocess
import sys
import time
import http.server
import socketserver
import threading
for _name in ("READ_PAGE_DEBUG", "READ_PAGE_DEBUG_DIR"):    # the user's debug log switches stay out
    os.environ.pop(_name, None)

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
os.makedirs(D, exist_ok=True)

import docx
import openpyxl
from pptx import Presentation

# docx with a heading, a paragraph and a table
d = docx.Document()
d.add_heading("Quarterly report", 0)
d.add_paragraph("Revenue grew 12% in Q3.")
t = d.add_table(rows=2, cols=2)
t.cell(0, 0).text, t.cell(0, 1).text = "Region", "Revenue"
t.cell(1, 0).text, t.cell(1, 1).text = "EMEA", "4.2M"
d.save(os.path.join(D, "report.docx"))

# xlsx
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Q3"
ws.append(["Region", "Revenue"])
ws.append(["EMEA", 4.2])
ws.append(["APAC", 3.1])
wb.save(os.path.join(D, "report.xlsx"))

# pptx with notes
pr = Presentation()
s = pr.slides.add_slide(pr.slide_layouts[1])
s.shapes.title.text = "Q3 results"
s.placeholders[1].text = "EMEA up 12%"
s.notes_slide.notes_text_frame.text = "mention the APAC delay"
pr.save(os.path.join(D, "report.pptx"))

os.chdir(D)
Handler = http.server.SimpleHTTPRequestHandler
httpd = socketserver.TCPServer(("127.0.0.1", 8765), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.3)

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "readpage.py")
for name, probe in (("report.docx", ["Quarterly report", "4.2M"]),
                    ("report.xlsx", ["Q3", "EMEA", "4.2"]),
                    ("report.pptx", ["Q3 results", "EMEA up 12%", "APAC delay"])):
    p = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, "http://127.0.0.1:8765/" + name, "--refresh", "--json"],
                       capture_output=True, timeout=180)
    try:
        m = json.loads(p.stdout.decode("utf-8", "replace"))
    except Exception:
        print(name, "no manifest:", p.stderr.decode("utf-8", "replace")[-200:])
        continue
    text = open(m["files"]["content"], encoding="utf-8", errors="replace").read()
    print("%-12s %-4s %-22s %6d ch  %5d ms  probes: %s" % (
        name, m["status"], m["content"]["engine"], m["content"]["chars"], m["elapsed_ms"],
        {k: (k in text) for k in probe}))

httpd.shutdown()
