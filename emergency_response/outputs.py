"""Assignment section 5 outputs, projected from the existing final simulation.

No dispatch, routing or event scheduling is performed here. Independent replay
must agree with simulation records and statistics before either file is written.
"""
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path

from .plan_validation import validate_plan
from .statistics import summarize


def make_plan(result):
    """Project committed assignments to the exact required JSON schema.

    Parameters: result is a final SimulationResult from simulate.
    Preconditions: all committed travel/treatment has completed; no input mutation.
    Postconditions: fresh list containing only responder_id,incident_id,path,time.
        time is recorded departure, not release/arrival/completion or a new dispatch
        calculation. path is the complete node sequence, including a singleton for
        a responder already at the incident. Unhandled incidents have no row.
    """
    return [{"responder_id":a.responder_id,"incident_id":a.incident_id,
             "path":list(a.route.nodes),"time":a.departure_time} for a in result.assignments]


def render_statistics(statistics, validation, *, configuration, incidents):
    """Summarize coverage, deadlines and response time in plain language.

    Parameters: statistics comes from the final simulation. validation is the
        matching successful replay. configuration records the run settings.
        incidents contains every incident from the original scenario.
    Preconditions: the simulation and independent replay agree.
    Postconditions: returns report text with rounded display values, counts
        by priority and the original run settings for reproducing the plan.
    """
    totals = Counter(incident.priority for incident in incidents)
    critical_handled = statistics.handled_by_priority["Critical"]
    if totals["Critical"] == 0:
        all_critical = "No Critical incidents in this scenario"
    else:
        all_critical = "Yes" if critical_handled == totals["Critical"] else "No"

    mean = statistics.average_response_seconds
    average = "N/A (no incidents handled)" if mean is None else f"{mean:.1f} seconds"
    percent = statistics.deadlines_met_percent_all
    deadline_percentage = "N/A (no incidents)" if percent is None else f"{percent:.1f}%"
    late = statistics.handled - statistics.deadlines_met
    mode = "Strict deadlines" if validation.strict_deadlines else "Late arrivals allowed"
    lines = [
        f"Emergency response results | {configuration.get('scenario', 'Scenario')}",
        f"Mode: {mode}",
        "",
        "Overview",
        f"  Incidents handled: {statistics.handled} of {statistics.total_incidents}",
        f"  Incidents not handled: {statistics.unhandled}",
        f"  Responders used: {statistics.responders_used}",
        f"  Average response time: {average}",
        "",
        "Arrival deadlines",
        f"  Reached on time: {statistics.deadlines_met} of {statistics.total_incidents} ({deadline_percentage})",
        f"  Reached late: {late}",
        "  The on-time percentage includes every incident, even those not handled.",
        "",
        "Incidents handled by priority",
    ]
    for priority in ("Critical", "High", "Medium", "Low"):
        handled = statistics.handled_by_priority[priority]
        lines.append(f"  {priority}: {handled} of {totals[priority]} handled")

    unhandled = set(validation.unhandled_incident_ids)
    missed_critical = sorted(
        incident.id for incident in incidents
        if incident.priority == "Critical" and incident.id in unhandled
    )
    lines.extend([
        f"  All Critical incidents handled: {all_critical}",
        "  Critical incidents not handled: " + (", ".join(missed_critical) or "None"),
        "  All incidents not handled: " + (", ".join(sorted(unhandled)) or "None"),
        "",
        "How to read these numbers",
        "  Handled means a responder completed treatment.",
        "  The deadline is the latest time a responder can arrive and still be on time.",
        "  Average response time includes waiting and travel for handled incidents only.",
        "",
        "Plan check: Passed under the selected rules and estimated travel times.",
        "",
        "Run configuration:",
        f"  Scenario: {configuration.get('scenario', 'Unspecified')}",
        f"  Deadline rule: {mode}",
    ])

    allocator = configuration.get("allocator")
    if allocator is not None:
        names = {"csp": "CP-SAT (assign by priority)", "nearest": "Nearest responder", "script": "Scripted assignments"}
        lines.append(f"  Responder assignment: {names.get(allocator, allocator)}")

    if configuration["routing_policy"] == "bayesian":
        lines.append("  Road estimates: Bayesian (uses road reports and weather)")
        threshold = configuration["blocked_threshold"]
        lines.append(f"  Road blockage cutoff: {threshold * 100:g}% (roads at or above this are excluded)")
    else:
        lines.append("  Road estimates: Assume all roads are open")

    traffic = configuration.get("traffic_policy")
    if traffic == "hmm-bounded":
        lines.append("  Traffic preference: Use historical traffic to consider detours")
        extra = configuration.get("max_extra_fraction")
        reduction = configuration.get("min_exposure_reduction")
        if extra is not None:
            lines.append(f"  Maximum extra travel time: {extra * 100:g}%")
        if reduction is not None:
            lines.append(f"  Minimum reduction in traffic exposure: {reduction * 100:g}%")
    elif traffic == "hmm-tie":
        lines.append("  Traffic preference: Prefer lower exposure when travel times tie")
    elif traffic == "bayesian-only":
        lines.append("  Traffic preference: Choose the shortest estimated route")

    time_limit = configuration.get("solver_time_limit_seconds")
    if time_limit is not None and allocator == "csp":
        lines.append(f"  Solver time limit per decision: {time_limit:g} seconds")
    return "\n".join(lines) + "\n"


