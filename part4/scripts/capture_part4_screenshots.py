"""Drive the running application with Playwright and capture real screenshots.

    python3 -m part4.run &                          # start the server
    python3 scripts/capture_part4_screenshots.py    # capture

Every image is a screenshot of a page this script actually loaded from the
running Flask application against the live PostgreSQL database. Nothing is
mocked and no image is composed by hand.

The script also performs the workflow it photographs: it creates a quote,
adds coverage, moves it through the states, authorizes payment, issues a
policy, runs a source check, reviews a model cluster, and approves an
indicator mapping. The resulting rows are real rows.

Output: part4/evidence/screenshots/
"""

from __future__ import annotations

import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

# part4/scripts/<file> -> part4 -> the course workspace, which must be on
# sys.path so `import part4...` resolves.
PART4 = Path(__file__).resolve().parent.parent
WORKSPACE = PART4.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from playwright.sync_api import sync_playwright  # noqa: E402

from part4.app.config import CONFIG  # noqa: E402
from part4.app.db import read_session  # noqa: E402
from part4.app.services import ml_pipeline_service as ml  # noqa: E402
from part4.app.services import regional_context_service as regional  # noqa: E402

BASE = f"http://{CONFIG.host}:{CONFIG.port}"
SHOTS = PART4 / "evidence" / "screenshots"
VIEWPORT = {"width": 1440, "height": 1000}

AGENT = "agent.demo"
ANALYST = "j.franchitti.analyst"


