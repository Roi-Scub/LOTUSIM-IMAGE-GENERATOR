# Modifications Unity à réutiliser

Audit local du 27 octobre 2026. Les chemins ci-dessous sont relatifs au projet
Unity cible. L’export est un **overlay sur le projet LOTUSim Unity**, pas un
projet Unity autonome et pas encore un package UPM indépendant.

## Socle et versions constatés

- Dépôt de base : `naval-group/LOTUSim-Unity-modules`, commit
  `68e56588f5b469201fcb50a90b571e357a89ad9c`.
- Éditeur : Unity `2022.3.18f1` (`d29bea25151d`).
- HDRP/Core/ShaderGraph : `14.0.10` ; Addressables : `1.21.21` ; Cinemachine :
  `2.9.7` ; Input System : `1.7.0` ; Newtonsoft JSON : `3.2.1`.
- ROS TCP Connector et Robotics Visualizations : dépendances Git, révision
  verrouillée dans `Packages/packages-lock.json` :
  `c27f00c6cf750d2d0564349b3039d19aa3925e7c`.
- Sous-modules du socle, sans modification locale détectée :
  `ROS-TCP-Endpoint` à `34dd958d1f9ed75c4fa119ccf5ebcb00075caa12`,
  `custom-hdrp` à `a47232071f053db4e609737a84b9d8a16c2fe681`.

Conserver les manifestes de paquets et les verrous du socle ; une version plus
récente du connecteur n’est pas réputée équivalente sans test du protocole.
Les scripts partagent encore l’assemblage Unity `Assembly-CSharp` avec des types
du projet de base. Les déplacer directement dans une autre `asmdef` casserait
cette dépendance : une extraction UPM exige d’abord des interfaces/assemblages
communs et des points d’extension explicites.

## Nouveaux fichiers réutilisables

Copier les dossiers complets suivants **avec leurs `.meta`**, y compris les
`.meta` des dossiers parents :

| Chemin Unity | Rôle |
| --- | --- |
| `Assets/Scripts/Dataset/` | Captures, annotations visibles/amodales, reconnaissance géométrique, réponse aux vagues, capteurs synthétiques, protocole LOTUSim, campagnes manuelles |
| `Assets/Editor/` | Constructeurs/importeurs, tests, outils de validation RGB, télémétrie locale |
| `Assets/Resources/Dataset/` | Shaders de masques et de capteurs chargés via `Resources.Load` |
| `Assets/Dataset/` | Configurations, plans compilés, matériaux du bateau observateur |
| `Assets/Scenes/Dataset/` | Scènes dédiées de génération et de validation |
| `Assets/Scenes/Models/` | Scènes de présentation/inspection des bibliothèques |
| `Assets/models/buoy/`, `aerial_library/`, `marine_library/` | Maillages, matériaux et textures procéduraux |
| `Assets/models/open_boats/`, `open_objects/` | Adaptations des modèles externes et crédits |

Inclure également les **29 nouveaux prefabs** de `Assets/Prefabs/` et leurs
`.meta`, notamment les deux observateurs, bouées, aéronefs et variantes de
navires. Inclure les nouveaux messages `LogMsg.cs`, `PowerStatusMsg.cs` et
`WaypointFollowerStatusMsg.cs` de `Assets/RosMessages/Lotusim/msg/`, avec leurs
`.meta`. Les modèles et les preuves de provenance restent associés : voir
`ASSETS_ET_LICENCES.md`.

À la date de l’audit, la sélection « nouveaux Assets + 15 fichiers suivis
modifiés + leurs métadonnées » représente environ **428 Mio** hors `ThirdParty`.
Les assets importés sont déjà présents : il n’est pas nécessaire de relancer les
constructeurs de bibliothèque pour ouvrir les scènes. Les constructeurs restent
utiles pour les reproduire ou modifier les modèles.

## Fichiers déjà présents : appliquer par groupes cohérents

