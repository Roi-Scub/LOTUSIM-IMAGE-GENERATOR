# Journal des versions

## Refactorisation en revue

- Conventions et formateurs épinglés pour Python, JavaScript, HTML/CSS, C#, C++ et HLSL.
- Sources dépliées et indentées, sans renommage des contrats applicatifs ou Unity.
- Tests d’inspection des sources rendus indépendants des espaces et retours à la ligne.
- Sources de référence et correctifs d’installation synchronisés avec le code formaté.
- Paquet Python structuré en sept domaines ; état de supervision et sécurité des rapports séparés du serveur HTTP.
- Frontend rangé par fonctionnalités, avec URL publiques conservées et liste de ressources explicite.
- Tests Python, Web, C++ et QA sortis de `scripts/` ; lanceur commun et contrôles des dépendances entre domaines.
- Équations de trajectoire partagées par planificateur et éditeur ; provenance couvrant les deux sources.
- Aucun rechargement du runtime, aucune fusion dans `main` et aucune nouvelle version publiée.

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
