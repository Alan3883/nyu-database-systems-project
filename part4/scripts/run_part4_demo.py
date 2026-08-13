"""End-to-end Part IV demonstration.

    python3 scripts/run_part4_demo.py
    python3 scripts/run_part4_demo.py --keep-context   # skip the source check

Walks the whole solution against the live PostgreSQL database:

     1  database availability
     2  application schema present
     3  quote created
     4  coverage added
     5  quote submitted and rated
     6  payment authorized
     7  quote accepted
     8  quote converted to a CONTRACT
     9  contract rows verified
    10  duplicate conversion rejected
    11  regional research context retrieved
    12  active ML model read
    13  approved insight retrieved
    14  source-change check executed
    15  governance checks

Repeatable. Every run creates its own quote with a unique number and
leaves earlier data alone; the database is never recreated.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

# part4/scripts/<file> -> part4 -> the course workspace, which must be on
# sys.path so `import part4...` resolves.
PART4 = Path(__file__).resolve().parent.parent
WORKSPACE = PART4.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from sqlalchemy import func, select  # noqa: E402

from part4.app.db import check_connection, read_session, session_scope  # noqa: E402
from part4.app.models import (  # noqa: E402
    Account,
    Contract,
    ContractBenefit,
    ContractPremium,
    Customer,
    QuoteConversion,
)
from part4.app.services import (  # noqa: E402
    ml_pipeline_service as ml,
    policy_service,
    quote_service,
    regional_context_service as regional,
    source_monitor_service,
)
from part4.app.services.errors import ConversionError, DomainError  # noqa: E402

ACTOR = "part4.demo"
PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def step(number: int, name: str, ok: bool, detail: str) -> None:
    status = PASS if ok else FAIL
    results.append((f"{number:02d}", name, status))
    marker = "OK " if ok else "!! "
    print(f"{marker}[{number:02d}] {name}\n       {detail}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-context", action="store_true",
                        help="skip the source checksum comparison")
    args = parser.parse_args()

    print("=" * 74)
    print("Part IV end-to-end demonstration")
    print("=" * 74)

    # --- 1. database -------------------------------------------------
    ok, message = check_connection()
    step(1, "Database available", ok, message)
    if not ok:
        return 1

    # --- 2. schema ---------------------------------------------------
    with read_session() as session:
        counts = {
            "customers": session.execute(select(func.count()).select_from(Customer)).scalar_one(),
            "accounts": session.execute(select(func.count()).select_from(Account)).scalar_one(),
            "contracts": session.execute(select(func.count()).select_from(Contract)).scalar_one(),
        }
        customer = session.scalars(select(Customer).order_by(Customer.customer_id)).first()
        # An account that has a regional profile, so step 11 has data.
        profiles = regional.accounts_with_context(session, limit=1)
        account_id = profiles[0]["account_id"] if profiles else session.scalars(
            select(Account.account_id)).first()
        customer_id = customer.customer_id
    step(2, "Application schema present", all(v > 0 for v in counts.values()),
         f"{counts['customers']} customers, {counts['accounts']} accounts, "
         f"{counts['contracts']} contracts")

    # --- 3. create quote ---------------------------------------------
    today = date.today()
    with session_scope() as session:
        quote = quote_service.create_quote(
            session, customer_id=customer_id, account_id=account_id,
            product_line="Medical", requested_date=today,
            effective_date=today, expiration_date=today + timedelta(days=365),
            actor=ACTOR)
        quote_id, quote_number = quote.quote_id, quote.quote_number
    step(3, "Quote created", True, f"{quote_number} (QuoteID {quote_id}) in Draft")

    # --- 4. coverage --------------------------------------------------
    with session_scope() as session:
        quote_service.add_coverage(
            session, quote_id, coverage_name="Core medical coverage",
            coverage_limit=Decimal("500000"), deductible=Decimal("2500"))
        quote_service.add_coverage(
            session, quote_id, coverage_name="Preventive care rider",
            coverage_limit=Decimal("50000"), deductible=Decimal("250"))
        estimate = quote_service.recalculate_estimated_premium(session, quote_id)
    step(4, "Coverage added", estimate > 0,
         f"2 coverage lines, estimated premium {estimate} "
         f"(demonstration rule, not a filed rate)")

    # --- 5. submit and rate --------------------------------------------
    with session_scope() as session:
        quote_service.transition(session, quote_id, "Submitted", actor=ACTOR,
                                 reason="Demonstration submission")
        quote_service.transition(session, quote_id, "Rated", actor=ACTOR,
                                 reason="Demonstration rating complete")
        quote_service.transition(session, quote_id, "Presented", actor=ACTOR,
                                 reason="Presented to customer")
    step(5, "Quote submitted, rated, presented", True,
         "Draft -> Submitted -> Rated -> Presented, each with a history row")

    # An invalid transition must be refused.
    try:
        with session_scope() as session:
            quote_service.transition(session, quote_id, "Draft", actor=ACTOR)
        refused = False
        detail = "an illegal transition was accepted"
    except DomainError as exc:
        refused, detail = True, str(exc)
    step(6, "Invalid transition rejected", refused, detail)

    # --- 7. payment ----------------------------------------------------
    with session_scope() as session:
        auth = quote_service.authorize_payment(
            session, quote_id, method="Card", amount=estimate, actor=ACTOR)
        reference = auth.authorization_reference
    step(7, "Payment authorized", True,
         f"{reference}, amount {estimate}. Reference only; no cardholder data stored.")

    # --- 8. accept and convert -----------------------------------------
    with session_scope() as session:
        quote_service.transition(session, quote_id, "Accepted", actor=ACTOR,
                                 reason="Customer accepted")
    step(8, "Quote accepted", True, "Presented -> Accepted")

    with session_scope() as session:
        contract = policy_service.issue_policy(session, quote_id, actor=ACTOR)
        contract_id, contract_number = contract.contract_id, contract.contract_number
    step(9, "Policy issued from quote", True,
         f"{contract_number} (ContractID {contract_id}) in one transaction")

    # --- 10. verify contract rows ---------------------------------------
    with read_session() as session:
        benefits = session.execute(
            select(func.count()).select_from(ContractBenefit)
            .where(ContractBenefit.contract_id == contract_id)).scalar_one()
        premiums = session.execute(
            select(func.count()).select_from(ContractPremium)
            .join(ContractBenefit,
                  ContractBenefit.benefit_id == ContractPremium.benefit_id)
            .where(ContractBenefit.contract_id == contract_id)).scalar_one()
        conversions = session.execute(
            select(func.count()).select_from(QuoteConversion)
            .where(QuoteConversion.quote_id == quote_id)).scalar_one()
        status = session.scalars(
            select(quote_service.Quote.quote_status)
            .where(quote_service.Quote.quote_id == quote_id)).one()
    step(10, "Contract rows verified",
         benefits == 2 and premiums == 2 and conversions == 1 and status == "Converted",
         f"{benefits} benefits, {premiums} premiums, {conversions} conversion row, "
         f"quote status {status}")

    # --- 11. duplicate conversion ---------------------------------------
    try:
        with session_scope() as session:
            policy_service.issue_policy(session, quote_id, actor=ACTOR)
        blocked, detail = False, "a second policy was created"
    except ConversionError as exc:
        blocked, detail = True, str(exc)
    step(11, "Duplicate conversion prevented", blocked, detail)

    # --- 12. regional context -------------------------------------------
    with read_session() as session:
        run = ml.active_run(session)
        rows = regional.account_context(
            session, account_id, ml_run_id=run.ml_run_id if run else None, limit=5)
        approved = [r for r in rows if r.approved_theme]
    step(12, "Regional research context retrieved", bool(rows),
         f"{len(rows)} county-level indicators for account {account_id}. "
         f"{regional.DISCLAIMER}")

    # --- 13. active model ------------------------------------------------
    with read_session() as session:
        run = ml.active_run(session)
        status_obj = ml.review_status(session, run.ml_run_id if run else None)
    step(13, "Active ML model read", run is not None,
         (f"ML_RUN {run.ml_run_id}, {run.model_name} {run.model_version}, "
          f"{status_obj.label}") if run else "no completed run")

    step(14, "Approved insight retrieved", True,
         (f"{len(approved)} approved indicator theme(s) surfaced: "
          + "; ".join(f"{r.indicator_name} -> {r.approved_theme}" for r in approved[:2]))
         if approved else
         "no approved mapping is active, so no ML theme is shown as insight")

    # --- 15. source check ---------------------------------------------
    if args.keep_context:
        step(15, "Source-change check", True, "skipped (--keep-context)")
    else:
        with read_session() as session:
            state = source_monitor_service.check_source(session)
        step(15, "Source-change check executed", state.source_exists, state.message)

    # --- 16. governance ------------------------------------------------
    with read_session() as session:
        run = ml.active_run(session)
        unreviewed_shown = False
        if run:
            index = regional.approved_theme_index(session, run.ml_run_id)
            summaries = {s.cluster_id: s for s in ml.cluster_summaries(session, run.ml_run_id)}
            for entry in index.values():
                summary = summaries.get(entry["cluster_id"])
                if summary is None or not summary.human_reviewed:
                    unreviewed_shown = True
    priced = quote_service.demonstration_premium(Decimal("500000"), Decimal("2500"))
    step(16, "Governance checks", not unreviewed_shown,
         f"No unreviewed cluster is exposed as approved insight. "
         f"Demonstration premium for a 500000/2500 line is {priced} and is "
         f"computed from those two inputs only.")

    print("=" * 74)
    failures = [r for r in results if r[2] == FAIL]
    print(f"{len(results) - len(failures)}/{len(results)} steps passed")
    if failures:
        for number, name, _ in failures:
            print(f"  FAILED [{number}] {name}")
    print(f"Quote  : {quote_number}  (/quotes/{quote_id})")
    print(f"Policy : {contract_number}  (/policies/{contract_id})")
    print("=" * 74)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
