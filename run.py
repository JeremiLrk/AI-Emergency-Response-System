"""Inspect Bayesian road beliefs and route with an explicit UCS policy."""
import argparse
import json
from dataclasses import asdict

from emergency_response.loaders import load_scenario
from emergency_response.routing import build_graph
from emergency_response.search import ucs
from emergency_response.bayesian import infer_scenario
from emergency_response.risk_routing import build_bayesian_graph, route_blockage_bounds
from emergency_response.simulation import simulate
from emergency_response.scripted import load_script


def main():
    """Parse CLI arguments, validate a scenario and print a JSON summary.

    Usage: python run.py Scenarios/Scenario1 --route H1 N2
    Full road posteriors are always printed. The default baseline route assumes
    Open roads; --routing-policy bayesian requires an explicit --block-threshold
    when routing, and uses edge-conditional expected travel times. Route blockage
    bounds are printed under either policy. --simulate-script executes explicit
    assignment fixtures rather than optimizing allocations. --allow-late changes
    deadline acceptance while retaining separate deadline outcomes.

    Parameters:
        None. Command-line input comes from sys.argv.

    Preconditions:
        Called with command-line arguments for an accessible scenario directory and,
        optionally, two valid route node IDs or a readable simulation script.
        --allow-late requires a simulation script. Bayesian routing requires a finite
        threshold in [0,1]; selecting that threshold is the caller's policy choice.
        argparse, loading and routing check these inputs. Files must be readable.

    Postconditions:
        On normal completion returns None and writes a JSON scenario summary,
        full distributions and optional route or scripted simulation result to
        stdout. Source files are unchanged; no plan/statistics files are written.
        No route means unreachable under the selected policy, not proven impossible
        in reality. Handled errors terminate via argparse/SystemExit.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", help="Scenario directory, e.g. Scenarios/Scenario1")
    parser.add_argument("--route", nargs=2, metavar=("START", "GOAL"))
    parser.add_argument("--routing-policy", choices=("baseline", "bayesian"), default="baseline")
    parser.add_argument("--block-threshold", type=float,
                        help="Bayesian policy: exclude roads with P(Blocked) >= this value; no default")
    parser.add_argument("--simulate-script", help="JSON fixture of explicit time/responder/incident dispatches")
    parser.add_argument("--allow-late", action="store_true",
                        help="Scripted simulation: allow late arrivals, keeping deadline results separate")
    args = parser.parse_args()
    if args.simulate_script and args.route:
        parser.error("Choose --route or --simulate-script, not both")
    if args.allow_late and not args.simulate_script:
        parser.error("--allow-late requires --simulate-script")
    if args.routing_policy == "baseline" and args.block_threshold is not None:
        parser.error("--block-threshold requires --routing-policy bayesian")
    if args.block_threshold is not None and not (args.route or args.simulate_script):
        parser.error("--block-threshold requires --route or --simulate-script")
    if args.routing_policy == "bayesian" and (args.route or args.simulate_script) and args.block_threshold is None:
        parser.error("Bayesian routing requires an explicit --block-threshold")
    try:
        scenario = load_scenario(args.scenario)
        beliefs = infer_scenario(scenario)
        # Counts describe the dataset, including future incidents; they are not plan metrics.
        result = {
            "scenario": scenario.directory.name,
            "stage": "Bayesian routing and optional scripted modeled execution; no CSP allocation",
            "units": {"distance": "metres", "speed": "metres/second", "time": "seconds"},
            "nodes": len(scenario.nodes), "directed_roads": len(scenario.roads),
            "responders": len(scenario.responders), "incidents": len(scenario.incidents),
            "known_incidents_at_zero": [i.id for i in scenario.known_incidents(0)],
            "road_reports": len(scenario.road_reports),
            "traffic_sequences": len(scenario.traffic_history),
            "historical_observations": sum(map(len, scenario.traffic_history.values())),
            "warnings": scenario.warnings,
            "road_beliefs": [{"from": road.source, "to": road.target,
                             "probabilities": beliefs[road.key]} for road in scenario.roads],
        }
        if args.route or args.simulate_script:
            if args.routing_policy == "baseline":
                graph = build_graph(scenario)
                result["routing_assumption"] = "All roads Open; normal speeds (optimistic baseline)"
                result["cost_interpretation"] = "Normal travel seconds, ignoring inferred road conditions"
            else:
                graph = build_bayesian_graph(scenario, beliefs, blocked_threshold=args.block_threshold)
                result["routing_assumption"] = "Edge blockage threshold; no route-level risk guarantee; traffic ignored"
                result["block_threshold"] = args.block_threshold
                result["cost_interpretation"] = "Sum of edge-conditional expected travel seconds; not unconditional arrival"
            if args.route:
                route = ucs(graph, *args.route)
                result["route"] = asdict(route) if route else None
                result["route_blockage_bounds"] = asdict(route_blockage_bounds(scenario, beliefs, route)) if route else None
            else:
                dispatcher = load_script(args.simulate_script)
                execution = simulate(scenario, graph, dispatcher, strict_deadlines=not args.allow_late,
                                     decision_times=dispatcher.decision_times)
                result["simulation"] = asdict(execution)
                for responder in result["simulation"]["responders"]:
                    responder["capabilities"] = sorted(responder["capabilities"])
                result["execution_assumption"] = "Deterministic route estimates; no sampled road truth or failure recovery"
                result["assignment_blockage_bounds"] = [asdict(route_blockage_bounds(scenario, beliefs, a.route))
                                                          for a in execution.assignments]
            result["retained_directed_roads"] = sum(len(graph.neighbors(n.id)) for n in scenario.nodes)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
