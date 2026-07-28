"""
Turns the raw LUMOplay MotionPlayer log files into the single spreadsheet
that the dashboard (data_viz.py) reads: usage_metrics.xlsx

Expected input folder structure (the "LumoUsage" folder):

    LumoUsage/
      Bioness/                 <- area folder
        BL1/                   <- device folder
          2024-01-09.log       <- one log file per device per day
          2024-01-10.log
        BL2/ ...
        BR1/ ...
      Gym/
        Gym_Wall_Left/ ...
        Gym_Floor_Left/ ...

Usage:
    python clean_logs.py LumoUsage
    python clean_logs.py LumoUsage -o usage_metrics.xlsx
    python clean_logs.py LumoUsage --year 2024
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# =====================================================================
# CONFIGURATION — these are the settings you are most likely to change
# =====================================================================

# The columns written to the output file, in this exact order.
# data_viz.py expects these names, so do not rename them without also
# updating the dashboard.
OUTPUT_COLUMNS = [
    "date",
    "game",
    "start_time",
    "end_time",
    "duration_minutes",
    "device",
    "area",
]

# Default name of the spreadsheet written out.
DEFAULT_OUTPUT_FILE = "usage_metrics.xlsx"

# Which log file extension to look for.
LOG_FILE_GLOB = "*.log"

# How a session's START timestamp is decided. See the "How a session is
# detected" note in the handover document.
#   "first_running"  -> the first line confirming the scene is running
#                       (matches the existing usage_metrics.xlsx)
#   "starting_scene" -> the "Starting scene" line itself
SESSION_START_EVENT = "first_running"

# If a log file ends while a scene is still running (for example the
# device was left switched on overnight and the log rolled over at
# midnight), the session has no "Stopping scene" line.
#   False -> drop the unfinished session (matches the existing file)
#   True  -> close it off at the last timestamp seen in that log file
KEEP_UNTERMINATED_SESSIONS = False

# Sessions shorter than this are discarded. 0 keeps everything, which is
# what the existing spreadsheet does.
MIN_DURATION_MINUTES = 0.0

# How a device folder name is turned into an "area".
# Checked in order; the first matching prefix wins. Anything that matches
# nothing falls back to the name of the area folder the device sits in.
DEVICE_AREA_RULES = [
    ("Gym_Wall", "Gym Wall"),
    ("Gym_Floor", "Gym Floor"),
    ("BL", "Bioness"),
    ("BR", "Bioness"),
]

# =====================================================================
# LOG LINE PATTERNS
# ---------------------------------------------------------------------
# A log line looks like this:
#
# 2024-01-09 09:35:00 UTC-08:00 [playlist][info] Starting scene Roses ...
# |----- timestamp -----|offset| |-channel-| |-------- message --------|
#
# Times are already local (the offset shown is the device's own clock),
# so the offset is read for validation but not used to convert anything.
# =====================================================================

LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"UTC(?P<offset>[+-]\d{2}:\d{2})\s+"
    r"\[(?P<channel>\w+)\]\[(?P<level>\w+)\]\s+"
    r"(?P<message>.*)$"
)

# "Starting scene Japanese Koi [12738]* (-1s): C:\..."
STARTING_RE = re.compile(r"^Starting scene (?P<game>.+?) \[\d+\]")

# "Stopping scene Japanese Koi [12738]* (-1s)"
STOPPING_RE = re.compile(r"^Stopping scene (?P<game>.+?) \[\d+\]")

# Two different lines both prove a scene is still running:
#   "Scene Japanese Koi [12738]* is currently running; assuming it is ..."
#   "Scene Japanese Koi [12738]* (-1s) has been running for 5 minutes"
RUNNING_RE = re.compile(
    r"^Scene (?P<game>.+?) \[\d+\]\*?"
    r"(?: \(-?\d+s\))? (?:is currently running|has been running for)"
)

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


# =====================================================================
# PARSING
# =====================================================================


def parse_line(line):
    """Break one raw log line into its parts, or return None if it is not
    a recognisable log line (blank lines, wrapped stack traces, etc.)."""
    match = LINE_RE.match(line.strip())
    if not match:
        return None
    return {
        "timestamp": datetime.strptime(match.group("ts"), TIMESTAMP_FORMAT),
        "offset": match.group("offset"),
        "channel": match.group("channel"),
        "message": match.group("message"),
    }


def extract_sessions(log_path, report):
    """Read one log file and return a list of play sessions found in it.

    A session runs from a scene starting to that scene stopping. Only the
    [playlist] lines matter; everything else in the log (network errors,
    CPU warnings, camera messages) is ignored.
    """
    sessions = []

    # Details of the scene currently open, or None between sessions.
    open_session = None
    last_timestamp = None

    with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            parsed = parse_line(raw_line)
            if parsed is None:
                continue

            last_timestamp = parsed["timestamp"]
            if parsed["channel"] != "playlist":
                continue

            message = parsed["message"]

            # --- a scene starts ---
            starting = STARTING_RE.match(message)
            if starting:
                if open_session is not None:
                    # A new scene started without the previous one stopping.
                    report.warn(
                        f"{log_path.name}: '{open_session['game']}' was still "
                        f"open when '{starting.group('game')}' started; "
                        "closing it at the new start time."
                    )
                    _close(open_session, parsed["timestamp"], sessions, report)
                open_session = {
                    "game": starting.group("game").strip(),
                    "started_at": parsed["timestamp"],
                    "first_running_at": None,
                }
                continue

            # --- a scene reports that it is running ---
            running = RUNNING_RE.match(message)
            if running:
                if open_session is None:
                    # No "Starting scene" line — this happens when a session
                    # was already running when the log file began (the logs
                    # roll over at midnight). Treat this as the start.
                    open_session = {
                        "game": running.group("game").strip(),
                        "started_at": parsed["timestamp"],
                        "first_running_at": parsed["timestamp"],
                        "carried_over": True,
                    }
                elif open_session["first_running_at"] is None:
                    open_session["first_running_at"] = parsed["timestamp"]
                continue

            # --- a scene stops ---
            stopping = STOPPING_RE.match(message)
            if stopping:
                if open_session is None:
                    report.warn(
                        f"{log_path.name}: stop recorded for "
                        f"'{stopping.group('game')}' with no matching start; "
                        "ignored."
                    )
                    continue
                _close(open_session, parsed["timestamp"], sessions, report)
                open_session = None

    # --- end of file with a scene still open ---
    if open_session is not None:
        if KEEP_UNTERMINATED_SESSIONS and last_timestamp is not None:
            report.note(
                f"{log_path.name}: '{open_session['game']}' never stopped; "
                "closed at the last line in the file."
            )
            _close(open_session, last_timestamp, sessions, report)
        else:
            report.dropped_unterminated += 1

    return sessions


def _close(open_session, end_time, sessions, report):
    """Turn an open scene into a finished session and add it to the list."""
    if SESSION_START_EVENT == "first_running":
        start_time = open_session["first_running_at"]
        if start_time is None:
            # The scene stopped before it ever reported itself as running,
            # so there is no confirmed start. Skip it.
            report.dropped_no_running += 1
            return
    else:
        start_time = open_session["started_at"]

    if end_time < start_time:
        report.warn(
            f"'{open_session['game']}' ended before it started; skipped."
        )
        return

    duration = (end_time - start_time).total_seconds() / 60.0
    sessions.append(
        {
            "game": open_session["game"],
            "start_time": start_time,
            "end_time": end_time,
            "duration_minutes": duration,
        }
    )


# =====================================================================
# FOLDER WALKING
# =====================================================================


def resolve_area(device_name, area_folder_name):
    """Work out the area for a device, using DEVICE_AREA_RULES first and
    the name of the folder the device sits in as a fallback."""
    for prefix, area in DEVICE_AREA_RULES:
        if device_name.startswith(prefix):
            return area
    return area_folder_name.replace("_", " ")


def find_log_files(root):
    """Find every log file under the root folder and work out which device
    and area each one belongs to, from its folder path."""
    found = []
    for log_path in sorted(root.rglob(LOG_FILE_GLOB)):
        device_name = log_path.parent.name
        area_folder = log_path.parent.parent.name
        found.append(
            {
                "path": log_path,
                "device": device_name,
                "area": resolve_area(device_name, area_folder),
            }
        )
    return found


# =====================================================================
# RUN REPORT
# =====================================================================


class RunReport:
    """Collects counts and warnings so the run can be summarised at the end."""

    def __init__(self):
        self.files_read = 0
        self.sessions_found = 0
        self.dropped_unterminated = 0
        self.dropped_no_running = 0
        self.dropped_too_short = 0
        self.dropped_wrong_year = 0
        self.warnings = []
        self.notes = []

    def warn(self, message):
        self.warnings.append(message)

    def note(self, message):
        self.notes.append(message)

    def print_summary(self, devices, output_path):
        print("\n" + "=" * 62)
        print("RUN SUMMARY")
        print("=" * 62)
        print(f"Log files read           : {self.files_read}")
        print(f"Devices found            : {len(devices)}")
        print(f"Sessions written         : {self.sessions_found}")
        if self.dropped_no_running:
            print(
                f"Dropped, never confirmed running : {self.dropped_no_running}"
            )
        if self.dropped_unterminated:
            print(
                f"Dropped, still running at end of log : "
                f"{self.dropped_unterminated}"
            )
        if self.dropped_too_short:
            print(f"Dropped, under minimum duration  : {self.dropped_too_short}")
        if self.dropped_wrong_year:
            print(f"Dropped, outside chosen year     : {self.dropped_wrong_year}")

        if devices:
            print("\nSessions per device:")
            for device, area, count in devices:
                print(f"  {device:<16} ({area:<10}) {count}")

        if self.notes:
            print("\nNotes:")
            for note in self.notes:
                print(f"  - {note}")

        if self.warnings:
            print(f"\nWarnings ({len(self.warnings)}):")
            for warning in self.warnings[:20]:
                print(f"  - {warning}")
            if len(self.warnings) > 20:
                print(f"  ... and {len(self.warnings) - 20} more")

        print(f"\nWritten to: {output_path}")
        print("=" * 62 + "\n")


# =====================================================================
# MAIN
# =====================================================================


def build_dataframe(root, report, year=None):
    """Read every log under the root folder into one table."""
    log_files = find_log_files(root)
    if not log_files:
        print(
            f"ERROR: no {LOG_FILE_GLOB} files found under '{root}'.\n"
            "Check that you pointed the script at the LumoUsage folder.",
            file=sys.stderr,
        )
        sys.exit(1)

    rows = []
    per_device = {}

    for entry in log_files:
        report.files_read += 1
        sessions = extract_sessions(entry["path"], report)

        for session in sessions:
            if session["duration_minutes"] < MIN_DURATION_MINUTES:
                report.dropped_too_short += 1
                continue
            if year is not None and session["start_time"].year != year:
                report.dropped_wrong_year += 1
                continue

            rows.append(
                {
                    "date": session["start_time"].date(),
                    "game": session["game"],
                    "start_time": session["start_time"],
                    "end_time": session["end_time"],
                    "duration_minutes": session["duration_minutes"],
                    "device": entry["device"],
                    "area": entry["area"],
                }
            )
            key = (entry["device"], entry["area"])
            per_device[key] = per_device.get(key, 0) + 1

    report.sessions_found = len(rows)

    if not rows:
        print(
            "ERROR: log files were read but no sessions were found.\n"
            "This usually means the log format has changed — check the "
            "patterns in the LOG LINE PATTERNS block.",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    df = df.sort_values(["start_time", "device"]).reset_index(drop=True)

    devices = sorted(
        [(device, area, count) for (device, area), count in per_device.items()]
    )
    return df, devices


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Clean LUMOplay usage logs into the spreadsheet used by the "
            "Interactive Technologies Usage Report dashboard."
        )
    )
    parser.add_argument(
        "input_folder",
        help="The LumoUsage folder containing area > device > log files.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT_FILE,
        help=f"Output spreadsheet name (default: {DEFAULT_OUTPUT_FILE}).",
    )
    parser.add_argument(
        "-y",
        "--year",
        type=int,
        default=None,
        help="Keep only sessions starting in this year (default: keep all).",
    )
    args = parser.parse_args()

    root = Path(args.input_folder)
    if not root.is_dir():
        print(f"ERROR: '{root}' is not a folder.", file=sys.stderr)
        sys.exit(1)

    report = RunReport()
    df, devices = build_dataframe(root, report, year=args.year)

    output_path = Path(args.output)
    df.to_excel(output_path, index=False)

    report.print_summary(devices, output_path)


if __name__ == "__main__":
    main()