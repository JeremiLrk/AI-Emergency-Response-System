"""Fixed-parameter HMM comparisons; preserve the earlier allocation benchmark."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform

from emergency_response.allocation import CspDispatcher
from emergency_response.baseline import NearestDispatcher
from emergency_response.bayesian import infer_scenario
from emergency_response.hmm import infer_traffic
from emergency_response.loaders import load_scenario
from emergency_response.risk_routing import build_bayesian_graph, route_blockage_bounds
from emergency_response.search import ucs
from emergency_response.simulation import simulate
from emergency_response.statistics import summarize
from emergency_response.traffic_routing import TrafficRouter


def compare_scenarios(root, *, blocked_threshold, max_extra_fraction=.05,
                      min_exposure_reduction=.10, time_limit_seconds=2.0):
    """Evaluate three fixed routing policies with identical inputs and allocators.

    Parameters: root holds scenarios; blocked_threshold filters Bayesian arcs;
        max_extra_fraction bounds extra travel, min_exposure_reduction requires a
        relative score improvement; time_limit_seconds is the CSP decision budget.
    Preconditions: valid/readable scenarios, OR-Tools installed. Defaults .05/.10
        were declared before evaluation; do not select them from benchmark outcomes.
    Postconditions: JSON-ready per-run metrics, assignments, scores and changes
        from Bayesian-only. Histories filtered once per scenario, not per event.
        Fresh dispatchers isolate runs; source inputs unchanged. Route changes on
        common assignments may also reflect changed earlier responder locations.
    """
    import ortools
    rows, audits = [], []
    for directory in sorted(Path(root).glob("Scenario*")):
        scenario = load_scenario(directory)
        beliefs, traffic = infer_scenario(scenario), infer_traffic(scenario)
        graph = build_bayesian_graph(scenario, beliefs, blocked_threshold=blocked_threshold)
        tie = TrafficRouter(scenario.roads, traffic)
        bounded = TrafficRouter(scenario.roads, traffic, policy="bounded",
            max_extra_fraction=max_extra_fraction, min_exposure_reduction=min_exposure_reduction)
        audit = {"scenario": directory.name, "reachable_pairs": 0, "tie_route_changes": 0,
                 "bounded_route_changes": 0, "bounded_changes": []}
        for a in scenario.nodes:
            for b in scenario.nodes:
                baseline = ucs(graph, a.id, b.id)
                if baseline is not None:
                    audit["reachable_pairs"] += 1
                    audit["tie_route_changes"] += tie(graph, a.id, b.id).roads != baseline.roads
                    alternative = bounded(graph, a.id, b.id)
                    if alternative.roads != baseline.roads:
                        audit["bounded_route_changes"] += 1
                        audit["bounded_changes"].append({"from": a.id, "to": b.id,
                            "baseline": asdict(baseline), "bounded": asdict(alternative),
                            "traffic_score": asdict(tie.describe(graph, alternative))})
        audits.append(audit)
        for strict in (True, False):
            for allocator in ("csp", "nearest"):
                base = None
                for name, planner in (("bayesian-only", None), ("hmm-tie", tie), ("hmm-bounded", bounded)):
                    dispatcher = CspDispatcher(time_limit_seconds=time_limit_seconds) if allocator == "csp" else NearestDispatcher()
                    result = simulate(scenario, graph, dispatcher, strict_deadlines=strict, route_planner=planner)
                    assignments = {a.incident_id: a for a in result.assignments}
                    if base is None:
                        base = assignments
                    common = sorted(set(base) & set(assignments))
                    explanations = [asdict(tie.describe(graph, a.route)) for a in result.assignments]
                    diagnostics = getattr(dispatcher, "diagnostics", ())
                    rows.append({"scenario": directory.name,
                        "deadline_policy": "strict" if strict else "allow_late", "allocator": allocator,
                        "traffic_policy": name, "statistics": asdict(summarize(result)),
                        "unproven_decisions": sum(not d.lexicographic_optimal for d in diagnostics),
                        "solver_statuses": sorted({d.status for d in diagnostics}),
                        "assignment_changes": {
                            "added_incidents": sorted(set(assignments)-set(base)),
                            "removed_incidents": sorted(set(base)-set(assignments)),
                            "responder_changes": [i for i in common if assignments[i].responder_id != base[i].responder_id],
                            "route_changes": [i for i in common if assignments[i].route.roads != base[i].route.roads],
                            "departure_changes": [i for i in common if assignments[i].departure_time != base[i].departure_time]},
                        "committed_detours": sum(e["extra_seconds"] > 0 for e in explanations),
                        "assignments": [asdict(a) for a in result.assignments],
                        "traffic_scores": explanations,
                        "blockage_bounds": [asdict(route_blockage_bounds(scenario, beliefs, a.route)) for a in result.assignments]})
    if not rows:
        raise ValueError("No scenarios found")
    return {"python_version": platform.python_version(), "ortools_version": ortools.__version__,
        "block_threshold": blocked_threshold, "max_extra_fraction": max_extra_fraction,
        "min_exposure_reduction": min_exposure_reduction, "solver_time_limit_seconds": time_limit_seconds,
        "solver_seed": 0, "solver_workers": 1, "response_scale": 1000,
        "exposure": "sum normal_seconds*historical P(High); never travel time or failure probability",
        "initial_convention": "P(X1): emission first, then transition/emission",
        "execution": "Historical beliefs frozen; deterministic Bayesian route estimates; no sampled road truth",
        "route_audits": audits, "comparisons": rows}


def main():
    """Write reproducible comparison JSON and print the 36 run summaries.

    Parameters: CLI root, threshold, fixed fractions, budget and output filename.
    Preconditions: output writable; requirements of compare_scenarios apply.
    Postconditions: writes one report, prints metrics; no scenario/code changes.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-root", default="Scenarios")
    parser.add_argument("--block-threshold", required=True, type=float)
    parser.add_argument("--max-extra-fraction", type=float, default=.05)
    parser.add_argument("--min-exposure-reduction", type=float, default=.10)
    parser.add_argument("--solver-time-limit", type=float, default=2.0)
    parser.add_argument("--output", default="results/traffic_comparison.json")
    args = parser.parse_args()
    report = compare_scenarios(args.scenario_root, blocked_threshold=args.block_threshold,
        max_extra_fraction=args.max_extra_fraction, min_exposure_reduction=args.min_exposure_reduction,
        time_limit_seconds=args.solver_time_limit)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    for row in report["comparisons"]:
        s, c = row["statistics"], row["assignment_changes"]
        average = s["average_response_seconds"]
        print(row["scenario"], row["deadline_policy"], row["allocator"], row["traffic_policy"],
              s["handled"], s["deadlines_met"], None if average is None else round(average, 3),
              "routes", len(c["route_changes"]), "responders", len(c["responder_changes"]),
              "detours", row["committed_detours"], "unproven", row["unproven_decisions"])
    print("All-pairs audits:", [{k:v for k,v in a.items() if k != "bounded_changes"}
                                for a in report["route_audits"]])


if __name__ == "__main__":
    main()
