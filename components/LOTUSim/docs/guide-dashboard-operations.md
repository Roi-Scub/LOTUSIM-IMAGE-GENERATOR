# LOTUSim Operations — supervision locale

Le dashboard réunit l’état des services, le suivi Unity, les agents logiciels, les campagnes et leurs rapports. La supervision reste en lecture seule. Depuis le 27 octobre 2026, **Paramétrage** permet aussi d’enregistrer des configurations et de préparer des campagnes, uniquement dans un nouveau dossier d’artifacts. Aucun bouton ne lance ou n’arrête une simulation ; aucun nouveau client ROS TCP et aucun envoi d’image ou de journal vers un hébergement externe.

## Démarrer

Depuis la racine du dépôt LOTUSim :

```bash
bash tools/start_ops_dashboard.command
```

Ouvrir **http://127.0.0.1:8766/**. Dans Unity, le menu **LOTUSim > Dataset > Operations > Open local dashboard** ouvre cette adresse, mais ne lance pas le serveur. Il faut garder son terminal ouvert. Ctrl+C dans ce terminal arrête seulement le dashboard ; Unity, Docker et les scénarios ne sont pas arrêtés.

Le chemin du dépôt Unity est découvert comme dépôt frère `LOTUSim-Unity-modules`. S’il est ailleurs :

```bash
bash tools/start_ops_dashboard.command --unity "/chemin/LOTUSim-Unity-modules"
```

`--port 8767` permet un autre port ; aucun processus existant n’est fermé si le port demandé est occupé. Le raccourci Unity utilise toujours 8766. `--no-docker` désactive l’inspection Docker.

## Les cinq vues

- **Vue d’ensemble** : services, aperçu de la caméra dataset, compteurs, chaîne de production et positions ENU du dernier instantané LOTUSim reçu par Unity.
- **Agents & chaîne** : planification, synchronisation, rendu, détecteur RGB, revue et exports. Ce sont les agents logiciels déterministes du projet, pas des agents LLM externes.
- **Journal d’activité** : événements structurés filtrables par source, niveau et texte. Ce n’est pas une copie de toutes les consoles Unity/Docker.
- **Campagnes & rapports** : résultats existants accessibles sans lancer de nouvelle analyse.
- **Paramétrage** : composition par blocs d’images, résolution et caméra, météo, houle, objets et vitesses. La préparation crée des fichiers à importer explicitement dans Unity. Voir [le guide des campagnes manuelles](guide-campagnes-manuelles-dashboard.md).

Pour observer une campagne, démarrer normalement les services et la génération dans Unity ; pour une analyse, utiliser le menu RGB Observer existant. Le dashboard suit leurs signaux sans modifier leur fonctionnement.

## Ce qui est mesuré

| Source | Cadence | Signification |
| --- | --- | --- |
| État de l’interface | 2 s | Flux SSE local, repli en interrogation HTTP |
| Docker et processus du conteneur | 10 s | Présence des services et ports d’écoute ; pas un test de santé fonctionnelle complet |
| Éditeur Unity | 1 s | Heartbeat, scène, Play/pause, compteurs et état du client ROS existant |
| Aperçu dataset | au plus une image / 2 s | Miniature 640 × 360 de la RenderTexture déjà produite, sans rendu caméra supplémentaire |
| Jobs Python | événements, écriture bornée | PID + date de naissance pour distinguer un processus réel d’un ancien statut |

La miniature est un aperçu de supervision, pas une modification de la résolution des images du corpus. Elle exige une caméra dataset effectivement rendue récemment, une campagne non terminée et au moins une capture produite. En dehors de ces conditions, l’interface indique **dernière capture / historique**, jamais une fausse vidéo directe. La validation GPU de cette miniature doit être faite lors d’une vraie campagne Unity ; les tests de compilation seuls ne suffisent pas.

Un instantané LOTUSim figé ou une pause reste identifié comme tel. Le champ `reply_observed` signifie qu’une réponse a été observée sur le client ROS existant, pas qu’une nouvelle sonde a confirmé la connexion. Un service disponible ne prouve pas que le scénario tourne ou que la caméra rend.

## Fichiers de suivi

- Unity : `LOTUSim-Unity-modules/artifacts/operations/unity.json` et `preview.jpg`.
- Planification : `artifacts/traffic-agents/ops-status.json` dans le dépôt qui reçoit le plan.
- Analyse RGB : `visual-observer/<analyse>/runtime.json`, plus `predictions/runtime.json` pour le détecteur.
- Statuts, événements et galeries de campagnes : emplacements habituels, non modifiés.

Les signaux Unity deviennent périmés après huit secondes sans heartbeat. Les anciens jobs ne sont pas déclarés actifs sur la seule foi d’un fichier. Les jobs lancés avant l’installation ne disposent pas forcément de leur identité de processus et peuvent rester « non confirmé » jusqu’à leur prochaine exécution.

## Protection et limites

Le serveur écoute seulement sur `127.0.0.1`, vérifie l’origine des requêtes et ne fournit pas de route de contrôle de simulation. Seules les routes de configuration acceptent des écritures JSON bornées, avec en-tête dédié et identifiants opaques ; elles ne modifient ni un scénario existant ni une scène Unity. Les images et rapports sont servis par jetons limités aux dossiers `artifacts` des deux projets, avec protections contre les sorties de chemin et liens symboliques. Les lignes de commande et variables d’environnement des processus ne sont pas exposées.

Les liens de rapports entre dossiers d’artifacts sont adaptés au serveur local ; les liens vers des documents hors de ces dossiers ne sont pas exposés par le dashboard. Aucun port ROS n’est sondé par une connexion TCP : l’inspection lit uniquement les processus et sockets d’écoute déjà présents dans le conteneur.

Le dashboard ne remplace ni les consoles de diagnostic ni une validation des annotations. Il n’ajoute pas de nouveaux modèles de détection ou de logique de trajectoire.

## Vérifier l’installation

```bash
python3 -m unittest discover -s scripts -p 'test_ops_*.py'
```

Les tests de serveur ouvrent uniquement des ports de boucle locale temporaires. Si Unity est ouvert, vérifier qu’un heartbeat apparaît dans `artifacts/operations/unity.json`, puis lancer une campagne habituelle pour contrôler le flux de miniature et l’avancement des compteurs.
