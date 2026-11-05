"""Inspect a real scenario and optionally route under an all-open baseline."""
import argparse
import json
from dataclasses import asdict

from emergency_response.loaders import load_scenario
from emergency_response.routing import build_graph
from emergency_response.search import ucs


def main():
    """Parse CLI arguments, validate a scenario and print a JSON summary.

    Usage: python run.py Scenarios/Scenario1 --route H1 N2
    The optional route uses normal speeds and assumes every road is Open. It does
    not assign a responder, enforce an incident deadline or consume report evidence.
    An unreachable route is printed as JSON null. Expected input failures are
    presented through argparse; final plan/statistics files are not generated yet.

    Parameters:
        None. Command-line input comes from sys.argv.

    Preconditions:
        Called with command-line arguments for an accessible scenario directory and,
        optionally, two valid route node IDs. argparse checks syntax; loading/search
        check their documented input constraints. The environment must permit reading
        files and writing stdout/stderr.

    Postconditions:
        On normal completion returns None and writes a JSON scenario summary,
        optionally with a baseline route, to stdout. Source files are unchanged and no
        plan/statistics files are written. Argument/handled input errors terminate via
        argparse/SystemExit instead of a normal return.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", help="Scenario directory, e.g. Scenarios/Scenario1")
    parser.add_argument("--route", nargs=2, metavar=("START", "GOAL"))
    args = parser.parse_args()
    try:
        scenario = load_scenario(args.scenario)
        # Counts describe the dataset, including future incidents; they are not plan metrics.
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
        # Explicit baseline: probability tables are loaded but do not yet affect costs.
        if args.route:
            route = ucs(build_graph(scenario), *args.route)
            result["routing_assumption"] = "All roads Open; normal speeds; traffic ignored (optimistic baseline)"
            result["route"] = asdict(route) if route else None
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
