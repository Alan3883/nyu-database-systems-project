"""Issued policy (CONTRACT) routes."""

from __future__ import annotations

from flask import Blueprint, render_template

from ..db import read_session
from ..services import policy_service

bp = Blueprint("policies", __name__, url_prefix="/policies")


@bp.route("/")
def list_policies():
    with read_session() as session:
        contracts = policy_service.list_contracts(session, limit=30)
    return render_template("policy_list.html", contracts=contracts)


@bp.route("/<int:contract_id>")
def policy_detail(contract_id: int):
    with read_session() as session:
        contract = policy_service.get_contract(session, contract_id)
        total = sum(
            float(premium.annualized_premium or 0)
            for benefit in contract.benefits
            for premium in benefit.premiums)
        quote = contract.conversion.quote if contract.conversion else None
    return render_template("policy_detail.html", contract=contract,
                           total_premium=total, quote=quote)
