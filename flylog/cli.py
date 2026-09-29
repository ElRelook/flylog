"""Command line interface: flylog vol.igc [--map carte.html] [--profile profil.png]"""

from __future__ import annotations

import argparse
import sys

from .parser import read_igc
from .stats import compute_stats
from .thermals import detect_thermals


def _format_duration(seconds: float) -> str:
    h, m = divmod(round(seconds / 60), 60)
    return f"{h}h{m:02d}"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("sync", "carnet"):
        from .logbook_cli import main as logbook_main
        return logbook_main(argv)
    return analyze_main(argv)


def analyze_main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="flylog", description="Analyse une trace de vol IGC.",
        epilog="Carnet de vol : « flylog sync » puis « flylog carnet » (voir flylog sync -h).",
    )
    ap.add_argument("igc", help="fichier .igc à analyser")
    ap.add_argument("--map", metavar="HTML", help="génère une carte interactive")
    ap.add_argument("--profile", metavar="PNG", help="génère le profil d'altitude")
    ap.add_argument("--min-climb", type=float, default=0.5,
                    help="taux de montée minimal d'un thermique en m/s (défaut : 0.5)")
    args = ap.parse_args(argv)

    flight = read_igc(args.igc)
    try:
        s = compute_stats(flight)
    except ValueError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    thermals = detect_thermals(flight, min_climb=args.min_climb)

    print(f"\n  Vol du {flight.date:%d/%m/%Y}" if flight.date else "\n  Vol")
    if flight.pilot:
        print(f"  Pilote : {flight.pilot}")
    if flight.glider:
        print(f"  Voile  : {flight.glider}")
    print()
    print(f"  Durée                 {_format_duration(s.duration.total_seconds())}")
    print(f"  Distance parcourue    {s.track_distance_km:.1f} km")
    print(f"  Déco → atterro        {s.straight_distance_km:.1f} km")
    print(f"  Éloignement max       {s.max_distance_from_takeoff_km:.1f} km")
    print(f"  Altitude déco         {s.takeoff_alt} m")
    print(f"  Altitude max          {s.max_alt} m")
    print(f"  Altitude atterro      {s.landing_alt} m")
    print(f"  Gain cumulé           {s.total_gain_m} m")
    print(f"  Vario max             +{s.max_climb:.1f} m/s")
    print(f"  Taux de chute max     {s.max_sink:.1f} m/s")
    print(f"  Vitesse sol max       {s.max_speed_kmh:.0f} km/h")

    print(f"\n  {len(thermals)} thermique(s) détecté(s)")
    for i, t in enumerate(thermals, 1):
        print(f"    #{i}  {t.start:%H:%M}  +{t.gain_m:>4} m  "
              f"{t.avg_climb:>4.1f} m/s  {t.duration_s / 60:>4.1f} min  "
              f"plafond {t.top_alt} m")
    print()

    if args.map or args.profile:
        from . import plot
        if args.map:
            plot.save_map(flight, thermals, args.map)
            print(f"  Carte enregistrée : {args.map}")
        if args.profile:
            plot.save_profile(flight, thermals, args.profile)
            print(f"  Profil enregistré : {args.profile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
