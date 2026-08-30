# Voice Master

Voice Master est une application Windows de transcription locale. Elle capture le
microphone, le son du PC par loopback WASAPI, ou les deux en même temps, puis restitue
les interventions sous la forme d'une conversation chronologique.

## Fonctionnalités

- capture **Micro**, **PC** ou **Micro + PC** ;
- transcription locale avec [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) ;
- affichage quasi direct avec le modèle Whisper `small` quantifié en INT8 ;
- alternance des tours de parole `Vous` / `PC` à partir des horodatages ;
- modes **Rapide** et **Précis** ;
- copie dans le presse-papiers ou export TXT à la demande ;
- aucun enregistrement ni texte conservé automatiquement.

## Installation

[![Télécharger Voice Master](https://img.shields.io/badge/Télécharger-Voice_Master-7C5CFC?style=for-the-badge&logo=windows11&logoColor=white)](https://github.com/aminechaff/voice_detection/releases/download/latest/VoiceMaster.exe?download=1)

1. Téléchargez **VoiceMaster.exe** avec le bouton ci-dessus.
2. Double-cliquez sur le fichier.
3. Une icône **Voice Master** est créée sur le Bureau.

Le lanceur installe l'application dans le profil Windows, sans fenêtre PowerShell et
sans demander d'installer Python. Lors des lancements suivants, il vérifie GitHub,
applique une éventuelle mise à jour, puis ouvre directement Voice Master. Une
installation existante reste utilisable hors connexion.

Prérequis : Windows 10/11 64 bits et une connexion Internet pour la première
installation ainsi que pour le premier téléchargement du modèle Whisper.

Windows peut afficher un avertissement SmartScreen puisque l'exécutable open source
n'est pas signé avec un certificat commercial. Le code du lanceur est disponible dans
[`launcher/VoiceMasterLauncher.cs`](launcher/VoiceMasterLauncher.cs).

### Lancement depuis les sources

Pour le développement, Python 3.11 64 bits reste nécessaire :

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\lancer.ps1
```

Le script crée un environnement `.venv`, installe les dépendances et démarre
l'application. Si [`uv`](https://docs.astral.sh/uv/) est disponible, il est utilisé
automatiquement ; sinon le script emploie `venv` et `pip`.

Installation manuelle :

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m voicemaster
```

## Utilisation

1. Sélectionner la source et les périphériques audio.
2. Choisir la langue, le mode et le modèle.
3. Activer **Texte en direct** avec le mode **Rapide** si nécessaire.
4. Démarrer puis arrêter l'enregistrement.
5. Copier le dialogue ou l'enregistrer dans un fichier TXT.

Pour séparer correctement les voix en mode combiné, utilisez de préférence un casque :
le microphone ne doit pas réenregistrer le son des haut-parleurs.

## Confidentialité

La capture et l'inférence s'effectuent localement. Les pistes audio sont écrites dans
un dossier temporaire propre à la session et supprimées après transcription. Aucun
service distant ne reçoit l'audio. Seul le téléchargement initial du modèle utilise
Hugging Face.

## Architecture

```text
src/voicemaster/
├── app.py             Interface et orchestration
├── audio.py           Capture WASAPI et normalisation
├── dialogue.py        Ordonnancement des tours de parole
└── transcription.py   Moteur Faster-Whisper
```

## Développement

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

Le projet est distribué sous licence [MIT](LICENSE). Les contributions sont décrites
dans [CONTRIBUTING.md](CONTRIBUTING.md).
