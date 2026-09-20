# Calendrier des rencontres seniors CSBW

Ce projet prépare le calendrier **2026-2027** du Club Sportif de Badminton de Wittelsheim. Il lit chaque jour les pages publiques d’[ICbad](https://icbad.ffbad.org/), repère les équipes seniors `68-CSBW`, puis génère :

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

Le workflow `.github/workflows/update.yml` s’exécute ensuite chaque jour à 5 h UTC et peut aussi être lancé manuellement. Aucun ordinateur ni tablette ne doit rester allumé.

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

Le workflow `.github/workflows/weekly-article.yml` s’exécute chaque dimanche à 17 h UTC pour la semaine du lundi au dimanche qui suit.

Il utilise les mêmes données que le calendrier, puis conserve uniquement :

- les rencontres à domicile ;
- celles dont le lieu contient « Salle Pierre Albouy » ;
- celles prévues pendant la semaine suivante.

Un seul article est créé par semaine. Une nouvelle exécution met à jour le même article grâce à son identifiant d’URL. Lorsqu’il n’y a aucune rencontre à domicile, aucun article n’est créé.

Exemple de contenu :

```html
<h2>📅 Vendredi 4 septembre : 2 rencontres d’interclub à la salle Pierre Albouy</h2>
<ul>
  <li>🕒 <strong>20h30</strong> - CSBW 1 reçoit Badminton Club Mulhouse</li>
  <li>🕒 <strong>20h30</strong> - CSBW 3 reçoit Colmar Badminton Racing</li>
</ul>
<h2>📅 Dimanche 6 septembre : 1 rencontre d’interclub à la salle Pierre Albouy</h2>
<ul>
  <li>🕒 <strong>10h00</strong> - CSBW 5 reçoit Sundgau Badminton</li>
</ul>
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

Le workflow publie directement l’article. Pour faire une phase d’essai en brouillon, remplacer `--status publish` par `--status draft` dans `weekly-article.yml`.

Une ancienne tâche Windows nommée `CSBW Weekly Home Interclubs Post` existe sur cet ordinateur. La désactiver seulement après la mise en service du workflow GitHub, afin d’éviter deux automatisations concurrentes :

```powershell
Disable-ScheduledTask -TaskName "CSBW Weekly Home Interclubs Post"
```

## Bloc « Interclub » de la page d’accueil

Le workflow quotidien synchronise aussi le widget Events Manager intitulé « Interclub » :

- du lundi au samedi, il publie toutes les rencontres de la semaine en cours ;
- le dimanche soir, il affiche la semaine qui commence le lendemain ;
- les rencontres à domicile et à l’extérieur sont incluses ;
- les évènements sont classés dans la catégorie WordPress `Interclubs` ;
- les rencontres à domicile utilisent l’emplacement `Salle Pierre Albouy`.

Cette synchronisation nécessite l’API REST d’Events Manager, disponible à partir de la version 7.3. Tant que le site conserve Events Manager 7.2.2.1, le workflow ignore cette étape sans bloquer la mise à jour du calendrier. Après la mise à jour de l’extension par l’administrateur WordPress, la prochaine exécution quotidienne alimentera automatiquement le widget.

## Paramètres de saison

La saison active se trouve dans `config.json` :

```json
"season_start_year": 2026
```

Pour 2027-2028, remplacer simplement `2026` par `2027`. `competition_ids` reste vide sauf si une compétition exceptionnelle doit être ajoutée explicitement.
