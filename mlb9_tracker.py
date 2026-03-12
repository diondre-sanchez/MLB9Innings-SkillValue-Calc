#!/usr/bin/env python3
"""
MLB 9 Innings 26 - Skill Value Tracker
=======================================
Reverse-engineer skill contributions to team value through controlled swap experiments.

Usage:
    python mlb9_tracker.py              # Interactive menu
    python mlb9_tracker.py --help       # Show all commands
"""

import json
import csv
import os
import sys
import argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# ── Config ────────────────────────────────────────────────────────────────────

DATA_FILE = Path("mlb9_experiments.json")
EXPORT_FILE = Path("mlb9_export.csv")

BATTER_TIERS = ["Bronze", "Silver", "Gold", "Legend"]
PITCHER_TIERS = ["Bronze", "Silver", "Gold", "Legend"]

BATTER_TIER_RANK = {t: i for i, t in enumerate(BATTER_TIERS)}  # Bronze=0 … Legend=4
PITCHER_TIER_RANK = {t: i for i, t in enumerate(PITCHER_TIERS)}  # Bronze=0 … Legend=4

BATTER_SKILLS_BY_TIER = {
    "Bronze": [
        "Concentration",
        "Fastball Crusher",
        "Fielding Specialist",
        "Going For The First Pitch",
        "Hawk Eye",
        "Head-On",
        "Lefty Specialist",
        "Pinch Hit Specialist",
        "Pull Hit",
        "Push Hit",
        "RBI Machine",
        "Righty Specialist",
    ],
    "Silver": [
        "Endurance",
        "Exhaustion",
        "Flashing The Leather",
        "Full Swing Hitter (FSH)",
        "Heavy Hitter (HH)",
        "It Aint Over Yet",
        "Leg Day",
        "Overcome Weakness",
        "Pinpoint Strike",
        "Professional",
        "Reliable",
        "Table Setter",
        "Training Junkie (TJ)",
    ],
    "Gold": [
        "5-Tool Player",
        "Ace Specialist",
        "Barrel It Up (BIU)",
        "Batting Machine (BM)",
        "Charisma",
        "Laser Beam",
        "Master Base Thief (MBT)",
        "Prediction",
        "Slugger Instinct (SI)",
        "Spotlight (SL)",
        "Spray Hitter",
        "Strengthen the Strength",
        "Super Sub",
    ],
    "Legend": [
        "Bad Ball Hitter (BBH)",
        "Batter's Chemistry (BC)",
        "Batter's Insight",
        "Born To Be A Star (BTBS)",
        "Chance Maker",
        "Contact Master",
        "Hard Hitter",
        "Pioneer",
        "Strategist",
    ],
}

PITCHER_SKILLS_BY_TIER = {
    "Bronze": [
        "Breaking Ball Mastery",
        "Calm Mind",
        "Danger Zone",
        "Fearless",
        "Lefty Specialist",
        "Lightning Pitch",
        "Pick-Off King",
        "Righty Specialist",
        "Seasoned Pitcher",
        "Strong Mentality",
        "Strong Stamina",
        "Thin Ice",
    ],
    "Silver": [
        "3-4-5 Specialist",
        "Control Artist",
        "Field Commander",
        "Firefighter",
        "Fixer",
        "Golden Pitcher (GP)",
        "Pace Controller",
        "Pitching Machine (PM)",
        "Power Pitcher",
        "Stability",
        "The Setup Man (SUM)",
        "Warmed Up",
        "Winning Streak",
    ],
    "Gold": [
        "Ace",
        "Cleaning Up Your Mess (CUYM)",
        "Crossfire",
        "Dominant Pitcher (Dom / DP)",
        "Elite Closer",
        "Finesse Pitcher (Fin / FP)",
        "Giant Crusher",
        "Groundballer",
        "Inning Eater",
        "Iron Will",
        "Pitching Coordinator",
        "Putaway Pitch",
        "The Last Boss",
        "The Untouchable",
    ],
    "Legend": [
        "Bullpen Day",
        "Control Master",
        "Cooperative Pitching (CP)",
        "Fireballer",
        "Mister Perfect (Mr. Perfect)",
        "Pitchers Chemistry (PC)",
        "Pitchers Insight",
        "Slow Starter (SS)",
        "Workhorse",
    ],
}

BATTER_SKILL_TO_TIER = {
    skill: tier
    for tier, skills in BATTER_SKILLS_BY_TIER.items()
    for skill in skills
}

PITCHER_SKILL_TO_TIER = {
    skill: tier
    for tier, skills in PITCHER_SKILLS_BY_TIER.items()
    for skill in skills
}



