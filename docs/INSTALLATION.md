# Installation & Deployment Guide

## Context-Aware Smart LLM Switching for Cost and Performance Optimization

---

## 1. Prerequisites

Before installing the application, ensure your environment meets the following requirements:

* **Python:** Version 3.10, 3.11, 3.12, or 3.13.
* **Operating System:** Windows 10/11, macOS (Apple Silicon or Intel), or Linux (Ubuntu, Debian, Fedora, Arch).
* **Package Manager:** `pip` (Python package manager).
* **Git:** Version 2.20+.

---

## 2. Step-by-Step Installation

### Step 2.1: Clone the Repository
```bash
git clone https://github.com/ramakrishna293029-cpu/context-aware-smart-llm-switching.git
cd context-aware-smart-llm-switching
```

### Step 2.2: Create and Activate a Python Virtual Environment

* **On Windows (PowerShell):**
  ```powershell
  python -m venv .venv
  .venv\Scripts\Activate.ps1
  ```

* **On Windows (Command Prompt):**
  ```cmd
  python -m venv .venv
  .venv\Scripts\activate.bat
  ```

* **On Linux / macOS (Bash / Zsh):**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

### Step 2.3: Install Dependencies
Install all required Python packages from the root `requirements.txt`:
```bash
pip install -r requirements.txt
```

---

## 3. Environment Configuration

Copy the example environment configuration file:

* **Windows:**
  ```powershell
  copy .env.example .env
  ```
* **Linux / macOS:**
  ```bash
  cp .env.example .env
  ```

Open `.env` in your text editor and provide your API keys:

```env
# Google Gemini API Key (Powers Tiers 1, 3, and 6)
GEMINI_API_KEY=your_gemini_api_key_here

# Groq Cloud API Key (Powers Tiers 2, 4, and 5)
GROQ_API_KEY=your_groq_api_key_here

# Optional: Dedicated Tier API Keys (if using separate enterprise accounts)
# GEMINI_TIER1_API_KEY=
# GROQ_TIER2_API_KEY=
# GEMINI_TIER3_API_KEY=
# GROQ_TIER4_API_KEY=
# GROQ_TIER5_API_KEY=
# GEMINI_TIER6_API_KEY=

# LinUCB Bandit Configuration
ROUTING_STRATEGY=balanced
EXPLORATION_ALPHA=0.5

# Cost & Safety Controls
MAX_COST_PER_REQUEST=0.05
DAILY_BUDGET_USD=10.0
MONTHLY_BUDGET_USD=100.0
REQUEST_TIMEOUT_SECONDS=45.0

# Mock Mode (Set to "false" to use real LLMs; "auto" uses mock only when keys are missing)
MOCK_MODELS_ENABLED=auto
```

> **Note on DEMO Mode:** If no API keys are provided in `.env`, the system automatically runs in offline **DEMO Mode** using deterministic mock adapters, allowing full offline testing and UI exploration.

---

## 4. Running the Application

### Option A: Standard Launcher (Recommended)
From the project root:
```bash
python run.py
```

### Option B: Backend Direct Launcher
From the project root:
```bash
python backend/run.py
```
Or navigate into the backend folder:
```bash
cd backend
python run.py
```

### Option C: Direct Uvicorn Command
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## 5. Accessing the System

Once started, open your web browser to:

* **Interactive Web Application:** [http://127.0.0.1:8000](http://127.0.0.1:8000)
* **Interactive API Docs (Swagger UI):** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
* **System Health Endpoint:** [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

---

## 6. Docker Container Deployment

To run the application inside an isolated Docker container:

```bash
# Build the container image
docker build -t smart-llm-router .

# Run the container with environment variables
docker run -d -p 8000:8000 --env-file .env --name smart-llm-router smart-llm-router
```
Navigate to `http://127.0.0.1:8000` to interact with the containerized application.
