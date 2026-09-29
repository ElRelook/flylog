# Changelog

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versions selon [SemVer](https://semver.org/lang/fr/).

## [0.2.0] - 2026-09-29

### Ajouté
- **Pilotage** : temps en virage, virages à gauche ou à droite, finesse sol en transition, facteur de charge estimé.
- **Vent estimé** à partir de la dérive en thermique.
- **Score type XContest** : distance libre à 3 points, triangle plat, triangle FAI.
- **Espaces aériens** : lecture OpenAir (format étendu `AY`) et détection des pénétrations. Classes E et G et secteurs vol à voile ignorés par défaut (`--all-airspaces`).
- **Moments forts** : plus forte montée, plus forte descente, vitesse max, facteur de charge, spirales.
- Exports **GPX** et **KML** (Google Earth 3D).
- **Incrustation vidéo** `flylog overlay` : ProRes 4444 ou VP9 transparent, calé sur l'heure de tournage d'un clip.
- Carnet : **noms des sites de déco** (ParaglidingEarth, cache local), colonne score.
- Interface web :
  - panneaux Pilotage, Score (tracé sur la carte) et Moments forts ;
  - vérification des espaces aériens ;
  - rejeu animé, exports et **image à partager** ;
  - carnet : **carte des thermiques de tous les vols**, progression, objectif annuel, badges et **comparaison de deux vols** ;
  - **carnet de démo** (`?demo=carnet`) et vol d'exemple (`?demo=vol`).
- **Application installable (PWA)** : hors ligne, « Partager vers FlyLog » sur Android, ouverture des `.igc`.
- CI : ruff, mypy et couverture de tests. Publication PyPI (`flylog-igc`) à chaque release.

### Corrigé
- Service worker : une requête réussie échouait si l'écriture en cache était impossible.

## [0.1.0] - 2026-09-29

### Ajouté
- Lecture des fichiers IGC, statistiques de vol, détection des thermiques.
- Carte interactive et profil d'altitude.
- Interface web avec Pyodide, carnet de vol synchronisé avec le dossier Syride.

### Corrigé
- Sauts d'horloge GPS pris pour un passage de minuit (vol de 27 h au lieu de 3 h).
- Thermiques coupés en plusieurs morceaux par une courte baisse du vario.
- Fonds de carte OpenStreetMap refusés (403) dans une carte ouverte en fichier local.

[0.2.0]: https://github.com/ElRelook/flylog/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ElRelook/flylog/releases/tag/v0.1.0
