# Contribuer à Voice Master

Merci de votre intérêt pour le projet.

## Environnement de développement

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

Les changements doivent rester compatibles avec Windows 10/11 et respecter le principe
de confidentialité du projet : aucun audio ni texte ne doit être conservé sans une action
explicite de l'utilisateur.

Avant une pull request :

- limiter la contribution à un sujet précis ;
- ajouter ou adapter les tests ;
- vérifier le micro, le loopback WASAPI et le mode combiné si la capture est modifiée ;
- ne jamais inclure de modèle, d'environnement virtuel ou d'enregistrement.

