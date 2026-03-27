# ByStander

ByStander is an AI-assisted emergency guidance application with a Flask backend
and a Flutter frontend.

Live frontend: [https://bystander-mu.vercel.app/](https://bystander-mu.vercel.app/)

## Project Structure

- `bystander_backend`: backend agents, API service, tests, and evaluation code
- `bystander_frontend`: Flutter app for web/mobile experiences
- `ml`: machine learning assets and experiments

## Prerequisites

Before running the project locally, install:

- Python 3.10+
- `pip`
- Flutter SDK
- Dart SDK

## Run ByStander Locally

### 1. Start the backend

From the repository root:

```bash
cd bystander_backend
python3 -m venv env
source env/bin/activate
pip install -r agents/requirements.txt
python3 agents/app.py
```

The backend starts on `http://127.0.0.1:5003`.

Helpful local endpoints:

- `POST /agent_workflow`
- `POST /find_facilities`
- `POST /call_script`
- `POST /synthesize_speech`
- `GET /health`

### 2. Start the frontend

Open a new terminal from the repository root:

```bash
cd bystander_frontend
flutter pub get
flutter run --dart-define=BYSTANDER_API_BASE_URL=http://127.0.0.1:5003
```

If Flutter asks you to choose a device, select the one you want to use.
For browser testing, Chrome works well.

## Deployment

- Frontend: [https://bystander-mu.vercel.app/](https://bystander-mu.vercel.app/)
- The Flutter app defaults to the hosted backend unless
  `BYSTANDER_API_BASE_URL` is overridden at runtime.

## Run MLflow

If you want to launch the MLflow UI locally:

```bash
cd bystander_backend
python3 -m venv env_mlflow
source env_mlflow/bin/activate
pip install -r agents/requirements.txt
mlflow ui
```

MLflow typically starts at `http://127.0.0.1:5000`.
