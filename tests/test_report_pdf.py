from backend.app.reporting.service import render_pdf, render_html


def test_pdf_renderer_returns_pdf_bytes():
    data = {"language":"en","case_id":"c","analysis_id":"a","findings":[],"methodology":"m","limitations":"l"}
    pdf = render_pdf(data)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 500


def test_arabic_html_has_rtl_direction():
    html = render_html({"language":"ar","case_id":"c","analysis_id":"a","findings":[],"methodology":"m","limitations":"l"}).decode("utf-8")
    assert "dir='rtl'" in html
    assert "تقرير تفسير" in html
