# Session locale

Les projets complets sont sous `runtime/LOTUSim` et
`runtime/LOTUSim-Unity-modules`. Les dossiers `components/` sont les sources à
intégrer, pas les projets exécutés. Pour un nouveau poste, suivre d’abord
l’[installation](INSTALLATION_COMPLETE.md).

## Démarrer

Avec Docker Desktop lancé, depuis la racine :

```bash
python3 scripts/start_local_stack.py
```

Le lanceur ouvre les onglets `dashboard`, `ros`, `sim` et `web`, vérifie les
montages et évite les doublons connus. Il ne construit ni ne recrée le conteneur
`lotusim-dev`. Pour Unity, ouvrir dans Hub le projet complet sous `runtime/`,
pas une ancienne copie. Le lanceur ne passe pas en Play.

| Service | Adresse locale |
| --- | --- |
| Dashboard | <http://127.0.0.1:8766/> |
| Interface officielle LOTUSim | <http://127.0.0.1:8080/> |
| API de cette interface | Port 5001 |
| ROS TCP Endpoint | Port 10000 |

Le monde dataset est `maritime_dataset.world`. Ne pas le lancer en parallèle
avec `lotusim.world` dans `/lotusim`. Les campagnes dataset n’ont pas besoin de
xDyn ; les anciens scénarios de propulsion peuvent en dépendre.

Consulter l’état sans créer de client ROS supplémentaire :

```bash
python3 scripts/start_local_stack.py status
python3 scripts/start_local_stack.py run dashboard
```

La seconde commande relance seulement le service nommé s’il est arrêté ; les
autres noms sont `ros`, `sim` et `web`. Un port Docker publié ne suffit pas à
prouver que le processus dans le conteneur est prêt.

## Faire un petit essai

Dans **Paramétrage**, préparer une bouée à 100 m, une image de jour et une de
nuit en 1280 × 720. Le fichier `examples/campagne-2-images.json` est une base
de configuration à consulter. Ne pas réutiliser un ancien identifiant de bundle.

Dans Unity, hors Play, choisir **LOTUSim > Dataset > Manual campaigns > Import
prepared campaign**, sélectionner le nouveau `manifest.json` puis lancer Play
dans la scène créée. Les sorties sont sous
`runtime/LOTUSim-Unity-modules/artifacts/manual-campaigns/` et apparaissent dans
le dashboard. Contrôler RGB, masques et exclusion de l’observateur avant d’augmenter
le volume.

## Arrêter

Quitter Play après l’arrêt de la campagne. Utiliser Ctrl+C dans les onglets des
services à arrêter. Pour arrêter aussi le conteneur :

```bash
docker stop --time 20 lotusim-dev
```

Cette commande ne ferme pas le dashboard du Mac : Ctrl+C dans son propre onglet.
Fermer Unity normalement. Ne pas lancer plusieurs fois un service dont l’arrêt
n’a pas été confirmé. Les journaux Unity sont dans `~/Library/Logs/Unity/Editor.log`.
