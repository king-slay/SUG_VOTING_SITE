"""Write defence/link.html with the public link as a large QR code and open it."""

import html
import sys
import webbrowser
from pathlib import Path

import qrcode
import qrcode.image.svg

url = sys.argv[1]
svg = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=20, border=2).to_string(encoding="unicode")
page = Path(__file__).with_name("link.html")
page.write_text(f"""<!doctype html>
<meta charset="utf-8"><title>Scan to vote</title>
<style>
  body {{ font-family: system-ui, sans-serif; text-align: center; margin: 40px; color: #142019; }}
  h1 {{ font-size: 2.5rem; margin: 0 0 8px; }}
  .qr svg {{ width: min(70vh, 90vw); height: auto; }}
  .url {{ font-size: 1.5rem; font-weight: 600; color: #0b6b3a; word-break: break-all; }}
</style>
<h1>UNN SUG E-Voting</h1>
<p>Scan with your phone camera to try the site.</p>
<div class="qr">{svg}</div>
<p class="url">{html.escape(url)}</p>
""", encoding="utf-8")
webbrowser.open(page.resolve().as_uri())
