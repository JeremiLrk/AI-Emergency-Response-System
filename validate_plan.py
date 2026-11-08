"""Independently validate an assignment-format plan against original scenario files."""
import argparse
from dataclasses import asdict
import json

from emergency_response.loaders import load_scenario
from emergency_response.plan_validation import load_plan, validate_plan


def main():
    """Read original scenario and strict JSON, report independent replay and exit.

    Parameters: CLI scenario/plan paths, original routing-policy/threshold, and
        --allow-late only for explicitly permitted experimental late plans.
    Preconditions: readable original inputs; use the same travel assumptions as
        generation (printed in statistics.txt). No OR-Tools dependency is needed.
    Postconditions: prints JSON validation report, exits0 for policy-valid,1 for
        invalid plan,2 for file/configuration errors. Never writes/replans anything.
        Validity is separate from deadlines/coverage/performance/actual road truth.
    """
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario")
    parser.add_argument("plan")
    parser.add_argument("--routing-policy",choices=("baseline","bayesian"),default="baseline")
    parser.add_argument("--block-threshold",type=float)
    parser.add_argument("--allow-late",action="store_true")
    args=parser.parse_args()
    try:
        report=validate_plan(load_scenario(args.scenario),load_plan(args.plan),
            routing_policy=args.routing_policy,blocked_threshold=args.block_threshold,
            strict_deadlines=not args.allow_late)
    except (OSError,ValueError,TypeError) as error:
        parser.error(str(error))
    print(json.dumps(asdict(report),indent=2,allow_nan=False))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
