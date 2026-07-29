# src/services/converter_jail/gslides_runner.py
"""In-jail trusted runner for Google Slides conversion (SDR-4437 HIGH-5).

Runs each generated build_slide_requests(html_str, assets_dir, page_id)
snippet and collects the returned request lists into a JSON file. NO network,
NO credentials. The host validates, uploads assets, substitutes placeholder
URLs, and executes the requests.

CLI: python -I gslides_runner.py <src_parent> <job_dir> <requests_out_path>
(<src_parent> is part of the launcher's CLI contract; this runner does NOT
put it on sys.path — importing anything via `src.services` would execute that
package's heavy __init__ and drag the credential-capable SDK graph into the
jail child. Siblings are imported as top-level modules instead.)
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent

if __package__ in (None, ""):
    # Script mode (inside the jail child): import siblings as top-level
    # modules so src/services/__init__.py (SDK/agent graph) never executes.
    sys.path.insert(0, str(_HERE))
    import protocol
    from codeprep import prepare_requests_code
else:
    # Imported on the trusted host (unit tests): normal package imports.
    from src.services.converter_jail import protocol
    from src.services.converter_jail.codeprep import prepare_requests_code


def _exec_snippet(code: str, html_str: str, assets_dir: str, page_id: str):
    """Run one snippet; return (requests_list_or_None, error_or_None)."""
    code = prepare_requests_code(code)
    tmp = Path(tempfile.mktemp(suffix=".py", prefix="jail_gslide_"))
    tmp.write_text(code, encoding="utf-8")
    try:
        spec = importlib.util.spec_from_file_location("jail_gslide", str(tmp))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        requests = module.build_slide_requests(html_str, assets_dir, page_id)
        if not isinstance(requests, list):
            return None, f"build_slide_requests returned {type(requests).__name__}"
        return requests, None
    except Exception as exc:
        return None, repr(exc)
    finally:
        if tmp.exists():
            tmp.unlink()


def run(job_dir: str, requests_out_path: str) -> None:
    manifest = json.loads((Path(job_dir) / protocol.MANIFEST_NAME).read_text())
    out = []
    for entry in manifest["slides"]:
        i = entry["index"]
        page_id = entry["page_id"]
        sdir = Path(job_dir) / entry["dir"]
        assets_dir = str(sdir / protocol.ASSETS_DIR)
        if not entry.get("has_code"):
            out.append({"index": i, "page_id": page_id, "requests": None,
                        "error": "no_code"})
            continue
        html_str = (sdir / protocol.HTML_NAME).read_text(encoding="utf-8")
        code = (sdir / protocol.CODE_NAME).read_text(encoding="utf-8")
        requests, error = _exec_snippet(code, html_str, assets_dir, page_id)
        out.append({"index": i, "page_id": page_id,
                    "requests": requests, "error": error})
    Path(requests_out_path).write_text(json.dumps(out))


if __name__ == "__main__":
    # argv: [runner, src_parent, job_dir, requests_out_path]
    run(sys.argv[2], sys.argv[3])
