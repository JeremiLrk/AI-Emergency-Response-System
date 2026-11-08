"""Assignment section 5 outputs, projected from the existing final simulation.

No dispatch, routing or event scheduling is performed here. Independent replay
must agree with simulation records and statistics before either file is written.
"""
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


def render_statistics(statistics, validation, *, configuration):
    """Render existing statistics with definitions, validity and reproducible settings.

    Parameters: statistics is summarize(result); validation is matching successful
        independent replay; configuration is JSON-compatible run settings mapping.
    Preconditions: valid replay/statistics agree; full final run, not a partial view.
    Postconditions: readable text with all section5.2 requirements. Numeric values
        retain Python float precision; N/A denotes empty denominators. Primary
        deadline percentage counts ALL incidents, including unhandled failures.
        Marks permitted late mode separately from strict deadline compliance.
    """
    average = "N/A (no incidents handled)" if statistics.average_response_seconds is None else f"{statistics.average_response_seconds} s"
    percentage = "N/A (no incidents)" if statistics.deadlines_met_percent_all is None else f"{statistics.deadlines_met_percent_all}%"
    handled_percentage = "N/A (no incidents handled)" if statistics.deadlines_met_percent_handled is None else f"{statistics.deadlines_met_percent_handled}%"
    return "\n".join([
        "System statistics:",
        f"* {statistics.handled} incidents handled",
        f"* {statistics.responders_used} responders used",
        f"* Average response time: {average}",
        f"* Deadlines met: {percentage} ({statistics.deadlines_met}/{statistics.total_incidents} incidents)",
        f"* Unhandled incidents: {statistics.unhandled}",
        f"* Deadlines met among handled incidents: {handled_percentage}",
        f"* Late handled incidents: {statistics.handled-statistics.deadlines_met}",
        "", "Units: all simulation times and durations are seconds; fractional seconds retained.",
        "Handled means treatment completed, including late responses when allowed.",
        "Responders used means distinct responders with a committed assignment.",
        "Response time = arrival - incident release; includes dispatch waiting and travel, excludes treatment.",
        "Average response excludes unhandled incidents; coverage must be considered alongside this average.",
        "Primary deadline percentage = on-time arrivals / ALL incidents * 100; unhandled count as not met.",
        "Deadline refers to arrival, not treatment completion; arrival equal to deadline is on time.",
        "", "Independent validation under selected policy: VALID",
        f"Deadline policy: {'strict' if validation.strict_deadlines else 'allow_late (experimental; permits assignment-deadline violations)'}",
        f"Every assigned arrival meets its deadline: {'yes' if validation.deadline_compliant else 'no'}",
        "Unhandled incident IDs: "+(", ".join(validation.unhandled_incident_ids) or "none"),
        "Validity is relative to declared estimates/policy; it does not establish optimality or actual road safety.",
        "Travel and arrivals are modeled estimates; no hidden-road failures or recovery are simulated.",
        "Historical HMM exposure is a separate preference, never a travel duration.",
        "Run configuration: "+json.dumps(configuration,sort_keys=True,allow_nan=False), ""])


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
    settings.update(routing_policy=routing_policy,blocked_threshold=blocked_threshold,
                    strict_deadlines=result.strict_deadlines)
    plan_text = json.dumps(plan,indent=2,allow_nan=False)+"\n"
    statistics_text = render_statistics(statistics,validation,configuration=settings)
    destination = Path(output_directory)
    destination.mkdir(parents=True,exist_ok=True)
    plan_path, statistics_path = destination/"plan.json", destination/"statistics.txt"
    plan_path.write_text(plan_text,encoding="utf-8")
    statistics_path.write_text(statistics_text,encoding="utf-8")
    return {"plan":str(plan_path.resolve()),"statistics":str(statistics_path.resolve()),
            "validation":asdict(validation)}
