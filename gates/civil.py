"""Civil gates — prismoidal earthwork, buffer clearance, consolidation settlement."""
from __future__ import annotations

import math

from verify import GATES, GateResult, fail, ok


@GATES.register("civil")
def prismoidal_volume(ctx: dict) -> list[GateResult]:
    """V = (L/6)(A1 + 4Am + A2). The average-end-area formula is the usual error."""
    c = (ctx.get("data") or {}).get("civil") or {}
    a1, am, a2 = float(c["A1_m2"]), float(c["Am_m2"]), float(c["A2_m2"])
    length = float(c["L_m"])
    volume = (length / 6.0) * (a1 + 4.0 * am + a2)

    claimed = c.get("volume_claimed_m3")
    if claimed is not None and abs(float(claimed) - volume) > 1e-6 * max(volume, 1.0):
        return [fail("prismoidal_volume", "PRISMOIDAL_MISMATCH",
                     "claimed volume does not match the prismoidal formula; "
                     "average-end-area truncates curved transitions",
                     observed=float(claimed), limit=round(volume, 6), unit=" m^3")]
    return [ok("prismoidal_volume", observed=round(volume, 6), unit=" m^3")]


@GATES.register("civil")
def buffer_clearance(ctx: dict) -> list[GateResult]:
    c = (ctx.get("data") or {}).get("civil") or {}
    required = float(c["clearance_required_m"])
    provided = float(c["clearance_provided_m"])
    if provided < required:
        return [fail("buffer_clearance", "CLEARANCE_VIOLATED",
                     "buffer separation is below the governing requirement",
                     observed=provided, limit=required, unit=" m")]
    return [ok("buffer_clearance", observed=provided, limit=required, unit=" m")]


@GATES.register("civil")
def settlement(ctx: dict) -> list[GateResult]:
    """Terzaghi one-dimensional consolidation, over-consolidated then virgin.

    Treating an over-consolidated clay as normally consolidated over-predicts
    settlement by an order of magnitude; the reverse under-predicts it.
    """
    c = (ctx.get("data") or {}).get("civil") or {}
    h = float(c["H_m"]) * 1000.0                      # mm
    e0 = float(c["e0"])
    cc = float(c["Cc"])
    cr = float(c.get("Cr", cc / 10.0))
    s0 = float(c["sigma0_kpa"])
    sp = float(c["sigma_p_kpa"])
    ds = float(c["delta_sigma_kpa"])

    if s0 <= 0 or sp <= 0:
        return [fail("settlement", "BAD_INPUT", "effective stresses must be positive")]

    if s0 + ds <= sp:                                  # stays in recompression
        s = (cr * h / (1.0 + e0)) * math.log10((s0 + ds) / s0)
    else:                                              # crosses preconsolidation
        s = (cr * h / (1.0 + e0)) * math.log10(sp / s0)
        s += (cc * h / (1.0 + e0)) * math.log10((s0 + ds) / sp)

    allowed = c.get("settlement_allow_mm")
    if allowed is not None and s > float(allowed):
        return [fail("settlement", "SETTLEMENT_EXCEEDED",
                     "consolidation settlement exceeds the serviceability limit",
                     observed=round(s, 6), limit=float(allowed), unit=" mm")]
    return [ok("settlement", observed=round(s, 6),
               limit=float(allowed) if allowed else None, unit=" mm")]
