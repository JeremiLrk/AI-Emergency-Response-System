"""Run online CP-SAT allocation, nearest baseline, scripts, or a single UCS route."""
import argparse
from dataclasses import asdict
import json
import sys
from math import isfinite
from pathlib import Path

from emergency_response.allocation import CspDispatcher, AllocationError
from emergency_response.baseline import NearestDispatcher
from emergency_response.bayesian import infer_scenario
from emergency_response.loaders import load_scenario
from emergency_response.risk_routing import build_bayesian_graph, route_blockage_bounds
from emergency_response.routing import build_graph
from emergency_response.scripted import load_script
from emergency_response.search import ucs
from emergency_response.simulation import simulate
from emergency_response.statistics import summarize
from emergency_response.hmm import infer_traffic
from emergency_response.traffic_routing import TrafficRouter
from emergency_response.outputs import write_outputs


def execution_output(scenario, graph, beliefs, dispatcher, *, strict_deadlines=True, route_planner=None,
                     output_directory=None, routing_policy="baseline", blocked_threshold=None,
                     configuration=None):
    """Execute one fresh dispatcher and prepare JSON-ready results/statistics.

    Parameters:
        scenario/graph: Loaded scenario and fixed routing snapshot for this run.
        beliefs: Full Bayesian distributions used only for reporting route bounds.
        dispatcher: Fresh CP-SAT/nearest/script callback; only receives snapshots.
        strict_deadlines: bool selecting the simulator's strict/late policy.
        route_planner: Optional independent HMM route selector; None preserves UCS.
        output_directory: Optional destination for required validated output files.
        routing_policy/blocked_threshold: Original graph cost assumptions, needed
            for independent replay before export; must match graph construction.
        configuration: Extra run settings recorded in statistics.txt.
    Preconditions: scenario/graph/beliefs valid; controller may know full input,
        but never forwards it to an allocator. Script wake-ups are explicit.
    Postconditions: returns simulation, statistics, diagnostics and risk bounds as
        JSON-compatible data. All commitments complete; inputs unchanged. No actual
        road failures are simulated. When output_directory is supplied, writes
        assignment-format files from this same result, after independent replay.
    """
    execution = simulate(scenario, graph, dispatcher, strict_deadlines=strict_deadlines,
                         decision_times=getattr(dispatcher, "decision_times", ()), route_planner=route_planner)
    state = asdict(execution)
    for responder in state["responders"]:
        responder["capabilities"] = sorted(responder["capabilities"])
    return {
        "output_files": (write_outputs(scenario,execution,output_directory,
            routing_policy=routing_policy,blocked_threshold=blocked_threshold,
            configuration=configuration) if output_directory is not None else None),
        "simulation": state,
        "statistics": asdict(summarize(execution)),
        "allocation_diagnostics": [asdict(d) for d in getattr(dispatcher, "diagnostics", ())],
        "assignment_blockage_bounds": [asdict(route_blockage_bounds(scenario, beliefs, a.route))
                                       for a in execution.assignments],
        "assignment_traffic_scores": ([asdict(route_planner.describe(graph, a.route))
                                      for a in execution.assignments] if route_planner else None),
        "execution_assumption": "Deterministic route estimates; no sampled road truth or failure recovery",
    }


