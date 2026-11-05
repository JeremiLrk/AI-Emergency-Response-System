"""Inspect a real scenario and optionally route under an all-open baseline."""
import argparse
import json
from dataclasses import asdict

from emergency_response.loaders import load_scenario
from emergency_response.routing import build_graph
from emergency_response.search import ucs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", help="Scenario directory, e.g. Scenarios/Scenario1")
    parser.add_argument("--route", nargs=2, metavar=("START", "GOAL"))
    args = parser.parse_args()
    try:
        scenario = load_scenario(args.scenario)
        result = {
            "scenario": scenario.directory.name,
            "stage": "loading and routing only; no dispatch plan",
            "units": {"distance": "metres", "speed": "metres/second", "time": "seconds"},
            "nodes": len(scenario.nodes), "directed_roads": len(scenario.roads),
            "responders": len(scenario.responders), "incidents": len(scenario.incidents),
            "known_incidents_at_zero": [i.id for i in scenario.known_incidents(0)],
            "road_reports": len(scenario.road_reports),
            "traffic_sequences": len(scenario.traffic_history),
            "historical_observations": sum(map(len, scenario.traffic_history.values())),
            "warnings": scenario.warnings,
        }
        if args.route:
            route = ucs(build_graph(scenario), *args.route)
            result["routing_assumption"] = "All roads Open; normal speeds; traffic ignored (optimistic baseline)"
            result["route"] = asdict(route) if route else None
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
