# LOTUSIM Image Generator

Génération d’images maritimes annotées avec LOTUSim, ROS 2 et Unity HDRP.
Une orchestration d’agents logiciels prépare les scénarios, coordonne les objets
et contrôle les trajectoires. Le dashboard local regroupe leur suivi, les réglages
de capture et la revue des images RGB, indépendante des annotations du simulateur.

Ce dépôt est une extension de [LOTUSim](https://github.com/naval-group/LOTUSim),
pas une distribution officielle de Naval Group.

[Version 1.0.0](https://github.com/Roi-Scub/LOTUSIM-IMAGE-GENERATOR/releases/tag/v1.0.0)
· [Documentation](docs/README.md) · [Contribuer](docs/CONTRIBUTION.md)
· [Changelog](CHANGELOG.md)

## Orchestration agentique

Le système répartit le travail entre des agents spécialisés. Pour les campagnes
coopératives, l’orchestrateur part d’une configuration, d’un catalogue de modèles
et d’une graine pour construire un plan de scène contrôlé avant son exécution.

| Agent ou étape | Rôle |
| --- | --- |
| `CatalogueAgent` | Valide les effectifs, capacités, vitesses et contraintes météo |
| `ObserverAgent` | Réserve la trajectoire du bateau observateur |
| `BuoyAgent`, `SeaTrafficAgent`, `AirTrafficAgent`, `FastDroneAgent` | Proposent les placements et trajectoires de chaque objet |
| `SafetyAgent` | Contrôle les séparations et les priorités ; les agents révisent les propositions conflictuelles |
| `DirectorAgent` | Vérifie le passage nominal des objets dans le champ de la caméra |
| Préparateur du moteur | Planifie le paquet, sélectionne le constructeur Unity/Unreal ou l’export neutre, puis vérifie les fichiers et leurs empreintes |
| Observateur RGB | Analyse les images sans annotations en entrée de détection et produit les rapports de comparaison |

Dans la chaîne connectée Unity, LOTUSim exécute le plan et transmet les poses via
ROS 2 après import et lancement de la scène. Les agents de préparation respectent
les capacités de l’adaptateur choisi :
préparer un bundle Unreal ne lance pas une simulation connectée.

Les états sont suivis dans **Agents & chaîne**. Plans, messages de négociation,
rapports de contrôle et empreintes permettent de relire les décisions et de
reproduire un scénario à configuration, catalogue et version de code identiques.
Ces agents sont déterministes, sans LLM ni service distant ; les trajectoires sont
planifiées avant lancement, pas renégociées face à un nouvel obstacle en cours de rendu.

Voir le [fonctionnement des agents de trafic](components/LOTUSim/docs/guide-trafic-agentique-lotusim-unity.md#réseau-dagents--fonctionnement-réel-de-cette-v1)
et les [plans coopératifs](docs/PLANS_COOPERATIFS.md).

## Démarrage rapide

Python 3.9+ et un navigateur suffisent pour le dashboard, sous macOS ou Linux :

```bash
git clone https://github.com/Roi-Scub/LOTUSIM-IMAGE-GENERATOR.git
cd LOTUSIM-IMAGE-GENERATOR
python3 scripts/verify_export.py
python3 scripts/start_dashboard.py --no-docker
```

Ouvrir <http://127.0.0.1:8766/>. Le serveur reste sur la machine locale. Cette
commande ne lance ni simulation ni moteur 3D ; Unity, ROS et Docker ne sont pas
nécessaires pour préparer une configuration.

Pour produire des images, suivre l’[installation complète](docs/INSTALLATION_COMPLETE.md).
Il faut les deux projets de base compatibles, leurs dépendances et les correctifs
de ce dépôt. `components/LOTUSim-Unity-modules/` n’est pas un projet Unity autonome.
La configuration de référence utilise Unity **2022.3.18f1**, HDRP **14.0.10**,
ROS 2 **Jazzy** et Gazebo **Harmonic**.

## Générer une campagne

1. Dans **Modèles 3D**, consulter la bibliothèque ou importer un mesh statique.
2. Dans **Paramétrage**, définir objets, distances, caméra, météo et budget d’images.
   Pour une scène continue, choisir un plan dans **Trafic coopératif** et régler
   la cadence des photos en secondes simulées.
3. Préparer le bundle, puis l’importer dans Unity, hors Play. Démarrer ensuite la
   scène avec LOTUSim et le ROS TCP Endpoint prêts.
4. Consulter les RGB, annotations et galeries dans **Campagnes & rapports**.
   La revue RGB optionnelle analyse les images sans cadres dessinés.

Commencer par deux images avant une campagne longue. Le dashboard prépare et
observe les sessions ; il ne déclenche pas Play.

## Fonctionnement

- **LOTUSim / Gazebo** : entités et trajectoires, avec poses acquittées par ROS 2.
- **Unity** : rendu maritime, caméra embarquée, captures et annotations issues du
  même rendu : masques, boîtes, classes, visibilité et exports JSON/COCO/YOLO selon le pilote.
- **Python** : configurations, plans coopératifs, bibliothèque SQLite et analyse
  locale Grounding DINO. Gazebo Transport peut relayer les images ; ce n’est pas
  lui qui reconnaît leur contenu.
- **Autres moteurs** : Unreal dispose d’un prototype d’aperçu RGB statique,
  sans connexion LOTUSim, houle ni annotations. Godot, Blender, O3DE et les profils
  personnalisés exportent seulement un contrat de scène. Voir les
  [adaptateurs](docs/ARCHITECTURE_MULTI_MOTEURS.md).

La houle, la flottabilité et les modes IR/nocturne restent des approximations
visuelles. Les statuts NR/PR/R sont des heuristiques de reconnaissabilité ; les
scores du détecteur ne sont pas des probabilités calibrées. Les contrôles de
trafic ne constituent pas une certification COLREG.

## Modèles 3D et crédits

**Gabriel Ricardon (Roi-Scub)** : bouée instrumentée (`buoy`), drone
(`small_drone`, variante `drone_racer_sim`), hélicoptère (`helicopter`), avion léger
(`airplane`), goéland (`seagull`), chalutier (`fishing_trawler`), porte-conteneurs
(`container_ship`), yacht (`motor_yacht`), hors-bord (`speedboat`), jetski (`jetski`),
ferry (`ferry`), voilier (`sailboat`) et bateau observateur simplifié (`dataset_observer`).
Leurs géométries, textures et matériaux originaux sont proposés sous **CC BY 4.0** :
réutilisation avec attribution. Le [périmètre de cette licence](docs/LICENCE_ASSETS.md)
exclut les modèles tiers et les ressources des moteurs.

Les variantes externes conservent leurs auteurs et leur licence **CC BY 4.0** :

| Modèle | Œuvre et auteur | Source |
| --- | --- | --- |
| `speedboat_zefiro` | ZEFIRO — angelo raffaele catalano | [Sketchfab](https://sketchfab.com/3d-models/zefiro-5c29921a556346f09684eadfbc51a91d) |
| `rib_assault` | Assault Boat — tnnv | [Sketchfab](https://sketchfab.com/3d-models/assault-boat-0d4fca4f2e014cd7b6aefd4653b1508c) |
| `motor_yacht_35` | motoryacht 35 — angelo raffaele catalano | [Sketchfab](https://sketchfab.com/3d-models/motoryacht-35-0bdd7a0de7254426890bb5745bb7da6d) |
| `jetski_seadoo_gti` | 2012 Sea-Doo GTI SE 130 — BoatUS Foundation | [Sketchfab](https://sketchfab.com/3d-models/2012-sea-doo-gti-se-130-d7b3e903d7dc43a694720bd347f4fadf) |
| `cabin_cruiser_minnow` | SS Minnow III — gogiart | [Sketchfab](https://sketchfab.com/3d-models/ss-minnow-iii-a2aa3f9dc66446a4b2c275b9380fc41e) |
| `rib_zodiac` | Zodiac boat — RedC130 | [Sketchfab](https://sketchfab.com/3d-models/zodiac-boat-a10b7997f1514bd7829ece74f68c681c) |
| `buoy_navigation_ozzy` | Buoy — OzzyDan | [Sketchfab](https://sketchfab.com/3d-models/buoy-8e0584c27c37417f925c6be4ff7c6d13) |
| `drone_amvlab` | drone amvlab — AMV Lab | [GitHub](https://github.com/amvlab/aircraft-models) |
| `helicopter_utility_gb` | Helicopter — Gigantic Burger | [Sketchfab](https://sketchfab.com/3d-models/helicopter-ef70283b1dea4ae8b18eec9231ce390e) |
| `airplane_a320` | airplane a320 — AMV Lab | [GitHub](https://github.com/amvlab/aircraft-models) |
| `airplane_c172` | Cessna 172 — Nobilis the Palaeovespa, aussi crédité e737 dans le miroir | [Sketchfab](https://sketchfab.com/3d-models/cessna-172-64cddaee5aff470682659a8c08525046) |
| `seagull_dayvable` | Seagull — Dayvable ; adaptation FBX/rig par viniciusbarros | [Sketchfab](https://sketchfab.com/3d-models/seagull-dc42ffc81c86480e9e7f7752fa134174) |
| `speedboat_smolbot` | Boat — Nicosama, selon la preuve créateur archivée | [Sketchfab](https://sketchfab.com/3d-models/boat-dc676eac5985450a9271f9b31eb47778) |
| `speedboat_racing` | Boat — milamila | [Sketchfab](https://sketchfab.com/3d-models/boat-bd6166ae8e294bd4a7d4e46be7f80f5d) |

Merci également à [bob6664569 / open-water](https://github.com/bob6664569/open-water),
[srcejon / sdrangel-3d-models](https://github.com/srcejon/sdrangel-3d-models),
[AMV Lab](https://github.com/amvlab/aircraft-models),
[bilawalsidhu / gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view) et
[viniciusbarros](https://github.com/viniciusbarros/msc_game_obstacle_course)
pour les sources ou conversions intermédiaires. Les fichiers sources, commits,
empreintes et adaptations sont conservés dans
[OpenBoats](components/LOTUSim-Unity-modules/ThirdParty/OpenBoats/manifest.json)
et [OpenObjects](components/LOTUSim-Unity-modules/ThirdParty/OpenObjects/manifest.json).

La FREMM et les autres modèles historiques, notamment LRAUV et x500, viennent du
socle LOTUSim et de ses fournisseurs : leurs notices restent applicables.
`fremm_observer` / `DatasetObserverFremm` sont des adaptations, pas une nouvelle
géométrie.
Le goéland Dayvable porte une mention **NoAI** à clarifier avant usage pour
l’entraînement ou diffusion d’un corpus. Voir les [licences et réserves](docs/ASSETS_ET_LICENCES.md).

## Développement

`main` est la branche de référence. Les sources portables sont dans `components/`,
les modifications du socle dans `patches/` et leurs copies dans `references/`.
Les clones complets exécutés sous `runtime/`, résultats, bases locales et poids IA
ne sont pas versionnés. Une modification ici ne redéploie pas les services ouverts.

Les [conventions](docs/CONVENTIONS_CODE.md) et le [guide de contribution](docs/CONTRIBUTION.md)
donnent les commandes de test, de formatage et de mise à jour de l’inventaire.
Le code reste sous [EPL-2.0](LICENSE) ; les médias gardent leurs licences propres.
