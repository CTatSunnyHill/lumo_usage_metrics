# Interactive Technologies Usage Report

Turns the daily LUMOplay log files from the IntTech systems into a usage dashboard.

Two scripts run in order:

1. `clean_logs.py` — reads the raw logs and writes `usage_metrics.xlsx`
2. `data_viz.py` — the Streamlit dashboard that reads that spreadsheet

Retrieving the raw logs from the devices is covered in *Retrieving IntTech Usage Logs*.
Why the project is built this way is covered in *Handover & Maintenance Notes*.

---

## Setup

```bash
pip install -r requirements.txt
```

## Step 1 — Clean the logs

The script needs the logs arranged by area and device. It reads the device and
the area **from the folder path**, so the folder names matter:

```
LumoUsage/
  Bioness/
    BL1/              2024-01-09.log  2024-01-10.log  ...
    BL2/              ...
    BR1/              ...
    BR2/              ...
  Gym/
    Gym_Wall_Left/    ...
    Gym_Wall_Right/   ...
    Gym_Floor_Left/   ...
```

Then run:

```bash
python clean_logs.py LumoUsage
```

| Option | What it does |
|---|---|
| `-o`, `--output` | Output filename (default `usage_metrics.xlsx`) |
| `-y`, `--year` | Keep only sessions starting in that year, e.g. `-y 2024` |

Examples:

```bash
python clean_logs.py LumoUsage -o usage_metrics.xlsx
python clean_logs.py LumoUsage -y 2024
```

The script prints a run summary — files read, sessions written, sessions dropped
and why, and a per-device count. **Read it.** A device showing zero sessions
usually means a misnamed folder, not a quiet month.

## Step 2 — View the dashboard

```bash
streamlit run data_viz.py
```

The dashboard looks for `usage_metrics.xlsx` in the same folder by default, so
the two filenames have to stay in step. If you rename the cleaning script's
output with `-o`, use the sidebar's **Upload Custom File** option instead.

---

## Output columns

`clean_logs.py` writes exactly these seven columns, and `data_viz.py` expects
all of them:

| Column | Meaning |
|---|---|
| `date` | Date the session started |
| `game` | LUMOplay game name |
| `start_time` | Session start (local time) |
| `end_time` | Session end (local time) |
| `duration_minutes` | Wall-clock length of the session |
| `device` | Device folder name, e.g. `BL1` |
| `area` | `Bioness`, `Gym Wall` or `Gym Floor` |

## Configuration

Settings live in the `CONFIGURATION` block at the top of `clean_logs.py`:

| Setting | Default | Notes |
|---|---|---|
| `SESSION_START_EVENT` | `"first_running"` | How a session's start time is decided. Read the handover notes before changing this. |
| `KEEP_UNTERMINATED_SESSIONS` | `False` | Whether to keep a session still running when a log file ends. |
| `MIN_DURATION_MINUTES` | `0.0` | Discard sessions shorter than this. |
| `DEVICE_AREA_RULES` | see file | Maps a device folder name to an area. Add a line here for a new device. |

Log line patterns are in the `LOG LINE PATTERNS` block below it. If LUMOplay
changes its log wording, that block is where the fix goes.

---

## Things to know

- **Sessions still running when a log ends are dropped.** A game spanning
  midnight loses its pre-midnight portion. This is intended.
- **A session's start is the first line confirming the game is running**, not
  the "Starting scene" line. This is deliberate and load-bearing — see the
  handover notes before changing it.
- **Duration is wall-clock**, not active engagement time.
- **Commit only `usage_metrics.xlsx`**, never the raw logs.

## Troubleshooting

| Problem | What to try |
|---|---|
| `no .log files found` | Point the script at the top-level `LumoUsage` folder, not an area or device folder. |
| `log files were read but no sessions were found` | The log format has probably changed. Check the `LOG LINE PATTERNS` block. |
| A device is missing from the report | Its folder is misspelled, or it has no logs. Check the per-device counts in the run summary. |
| Sessions under the wrong area | A device folder name doesn't match `DEVICE_AREA_RULES`. |
| Dashboard: "missing one of these required columns" | The spreadsheet wasn't produced by `clean_logs.py`, or a column was renamed. |