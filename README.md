# Emergency Response System

This Python project plans emergency responses after a storm. It checks road reports and past traffic, finds routes, and decides which available responders should take each call.

## Get started

Use **64-bit Python 3.12**. The project was tested on Windows with Python 3.12.14 and OR-Tools 9.15.6755. The application uses portable Python paths. macOS and Linux commands are provided below, but those operating systems have not been tested directly here.

First download the repository ZIP and extract it, or clone it:

```console
git clone https://github.com/JeremiLrk/AI-Emergency-Response-System.git
cd AI-Emergency-Response-System
```

Run all commands from the folder containing run.py and requirements.txt.

### Windows (PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

If the Windows launcher command is unavailable, use your installed Python 3.12 executable in place of py -3.12.

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

requirements.txt lists the one direct third-party dependency. pip installs OR-Tools' own dependencies automatically. The other project imports come from Python's standard library.

### Choose a scenario

If you use an IDE, select the environment where you installed the requirements and run `run.py` without arguments. Choose **1**, **2** or **3** for a scenario, or **0** to exit.

The menu runs the full planner with strict arrival deadlines. It uses CP-SAT for assignments, a 20% road blockage cutoff, and a historical traffic preference that allows up to 5% extra travel for at least 10% less exposure. It prints and saves two files in `results/menu/ScenarioN/`. Running the same scenario replaces its previous menu results.

| File | What you get |
| --- | --- |
| `plan.json` | Who handles each call, the route they take, and when they leave. |
| `statistics.txt` | Calls handled and reached on time, responders used, average response time, and the settings used. It also shows results by priority and observed reasons for unhandled calls. |

The average response time includes waiting and travel for calls that were handled. The deadline percentage includes all calls, including unhandled ones. A separate validator checks the plan using the original inputs and estimated travel times.

## Run the tests or check a plan

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe validate_plan.py Scenarios/Scenario1 results/menu/Scenario1/plan.json --routing-policy bayesian --block-threshold .2
```

On macOS or Linux, use:

```sh
./.venv/bin/python -m unittest discover -s tests -v
./.venv/bin/python validate_plan.py Scenarios/Scenario1 results/menu/Scenario1/plan.json --routing-policy bayesian --block-threshold .2
```

The test command runs all 160 tests. A successful run ends with OK. [What each test file checks](TESTING.md)

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

- `--allocator nearest` selects the nearest-responder comparison. `--compare` runs both allocators and creates separate `csp` and `nearest` folders.
- `--traffic-policy hmm-tie` uses traffic only to choose among equally fast routes. `bayesian-only` uses plain UCS. For explicit Bayesian runs, pass `--block-threshold`. Explicit runs without a routing policy use the all-open baseline.
- `--route H1 N2` inspects one route and writes no assignment files. `--simulate-script examples/scenario1_script.json` runs the scripted example. These modes and `--compare` are mutually exclusive.
- `--solver-time-limit` sets the CP-SAT time budget per decision. The default is two seconds. The output distinguishes proven optima, valid solutions found within the budget, and cases with no solution in time.

</details>

## Project notes

- [Code guide](CODE_GUIDE.md) follows a run through the main files.
- [Design](DESIGN.md) explains the rules, formulas and assumptions.
- [Testing](TESTING.md) records the tests and benchmark results.
- [LLM notes](LLM_NOTES.md) record what we accepted, corrected and tested, including the exact first prompt.
- [Data schema](DATA_SCHEMA.md) is an optional reference for input fields and validation rules.
