# Emergency Response System

This Python project plans emergency responses after a storm. It checks road reports and past traffic, finds routes, and decides which available responders should take each call.

## Get started

Use **64-bit Python 3.12** to reproduce the original setup. All 175 tests passed on Windows with Python 3.12.14 and OR-Tools 9.15.6755. **Python 3.14.10 also passed all tests and all three menu runs**, producing unchanged plans. The commands below use 3.12; if you have 3.14 installed, use `py -3.14` or `python3.14` when creating the environment instead. The other commands stay the same.

**Do not use Python 3.15 for this version of the project.** Its required OR-Tools release has no compatible Python 3.15 package, so installation fails. Newer Python is not automatically better when a required library does not support it yet. The tested 3.12 environment remains unchanged.

The application uses portable Python paths. macOS and Linux commands are provided below, but those operating systems have not been tested directly here.

First download the repository ZIP and extract it, or clone it:

```console
git clone https://github.com/JeremiLrk/AI-Emergency-Response-System.git
cd AI-Emergency-Response-System
```

Run all commands from the folder containing `run.py` and `requirements.txt`. The setup below is needed once on each computer. After that, use the shorter commands under **Run it again later**.

### Windows (PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

If `py -3.12` is unavailable or cannot find Python 3.12, use your installed Python 3.12 executable instead. In PowerShell, a quoted executable path needs `&` before it, for example `& "C:\path\to\python.exe" -m venv .venv`.

### macOS or Linux (terminal)

Check that python3.12 is installed, then run:

```sh
python3.12 --version
python3.12 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python run.py
```

If the installed command is python3, check python3 --version first and use it to create the environment when it reports Python 3.12. On Debian/Ubuntu, a missing venv or ensurepip module usually requires the matching python3.12-venv package from the system package manager.