L’état local comporte 15 fichiers suivis modifiés. Ils n’ont pas tous le même
rôle ; ne pas appliquer les réglages de poste indistinctement à une installation
existante.

### Intégration ROS et compatibilité des messages — 7 fichiers

| Fichier | Modification et raison |
| --- | --- |
| `Assets/Resources/ROSConnectionPrefab.prefab` | Boucle locale par défaut, connexion automatique désactivée et TF désactivé ; la source/configuration possède l’ouverture explicite |
| `Assets/RosMessages/Lotusim/msg/MASCmdMsg.cs` | Champ `sdf_file` ajouté dans l’ordre sérialisé attendu côté ROS |
| `Assets/RosMessages/Lotusim/msg/VesselPositionMsg.cs` | Champ `model_name` ajouté ; évite un décalage de désérialisation |
| `Assets/Scripts/lotusim_interface/InterfaceFactory.cs` | Création séparée de l’initialisation, namespace fourni une seule fois |
| `Assets/Scripts/lotusim_interface/LotusimConnector.cs` | Chargements de prefabs dédoublonnés, erreurs explicites, réponse visuelle aux vagues sans deuxième propriétaire de la pose |
| `Assets/Scripts/lotusim_interface/ROS2_interface/RosInterface.cs` | Abonnements idempotents, pas de `remove_subscriber` incompatible avec l’endpoint utilisé |
| `Assets/Scripts/lotusim_interface/ROSConnectionConfigurator.cs` | Réutilisation d’une connexion persistante et ouverture gardée par `HasConnectionThread` |

Ne pas panacher des messages générés anciens avec de nouveaux `.msg` côté
LOTUSim : vérifier les définitions et l’ordre des champs sur les deux côtés.
Le mode dataset dédié utilise sa propre source à pas acquittés et ne doit pas
cohabiter avec un ancien `LotusimInterface` consommant les mêmes poses.

### Affichage historique via Addressables — 1 fichier

`Assets/AddressableAssetsData/AssetGroups/SpawnInterface.asset` ajoute les modèles
aux adresses de génération historique. Utile à `defenseScenario` ; les scènes de
dataset référencent directement leurs prefabs et ne nécessitent pas ce mécanisme
pour chaque image. Préserver les schémas et réglages Addressables du socle.

### Navigation interactive / Launcher — 5 fichiers optionnels

- `Assets/Scripts/MultiUser/Launcher.cs` : propriétaire unique des callbacks,
  connexion spectateur automatique et conservation de l’adresse ROS configurée.
- `Assets/Scripts/camera/CameraDynamicTargetsNavigator.cs` : découverte des cibles
  ajoutées et suivi continu d’un modèle mobile.
- `Assets/Scenes/Launcher.unity` ; `Assets/Scenes/MultiUser/Launcher.unity` ;
  `Assets/Scenes/Defense/defenseScenario.unity` : scènes interactives associées.

Ces fichiers ne sont pas nécessaires à la scène dataset dédiée. Les conserver
comme option permet de ne pas imposer Photon, Leap/XR ou le Launcher à un flux de
génération automatisé. Ils comportent davantage de références aux assets du
projet d’origine : personnages, caméras, polices, panneaux et environnement.

### Réglages locaux — 2 fichiers, non applicables par défaut

- `Assets/XR/XRGeneralSettingsPerBuildTarget.asset` désactive le démarrage XR sur
  ce poste : option desktop, pas un prérequis universel de la bibliothèque.
- `Assets/msgbrowser_settings.asset` contient un **chemin absolu de poste** vers
  `interfaces/lotusim_msgs/msg`. Ne pas le recopier tel quel : reconfigurer le
  navigateur de messages avec le chemin de la nouvelle machine.

## Fermeture des références GUID : dépendances du socle

L’audit des nouveaux fichiers YAML Unity, rapproché des `.meta` du projet et des
paquets locaux, n’a trouvé **aucun GUID non résolu**. Cela ne signifie pas que
l’overlay est autonome. Les nouveaux assets référencent encore directement :

