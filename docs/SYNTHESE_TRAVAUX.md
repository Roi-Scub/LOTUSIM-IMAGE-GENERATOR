# Synthèse des travaux sur les images maritimes synthétiques

## Objectif scientifique

Le projet vise à produire des images maritimes annotées pour entraîner et évaluer des détecteurs d’objets, puis à déterminer quand une annotation géométriquement exacte devient peu exploitable : cible trop petite, masquée, immergée ou peu contrastée. La position connue dans le simulateur ne suffit pas à établir qu’un objet est reconnaissable dans l’image.

## Répartition entre les composants

LOTUSim et Gazebo gèrent les entités, les trajectoires cinématiques et les poses acquittées. Une seule connexion ROS TCP relie la scène dédiée au projet Unity. Unity HDRP fournit l’océan, les modèles, l’éclairage, les images et leurs masques/annotations issus du même rendu. Les outils Python réalisent ensuite une analyse indépendante des pixels RGB.

Le dashboard local réunit la supervision, les agents logiciels, les campagnes, les rapports et le paramétrage. Ses contrôles de présence de services ne créent pas de client ROS. Son éditeur prépare des fichiers ; le lancement dans Unity reste explicite.

## Réalisations incluses

- **Bibliothèque 3D** : bouées, oiseaux, drones, hélicoptères, avions et sept familles de navires, avec variantes externes, matériaux, éclairages et provenance.
- **Rendu maritime Unity** : houle, réponse visuelle des objets et de la FREMM observatrice, caméra solidaire de la passerelle, variations de lumière ; modes IR et vision nocturne synthétiques dans les pilotes qui les prennent en charge.
- **Annotations automatiques** : boîtes, masques visibles/amodaux, pourcentage visible, catégories, métadonnées de caméra et de scène, exports JSON/COCO/YOLO selon le pilote et images de contrôle.
- **Reconnaissabilité** : indicateurs NR, PR et R fondés sur des règles paramétrables ; ils restent des heuristiques à confronter à une référence humaine.
- **Trafic planifié** : agents logiciels déterministes de catalogue, trajectoire, placement et sécurité, avec profils de vitesse ; ce n’est pas un réseau de LLM externes ni une navigation COLREG certifiée.
- **Campagnes manuelles** : blocs d’images indépendantes, météo, composition, distances, vitesses, caméra et estimation de hauteur apparente en pixels. L’import crée une nouvelle scène, sans écraser les anciennes.
- **Validation RGB indépendante** : Grounding DINO local, revue et déduplication des propositions, exclusion du bateau observateur, base d’exemples et outils d’évaluation/calibration avec séparation des données.
- **Supervision** : dashboard local, télémétrie datée, progression des jobs, aperçu récent ou dernière capture explicitement historique et accès aux rapports.

## Ce que fait Gazebo dans cette chaîne

Le mode connecté utilise ses entités/poses pour piloter Unity. Une première chaîne de capteurs Gazebo natifs existe séparément pour les images de sa propre scène étiquetée. Le relais RGB optionnel transporte les pixels Unity par Gazebo Transport et vérifie leur intégrité ; **Gazebo ne devient pas pour autant un modèle de reconnaissance d’images**. La reconnaissance indépendante est réalisée par le détecteur visuel Python.

## Limites et travail restant

Les campagnes manuelles sont des prises de vue indépendantes, pas une vidéo continue. Leur compilation et leurs contrats de cycle de vie ont été vérifiés ; un petit essai GPU/ROS réel reste nécessaire avant une campagne importante. Unreal ne dispose pas d’adaptateur connecté ; son format de configuration est seulement exportable.

La hauteur de houle demandée, les nuages, la pluie et les réponses aux vagues sont des paramètres/proxies visuels, pas une hydrodynamique validée. Les modes IR/nocturne ne sont pas radiométriquement calibrés. Les vitesses et dimensions du catalogue comprennent des hypothèses représentatives, et la cible en pixels est une approximation de projection.

Les pourcentages visibles sont des mesures géométriques ; les scores du détecteur et les similarités de référence ne sont pas automatiquement des probabilités de justesse. L’annotation manuelle de référence, un plan d’expérience suffisamment diversifié et la validation statistique des seuils restent nécessaires pour conclure scientifiquement et finaliser un filtre de validité.

## Statut du code

Il s’agit d’une extension locale : les ajouts réutilisables sont séparés des correctifs du noyau et des adaptations d’installation. L’export fournit le code et les assets, pas une promesse d’autonomie vis-à-vis de LOTUSim, du projet Unity de base et de leurs dépendances. Les inventaires techniques détaillent les points de raccord.
