"""Mechanical gates — Darcy-Weisbach head loss, pump power, 25-year LCC.

23 of the 56 hidden tasks are mechanical: the single largest slice. These
gates deliberately recompute the friction factor rather than accept the
model's value, because friction factor is the most common silent error.
"""
from __future__ import annotations

import math

from verify import GATES, GateResult, fail, ok

G = 9.80665


def colebrook(Re: float, rel_roughness: float) -> float:
    """Darcy friction factor from Colebrook-White, iterative to 1e-12."""
    if Re <= 0:
        raise ValueError("Reynolds number must be positive")
    if Re < 2300:                                   # laminar
        return 64.0 / Re
    f = 0.25 / (math.log10(rel_roughness / 3.7 + 5.74 / Re ** 0.9)) ** 2
    for _ in range(200):
        rhs = -2.0 * math.log10(rel_roughness / 3.7 + 2.51 / (Re * math.sqrt(f)))
        new = 1.0 / (rhs * rhs)
        if abs(new - f) < 1e-12:
            return new
        f = new
    return f


@GATES.register("mechanical")
def head_loss(ctx: dict) -> list[GateResult]:
    m = (ctx.get("data") or {}).get("mechanical") or {}
    q = float(m["flow_m3s"])
    d = float(m["diameter_m"])
    length = float(m["length_m"])
    rho = float(m.get("density", 998.0))
    nu = float(m.get("kinematic_viscosity", 1.004e-6))
    eps = float(m.get("roughness_m", 1.5e-4))

    area = math.pi * d * d / 4.0
    v = q / area
    re = v * d / nu
    f = colebrook(re, eps / d)
    h_f = f * (length / d) * v * v / (2.0 * G)

    allowed = m.get("h_allow_m")
    if allowed is not None and h_f > float(allowed):
        return [fail("head_loss", "HEADLOSS_EXCEEDED",
                     f"Darcy-Weisbach head loss exceeds allowance (f={f:.6f}, Re={re:,.0f})",
                     observed=round(h_f, 6), limit=float(allowed), unit=" m")]
    return [ok("head_loss", f"f={f:.6f} Re={re:,.0f}",
               observed=round(h_f, 6), limit=float(allowed) if allowed else None, unit=" m")]


@GATES.register("mechanical")
def pump_power(ctx: dict) -> list[GateResult]:
    m = (ctx.get("data") or {}).get("mechanical") or {}
    rho = float(m.get("density", 998.0))
    q = float(m["flow_m3s"])
    head = float(m["total_head_m"])
    eff = float(m.get("pump_efficiency", 0.75))
    if not 0 < eff <= 1:
        return [fail("pump_power", "BAD_INPUT", "pump_efficiency must be in (0, 1]")]
    power_kw = rho * G * q * head / eff / 1000.0
    allowed = m.get("power_allow_kw")
    if allowed is not None and power_kw > float(allowed):
        return [fail("pump_power", "PUMP_POWER_EXCEEDED",
                     "shaft power exceeds budget at the stated efficiency",
                     observed=round(power_kw, 6), limit=float(allowed), unit=" kW")]
    return [ok("pump_power", observed=round(power_kw, 6),
               limit=float(allowed) if allowed else None, unit=" kW")]


@GATES.register("mechanical")
def lifecycle_cost(ctx: dict) -> list[GateResult]:
    """25-year NPV: capex plus discounted energy and maintenance."""
    m = (ctx.get("data") or {}).get("mechanical") or {}
    capex = float(m["capex"])
    kwh_year = float(m["annual_kwh"])
    price = float(m["energy_price_per_kwh"])
    maintenance = float(m.get("annual_maintenance", 0.0))
    rate = float(m.get("discount_rate", 0.06))
    years = int(m.get("years", 25))

    npv = capex
    for year in range(1, years + 1):
        npv += (kwh_year * price + maintenance) / ((1.0 + rate) ** year)

    allowed = m.get("budget_npv")
    if allowed is not None and npv > float(allowed):
        return [fail("lifecycle_cost", "LCC_EXCEEDED",
                     f"{years}-yr NPV exceeds budget at {rate:.1%} discount",
                     observed=round(npv, 2), limit=float(allowed), unit="")]
    return [ok("lifecycle_cost", observed=round(npv, 2),
               limit=float(allowed) if allowed else None, unit="")]
