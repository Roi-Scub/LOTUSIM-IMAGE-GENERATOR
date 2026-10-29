# Séquence multi-objets pilotée par LOTUSim

Ce mode est séparé du randomizer Unity autonome (menu 6). LOTUSim crée les
objets, évalue leurs trajectoires et déplace le bateau observateur. Unity
reçoit les poses ENU, charge leurs représentations visuelles, rend l'océan
HDRP et écrit les images et annotations. Aucun second contrôleur Unity ne
calcule les déplacements horizontaux des objets.

## Premier lancement

1. Quitter Play dans Unity. Si un simulateur est déjà lancé, l'arrêter proprement
   dans son terminal avant de recharger le module. Ne pas lancer deux mondes
   utilisant le namespace `/lotusim` dans le même domaine ROS.
2. Dans le devShell du conteneur, à la racine `/workspace`, compiler le module :

   ```bash
   source install/setup.bash
   colcon build --merge-install --packages-select lotusim_mas
   ```

3. Lancer le monde dédié, puis laisser actif le serveur ROS TCP habituel sur
   `127.0.0.1:10000` côté Mac. Le serveur ne lance pas lui-même le simulateur.

   ```bash
   mise run sim maritime_dataset.world
   ```

   Le monde reste nommé `lotusim`, donc les services restent sous `/lotusim`.
   Il utilise MAS, RenderPlugin et SceneBroadcaster, sans moteur de vol ni
   connexion XDyn. `--gui` permet d'observer les modèles et déplacements côté
   Gazebo si l'affichage du conteneur est disponible. L'affichage océanique
   réaliste et les captures de ce mode sont réalisés côté Unity.

4. Dans Unity : **LOTUSim > Dataset > 7 - Open multi-object sequence connected
   to LOTUSim**. Le menu crée les assets manquants et met à jour l'observateur
   de cette scène vers la FREMM, puis exporte le YAML et ouvre la scène dédiée.
   Il conserve la résolution, le rythme de capture et les anciens modes ; il
   ne remplace pas les autres scènes. Enregistrer les modifications avant ce menu.
5. Appuyer sur Play. Unity se connecte, vérifie le protocole du module LOTUSim
   **avant de créer le moindre objet**, puis lance `MaritimeRandomLotusim.yaml`,
   attend le premier instantané et commence les captures après le préchauffage
   de l'eau. Ne pas lancer ce scénario manuellement dans l'interface Web :
   cette campagne doit en acquérir la propriété en le lançant elle-même.
6. Ouvrir **Dataset > 4 - Campaign monitor** pour le suivi et la galerie.

Le conteneur doit monter le dépôt LOTUSim courant dans `/workspace`. Le menu
7 exporte dans le dépôt `LOTUSim` situé à côté du projet Unity. Les chemins
contenant des espaces sont supportés. Une installation à un autre emplacement
nécessite d'adapter ce chemin dans `DatasetLotusimSceneBuilder.ExportScenario`.

## Configuration

Les sept catégories de bateaux sont désormais activées dans la campagne
connectée, en plus des cinq catégories initiales : voir le
[guide de la bibliothèque marine](guide-bibliotheque-marine-unity.md).

- Unity : `Assets/Dataset/MaritimeRandomLotusim.asset` (asset indépendant,
  initialement copié de la configuration du randomizer autonome).
- Scène : `Assets/Scenes/Dataset/MaritimeRandomLotusim.unity`.
- LOTUSim : `assets/scenarios/MaritimeRandomLotusim.yaml`.
- Connexion : composant **Dataset Lotusim Source** sur `MaritimeRandomLotusim`
  dans la scène : adresse, port, namespace, timeout et fichier de scénario.

La configuration par défaut prévoit 60 secondes de temps de scénario, 30
étapes/s, une capture toutes les 5 étapes : **360 images**. Les distances,
altitudes, vitesses et contraintes du randomizer restent disponibles. Le cap
de déplacement du bateau est indépendant de la direction de regard.

### Houle évolutive et trafic maritime

La campagne contient maintenant **18 rencontres / 12 catégories** : les 11
rencontres initiales et un exemplaire de chacun des sept bateaux. Les positions,
instants de passage, distances, sens de traversée et vitesses sont tirés à partir
de `seed`. Un même seed rejoue le même plan ; changer cette valeur produit une
autre distribution. Les cibles restent en coordonnées du monde, pas attachées à
la caméra, et une enveloppe évite les intersections avec la route de la FREMM.

Dans la configuration connectée :

| Bateau | Distance au point de passage | Vitesse tirée, m/s |
| --- | --- | --- |
| Chalutier | 110–350 m | 2–4,5 |
| Porte-conteneurs | 650–1 400 m | 3–6 |
| Yacht | 120–400 m | 4–9 |
| Hors-bord | 100–320 m | 8–14 |
| Jetski | 75–230 m | 12–20 |
| Ferry | 400–900 m | 6–10 |
| Voilier | 110–340 m | 1,5–3,5 |

