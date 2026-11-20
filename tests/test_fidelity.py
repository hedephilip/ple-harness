"""Gate fidelity: does each gate actually reject what it claims to reject?

A gate that passes everything is decoration; a gate that fails a valid
deliverable is worse than no gate, because the repair loop then pushes the agent
to edit work the rubric already scores. So every gate here gets the same
treatment: a hand-computed passing case that must stay green, and one
single-parameter perturbation that must trip it with a specific cause code.

None of the numbers come from the benchmark. They are worked out from the
formulae the gates implement, which is the only way to tell a gate that is
correct from one that agrees with itself.

    python tests/test_fidelity.py        # prints the matrix
"""
from __future__ import annotations

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gates import assert_registered            # noqa: E402
from verify import GATES                       # noqa: E402

assert_registered()


def claims_text(payload: dict) -> str:
    """A deliverable carrying a machine-readable claims block."""
    return "<!-- PLE-CLAIMS\n" + json.dumps(payload) + "\n-->\n"


def ctx(discipline: str, data: dict, texts: dict | None = None,
        deliverables: list[str] | None = None,
        instruction: str = "") -> dict:
    texts = texts or {}
    return {
        "task_type": discipline,
        "instruction": instruction,
        "deliverables": deliverables if deliverables is not None else list(texts),
        "files": {path: text.encode() for path, text in texts.items()},
        "texts": dict(texts),
        "present": set(texts),
        "data": data,
    }


# --- structural: phi_b*Mn = 0.90*50*100/12 = 375 kip-ft
#                 phi_v*Vn = 1.00*0.6*50*(16*0.4) = 192 kip
#                 delta limit = 360/360 = 1.0 in
STRUCT = {"Fy_ksi": 50, "Zx_in3": 100, "Mu_kip_ft": 300,
          "d_in": 16, "tw_in": 0.4, "Vu_kip": 150,
          "L_span_in": 360, "delta_L_in": 0.8}

# 1.25*200 = 250 A required against 255 provided; ceil(250/24) = 11 cartons
ELEC = {"I_continuous_a": 200, "conductor_ampacity_a": 255,
        "I_load_a": 200, "L_ft": 150, "cmil": 250000, "voltage_v": 480,
        "phases": 3, "material": "copper", "upstream_vdrop_pct": 0.0,
        "segments": [], "units_required": 250, "units_per_carton": 24,
        "cartons_claimed": 11}

# 0.05 m3/s through 200 mm over 200 m: v=1.59 m/s, h_f about 2.0 m
# pump: 998*9.81*0.05*20/0.8 = 12.2 kW; 25-yr NPV about 202k
MECH = {"flow_m3s": 0.05, "diameter_m": 0.2, "length_m": 200,
        "h_allow_m": 50.0, "total_head_m": 20.0, "pump_efficiency": 0.8,
        "power_allow_kw": 50.0, "capex": 100000.0, "annual_kwh": 50000.0,
        "energy_price_per_kwh": 0.12, "annual_maintenance": 2000.0,
        "discount_rate": 0.06, "years": 25, "budget_npv": 500000.0}

# prismoidal (30/6)(100 + 4*200 + 100) = 5000; settlement about 8.3 mm
CIVIL = {"A1_m2": 100, "Am_m2": 200, "A2_m2": 100, "L_m": 30,
         "volume_claimed_m3": 5000, "clearance_required_m": 2.0,
         "clearance_provided_m": 3.0, "H_m": 3.0, "e0": 0.9, "Cc": 0.3,
         "sigma0_kpa": 100.0, "sigma_p_kpa": 200.0, "delta_sigma_kpa": 50.0,
         "settlement_allow_mm": 100.0}


def merged(base: dict, **overrides) -> dict:
    data = dict(base)
    data.update(overrides)
    return data


# (discipline, gate_id, data, expected_cause_code)
CASES = [
    ("structural", "flexure", merged(STRUCT, Mu_kip_ft=420), "FLEXURE_DCR_EXCEEDED"),
    ("structural", "shear", merged(STRUCT, Vu_kip=200), "SHEAR_DCR_EXCEEDED"),
    ("structural", "deflection", merged(STRUCT, delta_L_in=1.2), "DEFLECTION_EXCEEDED"),
    ("electrical", "ampacity", merged(ELEC, conductor_ampacity_a=240),
     "AMPACITY_INSUFFICIENT"),
    ("electrical", "segment_vdrop", merged(ELEC, cmil=25000), "VSEG_EXCEEDED"),
    ("electrical", "cumulative_vdrop", merged(ELEC, upstream_vdrop_pct=6.0),
     "VCUM_EXCEEDED"),
    ("electrical", "carton_takeoff", merged(ELEC, cartons_claimed=10), "CARTON_ROUNDING"),
    ("mechanical", "head_loss", merged(MECH, h_allow_m=0.5), "HEADLOSS_EXCEEDED"),
    ("mechanical", "pump_power", merged(MECH, power_allow_kw=1.0), "PUMP_POWER_EXCEEDED"),
    ("mechanical", "lifecycle_cost", merged(MECH, budget_npv=50000.0), "LCC_EXCEEDED"),
    ("civil", "prismoidal_volume", merged(CIVIL, volume_claimed_m3=3000),
     "PRISMOIDAL_MISMATCH"),
    ("civil", "buffer_clearance", merged(CIVIL, clearance_provided_m=1.0),
     "CLEARANCE_VIOLATED"),
    ("civil", "settlement", merged(CIVIL, settlement_allow_mm=1.0),
     "SETTLEMENT_EXCEEDED"),
]

