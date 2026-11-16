"""Gate self-audit.

These are the fixtures the blueprint originally got wrong: they are
hand-worked, published-formula problems, not artifacts written by the
same person who wrote the gate. A gate that rejects a correct answer is
worse than no gate, so every must-pass case here is computed by hand
from the governing formula.

Run from the repo root:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gates  # noqa: F401  registers every gate
from verify import GATES, GateResult, fail

CLAIMS_OK = {
    "units": {"flexure.Fy_ksi": "ksi", "flexure.Zx_in3": "in^3",
              "flexure.Mu_kip_ft": "kip-ft"},
    "flexure": {"Fy_ksi": 50, "Zx_in3": 100, "Mu_kip_ft": 300},
    "requirements": [{"clause": "AISC 360-16 F2", "value": "phi_b = 0.90"},
                     {"clause": "AISC 360-16 L3", "value": "L/360 live load"}],
}


def ctx_for(task_type: str, data: dict | None = None, files: dict | None = None,
            deliverables: list[str] | None = None, revisions: list | None = None,
            instruction: str = "") -> dict:
    claims = "\n<!-- PLE-CLAIMS\n" + json.dumps(CLAIMS_OK) + "\n-->\n"
    payload = (files if files is not None
               else {"memo.md": claims.encode()})
    return {
        "task_type": task_type,
        "instruction": instruction,
        "data": {**(data or {}), "revisions": revisions if revisions is not None else [
            {"doc_id": "S-201", "rank": "IFC", "revision": 1, "value": 11.0},
        ]},
        "files": payload,
        "deliverables": deliverables if deliverables is not None else ["memo.md"],
    }


def by_id(results, gate_id):
    return [r for r in results if r.gate_id == gate_id]


class TestStructural(unittest.TestCase):
    BASE = {"Fy_ksi": 50, "Zx_in3": 100, "Mu_kip_ft": 300,
            "d_in": 16, "tw_in": 0.4, "Vu_kip": 150,
            "L_span_in": 360, "delta_L_in": 0.8}

    def test_pass_case(self):
        # phi_b*Mn = 0.90 * 50 * 100 / 12 = 375 kip-ft
        # phi_v*Vn = 1.00 * 0.6 * 50 * (16*0.4) = 192 kip
        # delta limit = 360/360 = 1.0 in
        res = GATES.run("structural", ctx_for("structural", {"structural": self.BASE}))
        self.assertTrue(by_id(res, "flexure")[0].passed, by_id(res, "flexure")[0].detail)
        self.assertTrue(by_id(res, "shear")[0].passed)
        self.assertTrue(by_id(res, "deflection")[0].passed)
        self.assertTrue(GATES.all_hard_pass(res))

    def test_flexure_fails_at_400(self):
        bad = {**self.BASE, "Mu_kip_ft": 400}
        res = GATES.run("structural", ctx_for("structural", {"structural": bad}))
        node = by_id(res, "flexure")[0]
        self.assertFalse(node.passed)
        self.assertEqual(node.cause_code, "FLEXURE_DCR_EXCEEDED")
        self.assertAlmostEqual(node.limit, 375.0, places=6)
        self.assertFalse(GATES.all_hard_pass(res))

    def test_shear_and_deflection_fail(self):
        bad = {**self.BASE, "Vu_kip": 200, "delta_L_in": 1.2}
        res = GATES.run("structural", ctx_for("structural", {"structural": bad}))
        self.assertEqual(by_id(res, "shear")[0].cause_code, "SHEAR_DCR_EXCEEDED")
        self.assertEqual(by_id(res, "deflection")[0].cause_code, "DEFLECTION_EXCEEDED")


class TestElectrical(unittest.TestCase):
    BASE = {"I_continuous_a": 200, "conductor_ampacity_a": 255,
            "I_load_a": 200, "L_ft": 150, "cmil": 250000, "voltage_v": 480,
            "phases": 3, "material": "copper", "upstream_vdrop_pct": 0.0,
            "segments": [], "units_required": 250, "units_per_carton": 24,
            "cartons_claimed": 11}

    def test_pass_case(self):
        # 1.25 * 200 = 250 A required; 255 A provided
        # VD = sqrt(3)*12.9*200*150/250000 = 2.6812 V -> 0.5586 %
        # cartons = ceil(250/24) = 11
        res = GATES.run("electrical", ctx_for("electrical", {"electrical": self.BASE}))
        self.assertTrue(by_id(res, "ampacity")[0].passed)
        self.assertTrue(by_id(res, "segment_vdrop")[0].passed)
        self.assertAlmostEqual(by_id(res, "segment_vdrop")[0].observed, 0.558586, places=5)
        self.assertTrue(by_id(res, "carton_takeoff")[0].passed)
        self.assertTrue(GATES.all_hard_pass(res))

    def test_ampacity_requires_125_percent(self):
        bad = {**self.BASE, "conductor_ampacity_a": 240}   # 240 < 1.25*200
        res = GATES.run("electrical", ctx_for("electrical", {"electrical": bad}))
        node = by_id(res, "ampacity")[0]
        self.assertEqual(node.cause_code, "AMPACITY_INSUFFICIENT")
        self.assertAlmostEqual(node.limit, 250.0, places=6)

    def test_cumulative_catches_what_segments_miss(self):
        """Each segment passes (<3%); the run does not (<5%)."""
        seg = {"I_load_a": 100, "L_ft": 600, "cmil": 250000, "voltage_v": 480, "phases": 3}
        case = {**self.BASE, "upstream_vdrop_pct": 3.0, "segments": [seg, seg]}
        res = GATES.run("electrical", ctx_for("electrical", {"electrical": case}))
        self.assertTrue(by_id(res, "segment_vdrop")[0].passed)
        node = by_id(res, "cumulative_vdrop")[0]
        self.assertFalse(node.passed)
        self.assertEqual(node.cause_code, "VCUM_EXCEEDED")
        self.assertGreater(node.observed, 5.0)

    def test_carton_truncation_fails(self):
        bad = {**self.BASE, "cartons_claimed": 10}
        res = GATES.run("electrical", ctx_for("electrical", {"electrical": bad}))
        self.assertEqual(by_id(res, "carton_takeoff")[0].cause_code, "CARTON_ROUNDING")


class TestMechanical(unittest.TestCase):
    def test_colebrook_residual(self):
        """The solver must actually satisfy Colebrook-White."""
        re, rel = 422720.0, 1e-3
        f = gates.mechanical.colebrook(re, rel)
        residual = 1 / math.sqrt(f) + 2 * math.log10(rel / 3.7 + 2.51 / (re * math.sqrt(f)))
        self.assertLess(abs(residual), 1e-9)

    def test_head_loss_in_physical_band(self):
        case = {"flow_m3s": 0.05, "diameter_m": 0.15, "length_m": 100,
                "density": 998, "kinematic_viscosity": 1.004e-6,
                "roughness_m": 1.5e-4, "h_allow_m": 8.0}
        res = GATES.run("mechanical", ctx_for("mechanical", {"mechanical": case}))
        node = by_id(res, "head_loss")[0]
        self.assertTrue(node.passed)
        self.assertTrue(4.0 < node.observed < 7.0, node.observed)

    def test_pump_power_exact(self):
        # 998 * 9.80665 * 0.05 * 20 / 0.75 / 1000 = 13.0494 kW
        case = {"flow_m3s": 0.05, "total_head_m": 20.0, "pump_efficiency": 0.75,
                "density": 998, "power_allow_kw": 20.0}
        res = GATES.run("mechanical", ctx_for("mechanical", {"mechanical": case}))
        self.assertAlmostEqual(by_id(res, "pump_power")[0].observed, 13.04936, places=4)

    def test_lifecycle_npv_exact(self):
        # 100000 + 7000 * ((1-1.06^-25)/0.06) = 189483.36
        case = {"capex": 100000, "annual_kwh": 50000, "energy_price_per_kwh": 0.12,
                "annual_maintenance": 1000, "discount_rate": 0.06, "years": 25,
                "budget_npv": 250000}
        res = GATES.run("mechanical", ctx_for("mechanical", {"mechanical": case}))
        self.assertAlmostEqual(by_id(res, "lifecycle_cost")[0].observed, 189483.36, delta=1.0)


class TestCivil(unittest.TestCase):
    def test_prismoidal_vs_average_end_area(self):
        # prismoidal = (30/6)(100 + 4*200 + 100) = 5000
        # average-end-area would give (100+100)/2*30 = 3000 -> must be rejected
        case = {"A1_m2": 100, "Am_m2": 200, "A2_m2": 100, "L_m": 30,
                "volume_claimed_m3": 3000}
        res = GATES.run("civil", ctx_for("civil", {"civil": case}))
        node = by_id(res, "prismoidal_volume")[0]
        self.assertFalse(node.passed)
        self.assertEqual(node.cause_code, "PRISMOIDAL_MISMATCH")
        self.assertAlmostEqual(node.limit, 5000.0, places=6)

    def test_settlement_recompression_branch(self):
        # 0.03*4000/1.8 * log10(150/100) = 11.739 mm
        case = {"H_m": 4, "e0": 0.8, "Cc": 0.3, "Cr": 0.03,
                "sigma0_kpa": 100, "sigma_p_kpa": 200, "delta_sigma_kpa": 50,
                "settlement_allow_mm": 25}
        res = GATES.run("civil", ctx_for("civil", {"civil": case}))
        self.assertAlmostEqual(by_id(res, "settlement")[0].observed, 11.739, places=2)

    def test_settlement_virgin_branch(self):
        # 66.667*log10(2.0) + 666.667*log10(1.5) = 137.46 mm
        case = {"H_m": 4, "e0": 0.8, "Cc": 0.3, "Cr": 0.03,
                "sigma0_kpa": 100, "sigma_p_kpa": 200, "delta_sigma_kpa": 200,
                "settlement_allow_mm": 25}
        res = GATES.run("civil", ctx_for("civil", {"civil": case}))
        node = by_id(res, "settlement")[0]
        self.assertAlmostEqual(node.observed, 137.46, places=1)
        self.assertEqual(node.cause_code, "SETTLEMENT_EXCEEDED")


class TestCrossCutting(unittest.TestCase):
    def test_missing_deliverable_is_hard_fail(self):
        ctx = ctx_for("structural", {"structural": TestStructural.BASE},
                      deliverables=["memo.md", "schedule.xlsx"])
        res = GATES.run("structural", ctx)
        self.assertIn("MISSING_DELIVERABLE", [r.cause_code for r in res])
        self.assertFalse(GATES.all_hard_pass(res))

    def test_no_claims_block_fails(self):
        ctx = ctx_for("structural", {"structural": TestStructural.BASE},
                      files={"memo.md": b"Prose only, no claims."})
        res = GATES.run("structural", ctx)
        self.assertEqual(by_id(res, "claims_present")[0].cause_code, "NO_CLAIMS_BLOCK")

    def test_unit_missing_fails(self):
        claims = {"units": {}, "flexure": {"Fy_ksi": 50}}
        blob = ("<!-- PLE-CLAIMS\n" + json.dumps(claims) + "\n-->").encode()
        res = GATES.run("structural", ctx_for("structural", {"structural": TestStructural.BASE},
                                              files={"memo.md": blob}))
        self.assertEqual(by_id(res, "unit_declarations")[0].cause_code, "UNIT_MISSING")

    def test_numeric_conflict_between_deliverables(self):
        a = {"units": {"flexure.Mu_kip_ft": "kip-ft"}, "flexure": {"Mu_kip_ft": 300}}
        b = {"units": {"flexure.Mu_kip_ft": "kip-ft"}, "flexure": {"Mu_kip_ft": 340}}
        files = {
            "memo.md": ("<!-- PLE-CLAIMS\n" + json.dumps(a) + "\n-->").encode(),
            "calc.md": ("<!-- PLE-CLAIMS\n" + json.dumps(b) + "\n-->").encode(),
        }
        res = GATES.run("structural", ctx_for("structural", {"structural": TestStructural.BASE},
                                              files=files, deliverables=["memo.md", "calc.md"]))
        self.assertEqual(by_id(res, "numeric_agreement")[0].cause_code, "NUMERIC_CONFLICT")

    def test_revision_authority_prefers_addendum(self):
        revs = [{"doc_id": "S-201", "rank": "IFC", "revision": 1, "value": 11.0},
                {"doc_id": "S-201", "rank": "Addendum", "revision": 2, "value": 12.5}]
        res = GATES.run("structural", ctx_for("structural", {"structural": TestStructural.BASE},
                                              revisions=revs))
        self.assertTrue(by_id(res, "revision_authority")[0].passed)

    def test_revision_tie_is_hard_fail(self):
        revs = [{"doc_id": "S-201", "rank": "Addendum", "revision": 2, "value": 12.5},
                {"doc_id": "S-201", "rank": "Addendum", "revision": 3, "value": 13.0}]
        res = GATES.run("structural", ctx_for("structural", {"structural": TestStructural.BASE},
                                              revisions=revs))
        self.assertEqual(by_id(res, "revision_authority")[0].cause_code, "REVISION_CONFLICT")

    def test_requirements_listed_passes(self):
        res = GATES.run("structural", ctx_for(
            "structural", {"structural": TestStructural.BASE},
            instruction="List the code clauses you applied and their values."))
        self.assertTrue(by_id(res, "requirements_listed")[0].passed)

    def test_requirements_missing_fails(self):
        claims = {"units": {}, "flexure": {"Fy_ksi": 50}}
        blob = ("<!-- PLE-CLAIMS\n" + json.dumps(claims) + "\n-->").encode()
        res = GATES.run("structural", ctx_for(
            "structural", {"structural": TestStructural.BASE},
            files={"memo.md": blob},
            instruction="Size the beam to the applicable code clauses."))
        self.assertEqual(by_id(res, "requirements_listed")[0].cause_code,
                         "REQUIREMENTS_MISSING")

    def test_requirement_without_clause_or_value_fails(self):
        claims = {"units": {"flexure.Mu_kip_ft": "kip-ft"}, "flexure": {"Mu_kip_ft": 300},
                  "requirements": [{"clause": "AISC 360-16 F2"},
                                   {"value": "L/360"}]}
        blob = ("<!-- PLE-CLAIMS\n" + json.dumps(claims) + "\n-->").encode()
        res = GATES.run("structural", ctx_for(
            "structural", {"structural": TestStructural.BASE},
            files={"memo.md": blob},
            instruction="Size the beam to the applicable code clauses."))
        codes = {r.cause_code for r in by_id(res, "requirements_listed")}
        self.assertIn("REQUIREMENT_NO_VALUE", codes)
        self.assertIn("REQUIREMENT_NO_CLAUSE", codes)

    def test_revision_table_missing_is_not_a_pass(self):
        # The task says documents conflict, so a missing table is a real gap.
        res = GATES.run("structural", ctx_for(
            "structural", {"structural": TestStructural.BASE}, revisions=[],
            instruction="An Addendum supersedes the superseded IFC revision; "
                        "use the governing document."))
        self.assertEqual(by_id(res, "revision_authority")[0].cause_code,
                         "REVISION_TABLE_MISSING")

    def test_gates_decline_a_task_they_cannot_judge(self):
        """Regression, from kit check's smoke stage.

        A deliverable that carries no numbers, cites no code and ranks no
        revisions must not be failed for lacking a claims block or a revision
        table. Before this, the repair loop spent its whole budget asking for
        artefacts the task never requested.
        """
        res = GATES.run("unknown", ctx_for(
            "unknown", files={"hello.txt": b"HELLO\n"},
            deliverables=["hello.txt"], revisions=[]))
        self.assertEqual([r.gate_id for r in res], ["contract_deliverables"])
        self.assertTrue(all(r.passed for r in res))


class TestStrictSemantics(unittest.TestCase):
    def test_empty_result_set_is_fail(self):
        self.assertFalse(GATES.all_hard_pass([]))

    def test_soft_only_is_not_pass(self):
        soft = GateResult(gate_id="x", passed=False, severity="soft")
        self.assertFalse(GATES.all_hard_pass([soft]))

    def test_soft_failure_does_not_block(self):
        res = [GateResult(gate_id="hard", passed=True),
               GateResult(gate_id="aesthetic", passed=False, severity="soft")]
        self.assertTrue(GATES.all_hard_pass(res))

    def test_raising_gate_becomes_hard_failure(self):
        @GATES.register("__boom__")
        def explode(ctx):
            raise ValueError("gate blew up")

        res = GATES.run("__boom__", ctx_for("__boom__", {}, files={"memo.md": b"x"}))
        node = [r for r in res if r.gate_id == "explode"][0]
        self.assertFalse(node.passed)
        self.assertEqual(node.severity, "hard")
        self.assertEqual(node.cause_code, "GATE_ERROR")
        self.assertFalse(GATES.all_hard_pass(res))

    def test_signature_separates_different_causes(self):
        a = fail("flexure", "FLEXURE_DCR_EXCEEDED", "", observed=400, limit=375)
        b = fail("flexure", "FLEXURE_DCR_EXCEEDED", "", observed=380, limit=375)
        c = fail("flexure", "SHEAR_DCR_EXCEEDED", "", observed=400, limit=375)
        self.assertEqual(a.signature(), b.signature())   # same cause, same decade
        self.assertNotEqual(a.signature(), c.signature())  # different cause

    def test_every_discipline_has_gates(self):
        import gates as g
        index = g.gate_index()
        for discipline in g.DISCIPLINES:
            self.assertGreater(len(index[discipline]), len(GATES._cross), discipline)


if __name__ == "__main__":
    unittest.main(verbosity=2)