def write_outputs(scenario, result, output_directory, *, routing_policy="baseline",
                  blocked_threshold=None, configuration=None):
    """Validate and export one existing final run without recomputing its decisions.

    Parameters:
        scenario: Original validated inputs, used only by independent replay.
        result: Final immutable SimulationResult, sole source of exported decisions.
        output_directory: Destination for exact names plan.json/statistics.txt.
        routing_policy/blocked_threshold: Original run's travel estimation policy;
            passed explicitly to independent validation, not encoded in plan schema.
        configuration: Optional JSON-compatible extra run settings (allocator,
            traffic policy/fractions, solver limit); recorded in statistics.txt.
    Preconditions: all assignments completed; original scenario/configuration match
        execution. Source inputs and output files must not change concurrently.
    Postconditions: validates schema/operational constraints, reconstructed durations,
        arrival/completion and independent statistics BEFORE writing. Returns output
        paths and validation. Writes required files, replacing same-name previous
        outputs; never changes input data, dispatch decisions or Git index. File I/O
        errors propagate; two separate files are not a filesystem transaction.
    Raises: ValueError for invalid/inconsistent results, including fabricated timing;
        OSError for inaccessible output. No invalid plan is deliberately published.
    """
    plan = make_plan(result)
    validation = validate_plan(scenario,plan,routing_policy=routing_policy,
        blocked_threshold=blocked_threshold,strict_deadlines=result.strict_deadlines)
    if not validation.valid:
        details = "; ".join(f"row {e.row}: {e.code}: {e.message}" for e in validation.errors)
        raise ValueError("Export rejected by independent validation: "+details)
    for reconstructed in validation.assignments:
        recorded = result.assignments[reconstructed.row]
        if (reconstructed.travel_seconds != recorded.route.seconds or
                reconstructed.arrival_time != recorded.arrival_time or
                reconstructed.completion_time != recorded.completion_time):
            raise ValueError("Export timing disagrees with independent original-data replay")
    statistics = summarize(result)
    if validation.statistics != statistics:
        raise ValueError("Export statistics disagree with independent original-data replay")
    settings = dict(configuration or {})
    settings.setdefault("scenario", scenario.directory.name)
    settings.update(routing_policy=routing_policy,blocked_threshold=blocked_threshold,
                    strict_deadlines=result.strict_deadlines)
    plan_text = json.dumps(plan,indent=2,allow_nan=False)+"\n"
    statistics_text = render_statistics(
        statistics, validation, configuration=settings, incidents=scenario.incidents
    )
    destination = Path(output_directory)
    destination.mkdir(parents=True,exist_ok=True)
    plan_path, statistics_path = destination/"plan.json", destination/"statistics.txt"
    plan_path.write_text(plan_text,encoding="utf-8")
    statistics_path.write_text(statistics_text,encoding="utf-8")
    return {"plan":str(plan_path.resolve()),"statistics":str(statistics_path.resolve()),
            "validation":asdict(validation)}
