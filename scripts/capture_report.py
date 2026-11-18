"""Exercise the real offline report before capturing it for the portfolio."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser", type=Path)
    options = parser.parse_args()
    options.output.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=options.browser)
        page = browser.new_page(viewport={"width": 1440, "height": 1030})
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(options.report.resolve().as_uri())
        assert page.locator("#payout-table tbody tr").count() == 10
        page.screenshot(path=options.output / "abonos.png", full_page=True)
        page.select_option("#filter", "exception")
        assert page.locator("#payout-table tbody tr").count() == 3
        page.locator("#tab-lots").focus()
        page.keyboard.press("ArrowRight")
        assert page.locator("#queue").is_visible()
        assert page.locator("#queue-table tbody tr").count() == 7
        page.screenshot(path=options.output / "excepciones.png", full_page=True)
        page.locator("#tab-trace").click()
        assert page.locator("#trace").is_visible()
        assert page.get_by_text("analista_faro").is_visible()
        assert page.locator("#receipt-table tbody tr").count() == 8
        page.screenshot(path=options.output / "trazabilidad.png", full_page=True)
        browser.close()
    assert not errors, errors
    print(
        json.dumps(
            {
                "report_loaded": True,
                "payouts": 10,
                "filtered_exceptions": 3,
                "keyboard_navigation": True,
                "trace_receipts": 8,
                "resolution_visible": True,
                "page_errors": errors,
                "screenshots": 3,
            }
        )
    )


if __name__ == "__main__":
    main()
