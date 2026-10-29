# Journal des versions

## Non publié

- README et navigation documentaire recentrés sur l’installation et l’utilisation depuis `main`.
- Guides d’import regroupés ; notes d’export et de migration devenues redondantes retirées.
- Crédits des 14 modèles externes ; médias originaux de Gabriel Ricardon proposés sous CC BY 4.0, sans changement des licences tierces ni du code EPL-2.0.

## 1.0.0 du 29 octobre 2026 — Official Release

Première version majeure officielle du projet **LOTUSIM Image Generator**.
Il s’agit de la livraison de ce projet d’intégration, pas d’une version officielle
du simulateur LOTUSim publiée par Naval Group.

### Fonctionnalités livrées

- Dashboard local de supervision, journal, alertes regroupées et paramétrage des campagnes.
- Intégration LOTUSim/ROS2 et rendu Unity, capture RGB et annotations géométriques avec visibilité, occultation et statuts NR/PR/R.
- Bibliothèques d’objets maritimes et aériens, import de modèles depuis le dashboard et réponses visuelles à la houle.
- Scénarios coopératifs, bibliothèque de plans SQLite, édition de trajectoires et captures à cadence configurable.
- Analyse RGB indépendante, exclusion du bateau observateur et rapports de comparaison.
- Registre multi-moteur, contrats de scène et préparation de fichiers Unity/Unreal, avec capacités et limites explicites.
- Installation contrôlée sur des dépendances épinglées, documentation et inventaire SHA-256.

### Architecture et maintenabilité

- Conventions et formateurs épinglés pour Python, JavaScript, HTML/CSS, C#, C++ et HLSL.
- Sources dépliées et indentées, sans renommage des contrats applicatifs ou Unity.
- Tests d’inspection des sources rendus indépendants des espaces et retours à la ligne.
- Sources de référence et correctifs d’installation synchronisés avec le code formaté.
- Paquet Python structuré en sept domaines ; état de supervision et sécurité des rapports séparés du serveur HTTP.
- Frontend rangé par fonctionnalités, avec URL publiques conservées et liste de ressources explicite.
- Tests Python, Web, C++ et QA sortis de `scripts/` ; lanceur commun et contrôles des dépendances entre domaines.
- Équations de trajectoire partagées par planificateur et éditeur ; provenance couvrant les deux sources.
- Modules Unity regroupés par domaine : 84 sources et leurs `.meta` déplacées ensemble, sans changement des types ni des assemblages.
- Vérification des GUID, des dossiers Editor et des chemins Resources ; compilation hors éditeur adaptée aux déplacements et compatibilité des deux emplacements de l’importeur.
- Sources figées par le tag annoté `v1.0.0`, sans déploiement du runtime.

### Vérifications

- 725 tests applicatifs Python et 52 tests d’outillage réussis ; 14 suites Web exécutées.
- Compilation hors éditeur des 90 sources C# portables avec les références Unity installées.
- Conservation du contenu des 1 850 fichiers d’assets Unity d’origine ; 84 paires source/`.meta` réorganisées et 985 GUID uniques contrôlés.
- Pré-vérification de l’installateur sur deux clones temporaires propres aux commits de base épinglés.

### Périmètre et limites

Cette livraison contient les sources portables, correctifs, modèles sélectionnés
et notices. Elle n’inclut pas les projets complets sous `runtime/`, les poids IA,
conteneurs, images générées, bases de travail ou exécutables compilés. Les
licences et attributions des composants restent distinctes.

Unity conserve la chaîne de génération existante. Unreal reste un prototype
d’aperçu RGB statique, sans parité ROS, houle ou annotations ; les autres profils
nécessitent leur adaptateur natif. Les contrôles COLREG restent partiels et non
certifiants. La houle, la météo et les modes spectraux sont des approximations,
pas des capteurs physiques calibrés. La compilation hors éditeur ne constitue
pas une validation de rendu GPU ou une exécution des tests Play.

## 0.3.0 du 28 octobre 2026

- Centre d’alertes local avec regroupement par source, déduplication et filtre de
  gravité, sans notifications système ni réactivation d’anciens échecs archivés.
- Détails moteur et contrôles de trafic repliables ; erreurs de validation
  conservées près des actions et nouvel échec d’audit affiché automatiquement.
- Journal avec suspension de l’affichage indépendante de la collecte, compteur de
  nouveaux événements, suivi corrigé et export JSON des événements filtrés.
- Fenêtre de 80 événements et provenance de l’export explicites ; conservation de
  la position de lecture et absence de reconstruction pour de simples changements
  d’identifiants du producteur.
- Exclusion des résultats de QA navigateur du suivi Git et de l’inventaire
  portable ; les scripts de test et les assets sources restent versionnés.

## 0.2.0 du 28 octobre 2026

- Cadence des scénarios continus au choix : nombre de prises ou intervalle en
  secondes simulées, avec première prise à zéro et fin de scène exclue.
- Calendrier compilé sur les frames moteur, temps demandés et effectifs,
  quantification documentée et limite de 2 000 captures.
- Réglages dans Paramétrage et Trafic coopératif, aperçu du nombre de prises,
  conservation en bibliothèque SQLite et validation des empreintes du calendrier.
- Importeur Unity explicite des bundles contrôlés : nouvelle scène et nouveaux
  assets, calendrier `captureFrames` appliqué, originaux et rapport de dérivation
  conservés, sans lancement automatique du moteur ou de Play.
- Compatibilité conservée pour les plans antérieurs et les campagnes d'images
  indépendantes ; une cadence explicite remplace les rafales héritées.

## 0.1.0 du 28 octobre 2026

Première version portable de LOTUSIM Image Generator. Le code existant est importé
dans des commits thématiques à la date d'import. Ces commits ne reconstituent pas
artificiellement les dates ou les états intermédiaires du développement précédent.

### Fonctionnalités

- Raccord LOTUSim et ROS2, corrections de connexion Unity et timeline cinématique.
- Capture RGB Unity, annotations, visibilité, occultation, statuts NR, PR et R.
- Bibliothèques de bouées, aéronefs et navires, réponses visuelles à la houle,
  éclairages et notices de provenance.
- Chaîne indépendante d'analyse RGB, exclusions de l'observateur et rapports.
- Dashboard local, télémétrie, prévisualisation, paramètres des campagnes et galerie
  de meshes avec import automatique dans Unity.
- Registre de moteurs, contrat de scène commun et préparateurs Unity et Unreal.
- Scénarios coopératifs, contrôles de séparation et de rencontres limités,
  bibliothèque SQLite, édition et réaudit de révisions immuables.
- Installateur d'intégration avec dépendances épinglées, correctifs séparés,
  lanceurs locaux, tests, guides et manifeste SHA-256.

### Périmètre

Le dépôt contient les sources portables et les assets sélectionnés, pas les clones
complets des moteurs, caches, conteneurs, résultats ni bases SQLite de travail.
Les licences et attributions des composants restent distinctes.

Unity conserve sa chaîne existante. Unreal est un prototype d'aperçu statique ; les
autres profils exportent un contrat neutre et nécessitent un adaptateur natif.
Les contrôles COLREG sont partiels, non certifiants, sans navigation réactive.
Les rendus météo, thermiques et les réponses visuelles à la mer restent des
approximations de simulation, pas des mesures calibrées.