# ANSI colors (auto-disabled if terminal doesn't support them)
USE_COLOR = sys.stdout.isatty()

def c(text, code):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

TIER_COLORS = {
    "Bronze":  lambda t: c(t, "33"),   # yellow
    "Silver":  lambda t: c(t, "37"),   # white
    "Gold":    lambda t: c(t, "93"),   # bright yellow
    "Diamond": lambda t: c(t, "96"),   # bright cyan
    "Legend":  lambda t: c(t, "95"),   # bright magenta
}

def tier_str(tier, level=None):
    fn = TIER_COLORS.get(tier, lambda t: t)
    s = fn(tier)
    if level is not None:
        s += f" Lv{level}"
    return s

# ── Storage ───────────────────────────────────────────────────────────────────

def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"experiments": [], "next_id": 1}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ── Core Logic ────────────────────────────────────────────────────────────────

def skill_key(skill, tier, level):
    return f"{skill}|{tier}|{level}"

def infer_values(experiments):
    """
    Build relative value scores from pairwise deltas.

    For each experiment: swapped skill_A → skill_B, team value changed by delta.
      delta > 0  →  team value ROSE  →  B worth more than A  →  B advantage = +delta
      delta < 0  →  team value FELL  →  A worth more than B  →  A advantage = +|delta|

    We accumulate for each (skill, tier, level) how much MORE it is vs everything
    it's been compared against, then average those advantages.
    """
    advantages = defaultdict(list)  # key -> list of relative advantages

    for exp in experiments:
        ka = skill_key(exp["skill_a"], exp["tier_a"], exp["level_a"])
        kb = skill_key(exp["skill_b"], exp["tier_b"], exp["level_b"])
        delta = exp["delta"]
        # A was removed, B was added. delta = new_value - old_value
        # If delta < 0, value fell → A was worth more → A's advantage over B = -delta
        advantages[ka].append(-delta)   # A is worth (+) more if delta is negative
        advantages[kb].append(delta)    # B is worth (+) more if delta is positive

    scores = {}
    for key, vals in advantages.items():
        parts = key.split("|")
        scores[key] = {
            "skill": parts[0],
            "tier": parts[1],
            "level": int(parts[2]),
            "score": sum(vals) / len(vals),
            "n": len(vals),
            "raw": vals,
        }
    return scores

# ── Display Helpers ───────────────────────────────────────────────────────────

def print_header(title):
    print()
    print(c("═" * 56, "90"))
    print(c(f"  {title}", "1"))
    print(c("═" * 56, "90"))

def print_experiment(exp, idx=None):
    prefix = f"  [{exp['id']:>3}]" if idx is None else f"  [{idx:>3}]"
    a = f"{tier_str(exp['tier_a'], exp['level_a'])} {c(exp['skill_a'], '1')}"
    b = f"{tier_str(exp['tier_b'], exp['level_b'])} {c(exp['skill_b'], '1')}"
    delta = exp["delta"]
    if delta > 0:
        delta_str = c(f"+{delta}", "92")   # green = B better
    elif delta < 0:
        delta_str = c(str(delta), "91")    # red = A better
    else:
        delta_str = c("0", "90")
    arrow = c("→", "90")
    print(f"{prefix}  {a}  {arrow}  {b}    Δ {delta_str}")
    if exp.get("notes"):
        print(f"         {c(exp['notes'], '90')}")

# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_log(args=None):
    """Interactively log a new swap experiment."""
    data = load_data()
    print_header("LOG NEW EXPERIMENT")
    print(c("  Tip: swap ONE skill, keep everything else the same.\n", "90"))

    def pick(prompt, options, display_fn=None):
        for i, o in enumerate(options, 1):
            label = display_fn(o) if display_fn else str(o)
            print(f"    {c(str(i), '90')}. {label}")
        while True:
            raw = input(c(f"  {prompt} (1-{len(options)}): ", "96")).strip()
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return options[int(raw) - 1]
            print(c("  Invalid choice, try again.", "91"))

    print(c("  Skill A (removed):", "33"))
    skill_a = pick("Select skill", SKILL_NAMES)
    tier_a  = pick("Select tier",  TIERS, lambda t: tier_str(t))
    level_a = pick("Select level", LEVELS, lambda l: f"Level {l}")

    print()
    print(c("  Skill B (added):", "96"))
    skill_b = pick("Select skill", SKILL_NAMES)
    tier_b  = pick("Select tier",  TIERS, lambda t: tier_str(t))
    level_b = pick("Select level", LEVELS, lambda l: f"Level {l}")

    print()
    while True:
        raw = input(c("  Team value change (e.g. -15 or +22): ", "96")).strip()
        try:
            delta = float(raw.replace("+", ""))
            break
        except ValueError:
            print(c("  Please enter a number like -15 or 22.", "91"))

    notes = input(c("  Notes (optional, press Enter to skip): ", "90")).strip()

    exp = {
        "id":       data["next_id"],
        "skill_a":  skill_a,
        "tier_a":   tier_a,
        "level_a":  level_a,
        "skill_b":  skill_b,
        "tier_b":   tier_b,
        "level_b":  level_b,
        "delta":    delta,
        "notes":    notes,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    data["experiments"].append(exp)
    data["next_id"] += 1
    save_data(data)

    print()
    print(c("  ✓ Experiment logged!", "92"))
    print_experiment(exp)
    print()

def cmd_list(args=None):
    """List all logged experiments."""
    data = load_data()
    exps = data["experiments"]
    print_header(f"EXPERIMENTS ({len(exps)} total)")
    if not exps:
        print(c("  No experiments yet. Run: python mlb9_tracker.py log\n", "90"))
        return
    for exp in exps:
        print_experiment(exp)
    print()

def cmd_infer(args=None):
    """Show inferred relative skill values ranked."""
    data = load_data()
    exps = data["experiments"]
    print_header("INFERRED SKILL VALUES")

    if not exps:
        print(c("  No data yet. Log some experiments first.\n", "90"))
        return

    scores = infer_values(exps)
    if not scores:
        print(c("  Not enough data to infer values yet.\n", "90"))
        return

    # Optional tier filter
    tier_filter = None
    if args and hasattr(args, "tier") and args.tier:
        tier_filter = args.tier.capitalize()
        if tier_filter not in TIERS:
            print(c(f"  Unknown tier '{tier_filter}'. Valid: {', '.join(TIERS)}", "91"))
            return

    ranked = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
    if tier_filter:
        ranked = [r for r in ranked if r["tier"] == tier_filter]
        print(c(f"  Filtered to: {tier_str(tier_filter)}\n", "90"))

    if not ranked:
        print(c("  No data for that filter.\n", "90"))
        return

    max_score = max(abs(r["score"]) for r in ranked) or 1
    bar_width = 24

    print(f"  {'#':<4} {'Skill':<16} {'Tier+Lv':<16} {'Score':>8}  {'Comparisons':<6}  Chart")
    print(c("  " + "─" * 72, "90"))

    for i, r in enumerate(ranked, 1):
        bar_len = int(abs(r["score"]) / max_score * bar_width)
        bar = "█" * bar_len
        tier_lv = f"{r['tier']} Lv{r['level']}"
        score_str = f"{r['score']:+.1f}"
        color = "92" if r["score"] >= 0 else "91"
        print(
            f"  {i:<4} {r['skill']:<16} {tier_lv:<16} "
            f"{c(f'{score_str:>8}', color)}  "
            f"{r['n']:<6} comparisons  "
            f"{c(bar, color)}"
        )

    print()
    print(c(f"  Based on {len(exps)} experiment(s). More swaps = more accurate scores.", "90"))
    print(c("  Scores are RELATIVE — they show how skills rank against each other,", "90"))
    print(c("  not absolute team value contributions.\n", "90"))

def cmd_export(args=None):
    """Export all experiments to CSV."""
    data = load_data()
    exps = data["experiments"]

    if not exps:
        print(c("\n  No experiments to export.\n", "90"))
        return

    scores = infer_values(exps)

    path = Path(args.output) if (args and hasattr(args, "output") and args.output) else EXPORT_FILE

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)

        # Sheet 1: raw experiments
        writer.writerow(["=== RAW EXPERIMENTS ==="])
        writer.writerow(["ID", "Skill A", "Tier A", "Level A", "Skill B", "Tier B", "Level B", "Delta", "Notes", "Timestamp"])
        for exp in exps:
            writer.writerow([
                exp["id"], exp["skill_a"], exp["tier_a"], exp["level_a"],
                exp["skill_b"], exp["tier_b"], exp["level_b"],
                exp["delta"], exp.get("notes", ""), exp["timestamp"],
            ])

        writer.writerow([])

        # Sheet 2: inferred values
        writer.writerow(["=== INFERRED VALUES (relative scores) ==="])
        writer.writerow(["Rank", "Skill", "Tier", "Level", "Score", "Comparisons"])
        ranked = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
        for i, r in enumerate(ranked, 1):
            writer.writerow([i, r["skill"], r["tier"], r["level"], f"{r['score']:.2f}", r["n"]])

    print(c(f"\n  ✓ Exported {len(exps)} experiments to {path}\n", "92"))

