"""Scenario contracts asserted from the observable trace."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lifecycle_replay import replay

ROOT = Path(__file__).resolve().parents[1]


def example(name):
    return json.loads((ROOT / "examples" / f"{name}.json").read_text())


class LifecycleContracts(unittest.TestCase):
    def test_publish_gate_before_between_and_after_active_periods(self):
        report = replay(example("bringup"))
        frames = [r["emitted"] for r in report["trace"] if r["emitted"]]
        self.assertEqual([f["sample"] for f in frames], [11, 12, 14])
        self.assertEqual({f["frame_id"] for f in frames}, {"camera_optical"})
        self.assertEqual(report["final_state"], "finalized")
        self.assertEqual(report["published_frames"], 3)

    def test_rejected_activate_has_no_side_effect(self):
        first = replay([{"event": "activate"}])["trace"][0]
        self.assertEqual((first["state"], first["via"], first["outcome"]),
                         ("unconfigured", [], "rejected"))

    def test_failure_differs_from_error_and_reconfigure_uses_new_frame_id(self):
        report = replay(example("recover"))
        ordinary, injected = report["trace"][:2]
        self.assertEqual(ordinary["via"], ["configuring"])
        self.assertEqual(ordinary["outcome"], "configuration_failed")
        self.assertEqual(injected["via"], ["configuring", "errorprocessing"])
        self.assertEqual(injected["state"], "unconfigured")
        self.assertEqual([r["emitted"]["frame_id"] for r in report["trace"] if r["emitted"]],
                         ["camera_new", "camera_replaced"])

    def test_cleanup_is_rejected_while_active_and_keeps_the_publisher(self):
        trace = replay([{"event": "configure", "frame_id": "camera"},
                        {"event": "activate"}, {"event": "cleanup"},
                        {"event": "frame", "sample": 2}])["trace"]
        self.assertEqual((trace[2]["outcome"], trace[2]["state"]), ("rejected", "active"))
        self.assertEqual(trace[3]["emitted"], {"frame_id": "camera", "sample": 2})

    def test_finalized_rejects_all_following_commands(self):
        report = replay(example("finalized"))
        self.assertEqual(report["final_state"], "finalized")
        self.assertEqual(report["published_frames"], 0)
        self.assertEqual([r["outcome"] for r in report["trace"]],
                         ["error_finalized", "rejected", "rejected", "suppressed", "rejected"])

    def test_bad_file_fails_before_emitting_any_partial_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            scenario = Path(directory) / "invalid.json"
            scenario.write_text('[{"event":"shutdown"},{"event":"frame","sample":true}]')
            proc = subprocess.run([sys.executable, str(ROOT / "lifecycle_replay.py"),
                                   str(scenario), "--json"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")
        self.assertIn("event 2: sample", proc.stderr)

    def test_cli_json_matches_example_contract(self):
        proc = subprocess.run([sys.executable, str(ROOT / "lifecycle_replay.py"),
                               str(ROOT / "examples" / "recover.json"), "--json"],
                              capture_output=True, text=True, check=True)
        report = json.loads(proc.stdout)
        self.assertEqual((report["final_state"], report["published_frames"]), ("active", 2))
        self.assertEqual(report["trace"][-1]["emitted"],
                         {"frame_id": "camera_replaced", "sample": 21})


if __name__ == "__main__":
    unittest.main()
