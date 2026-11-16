"""Electrical gates — NEC 2023 ampacity and voltage drop.

18 of the 56 hidden tasks are electrical, so these four gates carry more
weight than any other discipline module.
"""
from __future__ import annotations

import math

from verify import GATES, GateResult, fail, ok

CONTINUOUS_FACTOR = 1.25   # NEC 210.19(A)(1) / 215.2(A)(1)
VSEG_LIMIT_PCT = 3.0       # branch-circuit segment
VCUM_LIMIT_PCT = 5.0       # feeder + branch cumulative
K_COPPER = 12.9            # ohm-cmil/ft
K_ALUMINUM = 21.2


def voltage_drop(K: float, current_a: float, length_ft: float,
                 cmil: float, phases: int) -> float:
    """NEC circular-mil voltage drop, in volts."""
    factor = math.sqrt(3.0) if phases == 3 else 2.0
    return factor * K * current_a * length_ft / cmil


@GATES.register("electrical")
def ampacity(ctx: dict) -> list[GateResult]:
    e = (ctx.get("data") or {}).get("electrical") or {}
    required = CONTINUOUS_FACTOR * float(e["I_continuous_a"])
    provided = float(e["conductor_ampacity_a"])
    if provided < required:
        return [fail("ampacity", "AMPACITY_INSUFFICIENT",
                     f"continuous load requires {CONTINUOUS_FACTOR:g}x; "
                     "conductor is undersized after adjustment",
                     observed=provided, limit=round(required, 6), unit=" A")]
    return [ok("ampacity", observed=provided, limit=round(required, 6), unit=" A")]


@GATES.register("electrical")
def segment_vdrop(ctx: dict) -> list[GateResult]:
    e = (ctx.get("data") or {}).get("electrical") or {}
    K = K_COPPER if str(e.get("material", "copper")).lower().startswith("c") else K_ALUMINUM
    vd = voltage_drop(K, float(e["I_load_a"]), float(e["L_ft"]),
                      float(e["cmil"]), int(e.get("phases", 3)))
    pct = vd / float(e["voltage_v"]) * 100.0
    if pct > VSEG_LIMIT_PCT:
        return [fail("segment_vdrop", "VSEG_EXCEEDED",
                     f"segment drop exceeds {VSEG_LIMIT_PCT:g}%",
                     observed=round(pct, 6), limit=VSEG_LIMIT_PCT, unit=" %")]
    return [ok("segment_vdrop", observed=round(pct, 6), limit=VSEG_LIMIT_PCT, unit=" %")]


@GATES.register("electrical")
def cumulative_vdrop(ctx: dict) -> list[GateResult]:
    """Cumulative is where most agents lose the task: each segment passes, the run does not."""
    e = (ctx.get("data") or {}).get("electrical") or {}
    K = K_COPPER if str(e.get("material", "copper")).lower().startswith("c") else K_ALUMINUM
    total = float(e.get("upstream_vdrop_pct", 0.0))
    for segment in e.get("segments", []):
        vd = voltage_drop(K, float(segment["I_load_a"]), float(segment["L_ft"]),
                          float(segment["cmil"]), int(segment.get("phases", 3)))
        total += vd / float(segment["voltage_v"]) * 100.0
    if total > VCUM_LIMIT_PCT:
        return [fail("cumulative_vdrop", "VCUM_EXCEEDED",
                     "source-to-load drop exceeds the cumulative limit even though "
                     "each individual segment may pass",
                     observed=round(total, 6), limit=VCUM_LIMIT_PCT, unit=" %")]
    return [ok("cumulative_vdrop", observed=round(total, 6), limit=VCUM_LIMIT_PCT, unit=" %")]


@GATES.register("electrical")
def carton_takeoff(ctx: dict) -> list[GateResult]:
    """Quantities round up. A takeoff of 10.4 cartons is 11 cartons."""
    e = (ctx.get("data") or {}).get("electrical") or {}
    units = float(e["units_required"])
    per_carton = float(e["units_per_carton"])
    if per_carton <= 0:
        return [fail("carton_takeoff", "BAD_INPUT", "units_per_carton must be > 0")]
    exact = units / per_carton
    required = float(math.ceil(exact - 1e-9))
    claimed = float(e.get("cartons_claimed", required))
    if claimed + 1e-9 < required:
        return [fail("carton_takeoff", "CARTON_ROUNDING",
                     "carton count was truncated instead of rounded up",
                     observed=claimed, limit=required, unit=" cartons")]
    return [ok("carton_takeoff", observed=claimed, limit=required, unit=" cartons")]
