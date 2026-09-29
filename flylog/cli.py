"""Command line interface: flylog vol.igc [--map carte.html] [--profile profil.png]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .airspace import check_airspaces, read_openair
from .formats import to_gpx, to_kml
from .metrics import notable_moments, piloting_metrics
from .parser import read_igc
from .score import best_scores
from .stats import compute_stats
from .thermals import detect_thermals


def _format_duration(seconds: float) -> str:
    h, m = divmod(round(seconds / 60), 60)
    return f"{h}h{m:02d}"


def _compass(deg: float) -> str:
    names = ["nord", "nord-est", "est", "sud-est", "sud", "sud-ouest", "ouest", "nord-ouest"]
    return names[round(deg / 45) % 8]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("sync", "carnet"):
        from .logbook_cli import main as logbook_main
        return logbook_main(argv)
    if argv and argv[0] == "overlay":
        from .overlay import main as overlay_main
        return overlay_main(argv[1:])
    return analyze_main(argv)


def analyze_main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="flylog", description="Analyse une trace de vol IGC.",
        epilog="Autres commandes : flylog sync, flylog carnet (carnet de vol), "
               "flylog overlay (incrustation vidéo). Ajoute -h pour l'aide de chacune.",
    )
    ap.add_argument("igc", help="fichier .igc à analyser")
    ap.add_argument("--map", metavar="HTML", help="génère une carte interactive")
    ap.add_argument("--profile", metavar="PNG", help="génère le profil d'altitude")
    ap.add_argument("--min-climb", type=float, default=0.5,
                    help="taux de montée minimal d'un thermique en m/s (défaut : 0.5)")
    ap.add_argument("--airspace", metavar="OPENAIR",
                    help="vérifie les espaces aériens d'un fichier OpenAir")
    ap.add_argument("--all-airspaces", action="store_true",
                    help="vérifie aussi les classes E et G et les secteurs vol à voile")
    ap.add_argument("--gpx", metavar="FICHIER", help="exporte la trace en GPX")
    ap.add_argument("--kml", metavar="FICHIER", help="exporte la trace en KML (Google Earth, 3D)")
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

    m = piloting_metrics(flight, thermals)
    print("\n  Pilotage")
    print(f"  Temps en virage       {m.circling_pct:.0f} %  (dont {m.left_turn_pct:.0f} % à gauche)")
    if m.avg_thermal_climb is not None:
        print(f"  Montée moy. thermique {m.avg_thermal_climb:.1f} m/s")
    if m.avg_glide_ratio is not None:
        best = f", max {m.best_glide_ratio:.1f}" if m.best_glide_ratio else ""
        print(f"  Finesse sol en transition {m.avg_glide_ratio:.1f}{best}  "
              f"à {m.avg_glide_speed_kmh:.0f} km/h")
    print(f"  Facteur de charge max {m.max_g:.1f} G (estimé)")
    if m.wind:
        print(f"  Vent moyen estimé     {m.wind.speed_kmh:.0f} km/h du {_compass(m.wind.direction_deg)}"
              f" ({m.wind.direction_deg:.0f}°)")

    scores = best_scores(flight)
    if scores:
        print("\n  Score (estimation type XContest)")
        for sc in scores:
            closing = f", fermeture {sc.closing_km:.1f} km" if sc.kind != "free" else ""
            print(f"    {sc.label:<15} {sc.distance_km:6.1f} km  → {sc.points:6.1f} pts{closing}")

    print(f"\n  {len(thermals)} thermique(s) détecté(s) (heures UTC)")
    for i, t in enumerate(thermals, 1):
        print(f"    #{i}  {t.start:%H:%M}  +{t.gain_m:>4} m  "
              f"{t.avg_climb:>4.1f} m/s  {t.duration_s / 60:>4.1f} min  "
              f"plafond {t.top_alt} m")

    moments = notable_moments(flight)
    if moments:
        print("\n  Moments forts")
        for mo in moments:
            print(f"    {mo.time:%H:%M:%S}  {mo.label} : {mo.value:g}")

    if args.airspace:
        found = check_airspaces(flight, read_openair(args.airspace), args.all_airspaces)
        print(f"\n  Espaces aériens : {'aucune pénétration détectée' if not found else ''}")
        for inf in found:
            a = inf.airspace
            flag = "  (limite sol : à vérifier)" if inf.uncertain else ""
            print(f"    ⚠ {inf.start:%H:%M:%S}  {a.name} [{a.label}, {a.floor} → {a.ceiling}]  "
                  f"{inf.duration_s:.0f} s à {inf.alt} m{flag}")
    print()

    for path, content in ((args.gpx, to_gpx), (args.kml, to_kml)):
        if path:
            Path(path).write_text(content(flight), encoding="utf-8")
            print(f"  Export enregistré : {path}")

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
