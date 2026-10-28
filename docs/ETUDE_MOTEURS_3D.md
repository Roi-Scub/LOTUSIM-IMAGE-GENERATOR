# Choix du moteur 3D pour les images maritimes annotées

Comparatif au 27 octobre 2026 pour LOTUSim, la génération d'images et leurs annotations.
**Unreal dispose d'un préparateur de scène et d'aperçu RGB statique ; le portage
complet LOTUSim et la validation native restent à réaliser.**
Un changement de moteur ne se réduit pas au menu du dashboard : les scènes, matériaux,
vagues, captures et masques spécifiques à Unity doivent être réimplémentés.

## Comparatif

Les appréciations d'adéquation ci-dessous sont des choix d'ingénierie, pas des résultats
de benchmark. Les licences des modèles et textures restent distinctes de celle du moteur.

| Solution | Droits et coût du moteur | Intérêt pour le projet | Limite principale |
| --- | --- | --- | --- |
| **Unreal Engine** | Propriétaire, sources accessibles sous EULA. Gratuité conditionnelle ; usage commercial non-jeu interne concerné par les sièges : 1 850 USD par utilisateur et par an au-delà du seuil applicable de 1 M USD. | Candidat photoréaliste avec système Water, vagues et flottabilité. | Adaptateur LOTUSim et annotations à développer ; licence de l'organisme et matériel à valider. [Licence](https://www.unrealengine.com/license), [Water](https://dev.epicgames.com/documentation/unreal-engine/water-system-in-unreal-engine). |
| **Godot** | MIT, usage commercial autorisé ; pas de redevance moteur ni de seuil de chiffre d'affaires imposé par cette licence. Notices à conserver. | Alternative temps réel ouverte, adaptée à un prototype maîtrisé. | Océan, masques d'instance et rendu maritime réaliste à construire et mesurer. [Licence](https://godotengine.org/license/), [formats 3D](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/available_formats.html). |
| **Blender, Cycles ou EEVEE** | Blender sous GPL ; les images et fichiers de scène produits ne deviennent pas GPL du seul fait du rendu. Les obligations des scripts/add-ons distribués se traitent séparément. | Très bon candidat pour un corpus généré en différé : Python, rendu automatisé, profondeur, indices d'objet et Cryptomatte. | Rejouer les états LOTUSim ; ce n'est pas un remplacement direct de l'application Unity temps réel. [Licence](https://www.blender.org/about/license/), [FAQ](https://www.blender.org/support/faq/), [passes](https://docs.blender.org/manual/en/latest/render/layers/passes.html). |
| **O3DE** | Code sous Apache-2.0 ou MIT au choix, avec dépendances tierces à examiner. | Socle ouvert orienté simulation, avec Gems ROS 2. | Installation et intégration plus exigeantes ; macOS expérimental. Privilégier une évaluation Windows/Linux. [Licence](https://github.com/o3de/o3de/blob/development/LICENSE.txt), [ROS 2](https://docs.o3de.org/docs/user-guide/gems/reference/robotics/ros2/), [plateformes](https://docs.o3de.org/docs/welcome-guide/supported-platforms/). |
| **Isaac Sim et Replicator** | Code du dépôt Apache-2.0, mais Omniverse Kit, médias et composants NVIDIA ont d'autres conditions : la pile n'est pas entièrement sous cette licence. | Outils spécialisés de randomisation, segmentation, bounding boxes et liaison ROS 2. | Les exigences documentées reposent sur une station GPU NVIDIA ; pas une solution native pour ce Mac Apple Silicon. [Licence](https://github.com/isaac-sim/IsaacSim/blob/develop/LICENSE), [conditions complémentaires](https://www.nvidia.com/en-us/agreements/enterprise-software/isaac-sim-additional-software-and-materials-license/), [matériel](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html). |
| **UNIGINE Sim** | Propriétaire, offre Sim sur devis. L'édition Community exclut notamment la défense ; les conditions de recherche financée doivent être examinées. | Offre de simulation industrielle incluant eau, météo et interfaces de simulation. | Ce n'est pas une solution gratuite de substitution pour un contexte naval/défense. [Éditions et restrictions](https://unigine.com/get-unigine). |

Unity reste l'option demandant le moins de travail immédiat puisque l'océan, les
préfabriqués et les annotations existent déjà. Son éligibilité doit toutefois être
vérifiée pour l'organisme et la version utilisés ; les conditions industrielles ne
se déduisent pas de la seule licence Personal du compte. [Conditions Unity](https://unity.com/pages/license-compliance).

## Ce que l'on peut affirmer pour Unreal

L'architecture peut conserver le dashboard, les configurations, les meshes sources,
les trajectoires LOTUSim et les formats d'évaluation. Unreal possède des fonctions
de capture et d'identification d'objets qui rendent un adaptateur plausible. En revanche,
les Object IDs de Movie Render Queue sont documentés comme expérimentaux et réservés
à l'éditeur, pas aux builds shipping : un exécutable autonome peut nécessiter un autre
chemin de production des masques. [Passes Epic](https://dev.epicgames.com/documentation/unreal-engine/cinematic-render-passes-in-unreal-engine).

Les images rendues répondant à la définition de *Non-Engine Products* ne déclenchent
pas les royalties correspondantes. Cela n'exonère pas nécessairement des abonnements
par siège. Le statut étudiant ne suffit pas à qualifier un travail réalisé pour une
entreprise comme usage éducatif exempté ; faire confirmer le cas par l'organisme.
[EULA, sections 4 et 6](https://www.unrealengine.com/eula/unreal).

Pour UE 5.8 sur Mac, Epic recommande 32 Go et un Apple Silicon M3. Le ray tracing
matériel sur M2+ est expérimental ; Nanite sur M2+ est en bêta. Vérifier le couple
version moteur/macOS/Xcode avant installation, et ne pas transposer les capacités
d'une station Windows RTX à ce Mac. [Exigences macOS](https://dev.epicgames.com/documentation/unreal-engine/macos-development-requirements-for-unreal-engine).

## Adaptateur à réaliser

Chaque moteur doit charger les objets avec leurs identifiants et classes, convertir
unités et repères, appliquer les poses au temps simulé demandé, puis produire une
paire RGB/masques et ses métadonnées avec la même caméra. Il doit gérer la visibilité
par profondeur, l'occultation par l'eau et les autres objets, ainsi que l'exclusion
du bateau observateur. Les règles NR/PR/R restent comparables, mais leurs seuils
doivent être réévalués avec le nouveau rendu. Unreal utilise notamment les centimètres
et un repère Z vertical : recopier directement des poses ROS en mètres serait erroné.
[Repères](https://dev.epicgames.com/documentation/en-us/unreal-engine/coordinate-system-and-spaces-in-unreal-engine),
[unités](https://dev.epicgames.com/documentation/en-us/unreal-engine/units-of-measurement-in-unreal-engine).

La présence d'une intégration communautaire telle que
[rclUE](https://github.com/rapyuta-robotics/rclUE) ne prouve pas sa compatibilité avec
notre version ROS 2, notre Mac et LOTUSim. La voie exacte de transport et de synchronisation
doit faire partie du prototype.

## Recommandation

Si la priorité est la liberté d'usage, tester **Godot** pour le temps réel ou **Blender**
pour le rendu différé. Si la priorité est le rendu maritime et l'écosystème visuel,
tester **Unreal** après validation des droits et du matériel. Isaac Sim devient pertinent
si une station NVIDIA adaptée est disponible.

Avant toute migration complète : une bouée, un bateau, dix poses LOTUSim et dix paires
RGB/masque. Vérifier l'alignement, une occultation par le bateau et une occultation par
l'eau, puis comparer avec la chaîne Unity. La décision doit suivre ce démonstrateur,
pas seulement une comparaison de captures promotionnelles.