def choose_scenario():
    """Return a bundled scenario path, or None if the user exits."""
    root = Path(__file__).resolve().parent / "Scenarios"
    print("Choose an emergency response scenario")
    for number in ("1", "2", "3"):
        print(f"  {number}. Scenario {number}")
    print("  0. Exit")
    while True:
        try:
            choice = input("Enter a number: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if choice == "0":
            return None
        if choice in ("1", "2", "3"):
            return root / f"Scenario{choice}"
        print("Please enter 1, 2, 3 or 0.")


def main():
    """Select a mode, run it and print explicit modeled results as JSON.

    Parameters: none; argparse reads sys.argv. Default mode is online CP-SAT.
        --allocator nearest selects greedy shortest-travel allocation; --compare
        runs both independently on the same graph. --simulate-script preserves
        fixtures; --route is route-only. --allow-late applies to execution modes.
        --solver-time-limit is a shared per-decision wall budget (default 2s).
        --output-dir selects required plan.json/statistics.txt destination (default
        current working directory); compare uses csp/nearest subdirectories.
    Preconditions: files readable, OR-Tools installed for CSP/compare, finite budget.
        Bayesian routing always requires an explicit --block-threshold. Mode/flag
        conflicts are checked rather than silently ignored.
    Postconditions: prints scenario/beliefs and requested route or modeled results.
        Limited solver states appear in diagnostics, not as certified no-work.
        Traffic exposure is reported separately from travel. Handled errors
        terminate via argparse; source files and Git index are unchanged.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", help="Scenario directory, e.g. Scenarios/Scenario1")
    parser.add_argument("--output-dir", default=".", help="Output directory (default current directory); compare uses allocator subdirectories")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--route", nargs=2, metavar=("START", "GOAL"))
    modes.add_argument("--simulate-script", help="JSON time/responder/incident fixture")
    modes.add_argument("--compare", action="store_true", help="Run CSP and nearest independently")
    parser.add_argument("--allocator", choices=("csp", "nearest"), default="csp")
    parser.add_argument("--routing-policy", choices=("baseline", "bayesian"), default="baseline")
    parser.add_argument("--block-threshold", type=float, help="Exclude P(Blocked)>=value; no default")
    parser.add_argument("--traffic-policy", choices=("bayesian-only", "hmm-tie", "hmm-bounded"), default="bayesian-only")
    parser.add_argument("--max-extra-fraction", type=float, help="Explicit bounded travel allowance, e.g. .05")
    parser.add_argument("--min-exposure-reduction", type=float, default=.10, help="Required fractional exposure improvement (default .10)")
    parser.add_argument("--allow-late", action="store_true", help="Allow late response; preserve deadline misses")
    parser.add_argument("--solver-time-limit", type=float, default=2.0, help="Shared wall seconds per CSP decision")
    interactive = len(sys.argv) == 1
    if interactive:
        scenario_path = choose_scenario()
        if scenario_path is None:
            return
        args = parser.parse_args([
            str(scenario_path),
            "--routing-policy", "bayesian",
            "--block-threshold", ".20",
            "--traffic-policy", "hmm-bounded",
            "--max-extra-fraction", ".05",
            "--min-exposure-reduction", ".10",
            "--output-dir", str(Path(__file__).resolve().parent / "results" / "menu" / scenario_path.name),
        ])
    else:
        args = parser.parse_args()
    if args.traffic_policy != "bayesian-only" and args.routing_policy != "bayesian":
        parser.error("HMM route policies require --routing-policy bayesian")
    if (args.traffic_policy == "hmm-bounded") != (args.max_extra_fraction is not None):
        parser.error("--max-extra-fraction is required only for --traffic-policy hmm-bounded")
    if args.traffic_policy != "hmm-bounded" and args.min_exposure_reduction != .10:
        parser.error("--min-exposure-reduction applies only to hmm-bounded")
    if args.route and args.allow_late:
        parser.error("--allow-late applies to execution, not --route")
    if args.route and args.output_dir != ".":
        parser.error("--output-dir applies to execution, not diagnostic --route")
    if (args.route or args.simulate_script or args.compare) and args.allocator != "csp":
        parser.error("--allocator nearest selects a normal execution; omit it for other modes")
    if args.routing_policy == "baseline" and args.block_threshold is not None:
        parser.error("--block-threshold requires --routing-policy bayesian")
    if args.routing_policy == "bayesian" and args.block_threshold is None:
        parser.error("Bayesian routing requires an explicit --block-threshold")
    if not isfinite(args.solver_time_limit) or args.solver_time_limit < 0:
        parser.error("--solver-time-limit must be finite nonnegative seconds")
    try:
        scenario = load_scenario(args.scenario)
        beliefs = infer_scenario(scenario)
        traffic = infer_traffic(scenario)
        planner = (None if args.traffic_policy == "bayesian-only" else TrafficRouter(
            scenario.roads, traffic, policy="bounded" if args.traffic_policy == "hmm-bounded" else "tie",
            max_extra_fraction=args.max_extra_fraction or 0.0,
            min_exposure_reduction=args.min_exposure_reduction))
        graph = (build_graph(scenario) if args.routing_policy == "baseline" else
                 build_bayesian_graph(scenario, beliefs, blocked_threshold=args.block_threshold))
        export_options = {"routing_policy":args.routing_policy,"blocked_threshold":args.block_threshold,
            "configuration":{"traffic_policy":args.traffic_policy,"max_extra_fraction":args.max_extra_fraction,
                "min_exposure_reduction":args.min_exposure_reduction,"solver_time_limit_seconds":args.solver_time_limit,
                "scenario":scenario.directory.name}}
        result = {
            "scenario": scenario.directory.name,
            "stage": "Online allocation, historical HMM routing and modeled execution",
            "traffic_policy": args.traffic_policy,
            "traffic_settings": {"max_extra_fraction": args.max_extra_fraction,
                                 "min_exposure_reduction": args.min_exposure_reduction},
            "traffic_beliefs": [{"from": r.source, "to": r.target, **asdict(traffic[r.key]),
                                "prior_only": traffic[r.key].prior_only} for r in scenario.roads],
            "units": {"distance": "metres", "speed": "metres/second", "time": "seconds"},
            "nodes": len(scenario.nodes), "directed_roads": len(scenario.roads),
            "responders": len(scenario.responders), "incidents": len(scenario.incidents),
            "known_incidents_at_zero": [i.id for i in scenario.known_incidents(0)],
            "road_reports": len(scenario.road_reports),
            "traffic_sequences": len(scenario.traffic_history),
            "historical_observations": sum(map(len, scenario.traffic_history.values())),
            "warnings": scenario.warnings,
            "road_beliefs": [{"from": r.source, "to": r.target, "probabilities": beliefs[r.key]}
                            for r in scenario.roads],
            "routing_policy": args.routing_policy,
            "routing_assumption": ("All roads Open; normal speeds (optimistic baseline)"
                if args.routing_policy == "baseline" else
                "Edge blockage threshold; no route-level risk guarantee; HMM never changes edge time"),
            "cost_interpretation": ("Normal travel seconds, ignoring inferred road conditions"
                if args.routing_policy == "baseline" else
                "Sum of edge-conditional expected travel seconds; not unconditional arrival"),
            "retained_directed_roads": sum(len(graph.neighbors(n.id)) for n in scenario.nodes),
        }
        if args.routing_policy == "bayesian":
            result["block_threshold"] = args.block_threshold
        if args.route:
            route = planner(graph, *args.route) if planner else ucs(graph, *args.route)
            result["route"] = asdict(route) if route else None
            result["traffic_route_exposure"] = asdict(planner.describe(graph, route)) if planner and route else None
            result["route_blockage_bounds"] = asdict(route_blockage_bounds(scenario, beliefs, route)) if route else None
        elif args.compare:
            result["comparison"] = {
                "csp": execution_output(scenario, graph, beliefs,
                    CspDispatcher(time_limit_seconds=args.solver_time_limit), strict_deadlines=not args.allow_late, route_planner=planner,
                    output_directory=Path(args.output_dir)/"csp", **{**export_options,
                        "configuration":{**export_options["configuration"],"allocator":"csp"}}),
                "nearest": execution_output(scenario, graph, beliefs,
                    NearestDispatcher(), strict_deadlines=not args.allow_late, route_planner=planner,
                    output_directory=Path(args.output_dir)/"nearest", **{**export_options,
                        "configuration":{**export_options["configuration"],"allocator":"nearest"}}),
            }
        else:
            dispatcher = (load_script(args.simulate_script) if args.simulate_script else
                          NearestDispatcher() if args.allocator == "nearest" else
                          CspDispatcher(time_limit_seconds=args.solver_time_limit))
            result["allocator"] = "script" if args.simulate_script else args.allocator
            export_options["configuration"]["allocator"] = result["allocator"]
            result.update(execution_output(scenario, graph, beliefs, dispatcher,
                                           strict_deadlines=not args.allow_late, route_planner=planner,
                                           output_directory=args.output_dir, **export_options))
        if interactive:
            print(f"\n{result['scenario']} complete.")
            for key in ("plan", "statistics"):
                output_path = Path(result["output_files"][key])
                print(f"\n{output_path.name}")
                print(output_path.read_text(encoding="utf-8").rstrip())
                print(f"Saved to {output_path}")
        else:
            print(json.dumps(result, indent=2))
    except (OSError, ValueError, TypeError, AllocationError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
