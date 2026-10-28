import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ark_assistant.app import demo_data
from ark_assistant.maa import doctor, load_settings
from ark_assistant.model import analyze, material_plan, match_job, normalize_inventory, normalize_job, resolve_stage
from ark_assistant.network import SafeRedirect, get_public_json, search_jobs


def inventory(**extra):
    row = {"name": "芬", "elite": 1, "level": 55, "skills": {"1": 7}}
    row.update(extra)
    return normalize_inventory({"operators": [row], "materials": {"30011": 12}})


def job(**extra):
    raw = {"stage_name": "1-7", "opers": [{"name": "芬", "skill": 1,
           "requirements": {"elite": 1, "level": 50, "skill_level": 7}}], "actions": [{"type": "Deploy"}]}
    raw.update(extra)
    return normalize_job(raw)


class AnalysisTests(unittest.TestCase):
    def test_demo_is_not_real_success(self):
        report = analyze(*demo_data())
        self.assertEqual(report["mode"], "ANALYSIS_ONLY")
        self.assertFalse(report["execution_enabled"])
        self.assertTrue(report["is_demo"])
        self.assertEqual(len(report["matches"]), 3)
        self.assertTrue(all(row["status"] != "SUCCEEDED" for row in report["matches"]))

    def test_known_requirements_candidate_not_completion(self):
        row = match_job(inventory(), job())
        self.assertEqual(row["status"], "CANDIDATE")
        self.assertIn("未", row["notice"])

    def test_unknown_skill_review(self):
        inv = inventory()
        inv["operators"][0]["skills"] = {}
        self.assertEqual(match_job(inv, job())["status"], "NEEDS_REVIEW")

    def test_skill_not_equivalent_to_other_skill_mastery(self):
        req = job()
        req["opers"][0].update(skill=2, requirements={"skill_level": 10})
        self.assertEqual(match_job(inventory(skills={"1": 10}), req)["status"], "NEEDS_REVIEW")

    def test_insufficient_level_blocks(self):
        self.assertEqual(match_job(inventory(level=40), job())["status"], "MISSING_REQUIREMENTS")

    def test_no_requirements_needs_review(self):
        req = job()
        req["opers"][0].pop("requirements")
        self.assertEqual(match_job(inventory(), req)["status"], "NEEDS_REVIEW")

    def test_unknown_only_requirements_needs_review(self):
        req = job()
        req["opers"][0]["requirements"] = {"future_field": 1}
        self.assertEqual(match_job(inventory(), req)["status"], "NEEDS_REVIEW")

    def test_unknown_additional_requirements_needs_review(self):
        req = job()
        req["opers"][0]["requirements"]["future_field"] = 1
        self.assertEqual(match_job(inventory(), req)["status"], "NEEDS_REVIEW")

    def test_same_operator_cannot_fill_two_slots(self):
        req = job()
        req["groups"] = [{"name": "另一位置", "opers": copy.deepcopy(req["opers"])}]
        row = match_job(inventory(), req)
        self.assertEqual(row["status"], "MISSING_REQUIREMENTS")
        self.assertEqual(len(row["assignments"]), 1)

    def test_group_alternative_and_unique_assignment(self):
        inv = inventory()
        inv["operators"].append({"name": "斑点", "elite": 1, "level": 55, "skills": {"1": 7}, "modules": {}})
        req = job()
        req["groups"] = [{"name": "替换位置", "opers": [copy.deepcopy(req["opers"][0]),
                          {"name": "斑点", "skill": 1, "requirements": {"level": 40}}]}]
        row = match_job(inv, req)
        self.assertEqual(row["status"], "CANDIDATE")
        self.assertEqual(len({s["operator"] for s in row["assignments"]}), 2)

    def test_unowned_and_unknown_all_opers_excluded(self):
        inv = normalize_inventory({"all_opers": [{"name": "芬", "own": True},
                        {"name": "斑点", "own": False}, {"name": "芙蓉"}]})
        self.assertEqual([row["name"] for row in inv["operators"]], ["芬"])

    def test_unrelated_account_fields_not_saved(self):
        inv = normalize_inventory({"operators": ["芬"], "unrelated": "discard",
                                   "materials": {}, "account_identifier": "discard"})
        self.assertNotIn("unrelated", inv)
        self.assertNotIn("account_identifier", inv)

    def test_id_mapping(self):
        inv = normalize_inventory({"own_opers": [{"id": "example_id"}]}, {"example_id": "芬"})
        self.assertEqual(inv["operators"][0]["name"], "芬")

    def test_negative_stock_and_bool_rejected(self):
        for amount in (-1, True, "12"):
            with self.assertRaises(ValueError):
                normalize_inventory({"operators": [], "materials": {"30011": amount}})

    def test_duplicate_operator_rejected(self):
        with self.assertRaises(ValueError):
            normalize_inventory(["芬", "芬"])

    def test_unknown_stock_is_not_zero(self):
        plan = material_plan(inventory(), {"materials": {"unknown_item": 5, "30011": 20}})
        self.assertIsNone(plan["items"][0]["deficit"])
        self.assertEqual(plan["items"][1]["deficit"], 8)

    def test_target_extras_removed(self):
        plan = material_plan(inventory(), {"targets": [{"name": "芬", "unrelated": "discard"}]})
        self.assertEqual(plan["targets"], [{"name": "芬"}])

    def test_stage_id_resolved_exactly(self):
        req = job(stage_name="main_01-07")
        self.assertEqual(match_job(inventory(), req, "1-7", {"main_01-07": "1-7"})["status"], "CANDIDATE")
        self.assertEqual(match_job(inventory(), req, "1-8", {"main_01-07": "1-7"})["status"], "WRONG_STAGE")

    def test_duplicate_activity_code_not_silently_matched(self):
        mapping = {"old_event_12": "VEC-12", "new_event_12": "VEC-12"}
        with self.assertRaises(ValueError):
            resolve_stage("VEC-12", mapping)
        self.assertEqual(match_job(inventory(), job(stage_name="old_event_12"), "new_event_12", mapping)["status"], "WRONG_STAGE")

    def test_duplicate_activity_search_requires_disambiguation_before_network(self):
        with patch("ark_assistant.network.get_public_json") as getter:
            with self.assertRaises(ValueError):
                search_jobs("VEC-12", stage_map={"old_event": "VEC-12", "new_event": "VEC-12"})
        getter.assert_not_called()

    def test_no_actions_rejected(self):
        for actions in (None, [], "video"):
            with self.assertRaises(ValueError):
                job(actions=actions)

    def test_unknown_module_review(self):
        req = job()
        req["opers"][0]["requirements"]["module"] = 1
        self.assertEqual(match_job(inventory(), req)["status"], "NEEDS_REVIEW")

    def test_module_level_checked(self):
        req = job()
        req["opers"][0]["requirements"].update(module=1, module_level=3)
        self.assertEqual(match_job(inventory(modules={"1": 1}), req)["status"], "MISSING_REQUIREMENTS")

    def test_demo_taints_mixed_report(self):
        self.assertTrue(analyze(inventory(), [job(is_demo=True)])["is_demo"])
        self.assertTrue(analyze(inventory(), [job()], {"is_demo": True})["is_demo"])

    def test_public_search_does_not_take_roster(self):
        raw = {"stage_name": "1-7", "actions": [{"type": "Output"}], "opers": []}
        with patch("ark_assistant.network.get_public_json", return_value={"data": [
                {"id": 1, "content": json.dumps(raw)}, {"id": 2, "content": "{}"}]}) as getter:
            jobs, info = search_jobs("1-7", 2)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(info["rejected_ids"], ["2"])
        query = getter.call_args.args[1]
        self.assertNotIn("operators", query)
        self.assertNotIn("inventory", query)

    def test_live_summary_requires_full_detail(self):
        summary = {"id": 1, "content": json.dumps({"stage_name": "1-7"})}
        full = {"id": 1, "content": json.dumps({"stage_name": "1-7", "actions": [{"type": "Output"}]})}
        with patch("ark_assistant.network.get_public_json", side_effect=[{"data": [summary]}, full]) as getter:
            jobs, info = search_jobs("1-7")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(info["detail_reads"], 1)
        self.assertEqual(getter.call_args_list[1].args[0], "/copilot/get/1")

    def test_wrong_stage_not_downloaded(self):
        summary = {"id": 1, "content": json.dumps({"stage_name": "1-8"})}
        with patch("ark_assistant.network.get_public_json", return_value={"data": [summary]}) as getter:
            jobs, info = search_jobs("1-7")
        self.assertEqual(jobs, [])
        self.assertEqual(info["wrong_stage"], 1)
        self.assertEqual(getter.call_count, 1)

    def test_detail_stage_change_rejected(self):
        summary = {"id": 1, "content": json.dumps({"stage_name": "1-7"})}
        full = {"id": 1, "content": json.dumps({"stage_name": "1-8", "actions": [{"type": "Output"}]})}
        with patch("ark_assistant.network.get_public_json", side_effect=[{"data": [summary]}, full]):
            jobs, info = search_jobs("1-7")
        self.assertEqual(jobs, [])
        self.assertEqual(info["rejected_ids"], ["1"])

    def test_detail_reads_bounded(self):
        rows = [{"id": i, "content": json.dumps({"stage_name": "1-7"})} for i in range(1, 11)]
        full = {"content": json.dumps({"stage_name": "1-7", "actions": [{"type": "Output"}]})}
        with patch("ark_assistant.network.get_public_json", side_effect=[{"data": rows}, full, full, full]) as getter:
            jobs, info = search_jobs("1-7")
        self.assertEqual(len(jobs), 3)
        self.assertEqual(getter.call_count, 4)
        self.assertEqual(info["deferred"], 7)

    def test_mutating_endpoint_rejected(self):
        for path in ("/copilot/upload", "/copilot/status", "/copilot/get/../upload", "/copilot/get/../get/1"):
            with self.assertRaises(ValueError):
                get_public_json(path)

    def test_redirect_to_non_read_endpoint_rejected(self):
        request = Request("https://prts.maa.plus/copilot/query")
        for url in ("https://prts.maa.plus/copilot/status", "https://other.invalid/copilot/query",
                    "https://user@prts.maa.plus/copilot/query", "https://prts.maa.plus:444/copilot/query"):
            with self.assertRaises(ValueError):
                SafeRedirect().redirect_request(request, None, 302, "Found", {}, url)

    def test_redirect_to_read_only_detail_allowed(self):
        request = Request("https://prts.maa.plus/copilot/query")
        redirected = SafeRedirect().redirect_request(request, None, 302, "Found", {},
                                                     "https://prts.maa.plus/copilot/get/1")
        self.assertEqual(redirected.get_method(), "GET")

    def test_query_limits(self):
        for limit in (0, 51, True):
            with self.assertRaises(ValueError):
                search_jobs("1-7", limit)

    def test_analysis_mode_cannot_be_enabled(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "config").mkdir()
            (root / "config/local.json").write_text(json.dumps({"analysis_only": False}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_settings(root)

    def test_doctor_no_configuration_never_connects(self):
        report = doctor("")
        self.assertEqual(report["status"], "NOT_CONFIGURED")
        self.assertFalse(report["game_connected"])


if __name__ == "__main__":
    unittest.main()