Ce sont des plages de génération cinématique, pas des performances certifiées
ni des vitesses de navigation recommandées en mer forte. Le cargo et le ferry
restent plus éloignés ; le jetski traverse plus rapidement. Tous les bateaux
reçoivent en plus la réponse visuelle amortie à neuf points de l'océan HDRP.

**Sea Evolution** remplace le tirage d'une mer éventuellement plate par une houle
continue, fortement variable : minimum 52 et maximum 95 km/h pour le vent HDRP,
bandes de houle 0,78–1, patch 384 m, modulation principale de 22 s et modulation
plus lente. Les transitions sont lissées, sans saut entre des préréglages. Ces
paramètres artistiques ne sont pas une hauteur significative de houle calibrée.
Chaque JSON d'image archive les valeurs de mer effectivement appliquées.
`unity_render_sea` documente ces paramètres côté YAML, mais ne pilote pas un
océan Gazebo : le rendu et la flottabilité de vague sont dans Unity.

Pour modifier : ouvrir `Assets/Dataset/MaritimeRandomLotusim.asset`, ajuster
**Sea Evolution**, **Classes**, **Observer Turn Deg** ou le seed, puis réexporter
avec le menu 8. La migration n'est appliquée qu'une fois ; les réglages suivants
sont conservés lors de la réouverture du menu 7.

### Jour, soirée et nuit lisible

La campagne connectée commence désormais **de jour**, puis passe en soirée et
en nuit de pleine lune. Elle ne tire plus un seul éclairage aléatoire pour toute
la série. Avec les réglages actuels (360 captures / 60 s de trajectoire) :

- images 1–120 : jour, temps de scénario 0–20 s ;
- images 121–240 : soirée, 20–40 s ;
- images 241–360 : nuit de pleine lune, 40–60 s.

Les changements sont des blocs de conditions expérimentales, pas une simulation
astronomique de 24 heures en une minute. Quelques rendus de stabilisation du ciel
et des réflexions sont effectués aux limites, sans avancer les objets ni perdre
de capture. Un autre nombre d'images est réparti aussi équitablement que possible
entre les trois phases ; au moins trois captures sont nécessaires.

Les réglages sont dans `MaritimeRandomLotusim.asset` → **Lighting** :
`cycleDayEveningNight`, `settleFrames`, puis `day`, `evening`, `night`.
Chaque profil règle la direction/hauteur de l'astre, l'intensité en lux,
la température de couleur et l'exposition fixe EV100. **Diminuer EV100 éclaircit
l'image**. Valeurs initiales : jour 80 000 lux / EV13, soirée 8 000 lux / EV9,
nuit 0,3 lux / EV−4. La lumière de lune est placée derrière et sur le côté de la
caméra pour éclairer les faces visibles des cibles. La nuit utilise une source directionnelle de type pleine lune
avec une exposition adaptée, pas un soleil diurne simplement étiqueté « nuit ».
Ces valeurs sont des choix de rendu, pas une calibration de caméra réelle.

L'éclairage qui forme les PNG est appliqué dans **Unity**, avec LOTUSim qui
conserve le contrôle des positions. Le YAML contient son calendrier sous
`unity_render_lighting` comme métadonnée de rendu ; Gazebo ne change pas son ciel
avec cette clé. Chaque JSON d'image contient le profil **effectivement appliqué**
(`light`, dont `illuminant` et `exposureEV100`), l'indice de phase et
`lightingTimeOfDay`. `events.json` archive le calendrier complet et son
identifiant est vérifié avec le reste du scénario.

Après cette mise à jour, quitter Play, ouvrir **Dataset > 7** une fois pour
activer les trois phases et réexporter le scénario, puis relancer Play.
Pas de recompilation du module Gazebo ni de redémarrage du serveur TCP pour ce
seul changement. Les anciennes images ne sont pas modifiées. Le mode Unity
autonome conserve son ancien comportement tant que ce cycle n'y est pas activé.

### Observateur FREMM

Le bateau `ObserverBoat` utilise le vrai maillage FREMM fourni dans les deux
projets, à son échelle d'origine (environ 142 m), pas un assemblage de cubes.
Le prefab Unity est `Assets/Prefabs/DatasetObserverFremm.prefab`, avec des
matériaux HDRP dérivés des matériaux importés. Côté LOTUSim,
`assets/models/fremm_observer/model.sdf` est une variante statique qui référence
le maillage `fremm/meshes/fremm.dae` ; le modèle FREMM d'origine reste inchangé.
Les deux représentations ont leur proue alignée avec le déplacement.

