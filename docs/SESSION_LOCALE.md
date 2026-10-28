# Session locale après déplacement — 27 octobre 2026

Répertoire actif : `/Users/gabrielricardon/Desktop/Perso/export`.
Les deux projets complets se trouvent sous `runtime/`, contrairement aux surcouches
portables sous `components/`. Le dashboard et Unity lisent désormais ces projets complets.

## Ouvrir la chaîne

Docker Desktop doit être lancé. Depuis ce dossier :

```bash
python3 scripts/start_local_stack.py
```

Quatre onglets Terminal sont ouverts : `dashboard`, `ros`, `sim`, `web`.
Si Unity n'est pas ouvert, le lanceur ouvre Unity Hub. Dans Hub, utiliser **Add >
Add project from disk**, choisir `runtime/LOTUSim-Unity-modules`, puis ouvrir cette
entrée précise. Le lancement direct de l'éditeur ne récupère pas la licence sur ce Mac.
Ne pas ouvrir l'ancienne entrée pointant sous `STAGE - CEMIS - LOTUSIM`.
Le lanceur vérifie le montage du conteneur et refuse les doublons connus.
Il ne reconstruit ni ne recrée les conteneurs.

- Dashboard : <http://127.0.0.1:8766/#settings>.
- Interface officielle LOTUSim : <http://127.0.0.1:8080/>.
- ROS TCP : port local 10000 ; API de l'interface officielle : port local 5001.
- Logs Unity lancé par Hub : `~/Library/Logs/Unity/Editor.log` ; les diagnostics des
  premières tentatives de lancement direct sont conservés sous `.local/logs/`.

Le monde ouvert est `maritime_dataset.world`, dédié aux campagnes pilotées.
Il n'a pas besoin de xDyn ; les anciens scénarios de propulsion peuvent, eux, en dépendre.
Ne pas lancer un autre monde simultanément dans le namespace `/lotusim`.
Le dashboard est un éditeur de plans et un observateur : il ne démarre pas Play.

Le lanceur du simulateur définit `LTTNG_UST_REGISTER_TIMEOUT=0` pour éviter une
attente initiale du traceur. Cela ne désactive pas les journaux LOTUSim et n'altère
pas les plans de campagne. Les indicateurs de service du lanceur inspectent les
processus et sockets dans le conteneur : un port publié par Docker Desktop ne suffit
pas à prouver qu'un serveur a réellement démarré.

La chaîne n'utilise pas de fonction réservée à Unity Pro. L'activation de licence
reste gérée dans Unity Hub ; l'éligibilité à Personal pour un travail de stage ou
effectué pour un organisme doit être vérifiée auprès de cet organisme selon les
[conditions Unity](https://unity.com/pages/license-compliance).

Pour consulter l'état sans aucune connexion réseau au serveur ROS :

```bash
python3 scripts/start_local_stack.py status
```

Pour relancer seulement un service arrêté dans un onglet Terminal :

```bash
python3 scripts/start_local_stack.py run dashboard
# autres noms : ros, sim, web
```

## Tester les mises à jour : pilote de deux images

1. Dans le dashboard, ouvrir **Paramétrage**. La configuration sauvegardée
   « Pilote de validation — 2 images » peut être rechargée et préparée.
   Une préparation écrit le plan ; elle ne lance pas la génération.
2. Un plan prêt existe déjà :
   `runtime/LOTUSim/artifacts/campaign-settings/prepared/a69ab5b1-ef36-4225-aa57-4ebed2b3eaab/manifest.json`.
   Il demande une bouée à 100 m, une image de jour et une de nuit en 1280×720,
   avec une hauteur de houle nominale de 1,5 m.
3. Dans Unity, hors Play : **LOTUSim > Dataset > Manual campaigns > Import prepared campaign**.
   Choisir ce `manifest.json`, en laissant `campaign.json` à côté. Une scène dédiée s'ouvre.
4. Lancer **Play** dans cette scène seulement. Les sorties vont sous
   `runtime/LOTUSim-Unity-modules/artifacts/manual-campaigns/` : RGB, annotations,
   overlays et métadonnées. Leur suivi est visible dans le dashboard.

La validation manuelle de ces deux images reste nécessaire avant une campagne longue.
La préparation des plans et les tests de code ne prouvent pas, à eux seuls, le rendu GPU.
Les tailles apparentes, vitesses de catalogue et paramètres météo sont des approximations
de scénario documentées ; l'image reconnaissable ou visible n'est pas garantie par le plan.

## Arrêter

Quitter Play et laisser la campagne finir son arrêt. Fermer Unity normalement si nécessaire.
Dans chaque onglet dédié, utiliser Ctrl+C. Pour arrêter tout le runtime du conteneur :

```bash
docker stop --time 20 lotusim-dev
```

Cela ne ferme pas le dashboard Python du Mac : utiliser Ctrl+C dans son onglet.
Ne pas relancer plusieurs fois des services dont l'arrêt n'est pas confirmé.

## Ce qui a été conservé

- Les anciens répertoires LOTUSim et Unity sont inchangés, à part leur arrêt propre.
- L'ancien conteneur est conservé arrêté : `lotusim-dev-before-export-20261027`.
- Son état est sauvegardé localement dans l'image
  `lotusim-dev:before-export-move-20261027`. Rien n'a été publié.
- Le nouveau conteneur expose ses ports uniquement sur `127.0.0.1`.
- Les poids du validateur RGB, sa base de connaissance et les configurations sont recopiés.
- Les gros corpus historiques restent dans les anciens dossiers pour éviter de dupliquer
  plus de 25 Go. Ils ne sont ni perdus ni automatiquement analysés au démarrage.
- Le venv RGB est recréé à son nouveau chemin, avec les paquets déjà disponibles sur ce Mac.

`manifest.json` décrit les sources portables et les nouveaux lanceurs, pas les caches,
binaires, dépendances et résultats du `runtime/`. Le manifeste initial est conservé
sous `.local/backups/manifest-before-relocation.json`.
