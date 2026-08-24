#!/usr/bin/env python3
"""Calculate an auditable FCFF DCF and two-dimensional sensitivity table."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


REQUIRED_CAPITAL = {"risk_free_rate", "equity_risk_premium", "beta", "pre_tax_cost_of_debt", "tax_rate", "market_equity", "gross_debt"}
REQUIRED_BRIDGE = {"cash", "gross_debt", "lease_liabilities", "minority_interest", "non_operating_assets", "diluted_shares"}


def number(value: Any, field: str) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric") from error
    if not math.isfinite(output):
        raise ValueError(f"{field} must be finite")
    return output


def calculate_wacc(capital: Mapping[str, Any]) -> Dict[str, float]:
    missing = REQUIRED_CAPITAL - set(capital)
    if missing:
        raise ValueError(f"missing capital fields: {sorted(missing)}")
    rf = number(capital["risk_free_rate"], "risk_free_rate")
    erp = number(capital["equity_risk_premium"], "equity_risk_premium")
    beta = number(capital["beta"], "beta")
    pre_tax_debt = number(capital["pre_tax_cost_of_debt"], "pre_tax_cost_of_debt")
    tax = number(capital["tax_rate"], "tax_rate")
    equity = number(capital["market_equity"], "market_equity")
    debt = number(capital["gross_debt"], "gross_debt")
    if equity <= 0 or debt < 0 or equity + debt <= 0 or not 0 <= tax < 1:
        raise ValueError("invalid capital weights or tax rate")
    cost_equity = rf + beta * erp
    after_tax_debt = pre_tax_debt * (1 - tax)
    wacc = equity / (equity + debt) * cost_equity + debt / (equity + debt) * after_tax_debt
    return {"cost_of_equity": cost_equity, "after_tax_cost_of_debt": after_tax_debt, "wacc": wacc}


def forecast_fcff(revenue_base: float, years: Sequence[Mapping[str, Any]]) -> list[Dict[str, float]]:
    revenue = number(revenue_base, "revenue_base")
    if revenue <= 0 or not years:
        raise ValueError("positive revenue_base and at least one forecast year are required")
    previous_nwc = revenue * number(years[0].get("opening_nwc_pct_revenue"), "opening_nwc_pct_revenue")
    output: list[Dict[str, float]] = []
    for index, assumptions in enumerate(years, 1):
        growth = number(assumptions.get("revenue_growth"), "revenue_growth")
        margin = number(assumptions.get("ebit_margin"), "ebit_margin")
        tax = number(assumptions.get("tax_rate"), "tax_rate")
        da_pct = number(assumptions.get("da_pct_revenue"), "da_pct_revenue")
        capex_pct = number(assumptions.get("capex_pct_revenue"), "capex_pct_revenue")
        nwc_pct = number(assumptions.get("nwc_pct_revenue"), "nwc_pct_revenue")
        if not -1 < growth < 5 or not -1 < margin < 1 or not 0 <= tax < 1:
            raise ValueError(f"implausible rate in forecast year {index}")
        revenue *= 1 + growth
        ebit = revenue * margin
        nopat = ebit * (1 - tax)
        depreciation = revenue * da_pct
        capex = revenue * capex_pct
        nwc = revenue * nwc_pct
        change_nwc = nwc - previous_nwc
        fcff = nopat + depreciation - capex - change_nwc
        output.append(
            {
                "year": index,
                "revenue": revenue,
                "ebit": ebit,
                "nopat": nopat,
                "depreciation_amortization": depreciation,
                "capex": capex,
                "change_nwc": change_nwc,
                "fcff": fcff,
            }
        )
        previous_nwc = nwc
    return output


def value_fcff(fcff: Sequence[Mapping[str, Any]], wacc: float, terminal_growth: float, bridge: Mapping[str, Any]) -> Dict[str, Any]:
    missing = REQUIRED_BRIDGE - set(bridge)
    if missing:
        raise ValueError(f"missing bridge fields: {sorted(missing)}")
    if wacc <= terminal_growth or wacc <= 0 or terminal_growth <= -1:
        raise ValueError("wacc must be positive and exceed terminal growth")
    cashflows = [number(row["fcff"], "fcff") for row in fcff]
    if not cashflows:
        raise ValueError("at least one FCFF year is required")
    present_values = [cash / (1 + wacc) ** year for year, cash in enumerate(cashflows, 1)]
    terminal_value = cashflows[-1] * (1 + terminal_growth) / (wacc - terminal_growth)
    present_terminal = terminal_value / (1 + wacc) ** len(cashflows)
    enterprise_value = sum(present_values) + present_terminal
    equity_value = (
        enterprise_value
        + number(bridge["cash"], "cash")
        + number(bridge["non_operating_assets"], "non_operating_assets")
        - number(bridge["gross_debt"], "gross_debt")
        - number(bridge["lease_liabilities"], "lease_liabilities")
        - number(bridge["minority_interest"], "minority_interest")
    )
    shares = number(bridge["diluted_shares"], "diluted_shares")
    if shares <= 0:
        raise ValueError("diluted_shares must be positive")
    return {
        "pv_explicit_fcff": sum(present_values),
        "terminal_value": terminal_value,
        "pv_terminal_value": present_terminal,
        "terminal_value_share_of_ev": present_terminal / enterprise_value if enterprise_value else None,
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "value_per_share": equity_value / shares,
    }


def sensitivity(fcff: Sequence[Mapping[str, Any]], bridge: Mapping[str, Any], wacc_values: Sequence[float], growth_values: Sequence[float]) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for wacc in wacc_values:
        row: Dict[str, Any] = {"wacc": wacc, "values": {}}
        for growth in growth_values:
            row["values"][str(growth)] = value_fcff(fcff, wacc, growth, bridge)["value_per_share"] if wacc > growth else None
        rows.append(row)
    return rows


def run(config: Mapping[str, Any]) -> Dict[str, Any]:
    for section in ("valuation_date", "sources", "revenue_base", "forecast_years", "capital", "terminal_growth", "bridge", "sensitivity"):
        if section not in config:
            raise ValueError(f"missing config section: {section}")
    if not isinstance(config["sources"], list) or not config["sources"]:
        raise ValueError("sources must be a non-empty evidence list")
    wacc = calculate_wacc(config["capital"])
    forecast = forecast_fcff(number(config["revenue_base"], "revenue_base"), config["forecast_years"])
    terminal_growth = number(config["terminal_growth"], "terminal_growth")
    valuation = value_fcff(forecast, wacc["wacc"], terminal_growth, config["bridge"])
    wacc_values = sorted({wacc["wacc"], *(number(item, "sensitivity.wacc") for item in config["sensitivity"]["wacc_values"])})
    growth_values = sorted({terminal_growth, *(number(item, "sensitivity.growth") for item in config["sensitivity"]["growth_values"])})
    table = sensitivity(forecast, config["bridge"], wacc_values, growth_values)
    center = next((row["values"].get(str(terminal_growth)) for row in table if row["wacc"] == wacc["wacc"]), None)
    return {
        "status": "implemented_calculation_formula_recalculation_unverified",
        "valuation_date": config["valuation_date"],
        "sources": config["sources"],
        "wacc": wacc,
        "forecast": forecast,
        "valuation": valuation,
        "sensitivity": table,
        "checks": {
            "wacc_exceeds_terminal_growth": wacc["wacc"] > terminal_growth,
            "sensitivity_center_matches_base": center is not None and math.isclose(center, valuation["value_per_share"], rel_tol=1e-12),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    value = json.loads(args.config.read_text(encoding="utf-8"))
    report = run(value)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
