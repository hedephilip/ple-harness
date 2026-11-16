"""Structural gates — AISC 360-16 LRFD.

Demand (M_u, V_u, delta_L) comes from the model's analysis. Capacity is
*recomputed here* from the section and material properties. If the model
reports a capacity, it is ignored: that is the whole point.
"""
from __future__ import annotations

from verify import GATES, GateResult, fail, ok

PHI_B = 0.90            # AISC 360-16 F1, compact braced I-shape
PHI_V = 1.00            # AISC 360-16 G1, rolled I-shape, h/tw <= 2.24*sqrt(E/Fy)
DEFLECTION_RATIO = 360  # L/360 live load


@GATES.register("structural")
def flexure(ctx: dict) -> list[GateResult]:
    s = (ctx.get("data") or {}).get("structural") or {}
    phi_mn = PHI_B * float(s["Fy_ksi"]) * float(s["Zx_in3"]) / 12.0   # kip-ft
    mu = float(s["Mu_kip_ft"])
    if mu > phi_mn:
        return [fail("flexure", "FLEXURE_DCR_EXCEEDED",
                     "phi_b*Mn exceeded; increase section or reduce span",
                     observed=mu, limit=round(phi_mn, 6), unit=" kip-ft")]
    return [ok("flexure", observed=mu, limit=round(phi_mn, 6), unit=" kip-ft")]


@GATES.register("structural")
def shear(ctx: dict) -> list[GateResult]:
    s = (ctx.get("data") or {}).get("structural") or {}
    aw = float(s["d_in"]) * float(s["tw_in"])                    # in^2
    phi_vn = PHI_V * 0.6 * float(s["Fy_ksi"]) * aw               # kip
    vu = float(s["Vu_kip"])
    if vu > phi_vn:
        return [fail("shear", "SHEAR_DCR_EXCEEDED",
                     "phi_v*Vn exceeded; web is under-strength",
                     observed=vu, limit=round(phi_vn, 6), unit=" kip")]
    return [ok("shear", observed=vu, limit=round(phi_vn, 6), unit=" kip")]


@GATES.register("structural")
def deflection(ctx: dict) -> list[GateResult]:
    s = (ctx.get("data") or {}).get("structural") or {}
    limit = float(s["L_span_in"]) / DEFLECTION_RATIO
    delta = float(s["delta_L_in"])
    if delta > limit:
        return [fail("deflection", "DEFLECTION_EXCEEDED",
                     f"live-load deflection exceeds L/{DEFLECTION_RATIO}",
                     observed=delta, limit=round(limit, 6), unit=" in")]
    return [ok("deflection", observed=delta, limit=round(limit, 6), unit=" in")]
