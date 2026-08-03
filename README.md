# MetaMind 🧠

MetaMind is an AI-powered study companion that measures **deep conceptual understanding**, not mere recall. Instead of passive quizzing or simple flashcards, MetaMind challenges students to explain concepts in their own words, generates calibrated counterarguments and edge-case challenges, and adapts spaced repetition based on understanding.

---

## 🌟 Key Features

- **Explain & Defend Core Loop**: Explain a concept, face an AI-generated pedagogical challenge, defend your reasoning, and receive structured evaluation.
- **Calibrated Multi-Agent AI**: Transparent step-by-step reasoning (acknowledgement, location, classification, challenge presentation, rubric-based scoring).
- **Adaptive Spaced Repetition**: Surfaces weak concepts and misconceptions dynamically.
- **Modern Full-Stack Architecture**:
  - **Backend**: FastAPI (Python), Supabase (PostgreSQL + pgvector), Multi-LLM provider support (Gemini, Claude, OpenAI, Groq, Ollama).
  - **Frontend**: Vite + React / Vanilla JS with responsive, interactive UI.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Node.js 18+
- Supabase account or local Supabase instance

### 1. Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # Configure your database and API keys
uvicorn main:app --reload
```

### 2. Frontend Setup

```bash
cd frontend
npm install
cp .env.example .env      # Configure your Supabase anon keys
npm run dev
```

---

## 📁 Repository Structure

```
MetaMind/
├── backend/            # FastAPI backend service, routers, agents, database models
│   ├── auth.py         # Authentication helpers
│   ├── config.py       # Pydantic configuration & environment management
│   ├── database.py     # Database session & engine
│   ├── main.py         # Application entrypoint
│   ├── models.py       # SQLModel / SQLAlchemy schema
│   ├── routers/        # API route handlers
│   └── services/       # AI agents, scoring, debate logic
├── frontend/           # Web client UI
│   ├── src/            # Components, state, styles
│   └── index.html      # Main HTML entry
├── MetaMind_Development_Plan.md # Technical specification & architecture docs
└── README.md
```

---

## 📄 License

MIT License.
