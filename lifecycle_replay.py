"""Replay a small, synchronous teaching model of a managed camera node."""
import argparse
import json
import sys
from pathlib import Path

COMMANDS = {
    "unconfigured": {"configure", "shutdown"},
    "inactive": {"activate", "cleanup", "shutdown"},
    "active": {"deactivate", "shutdown"},
    "finalized": set(),
}
EVENT_KEYS = {
    "configure": {"event", "frame_id", "inject"},
    "activate": {"event"}, "deactivate": {"event"}, "cleanup": {"event"},
    "shutdown": {"event"}, "frame": {"event", "sample"},
}


def parse_events(data):
    if not isinstance(data, list) or not data:
        raise ValueError("scenario must be a nonempty JSON list")
    for index, event in enumerate(data, 1):
        if not isinstance(event, dict) or not isinstance(event.get("event"), str):
            raise ValueError(f"event {index}: expected an object with an event name")
        name = event["event"]
        if name not in EVENT_KEYS or event.keys() - EVENT_KEYS[name]:
            raise ValueError(f"event {index}: unknown event name or field")
        if name == "configure":
            if not isinstance(event.get("frame_id"), str):
                raise ValueError(f"event {index}: frame_id must be a string")
            if event.get("inject", "none") not in ("none", "recoverable", "fatal"):
                raise ValueError(f"event {index}: inject must be none, recoverable or fatal")
        if name == "frame" and (type(event.get("sample")) is not int or event["sample"] < 0):
            raise ValueError(f"event {index}: sample must be a nonnegative integer")
    return data


def replay(events):
    """Return a deterministic trace; a sample is a synthetic frame sequence ID."""
    state, frame_id, count = "unconfigured", None, 0
    trace = []
    for step, event in enumerate(parse_events(events), 1):
        name = event["event"]
        before = state
        path = []
        emitted = None
        if name == "frame":
            if state == "active":
                emitted = {"frame_id": frame_id, "sample": event["sample"]}
                count += 1
                outcome = "published"
            else:
                outcome = "suppressed"
        elif name not in COMMANDS[state]:
            outcome = "rejected"
        elif name == "configure":
            path.append("configuring")
            fault = event.get("inject", "none")
            if not event["frame_id"].strip():
                outcome = "configuration_failed"
            elif fault != "none":
                path.append("errorprocessing")
                state = "unconfigured" if fault == "recoverable" else "finalized"
                frame_id = None
                outcome = "error_recovered" if fault == "recoverable" else "error_finalized"
            else:
                frame_id = event["frame_id"]
                state, outcome = "inactive", "ok"
        else:
            path.append({"activate": "activating", "deactivate": "deactivating",
                         "cleanup": "cleaningup", "shutdown": "shuttingdown"}[name])
            state = {"activate": "active", "deactivate": "inactive",
                     "cleanup": "unconfigured", "shutdown": "finalized"}[name]
            if name in ("cleanup", "shutdown"):
                frame_id = None
            outcome = "ok"
        trace.append(dict(step=step, event=name, before=before, via=path,
                          state=state, outcome=outcome, emitted=emitted))
    return {"final_state": state, "published_frames": count, "trace": trace}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path, help="JSON event file")
    parser.add_argument("--json", action="store_true", help="print the complete trace as JSON")
    args = parser.parse_args()
    try:
        report = replay(json.loads(args.scenario.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        print(f"Scenario error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for row in report["trace"]:
            states = " > ".join([row["before"], *row["via"], row["state"]])
            if not row["via"] and row["state"] == row["before"]:
                states = row["state"]
            print(f'{row["step"]:02} {row["event"]:10} {states} [{row["outcome"]}]')
        print(f'Final: {report["final_state"]}; frames published: {report["published_frames"]}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
