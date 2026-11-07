"""Exact Bayesian road inference; no routing choices occur in this module.

Course: Bayes' Nets part 1 slides 10-17 (conditional independence and
factorization), part 2 slides 4-6 and 11 (multiply factors, marginalize,
normalize). Model: Weather -> Status -> independent source report variables.
Reports are time-zero evidence and are consumed once, not once per dispatch.
"""
from collections.abc import Mapping
from math import fsum

from .loaders import validate_road_probabilities
from .models import SOURCES, WEATHER, Scenario

STATUSES = ("Open", "Congested", "Blocked")


def infer_road_status(probabilities, *, weather=None, reports=None):
    """Return the full status posterior for one directed road.

    Parameters:
        probabilities: Parsed road_probabilities.json CPT dictionary. Report
            tables use [true status][reported status], never the reverse.
        weather: Known local Clear/Rain/Storm, or None when not observed.
        reports: Mapping Citizen/Police/Sensor -> reported Open/Congested/Blocked.
            None or an empty mapping means no reports. At most one per source;
            duplicate observations must be rejected before constructing a mapping.

    Preconditions:
        CPTs and supplied labels are checked. reports must be a mapping if given.
        Caller must supply independent source observations conditional on status,
        not correlated/replayed duplicates. Missingness is assumed uninformative.
        No inputs may be mutated concurrently. These statistical assumptions are
        not established by numerical validation.

    Postconditions:
        Returns a fresh dict with exactly Open/Congested/Blocked probabilities,
        nonnegative and summing to one within floating-point precision. Unknown
        weather is summed out; missing report variables contribute a factor one.
        Inputs are unchanged. No status is selected and no road is removed.

    Raises:
        ValueError: Invalid CPTs/labels/reports, or zero evidence likelihood
            (including numerical underflow). No arbitrary fallback is returned.
    """
    validate_road_probabilities(probabilities)
    if weather is not None and weather not in WEATHER:
        raise ValueError(f"Unknown local weather: {weather!r}")
    if reports is not None and not isinstance(reports, Mapping):
        raise ValueError("Reports must be a source-to-status mapping")
    reports = {} if reports is None else dict(reports)
    for source, reported in reports.items():
        if source not in SOURCES or reported not in STATUSES:
            raise ValueError(f"Invalid report source/status: {source!r}/{reported!r}")

    weights = {}
    for status in STATUSES:
        if weather is None:
            # Variable elimination: sum over the unobserved local weather.
            prior = fsum(probabilities["weather_prior"][w]
                         * probabilities["road_status_given_weather"][w][status]
                         for w in sorted(WEATHER))
        else:
            # The known weather prior is a common factor and cancels on normalization.
            prior = probabilities["road_status_given_weather"][weather][status]
        weight = prior
        for source in sorted(reports):
            weight *= probabilities[SOURCES[source]][status][reports[source]]
        weights[status] = weight
    normalizer = fsum(weights.values())
    if normalizer <= 0:
        raise ValueError("Road evidence has zero likelihood or numerical underflow")
    return {status: weights[status] / normalizer for status in STATUSES}


def infer_scenario(scenario: Scenario):
    """Infer one independent marginal distribution per directed scenario road.

    Parameters:
        scenario: Validated Scenario containing roads, reports and Bayesian CPTs.

    Preconditions:
        Normally call load_scenario first. Road endpoint pairs must be unique.
        Unknown report roads, duplicate source reports and inconsistent local
        weather are checked again here to protect directly assembled scenarios.
        Shared dictionaries must not be mutated during this call.

    Postconditions:
        Returns a new dict (from,to) -> full probability dict for every road,
        including unreported roads. A report's weather is used only for its own
        direction. Unreported roads marginalize weather_prior. No state changes,
        joint cross-road distribution, inferred ground truth or routing decisions.

    Raises:
        ValueError: Invalid evidence, duplicate roads, or invalid inference inputs.
    """
    validate_road_probabilities(scenario.road_probabilities)
    evidence = {road.key: {} for road in scenario.roads}
    if len(evidence) != len(scenario.roads):
        raise ValueError("Directed road endpoint pairs must be unique")
    weather = {}
    for report in scenario.road_reports:
        if report.road not in evidence:
            raise ValueError(f"Report references unknown directed road: {report.road}")
        if report.source in evidence[report.road]:
            raise ValueError(f"Duplicate report source on {report.road}: {report.source}")
        if report.road in weather and weather[report.road] != report.weather:
            raise ValueError(f"Conflicting known weather on {report.road}")
        if report.weather not in WEATHER:
            raise ValueError(f"Invalid report weather: {report.weather!r}")
        weather[report.road] = report.weather
        evidence[report.road][report.source] = report.reported_status
    return {road: infer_road_status(scenario.road_probabilities,
                                  weather=weather.get(road), reports=reports)
            for road, reports in evidence.items()}