BASES = {"structural": STRUCT, "electrical": ELEC, "mechanical": MECH, "civil": CIVIL}


def nodes(discipline: str, data: dict):
    results = GATES.run(discipline, ctx(discipline, {discipline: data}))
    return results


def find(results, gate_id):
    for result in results:
        if result.gate_id == gate_id:
            return result
    return None


class TestDisciplineFidelity(unittest.TestCase):
    def test_passing_case_stays_green(self):
        """No gate may fire on a hand-computed compliant design."""
        for discipline, base in BASES.items():
            with self.subTest(discipline=discipline):
                for result in nodes(discipline, base):
                    if result.gate_id in {c[1] for c in CASES}:
                        self.assertTrue(result.passed,
                                        f"{result.gate_id} rejected a valid case: "
                                        f"{result.cause_code} {result.detail}")

    def test_perturbation_trips_the_right_gate(self):
        for discipline, gate_id, data, code in CASES:
            with self.subTest(gate=gate_id):
                node = find(nodes(discipline, data), gate_id)
                self.assertIsNotNone(node, f"{gate_id} produced no result")
                self.assertFalse(node.passed, f"{gate_id} passed a violating case")
                self.assertEqual(node.cause_code, code)


class TestCrossFidelity(unittest.TestCase):
    def test_missing_deliverable_is_caught(self):
        results = GATES.run("structural", ctx(
            "structural", {"structural": STRUCT}, texts={}, deliverables=["memo.md"]))
        node = find(results, "contract_deliverables")
        self.assertFalse(node.passed)
        self.assertEqual(node.cause_code, "MISSING_DELIVERABLE")

    def test_claims_block_absence_is_caught(self):
        results = GATES.run("structural", ctx(
            "structural", {"structural": STRUCT}, texts={"memo.md": "Prose, no claims."}))
        node = find(results, "claims_present")
        self.assertIsNotNone(node)
        self.assertFalse(node.passed)
        self.assertEqual(node.cause_code, "NO_CLAIMS_BLOCK")

    def test_unreadable_deliverable_declines_rather_than_fails(self):
        """A .docx cannot hold a markdown claims block; the gate must stand aside."""
        results = GATES.run("structural", ctx(
            "structural", {"structural": STRUCT}, texts={}, deliverables=["memo.docx"]))
        self.assertIsNone(find(results, "claims_present"))

    def test_missing_unit_map_is_caught(self):
        text = claims_text({"Fy_ksi": 50, "units": {}})
        results = GATES.run("structural", ctx(
            "structural", {"structural": STRUCT}, texts={"memo.md": text}))
        node = find(results, "unit_declarations")
        self.assertFalse(node.passed)
        self.assertEqual(node.cause_code, "UNIT_MISSING")

    def test_disagreeing_numbers_across_files_are_caught(self):
        left = claims_text({"Fy_ksi": 50, "units": {"Fy_ksi": "ksi"}})
        right = claims_text({"Fy_ksi": 60, "units": {"Fy_ksi": "ksi"}})
        results = GATES.run("structural", ctx(
            "structural", {"structural": STRUCT},
            texts={"a.md": left, "b.md": right}))
        node = find(results, "numeric_agreement")
        self.assertFalse(node.passed)
        self.assertEqual(node.cause_code, "NUMERIC_CONFLICT")

    def test_unlisted_requirements_are_caught(self):
        text = claims_text({"Fy_ksi": 50, "units": {"Fy_ksi": "ksi"}})
        results = GATES.run("structural", ctx(
            "structural", {"structural": STRUCT}, texts={"memo.md": text},
            instruction="Size the beam to the applicable code clauses."))
        node = find(results, "requirements_listed")
        self.assertFalse(node.passed)
        self.assertEqual(node.cause_code, "REQUIREMENTS_MISSING")

    def test_conflicting_revision_authority_is_caught(self):
        rows = [
            {"doc_id": "S-201", "rank": "Addendum", "revision": 2, "value": 12.5},
            {"doc_id": "S-201", "rank": "Addendum", "revision": 2, "value": 11.0},
        ]
        data = {"structural": STRUCT, "revisions": rows}
        results = GATES.run("structural", ctx(
            "structural", data, texts={"memo.md": claims_text({"Fy_ksi": 50})}))
        node = find(results, "revision_authority")
        self.assertFalse(node.passed, "two equally-ranked documents disagreed "
                                      "and the gate accepted one of them")
        self.assertTrue(node.cause_code, "a failing revision gate needs a cause code")


def matrix() -> list[str]:
    lines = ["| gate | valid case | perturbed case |", "|---|---|---|"]
    for discipline, gate_id, data, code in CASES:
        base = find(nodes(discipline, BASES[discipline]), gate_id)
        bad = find(nodes(discipline, data), gate_id)
        ok_text = "pass" if base and base.passed else "FAIL"
        bad_text = f"{bad.cause_code}" if bad and not bad.passed else "FAIL (passed)"
        lines.append(f"| {gate_id} | {ok_text} | {bad_text} |")
    return lines


if __name__ == "__main__":
    print("\n".join(matrix()))
