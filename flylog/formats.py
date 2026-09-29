"""Export a flight to GPX (any GPS software) or KML (Google Earth, 3D track)."""

from __future__ import annotations

from xml.sax.saxutils import escape

from .parser import Flight
from .thermals import Thermal, detect_thermals


def to_gpx(flight: Flight) -> str:
    fixes = [f for f in flight.fixes if f.valid]
    name = f"Vol du {flight.date:%d/%m/%Y}" if flight.date else "Vol"
    points = "\n".join(
        f'      <trkpt lat="{f.lat:.6f}" lon="{f.lon:.6f}"><ele>{f.alt}</ele>'
        f"<time>{f.time:%Y-%m-%dT%H:%M:%SZ}</time></trkpt>"
        for f in fixes
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="FlyLog" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>{escape(name)}</name>
    <trkseg>
{points}
    </trkseg>
  </trk>
</gpx>
"""


def to_kml(flight: Flight, thermals: list[Thermal] | None = None) -> str:
    fixes = [f for f in flight.fixes if f.valid]
    thermals = detect_thermals(flight) if thermals is None else thermals
    name = escape(f"Vol du {flight.date:%d/%m/%Y}" if flight.date else "Vol")
    coords = " ".join(f"{f.lon:.6f},{f.lat:.6f},{f.alt}" for f in fixes)
    marks = "\n".join(
        f"""    <Placemark>
      <name>Thermique {i} : +{t.gain_m} m</name>
      <description>{t.avg_climb:.1f} m/s pendant {t.duration_s / 60:.1f} min, plafond {t.top_alt} m</description>
      <styleUrl>#thermal</styleUrl>
      <Point><altitudeMode>absolute</altitudeMode><coordinates>{t.lon:.6f},{t.lat:.6f},{t.top_alt}</coordinates></Point>
    </Placemark>"""
        for i, t in enumerate(thermals, 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{name}</name>
    <Style id="track"><LineStyle><color>ff0c59e8</color><width>3</width></LineStyle>
      <PolyStyle><color>400c59e8</color></PolyStyle></Style>
    <Style id="thermal"><IconStyle><color>ff0b9ef5</color>
      <Icon><href>http://maps.google.com/mapfiles/kml/shapes/triangle.png</href></Icon></IconStyle></Style>
    <Placemark>
      <name>Trace</name>
      <styleUrl>#track</styleUrl>
      <LineString>
        <extrude>1</extrude>
        <altitudeMode>absolute</altitudeMode>
        <coordinates>{coords}</coordinates>
      </LineString>
    </Placemark>
{marks}
  </Document>
</kml>
"""