def cmd_delete(args=None):
    """Delete an experiment by ID."""
    data = load_data()
    if args and hasattr(args, "id") and args.id:
        exp_id = args.id
    else:
        cmd_list()
        raw = input(c("  Enter experiment ID to delete: ", "91")).strip()
        if not raw.isdigit():
            print(c("  Invalid ID.\n", "91"))
            return
        exp_id = int(raw)

    before = len(data["experiments"])
    data["experiments"] = [e for e in data["experiments"] if e["id"] != exp_id]
    if len(data["experiments"]) < before:
        save_data(data)
        print(c(f"\n  ✓ Deleted experiment #{exp_id}\n", "92"))
    else:
        print(c(f"\n  No experiment with ID #{exp_id} found.\n", "91"))

def cmd_summary(args=None):
    """Quick summary stats."""
    data = load_data()
    exps = data["experiments"]
    print_header("SUMMARY")
    print(f"  Total experiments : {c(str(len(exps)), '93')}")
    if exps:
        tiers_seen = set(e["tier_a"] for e in exps) | set(e["tier_b"] for e in exps)
        skills_seen = set(e["skill_a"] for e in exps) | set(e["skill_b"] for e in exps)
        deltas = [e["delta"] for e in exps]
        print(f"  Skills tracked    : {c(str(len(skills_seen)), '93')}  ({', '.join(sorted(skills_seen))})")
        print(f"  Tiers seen        : {c(str(len(tiers_seen)), '93')}  ({', '.join(t for t in TIERS if t in tiers_seen)})")
        print(f"  Avg delta         : {c(f'{sum(deltas)/len(deltas):+.1f}', '93')}")
        print(f"  Largest gain      : {c(f'+{max(deltas)}', '92')}")
        print(f"  Largest loss      : {c(str(min(deltas)), '91')}")
        print(f"  Data file         : {c(str(DATA_FILE.resolve()), '90')}")
    print()

# ── Interactive Menu ──────────────────────────────────────────────────────────

def interactive_menu():
    menu = [
        ("Log new experiment",       cmd_log),
        ("List all experiments",     cmd_list),
        ("View inferred values",     cmd_infer),
        ("Summary stats",            cmd_summary),
        ("Export to CSV",            cmd_export),
        ("Delete an experiment",     cmd_delete),
        ("Quit",                     None),
    ]

    print(c("""
╔══════════════════════════════════════════╗
║   MLB 9 Innings 26 — Skill Value Tracker ║
║   Reverse-engineer team value by skill   ║
╚══════════════════════════════════════════╝""", "93"))

    while True:
        print(c("  MENU", "1"))
        for i, (label, _) in enumerate(menu, 1):
            print(f"    {c(str(i), '96')}. {label}")
        print()
        raw = input(c("  Choose (1-7): ", "96")).strip()
        if not raw.isdigit() or not (1 <= int(raw) <= len(menu)):
            print(c("  Invalid choice.\n", "91"))
            continue
        choice = int(raw)
        label, fn = menu[choice - 1]
        if fn is None:
            print(c("\n  Goodbye!\n", "90"))
            break
        fn()

# ── CLI Entry Point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="MLB 9 Innings 26 — Skill Value Tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  (no args)          Interactive menu
  log                Log a new swap experiment
  list               List all experiments
  infer              Show inferred skill values
  infer --tier Gold  Filter inferred values by tier
  summary            Quick stats overview
  export             Export to CSV (default: mlb9_export.csv)
  export -o my.csv   Export to custom path
  delete             Interactively delete an experiment
  delete --id 5      Delete experiment #5 directly
        """
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("log",     help="Log a new swap experiment")
    sub.add_parser("list",    help="List all experiments")

    p_infer = sub.add_parser("infer", help="Show inferred skill values")
    p_infer.add_argument("--tier", help="Filter by tier (Bronze/Silver/Gold/Diamond/Legend)")

    sub.add_parser("summary", help="Summary stats")

    p_export = sub.add_parser("export", help="Export to CSV")
    p_export.add_argument("-o", "--output", help="Output CSV path", default=str(EXPORT_FILE))

    p_del = sub.add_parser("delete", help="Delete an experiment")
    p_del.add_argument("--id", type=int, help="Experiment ID to delete")

    args = parser.parse_args()

    dispatch = {
        "log":     cmd_log,
        "list":    cmd_list,
        "infer":   cmd_infer,
        "summary": cmd_summary,
        "export":  cmd_export,
        "delete":  cmd_delete,
    }

    if args.command:
        dispatch[args.command](args)
    else:
        interactive_menu()

if __name__ == "__main__":
    main()