La caméra est maintenant à **hauteur de la passerelle de navigation**, en position
locale `(30,3 ; 12,4 ; −5,5)` m : X vers la proue, Y vers le haut, Z vers bâbord.
Le modèle est une coque visuelle sans intérieur de passerelle exploitable. Ses
vitres sont opaques dans cette chaîne : l'œil est donc juste devant la façade
vitrée inclinée, dont la position a été mesurée sur le maillage. Il regarde vers
l'avant, décalé de 15° vers tribord. Ce n'est pas une cabine intérieure avec
instruments modélisés. L'ancien point du pont avant reste configurable avec
`Observer Deck Offset M = (60 ; 8,85 ; −3)`.

La FREMM avance à 4 m/s et vire progressivement de **8° à bâbord sur 60 s**.
LOTUSim calcule l'arc et son orientation, et publie la vitesse tangente réelle.
En fin de trajectoire, le déplacement est environ 16,7 m vers la gauche et
239,2 m vers le nord. La caméra suit ce cap et est **réellement enfant du visuel
FREMM**, avec position et rotation locales constantes, sans stabilisation d'horizon.
Elle hérite du roulis, du tangage et du pilonnement. Le montage reste actif dans
l'aperçu après la fin de l'enregistrement ; le suivi ne s'arrête plus au dernier PNG.

Le gain angulaire visuel de l'observateur est de 1,8, limité à 7° de roulis et
4° de tangage pour rendre l'effet perceptible. Il agit sur le bateau entier,
pas sur une oscillation indépendante de caméra. Les angles atteints dépendent
des vagues ; les limites ne sont pas une amplitude imposée. Cette réponse reste
une approximation visuelle, pas une tenue à la mer calibrée.

Le montage est préparé avant que HDRP mémorise ses matrices de caméra. L'eau CPU
provient du rendu terminé précédent, ce qui est indiqué dans les métadonnées ;
le pont et la caméra utilisent le même échantillon pendant le rendu suivant.
Il n'y a pas de second contrôleur de la racine ROS.

Pour retrouver l'ancien point haut, désactiver **Observer Deck Camera** et régler
**Observer Height M** à 45. Les offsets et le regard restent configurables.

La FREMM est l'observateur, pas une classe cible de cette campagne. Son rendu
peut occulter une cible et cette occultation est prise en compte par la
profondeur de la caméra. Le modèle d'observateur et ses poses sont conservés
dans les instantanés `.lotusim.json`, et la hauteur caméra dans la configuration.

Après une modification de la configuration Unity, quitter Play puis utiliser
**Dataset > 8 - Export connected configuration to LOTUSim YAML**. Un identifiant
de plan vérifie la correspondance entre ce YAML et la configuration au lancement.
En cas de divergence, la campagne échoue explicitement plutôt que de produire
un corpus incohérent. Le menu refuse d'écraser un YAML qui ne porte pas son
marqueur de génération.

## Synchronisation et connexion unique

Le transport est le même `ROSConnection` singleton que le connecteur existant.
La scène dédiée ne contient ni Launcher, ni Photon, ni Leap, ni ancien
`LotusimInterface`. Elle refuse un deuxième connecteur ou un deuxième contrôleur.

```text
LOTUSim calcule l'étape N et lit les poses dans son ECM
    → réponse ROS au client Unity unique
    → application des poses, océan, rendu RGB et masques du même rendu
    → enregistrement, puis demande de l'étape N+1
```

Les échanges utilisent `lotusim_msgs/srv/String` : d'abord
`/lotusim/dataset_control` avec `{"operation":"capabilities"}`, puis
`/lotusim/launch_scenario`. Le contrôle porte ensuite les opérations JSON
`step`, `inspect` et `stop`. La vérification initiale est en lecture seule,
même si un autre scénario tourne. Les poses font partie des réponses du service : **l'absence
de lignes RegisterSubscriber(renderer_poses) n'est donc pas une panne dans ce
mode**. Les topics MAS `/lotusim/poses` et RenderPlugin restent disponibles pour
les autres outils. Une étape répétée est idempotente ; un saut ou retour en
arrière est rejeté. Les objets restent à leur pose lorsque Unity attend.

Le temps du scénario (`frame / fps`) est distinct de l'horloge globale Gazebo
et de celle de l'eau Unity. C'est un verrouillage des trajectoires cinématiques,
pas une synchronisation de toute la physique Gazebo. La durée réelle d'une
campagne dépend des performances de rendu et du débit ROS ; une séquence de
60 secondes peut demander davantage de temps à générer.

## Images et traçabilité

La campagne dispose maintenant de sorties RGB 4K, IR synthétique et vision
nocturne co-enregistrées : voir le
[guide des capteurs et de la galerie à 100 %](guide-capteurs-rgb-ir-vision-nocturne.md).