def wait_for_server(timeout: int = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise SystemExit(f"No application responding at {BASE}. Start it with "
                     f"'python3 -m part4.run'.")


def context() -> dict:
    """Identifiers the capture needs, read straight from the database."""
    with read_session() as session:
        run = ml.active_run(session)
        accounts = regional.accounts_with_context(session, limit=1)
        account_id = accounts[0]["account_id"]
        rows = regional.account_context(session, account_id, limit=3)
        summaries = ml.cluster_summaries(session, run.ml_run_id)
        unreviewed = [s for s in summaries if not s.human_reviewed]
        target = (unreviewed or summaries)[0]
    return {
        "run_id": run.ml_run_id,
        "account_id": account_id,
        "account_name": accounts[0]["account_name"],
        "indicator_id": rows[0].indicator_id,
        "indicator_name": rows[0].indicator_name,
        "cluster_id": target.cluster_id,
        "cluster_label": target.cluster_label,
    }


def shot(page, name: str, *, full: bool = True) -> None:
    path = SHOTS / name
    page.screenshot(path=str(path), full_page=full)
    print(f"  captured {name}")


def shot_top(page, name: str, locator) -> None:
    """Capture from the top of the page down to the end of `locator`.

    Long pages such as a six-cluster review run to several thousand
    pixels. A full-page capture of one is unreadable once it is scaled to
    fit a Word page, so the report gets the header plus the first item and
    the rest stays in the running application.
    """
    box = locator.bounding_box()
    page.screenshot(path=str(SHOTS / name),
                    full_page=True,
                    clip={"x": 0, "y": 0,
                          "width": page.viewport_size["width"],
                          "height": box["y"] + box["height"] + 12})
    print(f"  captured {name}")


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    wait_for_server()
    ctx = context()
    print(f"Active ML_RUN {ctx['run_id']}, account {ctx['account_id']} "
          f"({ctx['account_name']}), cluster {ctx['cluster_id']}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)

        # --- 01 dashboard --------------------------------------------
        page.goto(f"{BASE}/", wait_until="networkidle")
        shot(page, "01_dashboard.png")

        # --- 02 quote creation form ----------------------------------
        page.goto(f"{BASE}/quotes/new", wait_until="networkidle")
        page.select_option("#account_id", str(ctx["account_id"]))
        page.select_option("#product_line", "Medical")
        page.fill("#actor", AGENT)
        page.fill("#requested_date", date.today().isoformat())
        page.fill("#coverage_name", "Core medical coverage")
        page.fill("#coverage_limit", "500000")
        page.fill("#deductible", "2500")
        shot(page, "02_create_quote.png")

        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")
        quote_url = page.url
        quote_id = int(quote_url.rstrip("/").split("/")[-1])
        print(f"  created quote {quote_id}")

        # --- 03 quote detail, draft with coverage ---------------------
        page.fill("#cn", "Preventive care rider")
        page.fill("#cl", "50000")
        page.fill("#dd", "250")
        page.click("form[action$='/coverage'] button[type=submit]")
        page.wait_for_load_state("networkidle")
        shot(page, "03_quote_detail.png")

        # --- 04 regional research context on the quote ----------------
        page.click("form[action$='/record-context'] button[type=submit]")
        page.wait_for_load_state("networkidle")
        panel = page.locator("div.panel", has=page.get_by_role(
            "heading", name="Regional research context")).first
        panel.scroll_into_view_if_needed()
        panel.screenshot(path=str(SHOTS / "04_regional_context.png"))
        print("  captured 04_regional_context.png")

        # --- move the quote through the workflow ----------------------
        for status in ("Submitted", "Rated", "Presented"):
            page.select_option("#ns", status)
            page.fill("#ta", AGENT)
            page.fill("#tr", f"Demonstration transition to {status}")
            page.click("form[action$='/transition'] button[type=submit]")
            page.wait_for_load_state("networkidle")

        page.fill("#pu", AGENT)
        page.click("form[action$='/payment'] button[type=submit]")
        page.wait_for_load_state("networkidle")

        page.select_option("#ns", "Accepted")
        page.fill("#ta", AGENT)
        page.fill("#tr", "Customer accepted the quote")
        page.click("form[action$='/transition'] button[type=submit]")
        page.wait_for_load_state("networkidle")

        # --- 05 accepted quote with payment authorized ----------------
        # Clipped to the quote summary, coverage, and workflow panels.
        # The full page runs past 4,700 pixels and would be unreadable
        # once scaled onto a report page.
        shot_top(page, "05_accepted_quote.png",
                 page.locator("div.panel", has=page.get_by_role(
                     "heading", name="Workflow actions")).first)

        # --- 06 issued policy -----------------------------------------
        page.fill("#ia", AGENT)
        page.click("form[action$='/issue'] button[type=submit]")
        page.wait_for_load_state("networkidle")
        policy_url = page.url
        shot(page, "06_policy_issued.png")
        print(f"  issued policy at {policy_url}")

        # --- 07 ML pipeline dashboard with a live source check --------
        page.goto(f"{BASE}/ml/", wait_until="networkidle")
        page.click("form[action$='/source-check'] button[type=submit]")
        page.wait_for_load_state("networkidle")
        shot(page, "07_ml_dashboard_source_check.png")

        # --- 08 cluster review and indicator approval -----------------
        page.goto(f"{BASE}/ml/runs/{ctx['run_id']}", wait_until="networkidle")
        cluster = ctx["cluster_id"]
        page.fill(f"#int{cluster}",
                  "Passages in this cluster discuss county-level economic and "
                  "housing conditions reported alongside health outcomes. Used "
                  "as regional research context for portfolio review only.")
        page.fill(f"#rev{cluster}", ANALYST)
        page.select_option(f"#dec{cluster}", "approve")
        page.click(f"form[action$='/clusters/{cluster}/review'] button[type=submit]")
        page.wait_for_load_state("networkidle")

        page.select_option(f"#ind{cluster}", str(ctx["indicator_id"]))
        page.fill(f"#app{cluster}", ANALYST)
        page.fill(f"#not{cluster}",
                  "Theme corresponds to an existing curated indicator. "
                  "Research context only; not a rating or eligibility input.")
        page.click(f"form[action$='/clusters/{cluster}/map'] button[type=submit]")
        page.wait_for_load_state("networkidle")
        shot_top(page, "08_ml_review.png", page.locator("div.cluster").first)

        # --- 09 the approved insight in the business context ----------
        page.goto(f"{BASE}/quotes/{quote_id}", wait_until="networkidle")
        panel = page.locator("div.panel", has=page.get_by_role(
            "heading", name="Regional research context")).first
        panel.scroll_into_view_if_needed()
        panel.screenshot(path=str(SHOTS / "09_approved_insight.png"))
        print("  captured 09_approved_insight.png")

        # --- 10 quote list ---------------------------------------------
        page.goto(f"{BASE}/quotes/?status=Converted", wait_until="networkidle")
        shot(page, "10_quote_list.png", full=False)

        browser.close()

    print(f"\nScreenshots written to {SHOTS.relative_to(WORKSPACE)}")
    for path in sorted(SHOTS.glob("*.png")):
        print(f"  {path.name:<38}{path.stat().st_size / 1024:>8.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