- `Assets/Settings/HDRP High Fidelity.asset` ;
- `Assets/Settings/SkyandFogSettingsProfile.asset` ;
- `Assets/models/boat/fremm.dae` ;
- `Assets/IslandTools/Environment/Terrain/Terrains/Terrain 3.asset` pour certaines
  scènes pilotes ;
- `Assets/Audio/Music/ES_Underwater Ambience 4.mp3` pour certaines scènes pilotes ;
- les scripts d’interface d’origine, présents dans le groupe de correctifs ROS.

Ces dépendances doivent rester disponibles dans le **projet officiel de base**.
Elles ne doivent pas être déclarées nouvelles créations de ce travail ni être
recopiées dans une bibliothèque d’assets « CC BY » par simple association.
Leurs dépendances transitives et les paquets Unity restent à la charge du socle.
Les appels `AssetDatabase.LoadAssetAtPath`, `Shader.Find("HDRP/Lit")`,
`Shader.Find("HDRP/Unlit")` et `Resources.Load` ajoutent des dépendances textuelles
qui ne sont pas, elles, un lien GUID. Conserver les chemins des dossiers et les
shaders ; vérifier aussi l’inclusion de shaders lors d’un futur build joueur.

## Cache du connecteur : vérification ciblée

La correction anti-double-client constatée est dans les fichiers suivis du
projet, **pas dans un patch caché de `Library/PackageCache`**. Le `Connect()` du
connecteur installé reste non idempotent ; c’est le configurateur qui évite un
second appel, avec `ConnectOnStart=false`. Les sources du package ont les dates
de l’import initial du 2 octobre ; aucun fichier plus récent ni patch local de ce
package n’a été trouvé. Les deux sous-modules inspectés sont propres.

Il s’agit d’une vérification locale du contenu et des dates, pas d’une nouvelle
comparaison octet-à-octet avec le serveur Git. Pour une certification de
reconstruction, retélécharger la révision verrouillée dans une installation
isolée et comparer les empreintes. **Ne jamais exporter tout `Library/`** pour
« conserver la correction ».

## Préconditions d’installation et validation

1. Appliquer l’overlay hors Play sur un clone sauvegardé du bon socle, en
   conservant les chemins et GUID ; examiner les correctifs suivis par groupe.
2. Utiliser Linear Color Space et définir `ROS2` pour la cible. Vérifier HDRP
   Water, CPU Script Interactions et Custom Pass. Ces options sont activées dans
   l’asset HDRP constaté ; elles ne sont pas remplacées globalement par l’export.
3. Disposer les deux projets en dossiers voisins nommés `LOTUSim` et
   `LOTUSim-Unity-modules`. Plusieurs constructeurs calculent encore `CoreRoot`
   ainsi. L’observateur RGB attend l’environnement Python `.venv-vision` du cœur,
   à reconstruire ; ne pas recopier un environnement virtuel de la machine.
4. Installer/reconstruire les modules LOTUSim correspondants et l’endpoint ROS
   compatible. Une source unique lance son scénario, acquitte chaque pas puis
   n’arrête que le scénario dont elle possède le jeton.
5. Faire un test court de 2–3 images, puis contrôler RGB, masques, annotations,
   exclusion du bateau et fermeture du scénario avant une grande campagne.

Les campagnes manuelles importent explicitement le `manifest.json` préparé par
le dashboard, génèrent une nouvelle scène et des images indépendantes. Ne pas
confondre ce fonctionnement avec une séquence vidéo continue. Les tests de code
et compilations ne remplacent pas cette vérification sur le GPU cible.

À exclure de l’overlay : `.git`, `Library`, `Temp`, `Logs`, `UserSettings`,
`artifacts`, dumps `mono_crash*`, `.DS_Store`, environnements Python, caches de
modèles et données personnelles. Conserver séparément les licences et preuves de
provenance, plutôt que les caches de compilation ou de téléchargement.
