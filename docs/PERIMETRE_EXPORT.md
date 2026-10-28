# Périmètre du dossier exporté

## Inclus

Les nouveaux fichiers utiles des dossiers `tools`, `scripts`, des guides, des configurations de perception et de scénario, des modèles/mondes Gazebo, et les trois fichiers C++ de timeline dataset sont conservés dans l’overlay LOTUSim. Les nouveaux dossiers Unity, leurs `.meta`, les 29 prefabs ajoutés et les archives de provenance `ThirdParty` sont conservés dans l’overlay Unity.

Les modifications de fichiers existants sont fournies en patchs, avec leurs versions complètes dans `references/modified-sources/`. Le manifeste décrit précisément les fichiers et leurs empreintes. Les noms `LOTUSim` et `LOTUSim-Unity-modules` restent des conventions de raccord pour certains constructeurs Unity ; l’export n’a pas encore transformé ces scripts en package UPM indépendant.

## Exclusions volontaires

| Ensemble | Raison et récupération |
| --- | --- |
| `.git`, identifiants, fichiers `.env`, caches et métadonnées système | Aucun secret ni dépôt Git imbriqué n’est requis pour réutiliser le code. |
| `Library`, `Temp`, `Logs`, `.csproj` et caches de paquets Unity | Régénérés par le projet Unity complet et son verrou de dépendances. |
| `build`, `install`, journaux colcon et binaires du poste | À reconstruire pour la plateforme cible. |
| `.venv-vision`, roues et poids du détecteur | À installer/préparer séparément ; versions, révision et empreinte des poids documentées. |
| `artifacts` et corpus/galeries/rapports déjà générés | Volumineux et distincts des sources. Les résultats d’origine restent dans les dépôts de travail ; copier seulement les données choisies et autorisées. |
| Posters, pièces pédagogiques et fichiers personnels hors des dépôts | Hors du périmètre logiciel exporté ; ne pas les publier par accident. |
| `Assets/msgbrowser_settings.asset` | Préférence d’éditeur contenant un ancien chemin local ; listée dans l’inventaire Unity, inutile au runtime. |
| Sauvegardes `.bak`, fichiers `.partial`, `.pyc`, `.DS_Store` | Artefacts de travail, non nécessaires. |

La configuration JSON du pilote à deux images est reprise comme exemple explicite, sans ses résultats ni un manifeste de campagne ancien à réutiliser aveuglément.

## Préserver les dépendances et les notices

Les dépôts officiels complets ne sont pas dupliqués ici. Leur licence, leurs versions et les verrous requis sont conservés comme références, et l’installation complète part de clones aux commits indiqués. Les assets du socle (FREMM d’origine, environnement HDRP, terrain, audio, packages) restent dans ce socle.

Les modèles externes gardent leurs preuves, sources et attributions. Le dossier ne déclare pas que tout média est libre de toute restriction pour tout usage : consulter `ASSETS_ET_LICENCES.md`, notamment le signalement `noai` de l’oiseau Dayvable. Aucune licence globale nouvelle n’est imposée à cet assemblage.

Les guides historiques des composants conservent leur contenu technique ; leurs anciens chemins personnels vers les deux dépôts sont remplacés par `/chemin/projets/...` dans cette copie. Ces guides décrivent parfois des essais historiques : pour une nouvelle installation, commencer par les guides à la racine de `docs/` de cet export.

La copie exportée de `tools/ops_collector.py` comporte une adaptation isolée pour Python 3.9 : normalisation des fractions de seconde ISO avant lecture des horodatages Unity. Les tests contrôlent qu’un heartbeat à sept décimales reste récent. Cette adaptation ne retire aucune protection ni ne change les poses ; le fichier du projet de travail d’origine n’est pas modifié.
