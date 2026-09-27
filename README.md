# Calendrier des rencontres seniors CSBW

Ce projet prépare le calendrier **2026-2027** du Club Sportif de Badminton de Wittelsheim. Il lit chaque dimanche les pages publiques d’[ICbad](https://icbad.ffbad.org/), repère les équipes seniors `68-CSBW`, puis génère :

- `public/index.html` : calendrier responsive pour WordPress ;
- `public/rencontres.json` : données réutilisables ;
- `public/calendrier.ics` : abonnement Google Calendar, iPhone ou Outlook.

La saison 2026-2027 est déjà sélectionnable sur ICbad, mais le Grand Est et le Comité 68 ne sont pas encore publiés au 10 juillet 2026. En attendant, la page affiche un message propre. Elle se remplira automatiquement dès la publication des équipes et des poules.

## Fonctionnement

Le collecteur inspecte uniquement :

- les interclubs nationaux seniors ;
- les compétitions régionales de la Ligue Grand Est ;
- les compétitions seniors du Comité Départemental 68.

Les compétitions jeunes, vétérans et corpo sont exclues. Les identifiants ne sont pas codés en dur : ils sont redécouverts pour chaque saison.

## Essai local

Depuis ce dossier :

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m scraper.scraper --no-delay
```

Ouvrir ensuite `public/index.html` dans le navigateur. Pour vérifier l’ancien calendrier réel sans modifier la configuration :

```powershell
.\.venv\Scripts\python.exe -m scraper.scraper --season 2025 --output-dir build-2025 --no-delay
```

Pour afficher un calendrier 2026-2027 rempli de rencontres fictives sans toucher à `public` :

```powershell
.\.venv\Scripts\python.exe -m scraper.scraper --demo
```

Ouvrir ensuite `build-demo/index.html`. Le titre « Aperçu test » permet de ne pas confondre cette page avec le calendrier officiel.

## Correction manuelle

Le fichier `overrides.json` permet de corriger une donnée ICbad, supprimer une rencontre ou en ajouter une avant sa publication officielle.

Correction d’un lieu :

```json
{
  "delete": [],
  "upsert": [
    {
      "id": "719092",
      "season": "2026-2027",
      "venue": "Salle Pierre Albouy, 68310 Wittelsheim"
    }
  ]
}
```

Ajout manuel compact :

```json
{
  "delete": [],
  "upsert": [
    {
      "id": "manual-csbw2-2026-10-02",
      "season": "2026-2027",
      "team": "CSBW 2",
      "start": "2026-10-02T20:30:00+02:00",
      "opponent": "Adversaire à confirmer",
      "is_home": true,
      "venue": "Salle Pierre Albouy, 68310 Wittelsheim"
    }
  ]
}
```

Pour masquer une rencontre ICbad, ajouter son identifiant dans `delete`. L’identifiant se trouve dans `rencontres.json` ou à la fin de l’URL ICbad.

## Publication gratuite sur GitHub Pages

Le dossier est conçu pour devenir la racine d’un dépôt GitHub séparé.

1. Créer un dépôt, par exemple `csbw-rencontres`.
2. Y envoyer tout le contenu de ce dossier.
3. Dans **Settings > Pages > Build and deployment**, choisir **GitHub Actions**.
4. Lancer une première fois l’action **Mise à jour des rencontres CSBW**.

Le workflow `.github/workflows/weekly-article.yml` prépare le calendrier, les événements WordPress et l’article chaque dimanche dès **8 h 17, heure de Paris**, avec trois nouvelles tentatives à **12 h 17, 15 h 17 et 17 h 17** (`timezone: Europe/Paris`). L’article est enregistré dans WordPress avec le statut **Programmé**, pour **19 h le même dimanche**, en été comme en hiver. GitHub ne doit donc plus démarrer à 19 h pour publier. Un article déjà publié reste intact, y compris ses modifications manuelles. Aucun ordinateur ni tablette ne doit rester allumé. Le workflow `update.yml` reste disponible uniquement sur lancement manuel pour actualiser GitHub Pages sans modifier WordPress. Les erreurs temporaires d’ICbad (`429`, `500`, `502`, `503` et `504`) sont retentées automatiquement.

Limite : GitHub peut retarder ou omettre la préparation. Une fois l’article programmé, WordPress utilise WP-Cron, généralement déclenché par les visites. Sans tâche chez l’hébergeur ou service externe, une absence de visites ou une panne peut encore retarder la publication après 19 h. La plage 19 h-20 h n’est donc pas garantie. Références : [planification GitHub](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), [WP-Cron](https://developer.wordpress.org/plugins/cron/).

L’adresse obtenue ressemblera à :

```text
https://NOM-UTILISATEUR.github.io/csbw-rencontres/
```

## Intégration WordPress

Dans l’article ou la page WordPress, insérer un bloc **HTML personnalisé** :

```html
<iframe
  src="https://NOM-UTILISATEUR.github.io/csbw-rencontres/"
  title="Calendrier des rencontres seniors du CSBW"
  loading="lazy"
  style="width:100%;height:760px;border:0;background:transparent;"
></iframe>
```

Cette opération n’est faite qu’une fois. Les mises à jour suivantes arrivent dans l’iframe automatiquement.

## Article hebdomadaire sur l’occupation de la salle

Le workflow `.github/workflows/weekly-article.yml` démarre chaque dimanche à 8 h 17, 12 h 17, 15 h 17 et 17 h 17 (Europe/Paris) pour la semaine du lundi au dimanche qui suit. Chaque tentative collecte le calendrier une seule fois, synchronise les événements de cette semaine, puis programme l’article pour dimanche 19 h à partir des mêmes données. Les tentatives suivantes actualisent le même article programmé ; elles ne créent pas de doublon. Si la préparation arrive après 19 h, l’article est publié immédiatement, sauf s’il est déjà publié. Si la synchronisation échoue, la préparation de l’article est arrêtée. Le calendrier GitHub Pages est ensuite déployé.

Les lectures et mises à jour de l’article WordPress sont retentées après 10, 30 puis 60 secondes en cas de coupure réseau ou d’erreur HTTP `429`, `500`, `502`, `503`, `504`. Un nouvel article est d’abord réservé en brouillon, puis publié par son identifiant. Une création dont la réponse est perdue n’est jamais répétée aveuglément : le prochain rattrapage recherche d’abord le même identifiant d’URL. Les erreurs d’authentification ne sont pas retentées. Des secrets manquants font échouer la tâche au lieu d’annoncer un faux succès ; les aperçus disponibles sont conservés même en cas d’échec.

Il utilise les mêmes données que le calendrier, puis conserve uniquement :

- les rencontres à domicile ;
- celles dont le lieu contient « Salle Pierre Albouy » ;
- celles prévues pendant la semaine suivante.

Un seul article est créé par semaine. Une exécution manuelle peut mettre à jour le même article grâce à son identifiant d’URL ; les exécutions programmées ne touchent pas à un article déjà publié. Lorsqu’il n’y a aucune rencontre à domicile, aucun article n’est créé. Si toutes les rencontres à domicile disparaissent lors d’une nouvelle vérification, l’article encore programmé repasse en brouillon, sans suppression. Après publication, les corrections restent manuelles.

Exemple de contenu :

```html
<p><strong>Du 31 août au 6 septembre</strong></p>
<p>📍 Salle Pierre Albouy</p>
<h2>📅 Vendredi 4 septembre : 2 rencontres</h2>
<p>🕒 <strong>20 h 30</strong> · CSBW 1 reçoit Badminton Club Mulhouse</p>
<p>🕒 <strong>20 h 30</strong> · CSBW 3 reçoit Colmar Badminton Racing</p>
<h2>📅 Dimanche 6 septembre : 1 rencontre</h2>
<p>🕒 <strong>10 h 00</strong> · CSBW 5 reçoit Sundgau Badminton</p>
```

Pour voir l’aperçu fictif :

```powershell
.\.venv\Scripts\python.exe -m scraper.weekly_article --demo --week-start 2026-08-31
```

La page de test est créée dans `build-weekly-demo/index.html`.

### Autoriser la publication WordPress

Dans le dépôt GitHub, créer deux secrets dans **Settings > Secrets and variables > Actions** :

- `WP_USERNAME` : le nom d’utilisateur WordPress ;
- `WP_APPLICATION_PASSWORD` : un mot de passe d’application créé dans le profil WordPress.

Le mot de passe habituel du compte WordPress ne doit pas être placé dans GitHub. Si la rubrique « Mots de passe d’application » n’apparaît pas dans le profil, un administrateur du site devra l’activer ou fournir un autre accès de publication.

L’exécution automatique utilise `--schedule-sunday` et transmet à WordPress une date UTC explicite correspondant au dimanche précédent la semaine ciblée, à 19 h à Paris. Le statut et la date retournés par WordPress sont vérifiés. Lors d’un lancement manuel, le champ `status` propose `draft` (brouillon, par défaut) ou `publish`. Cocher `schedule_sunday` avec `publish` pour programmer à 19 h ; sans cette case, `publish` conserve la publication immédiate. Attention : même en mode brouillon, les événements WordPress sont synchronisés. Pour un essai sans modification de WordPress, utiliser le workflow de test en lecture seule décrit plus bas.

Une ancienne tâche Windows nommée `CSBW Weekly Home Interclubs Post` existe sur cet ordinateur. La désactiver seulement après la mise en service du workflow GitHub, afin d’éviter deux automatisations concurrentes :

```powershell
Disable-ScheduledTask -TaskName "CSBW Weekly Home Interclubs Post"
```

## Bloc « Interclub » de la page d’accueil

Le workflow du dimanche synchronise aussi le widget Events Manager intitulé « Interclub » :

- le dimanche, lors de la préparation anticipée de l’article, il synchronise toutes les rencontres du lundi au dimanche qui suit ; les règles d’affichage du widget restent inchangées ;
- aucune vérification quotidienne n’est programmée ;
- les rencontres à domicile et à l’extérieur sont incluses ;
- les évènements sont classés dans la catégorie WordPress `Interclubs` ;
- les rencontres à domicile utilisent l’emplacement `Salle Pierre Albouy`.

Cette synchronisation nécessite l’API REST d’Events Manager, disponible à partir de la version 7.3. Le site utilise désormais la version 7.4.5 ; le test du 25 septembre 2026 confirme la connexion depuis GitHub et la lecture des sept événements de la semaine du 28 septembre. Les événements saisis manuellement sont reconnus par leur lien ICbad : leurs titres, descriptions et emplacements sont conservés lors des mises à jour. Si un même lien ICbad apparaît dans plusieurs événements, la synchronisation s’arrête pour éviter une modification ambiguë.

Le workflow manuel `Test connexion Events Manager (lecture seule)` vérifie les identifiants, lit les événements et simule la synchronisation de la semaine du 28 septembre 2026. Il ne publie et ne modifie aucun événement. Pour simuler une autre semaine :

```powershell
.\.venv\Scripts\python.exe -m scraper.wordpress_events --week-start 2026-09-28 --dry-run
```

## Paramètres de saison

La saison active se trouve dans `config.json` :

```json
"season_start_year": 2026
```

Pour 2027-2028, remplacer simplement `2026` par `2027`. `competition_ids` reste vide sauf si une compétition exceptionnelle doit être ajoutée explicitement.
