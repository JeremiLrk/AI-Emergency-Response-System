"""Reproduce CSP-versus-nearest coverage/response comparisons on supplied scenarios."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform

from emergency_response.allocation import CspDispatcher
from emergency_response.baseline import NearestDispatcher
from emergency_response.bayesian import infer_scenario
from emergency_response.loaders import load_scenario
from emergency_response.risk_routing import build_bayesian_graph
from emergency_response.simulation import simulate
from emergency_response.statistics import summarize


def compare_scenarios(root, *, blocked_threshold, time_limit_seconds=2.0):
    """Evaluate both dispatchers in strict/late modes with identical graph policies.

    Parameters: root holds ScenarioN directories; blocked_threshold is explicit;
        time_limit_seconds is the shared wall budget per current CSP snapshot.
    Preconditions: readable scenarios, OR-Tools installed, valid policy/budget.
    Postconditions: JSON-ready metrics/assignments and solver proof/fallback counts.
        Fresh runs isolate policies; no Scenario reaches a dispatcher. Runtime is
        not guaranteed repeatable; outcomes are modeled, not real-world forecasts.
    """
    import ortools
    rows = []
    for directory in sorted(Path(root).glob("Scenario*")):
        scenario = load_scenario(directory)
        graph = build_bayesian_graph(scenario, infer_scenario(scenario), blocked_threshold=blocked_threshold)
        for strict in (True, False):
            for name in ("csp", "nearest"):
                dispatcher = CspDispatcher(time_limit_seconds=time_limit_seconds) if name == "csp" else NearestDispatcher()
                result = simulate(scenario, graph, dispatcher, strict_deadlines=strict)
                diagnostics = getattr(dispatcher, "diagnostics", ())
                rows.append({"scenario": directory.name, "deadline_policy": "strict" if strict else "allow_late",
                    "allocator": name, "statistics": asdict(summarize(result)),
                    "solver_decisions": len(diagnostics),
                    "unproven_decisions": sum(not d.lexicographic_optimal for d in diagnostics),
                    "solver_statuses": sorted({d.status for d in diagnostics}),
                    "assignments": [asdict(a) for a in result.assignments]})
    if not rows:
        raise ValueError("No ScenarioN directories found")
    return {"ortools_version": ortools.__version__, "python_version": platform.python_version(),
            "routing_policy": "bayesian", "block_threshold": blocked_threshold,
            "solver_time_limit_seconds": time_limit_seconds, "solver_workers": 1, "solver_seed": 0,
            "response_scale": 1000, "execution": "fixed modeled route estimates; no HMM/hidden road truth",
            "comparisons": rows}


def main():
    """Write comparison JSON and print a compact metrics table.

    Parameters: none; CLI supplies root, explicit threshold, budget and output path.
    Preconditions: output parent writable; input/policy requirements apply above.
    Postconditions: creates/replaces comparison JSON and prints coverage, deadline
        counts, mean response seconds and proof warnings; scenarios unchanged.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-root", default="Scenarios")
    parser.add_argument("--block-threshold", required=True, type=float)
    parser.add_argument("--solver-time-limit", default=2.0, type=float)
    parser.add_argument("--output", default="results/allocation_comparison.json")
    args = parser.parse_args()
    result = compare_scenarios(args.scenario_root, blocked_threshold=args.block_threshold,
                               time_limit_seconds=args.solver_time_limit)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print("Scenario  Mode        Allocator Handled Met  Avg response(s) Unproven decisions")
    for row in result["comparisons"]:
        s = row["statistics"]
        average = "N/A" if s["average_response_seconds"] is None else f"{s['average_response_seconds']:.3f}"
        print(f"{row['scenario']:9} {row['deadline_policy']:11} {row['allocator']:9} "
              f"{s['handled']:2}/{s['total_incidents']:<2} {s['deadlines_met']:2} {average:>15} {row['unproven_decisions']:5}")


if __name__ == "__main__":
    main()
