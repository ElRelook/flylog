"""Logbook commands: flylog sync [--source DIR] / flylog carnet"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import logbook
from .sites import SiteNamer


def _duration(seconds: float) -> str:
    h, m = divmod(round(seconds / 60), 60)
    return f"{h}h{m:02d}"


def _date(entry: logbook.LogEntry) -> str:
    y, m, d = entry.takeoff_time[:10].split("-")
    return f"{d}/{m}/{y}"


def cmd_sync(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser()
    if not source.is_dir():
        print(f"Dossier introuvable : {source}\n"
              "Indique où sont tes fichiers .igc avec --source DOSSIER", file=sys.stderr)
        return 1

    print(f"\n  Synchronisation de {source}")
    namer = None if args.no_sites else SiteNamer()
    result = logbook.sync(source, Path(args.db), namer)
    if result.rebuilt:
        print("    (nouvelle version de l'analyse : tous les vols ont été recalculés)")
    for e in result.added:
        print(f"    + {_date(e)}  {_duration(e.duration_s):>6}  {e.distance_km:6.1f} km  "
              f"plafond {e.max_alt} m  {e.site or ''}")
    for path, err in result.errors:
        print(f"    ! {Path(path).name} ignoré : {err}")
    print(f"\n  {len(result.added)} nouveau(x) vol(s), {result.known} déjà dans le carnet"
          + (f", {len(result.errors)} fichier(s) ignoré(s)" if result.errors else ""))
    if namer is not None and not namer.online:
        print("  (noms des sites indisponibles hors ligne : ils seront ajoutés à la prochaine synchro)")
    print(f"  Carnet : {args.db}\n")
    return 0


def cmd_carnet(args: argparse.Namespace) -> int:
    entries = sorted(logbook.load(Path(args.db)).values(), key=lambda e: e.takeoff_time)
    if not entries:
        print("Carnet vide : lance d'abord « flylog sync ».", file=sys.stderr)
        return 1

    t = logbook.totals(entries)
    assert t.best_alt and t.longest and t.farthest  # the logbook is not empty
    print(f"\n  Carnet de vol : {t.flights} vols, {_duration(t.duration_s)} de vol "
          f"depuis le {_date(entries[0])}\n")
    print(f"  Distance totale     {t.distance_km:,.0f} km".replace(",", " "))
    print(f"  Gain cumulé total   {t.gain_m:,} m".replace(",", " "))
    print(f"  Plafond record      {t.best_alt.max_alt} m ({_date(t.best_alt)})")
    print(f"  Plus long vol       {_duration(t.longest.duration_s)} ({_date(t.longest)})")
    print(f"  Plus grande distance {t.farthest.distance_km:.1f} km ({_date(t.farthest)})")

    sites: dict[str, int] = {}
    for e in entries:
        sites[e.site or "site inconnu"] = sites.get(e.site or "site inconnu", 0) + 1
    print("\n  Sites de décollage")
    for name, n in sorted(sites.items(), key=lambda kv: -kv[1]):
        print(f"    {n:>3} vol{'s' if n > 1 else ' '}  {name}")

    print("\n  Par année")
    for year, (n, d) in t.by_year.items():
        print(f"    {year}   {n:>3} vols   {_duration(d):>7}")

    shown = entries[::-1] if args.all else entries[::-1][:15]
    print(f"\n  {'Date':<10}  {'Durée':>6}  {'Dist.':>8}  {'Plafond':>7}  {'Gain':>6}  {'Score':>7}  Site")
    for e in shown:
        print(f"  {_date(e):<10}  {_duration(e.duration_s):>6}  {e.distance_km:>5.1f} km  "
              f"{e.max_alt:>5} m  {e.gain_m:>4} m  {e.score_points:>7.1f}  {e.site or ''}")
    if len(shown) < len(entries):
        print(f"  … {len(entries) - len(shown)} vol(s) plus ancien(s) : flylog carnet --all")
    print()
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="flylog", description="Carnet de vol FlyLog.")
    sub = ap.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="ajoute au carnet les nouveaux vols d'un dossier",
                            description="Ajoute au carnet les nouveaux fichiers .igc d'un dossier. "
                                        "Par défaut, le dossier où Syride copie tes vols.")
    p_sync.add_argument("--source", default=str(logbook.default_source()),
                        help="dossier contenant les .igc (défaut : %(default)s)")
    p_sync.add_argument("--no-sites", action="store_true",
                        help="ne cherche pas le nom des sites de déco (ParaglidingEarth)")

    p_carnet = sub.add_parser("carnet", help="affiche le carnet de vol")
    p_carnet.add_argument("--all", action="store_true", help="affiche tous les vols")

    for p in (p_sync, p_carnet):
        p.add_argument("--db", default=str(logbook.default_db()),
                       help="fichier du carnet (défaut : %(default)s)")

    args = ap.parse_args(argv)
    return cmd_sync(args) if args.command == "sync" else cmd_carnet(args)
