# Compass Health

Compass Health is a bilingual AI-assisted meal planning and health tracking system built with FastAPI, vanilla JavaScript, and SQLite.

It is designed around a real user workflow instead of a chat demo:

1. collect health profile and food constraints
2. audit whether the user's food library is nutritionally feasible
3. generate a candidate dish pool
4. arrange a weekly meal plan
5. produce a shopping list
6. close the loop with daily and weekly feedback

## What It Does

- health profile setup with BMR and calorie target calculation
- food preference and fixed-meal management
- closed-loop nutrition audit against a structured food library
- weekly meal planning from a selected breakfast pool and shared main-dish pool
- shopping list generation from persisted meal plans
- daily and weekly feedback based on actual diet and exercise logs
- bilingual UI and API responses in Chinese and English

## Why This Project Is Interesting

This project uses a hybrid architecture instead of handing everything to an LLM.

- deterministic engine for nutrition audit, target calculation, weekly arrangement, and procurement
- bounded LLM usage only for soft tasks such as food classification and dish naming
- structured user-state memory from database records rather than prompt-only chat history
- real local full-stack app with frontend, backend, database, logs, and tests

## System Flow

### Inputs

- user profile: age, gender, height, weight, target weight, goal
- user preferences: food library, fixed meals, saved recipes
- user behavior: diet logs, exercise logs, water logs, physical condition
- planning selections: breakfast pool and main-dish pool selections

### Processing

- `services/nutrition_audit.py`: checks food-library feasibility and micronutrient coverage
- `services/planning_context.py`: builds per-day planning context with priority rules
- `services/menu_planner.py`: generates dish pools and arranges weekly schedules
- `services/recipe_suggester.py`: asks the LLM to name or revise dish sketches
- `services/procurement.py`: aggregates shopping lists from persisted plans
- `services/feedback_loop.py`: generates daily and weekly execution feedback

### Outputs

- candidate dish pool
- weekly arranged meal plan
- shopping list
- daily feedback report
- weekly review and adjustment suggestions

## Architecture

```text
frontend (vanilla JS SPA)
  -> api.js
  -> FastAPI routers
  -> service layer
  -> SQLite

LLM usage
  -> DeepSeek API
  -> preference classification
  -> dish naming / recipe-language generation

deterministic core
  -> calorie targets
  -> planning context
  -> nutrition audit
  -> weekly arrangement
  -> procurement
  -> feedback loop
```

## Tech Stack

- Backend: FastAPI, SQLAlchemy, APScheduler
- Frontend: vanilla JavaScript, HTML, CSS
- Database: SQLite
- LLM API: DeepSeek via OpenAI-compatible client
- Auth: JWT access token + refresh token
- Testing: pytest

## Key Engineering Decisions

### 1. Controlled tool orchestration instead of open-ended agent autonomy

The system does not let the model freely decide all tools. Most steps are explicitly orchestrated in code:

- audit first
- generate pool second
- name dishes only when needed
- arrange plan after user selection
- aggregate shopping list from persisted plan

This keeps the nutrition logic deterministic and testable.

### 2. Structured memory instead of chat-history stuffing

The main memory layer is persisted user state:

- profile
- settings
- food preferences
- fixed meals
- saved recipes
- diet / exercise / condition history
- planned meals

`planning_context.py` assembles those records into a day-level context and applies the priority chain:

`recorded > fixed > recipe > generated`

### 3. Bounded LLM surface

The LLM is intentionally limited to:

- classifying free-text food preferences into canonical slugs
- naming candidate dish sketches
- generating human-readable cooking descriptions

Core nutrition and scheduling decisions stay local.

## Local Run

### Option A

Double-click:

- `start.bat`

This starts both servers and opens the app automatically.

### Option B

Backend:

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Frontend:

```bash
cd frontend
python -m http.server 5500
```

### Local URLs

- App: [http://localhost:5500](http://localhost:5500)
- API: [http://localhost:8000](http://localhost:8000)
- API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## Environment Variables

Create `backend/.env` from `backend/.env.example`.

Important variables:

- `SECRET_KEY`
- `ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `REFRESH_TOKEN_EXPIRE_DAYS`
- `DATABASE_URL`
- `DEEPSEEK_API_KEY`
- `LOG_DIR`
- `ALLOW_WEAK_SECRET_KEY`
- `TRUST_PROXY`

## Project Structure

```text
compass-health/
├─ backend/
│  ├─ main.py
│  ├─ auth.py
│  ├─ database.py
│  ├─ models.py
│  ├─ middleware.py
│  ├─ logging_config.py
│  ├─ routers/
│  ├─ services/
│  ├─ tests/
│  └─ requirements.txt
├─ frontend/
│  ├─ index.html
│  ├─ css/
│  └─ js/
├─ start.bat
├─ stop.bat
└─ README.md
```

## Current Deployment Status

This repository is currently set up as a real local runnable system:

- FastAPI runs locally on port `8000`
- frontend static server runs locally on port `5500`
- database is local SQLite by default

It is not yet packaged in this repo as a cloud deployment template.

## Demo Talking Points

If you are using this project in interviews, the strongest talking points are:

- hybrid AI architecture: deterministic planning plus bounded LLM usage
- structured memory via persisted user state and planning context
- end-to-end runnable product instead of prompt demo
- service-layer decomposition with explicit audit / planner / procurement / feedback modules
- user-facing resilience: quotas, logs, warnings, and fallback guidance

## Notes

- Do not commit `backend/.env`
- Do not commit `backend/compass.db`
- Do not commit `backend/logs/` or local backup files