Sortie : `artifacts/dataset-lotusim/seq_<date>_<id>/` dans le projet Unity.

- `rgb/` : images sans annotation incrustée ; `overlays/` : aperçu annoté.
- `masks/`, `amodal/`, `labels/`, `annotations.coco.json` : exports existants.
- `annotations/fXXXXXX.json` : poses affichées, racines contrôlées par LOTUSim,
  identités persistantes, pose du bateau, temps et identifiants de campagne.
- `annotations/fXXXXXX.lotusim.json` : instantané ENU original reçu du simulateur.
- YAML demandé, configuration, événements planifiés et provenance archivés.

La flottabilité de la bouée ne modifie que son enfant visuel dans Unity ; les
poses racines LOTUSim et les poses visuelles sont distinguées dans les JSON.
Les petites oscillations de caméra restent également un effet d'océan Unity.
Les masques et boîtes décrivent la géométrie effectivement rendue, avec la
politique existante « eau occultante », pas une mesure de reconnaissabilité.

## Arrêt et diagnostics

La campagne n'arrête automatiquement que le scénario qu'elle a lancé, via son
jeton de session. Un scénario déjà actif entraîne un refus, sans arrêt forcé.
Un ancien jeton ne peut pas arrêter une nouvelle campagne. À la fin, les images
sont conservées même si le nettoyage n'est pas confirmé
(`complete_cleanup_unconfirmed`). Quitter Play tente un arrêt ciblé, mais une
coupure réseau ou un arrêt avant réception de l'accusé de lancement peut laisser
un scénario actif : vérifier LOTUSim avant de relancer.

Pour vérifier le module chargé :

```bash
ros2 service type /lotusim/dataset_control
ros2 service call /lotusim/dataset_control lotusim_msgs/srv/String '{data: "{\"operation\":\"capabilities\"}"}'
```

Si le service manque, le simulateur utilise encore l'ancien module : recompiler
puis relancer seulement le simulateur. Un simulateur suspendu qui ne traite plus
ses mises à jour ne peut pas répondre aux opérations différées.

La réponse attendue contient `schema: lotusim-dataset-capabilities-1`,
`snapshotSchema: lotusim-dataset-step-1`, `ownedStop: true` et
`steppedTimeline: true`. Le virage exige également
`constantTurnTrajectories: true` : un ancien module est refusé avant tout
lancement au lieu d'ignorer silencieusement le virage. L'ancienne réponse
**texte** `Scenario launched: …`
n'est pas un instantané JSON : elle indique qu'un ancien module est chargé.
La nouvelle vérification empêche ce lancement accidentel ; en cas d'autre
réponse invalide, le diagnostic indique l'étape et conserve la réponse dans
`lotusim-last-response.txt` à la racine du dossier de campagne.
Un scénario lancé avant ce correctif peut rester actif sans jeton de propriété :
le vérifier et l'arrêter explicitement ou redémarrer le simulateur, sans essayer
de l'arrêter automatiquement depuis un autre client.

Le serveur TCP peut journaliser `No more data available` lorsque Unity ferme
normalement sa connexion en quittant Play : vérifier d'abord le statut de la
campagne. Ce message après un statut `complete` n'annule pas les images écrites.

## Limites et suite

Validation de cette évolution : planification sur 100 seeds, huit captures de
test réparties sur les 60 s de trajectoire, 95 annotations couvrant les 12
catégories, cohérence COCO / masques / YOLO, arc et vitesses réels dans l'ECM,
montage caméra et sept réponses à la houle vérifiés. Le test utilise un domaine
ROS et un port dédiés ; il ne démarre ni n'arrête le simulateur de travail.

Les trajectoires sont cinématiques, à altitude constante pour les aéronefs de
cette première campagne ; ce n'est ni un modèle aérodynamique ni un modèle
hydrodynamique. Le bâtiment observateur est la FREMM, mais sa trajectoire reste
cinématique ; ce changement de modèle n'ajoute pas un moteur hydrodynamique.
Les vagues, la lumière et la flottabilité visuelle ne sont pas répliquées dans
Gazebo. Les capteurs d'annotation Gazebo sont un chantier distinct : ce mode
produit les annotations du rendu Unity.

Le mode d'écoute libre d'un scénario LOTUSim quelconque n'est pas encore livré :
cette version gère le scénario dédié et son catalogue connu. Le protocole de
poses et la séparation entre racine simulée et annotation rendent cette
extension possible sans réintroduire un deuxième pilote de déplacements.

Tests reproductibles côté devShell (domaines isolés, sans arrêt du simulateur
de l'utilisateur) : `tests/python/integration/test_dataset_connected.py --plugin-dir <libdir>`.
Le script de serveur `test_dataset_bridge_server.py` est réservé au banc de test
Unity isolé (domaine 97, port 10001), pas au lancement de production.
