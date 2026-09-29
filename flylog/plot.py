"""Visual outputs: interactive map (folium) and altitude profile (matplotlib).

These need the optional dependencies: pip install "flylog[plot]"
"""

from __future__ import annotations

from pathlib import Path

from .parser import Flight
from .stats import vario
from .thermals import Thermal


def save_map(flight: Flight, thermals: list[Thermal], path: str | Path) -> None:
    import folium

    fixes = [f for f in flight.fixes if f.valid]
    points = [(f.lat, f.lon) for f in fixes]
    center = (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )

    # Esri tiles work from a local file:// page, unlike OpenStreetMap's servers
    # which reject requests without a Referer header (HTTP 403).
    m = folium.Map(location=center, zoom_start=13, tiles=None)
    esri = "https://server.arcgisonline.com/ArcGIS/rest/services/{}/MapServer/tile/{{z}}/{{y}}/{{x}}"
    folium.TileLayer(esri.format("World_Topo_Map"), attr="Tiles © Esri", name="Topo").add_to(m)
    folium.TileLayer(esri.format("World_Imagery"), attr="Tiles © Esri", name="Satellite").add_to(m)

    # Track colored by climb rate: blue = sink, red = climb.
    rates = [max(-3.0, min(3.0, r)) for r in vario(fixes, 10)]
    folium.ColorLine(
        points, colors=rates[1:], colormap=["#2166ac", "#f7f7f7", "#b2182b"],
        weight=4, opacity=0.9,
    ).add_to(m)

    folium.Marker(points[0], tooltip="Décollage", icon=folium.Icon(color="green", icon="plane")).add_to(m)
    folium.Marker(points[-1], tooltip="Atterrissage", icon=folium.Icon(color="red", icon="flag")).add_to(m)

    for i, t in enumerate(thermals, 1):
        folium.CircleMarker(
            (t.lat, t.lon), radius=6 + t.gain_m / 50, color="#e08214", fill=True,
            fill_opacity=0.6,
            tooltip=f"Thermique {i} : +{t.gain_m} m, {t.avg_climb:.1f} m/s, {t.duration_s / 60:.1f} min",
        ).add_to(m)

    folium.LayerControl().add_to(m)
    m.save(str(path))


def save_profile(flight: Flight, thermals: list[Thermal], path: str | Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    fixes = [f for f in flight.fixes if f.valid]
    times = [f.time for f in fixes]

    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(times, [f.alt for f in fixes], color="#2166ac", linewidth=1.5)
    ax.fill_between(times, [f.alt for f in fixes], color="#2166ac", alpha=0.1)
    for t in thermals:
        ax.axvspan(t.start, t.end, color="#e08214", alpha=0.25)

    ax.set_ylabel("Altitude (m)")
    ax.set_title("Profil d'altitude (zones orange = thermiques)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
