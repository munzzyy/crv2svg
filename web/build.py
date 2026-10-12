"""Write dist/crv2svg.html: web/index.html with the scripts inlined, as one file with no companions."""

import base64
import hashlib
import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent
OUT = WEB.parent / "dist" / "crv2svg.html"
SCRIPT_TAGS = re.compile(r'<script src="crv2svg\.js"></script>\s*<script src="app\.js"></script>')


def build():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    code = "\n;\n".join((WEB / name).read_text(encoding="utf-8") for name in ("crv2svg.js", "app.js"))
    code = code.replace("</script", "<\\/script").replace("<!--", "<\\!--")
    digest = base64.b64encode(hashlib.sha256(code.encode("utf-8")).digest()).decode("ascii")

    if not SCRIPT_TAGS.search(page) or page.count("script-src 'self'") != 1:
        sys.exit("web/index.html no longer matches what build.py expects")
    page = page.replace("script-src 'self'", "script-src 'sha256-%s'" % digest)
    page = SCRIPT_TAGS.sub(lambda _: "<script>" + code + "</script>", page)
    if page.count("<script") != 1:
        sys.exit("expected exactly one script element in the built page")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_bytes(page.encode("utf-8"))
    print("%s (%d bytes, script sha256-%s)" % (OUT, OUT.stat().st_size, digest))


if __name__ == "__main__":
    build()