The pinned OR-Tools release provides Python 3.12 packages for Windows x86-64, Intel and Apple Silicon Macs, and common 64-bit Linux systems. Older or unusual operating systems may lack a compatible package. See the [release files](https://pypi.org/project/ortools/9.15.6755/#files) for the supported platform versions. If pip reports no matching distribution, check the Python version, architecture and pip version first.

`requirements.txt` lists the one direct third-party dependency, OR-Tools. pip installs its own dependencies automatically. The project and tests otherwise use Python's standard library. **pytest is not required:** tests use the built-in `unittest` framework, so no separate test package needs installing.

### Run it again later

You do not need to recreate the environment or reinstall the requirements for every run.

Windows:

```powershell
.\.venv\Scripts\python.exe run.py
```

macOS or Linux:

```sh
./.venv/bin/python run.py
```

### Choose a scenario

If you use an IDE, select the environment where you installed the requirements and run `run.py` without arguments. Choose **1**, **2** or **3** for a scenario, or **0** to exit. The settings are the same for all three scenarios; you do not need to enter extra arguments.

The menu runs the full planner with strict arrival deadlines. It uses CP-SAT for assignments, a 20% road blockage cutoff, and a historical traffic preference that allows up to 5% extra travel for at least 10% less exposure. It prints and saves two files in `results/menu/ScenarioN/`. For example, Scenario 1 saves to `results/menu/Scenario1/`. Running the same scenario replaces its previous menu results.

| File | What you get |
| --- | --- |
| `plan.json` | Who handles each call, the route they take, and when they leave. |
| `statistics.txt` | Calls handled and reached on time, responders used, average response time, and the settings used. It also shows results by priority and observed reasons for unhandled calls. |

The average response time includes waiting and travel for calls that were handled. The deadline percentage includes all calls, including unhandled ones. A separate validator checks the plan using the original inputs and estimated travel times.

## Run all tests

The first command in each block runs the complete suite, including full-system tests on all three scenarios. The second command separately checks a saved Scenario 1 plan; choose Scenario 1 in the menu first if that plan has not been generated.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe validate_plan.py Scenarios/Scenario1 results/menu/Scenario1/plan.json --routing-policy bayesian --block-threshold .2
```

On macOS or Linux, use:

```sh
./.venv/bin/python -m unittest discover -s tests -v
./.venv/bin/python validate_plan.py Scenarios/Scenario1 results/menu/Scenario1/plan.json --routing-policy bayesian --block-threshold .2
```

The test command runs all 175 tests. Search checks compare UCS with A* from the course on all three scenarios, and independently check both against every simple path in small graphs. UCS remains the normal planner. A successful run ends with OK. [What each test file checks](TESTING.md)

Use the same road and deadline settings as the saved run. For a plan generated with `--allow-late`, add that flag to the validator too. Exit codes are 0 for a valid plan under the selected rules, 1 for an invalid plan, and 2 for file or configuration errors.

## Reproduce the comparisons

```powershell
.\.venv\Scripts\python.exe benchmark.py --block-threshold .2
.\.venv\Scripts\python.exe benchmark_traffic.py --block-threshold .2 --max-extra-fraction .05 --min-exposure-reduction .10
```

On macOS or Linux, use:

```sh
./.venv/bin/python benchmark.py --block-threshold .2
./.venv/bin/python benchmark_traffic.py --block-threshold .2 --max-extra-fraction .05 --min-exposure-reduction .10
```

The first compares CP-SAT with a nearest-responder rule. The second also compares three ways of using historical traffic. Both cover all three scenarios and both deadline modes.

In the strict runs, CP-SAT handled **6/7**, **11/12** and **13/20** calls. Nearest handled **5/7**, **11/12** and **15/20** under the same road rules. The bounded traffic setting changed seven possible routes in Scenario 3, while the routes actually dispatched stayed the same. [Full results and how to read them](TESTING.md)

<details>
<summary>Advanced commands</summary>

Run a scenario with the same settings as the menu and choose the output folder:

```powershell
.\.venv\Scripts\python.exe run.py Scenarios/Scenario1 --routing-policy bayesian --block-threshold .2 --traffic-policy hmm-bounded --max-extra-fraction .05 --min-exposure-reduction .10 --output-dir results/plans/Scenario1/strict
```

On macOS or Linux, use ./.venv/bin/python in place of the Windows executable in the command above. All scenario paths and arguments are the same.

Add `--allow-late` to let responders arrive after the deadline. Use a different output folder to keep both plans. Explicit runs write to the current directory when you omit `--output-dir`.

For example, to generate the saved allow-late plan for Scenario 1:

```powershell
.\.venv\Scripts\python.exe run.py Scenarios/Scenario1 --routing-policy bayesian --block-threshold .2 --traffic-policy hmm-bounded --max-extra-fraction .05 --min-exposure-reduction .10 --allow-late --output-dir results/plans/Scenario1/allow_late
```

Replace `Scenario1` with `Scenario2` or `Scenario3` in both the input and output paths to generate the corresponding plans for the other scenarios.

- `--allocator nearest` selects the nearest-responder comparison. `--compare` runs both allocators and creates separate `csp` and `nearest` folders.
- `--traffic-policy hmm-tie` uses traffic only to choose among equally fast routes. `bayesian-only` uses plain UCS. For explicit Bayesian runs, pass `--block-threshold`. Explicit runs without a routing policy use the all-open baseline.
- `--route H1 N2` inspects one route and writes no assignment files. `--simulate-script examples/scenario1_script.json` runs the scripted example. These modes and `--compare` are mutually exclusive.
- `--solver-time-limit` sets the CP-SAT time budget per decision. The default is two seconds. The output distinguishes proven optima, valid solutions found within the budget, and cases with no solution in time.

</details>

## Results directory

The `results/` directory contains generated plans and saved evaluation results.

| File or directory | Description |
| --- | --- |
| [`results/menu/`](results/menu/) | Results generated by the normal scenario menu. Each scenario contains a `plan.json` and `statistics.txt` using the main strict-deadline configuration. |
| [`results/plans/`](results/plans/) | Saved experimental plans for all three scenarios, with separate `strict` and `allow_late` directories. |
| [`allocation_comparison.json`](results/allocation_comparison.json) | Results of comparing CP-SAT with the nearest-responder baseline across all scenarios and both deadline modes. Generated by `benchmark.py`. |
| [`traffic_comparison.json`](results/traffic_comparison.json) | Results of comparing Bayesian-only, HMM tie-breaking and HMM bounded routing. Generated by `benchmark_traffic.py`. |
| [`plan_export_validation.json`](results/plan_export_validation.json) | Saved validation results for the six exported experimental plans, including independently reconstructed arrival times, treatment completion times and statistics. |

### Normal results and experimental plans

The normal menu generates new results rather than loading the saved plans. Running the same scenario again replaces its previous menu output.

The strict plans in `results/plans/` use the same settings as the normal menu. They are retained alongside the allow-late plans as saved experimental results.

Each experimental plan contains the same two required output files, `plan.json` and `statistics.txt`. The difference between strict and allow-late plans is the deadline policy, not the output format.

The commands in the **Advanced commands** section reproduce these experimental plans.

### Benchmark results

The benchmark JSON files contain more detailed information than the normal output files.

- `allocation_comparison.json` contains 12 simulation runs: three scenarios, two allocators and two deadline modes. It records the settings, assignments, statistics and available solver information. This comparison uses Bayesian routing without HMM traffic preferences.
- `traffic_comparison.json` contains 36 simulation runs: three scenarios, two allocators, two deadline modes and three traffic policies. It also includes route comparisons showing where the HMM changes possible routes.

Both files can be regenerated using the commands in the **Reproduce the comparisons** section.

### Validation results

The `plan_export_validation.json` file records the validation checks performed during development for the six exported plans in `results/plans/`.

It includes the validity of each plan, the independently reconstructed assignment timings, calculated statistics, deadline compliance and standalone validator exit codes.

All six saved plans passed validation under their selected deadline policies. The three allow-late plans contain missed arrival deadlines, which are permitted by that policy.

Individual plans can be checked again using `validate_plan.py`. For example:

```powershell
.\.venv\Scripts\python.exe validate_plan.py Scenarios/Scenario1 results/plans/Scenario1/strict/plan.json --routing-policy bayesian --block-threshold .2
```

For an allow-late plan:

```powershell
.\.venv\Scripts\python.exe validate_plan.py Scenarios/Scenario1 results/plans/Scenario1/allow_late/plan.json --routing-policy bayesian --block-threshold .2 --allow-late
```

On macOS or Linux, replace the Windows Python executable with `./.venv/bin/python`.

These commands reproduce the individual validation checks. The combined `plan_export_validation.json` file is a saved development report and is not automatically regenerated by the normal menu or standalone validator.

**None of the saved results are required as input to the planner.** The program calculates its assignments from the original scenario files in `Scenarios/`. The saved outputs are included for inspection, comparison and evaluation.

## Project notes

- [Code guide](CODE_GUIDE.md) follows a run through the main files.
- [Design](DESIGN.md) explains the rules, formulas and assumptions.
- [Testing](TESTING.md) records the tests and benchmark results.
- [LLM notes](LLM_NOTES.md) describe the development process, design decisions, corrections and LLM collaboration, including the exact first substantive prompt.
