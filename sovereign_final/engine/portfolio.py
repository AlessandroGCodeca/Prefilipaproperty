"""
engine/portfolio.py — the flats you own, in numbers: the loan's balance
today, your equity, the last twelve months as they really were (the ledger),
the tax on them, and how the model's assumptions compare with your own
figures — the one place the model meets what actually happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from engine import financial


def months_between(start: str | None, today: date) -> int:
    """Whole months from a "YYYY-MM-DD" (or "YYYY-MM") date to `today`."""
    if not start:
        return 0
    y, m = int(start[:4]), int(start[5:7])
    return max((today.year - y) * 12 + today.month - m, 0)


def balance_after(principal: float, rate: float, years: int, months: int,
                  fixation_years: int | None = None, reset_rate: float | None = None) -> float:
    """The loan's balance after `months` payments (the annuity reset at the
    end of a fixation, as financial.loan_schedule does yearly)."""
    if principal <= 0 or not years:
        return 0.0
    bal, r = principal, rate / 12
    payment = financial.calc_mortgage(principal, rate, years)
    for n in range(min(months, years * 12)):
        if fixation_years and reset_rate is not None and n == fixation_years * 12 and bal > 0:
            r = reset_rate / 12
            payment = financial.calc_mortgage(bal, reset_rate, years - fixation_years)
        bal -= min(payment - bal * r, bal)
    return round(max(bal, 0.0), 2)


@dataclass
class FlatNumbers:
    id: str
    name: str
    currency: str
    value: float
    value_source: str
    balance: float
    equity: float
    payment: float
    rent_12m: float
    costs_12m: float
    vacancy_rate: float | None
    months_on_record: int
    tax_year_est: float
    cash_flow_12m: float
    gross_yield: float
    net_yield: float
    model_rent: float | None
    model_hoa: float | None


def flat_numbers(f: dict, ledger: list[dict], today: date | None = None) -> FlatNumbers:
    """One flat's figures. The last 12 months come from the ledger where it
    has months, the planned rent and costs fill the rest."""
    from engine.regional_prices import benchmark_median
    today = today or date.today()
    market = f.get("market") or "sk"
    mk = {"market": market}
    size = f.get("size_m2") or 0
    principal = f.get("loan_principal") or 0
    rate = f.get("loan_rate") or 0
    years = f.get("loan_years") or 0
    paid_months = months_between(f.get("loan_start") or f.get("bought_on"), today)
    balance = balance_after(principal, rate, years, paid_months, f.get("fixation_years"),
                            f.get("reset_rate"))
    payment = financial.calc_mortgage(principal, rate, years) if principal and years else 0.0
    value, source = f.get("value_estimate"), "yours"
    if not value:
        median = benchmark_median(f.get("district") or "", f.get("rooms"), market=market)
        value, source = ((median * size, "district median") if median and size
                         else (f.get("price") or 0, "price paid"))
    cutoff = f"{today.year - 1}-{today.month:02d}"
    recent = [m for m in ledger if m["month"] > cutoff][-12:]
    n = len(recent)
    planned_rent = f.get("rent_monthly") or 0
    planned_costs = (f.get("hoa_monthly") or 0) + (f.get("other_costs_monthly") or 0)
    rent_12 = sum(m.get("rent_received") or 0 for m in recent) + planned_rent * (12 - n)
    costs_12 = sum(m.get("costs") or 0 for m in recent) + planned_costs * (12 - n)
    vacancy = (sum(m.get("vacant_days") or 0 for m in recent) / (n * 30.4)) if n else None
    # Interest of the coming year (deductible for a company, and for a
    # Czech individual on actual expenses).
    interest = (financial.loan_schedule(balance, rate, max(years - paid_months // 12, 1))[0][0]
                if balance and rate else 0.0)
    rules = financial.tax_rules() if market == "sk" else financial.markets.tax_rules(None, market)
    if f.get("structure") == "sro":
        profit = rent_12 - costs_12 - interest
        tax = financial.calc_tax_sro(profit, rent_12, rules=rules)
    else:
        # Slovakia: §6(3) rent, the yearly exemption off; Czechia: actual
        # expenses with the interest.
        taxable = (rent_12 - costs_12 - (interest if market == "cz" else 0.0)
                   - (rules.get("rental_exemption") or 0.0 if market == "sk" else 0.0))
        tax = financial.calc_income_tax_personal(max(taxable, 0.0), rules,
                                                 financial.other_annual_income(market))
    cash_flow = rent_12 - costs_12 - payment * 12 - tax
    price = f.get("price") or 0
    model_rent = financial.get_rent_estimate(f.get("district") or "", size, f.get("rooms"), **mk) \
        if size else None
    return FlatNumbers(
        id=f["id"], name=f.get("name") or "", currency="CZK" if market == "cz" else "EUR",
        value=round(value, 2), value_source=source, balance=balance,
        equity=round(value - balance, 2), payment=round(payment, 2),
        rent_12m=round(rent_12, 2), costs_12m=round(costs_12, 2), vacancy_rate=vacancy,
        months_on_record=n, tax_year_est=round(tax, 2), cash_flow_12m=round(cash_flow, 2),
        gross_yield=rent_12 / price if price else 0.0,
        net_yield=(rent_12 - costs_12) / price if price else 0.0,
        model_rent=model_rent, model_hoa=financial.calc_hoa(size, **mk) if size else None)


def calibration(flats: list[dict], numbers: list[FlatNumbers]) -> list[dict]:
    """The model's assumptions next to your flats' own figures."""
    rows = []
    for f, n in zip(flats, numbers):
        months = max(n.months_on_record, 1)
        if n.model_rent and f.get("rent_monthly"):
            rows.append({"Flat": n.name, "Assumption": "Rent a month",
                         "Model": round(n.model_rent), "Yours": round(f["rent_monthly"]),
                         "Gap %": round((f["rent_monthly"] / n.model_rent - 1) * 100, 1)})
        if n.model_hoa and f.get("hoa_monthly"):
            rows.append({"Flat": n.name, "Assumption": "Building fee a month",
                         "Model": round(n.model_hoa), "Yours": round(f["hoa_monthly"]),
                         "Gap %": round((f["hoa_monthly"] / n.model_hoa - 1) * 100, 1)})
        if n.vacancy_rate is not None:
            model = financial.VACANCY_RATE * 100
            rows.append({"Flat": n.name, "Assumption": f"Vacancy % ({months} months on record)",
                         "Model": round(model, 1), "Yours": round(n.vacancy_rate * 100, 1),
                         "Gap %": round((n.vacancy_rate * 100 / model - 1) * 100, 1)
                         if model else None})
    return rows
