import re, pathlib
SRC = pathlib.Path.home() / "Downloads/html-slides-vs--powerpoint--a-better-way-to-present.html"
OUT = pathlib.Path("evals/fixtures/meridian/gold")
html = SRC.read_text()
sections = re.findall(r'<div class="slide-container">\s*(<section.*?</section>)', html, re.S)
assert len(sections) == 10, f"expected 10 slides, got {len(sections)}"
scripts = re.findall(r'<script>\s*(\(function\(\).*?)</script>', html, re.S)  # the two canvas IIFEs
for pos, sec in enumerate(sections):
    assert "<style" not in sec.lower(), f"slide {pos} leaked a <style> block"
    assert "slide-wrapper" not in sec and "slide-container" not in sec
    (OUT / f"{pos}.html").write_text(sec.strip() + "\n")
# Map canvas id -> position; write per-canvas scripts to gold/<pos>.js
for sc in scripts:
    cid = re.search(r"Canvas:\s*(\w+)", sc)
    canvas_id = cid.group(1) if cid else None
    for pos, sec in enumerate(sections):
        if canvas_id and f'id="{canvas_id}"' in sec:
            (OUT / f"{pos}.js").write_text(sc.strip() + "\n")
print("wrote", len(sections), "slides,", len(scripts), "scripts")
