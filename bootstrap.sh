#!/usr/bin/env bash
set -euo pipefail

mkdir -p \
  backend/app/routers \
  backend/app/fin \
  backend/app/viability \
  backend/tests \
  frontend/src

cat > .gitignore <<'EOF'
.env
.venv/
__pycache__/
*.pyc
.pytest_cache/
node_modules/
dist/
.DS_Store
EOF

cat > compose.yaml <<'EOF'
services:
  db:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_DB: graminsetu
      POSTGRES_USER: graminsetu
      POSTGRES_PASSWORD: graminsetu_dev
    ports:
      - "127.0.0.1:5433:5432"
    volumes:
      - graminsetu_pg:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U graminsetu -d graminsetu"]
      interval: 3s
      timeout: 3s
      retries: 20

volumes:
  graminsetu_pg:
EOF

cat > backend/requirements.txt <<'EOF'
fastapi>=0.115,<1.0
uvicorn[standard]>=0.30,<1.0
sqlalchemy>=2.0,<2.1
psycopg[binary]>=3.2,<4.0
pydantic-settings>=2.5,<3.0
pytest>=8.0,<9.0
httpx>=0.27,<1.0
EOF

cat > backend/.env.example <<'EOF'
DATABASE_URL=postgresql+psycopg://graminsetu:graminsetu_dev@localhost:5433/graminsetu
EOF

if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
fi

touch \
  backend/app/__init__.py \
  backend/app/routers/__init__.py \
  backend/app/fin/__init__.py \
  backend/app/viability/__init__.py

cat > backend/app/config.py <<'EOF'
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    database_url: str

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        extra="ignore",
    )


settings = Settings()
EOF

cat > backend/app/db.py <<'EOF'
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
EOF

cat > backend/app/models.py <<'EOF'
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # MVP profile payload; monetary values remain JSON integers.
    # Normalize into dedicated tables when the schema stabilizes.
    profile: Mapped[dict] = mapped_column(JSON, nullable=False)

    status: Mapped[str] = mapped_column(
        String(40),
        default="profile_saved",
        nullable=False,
    )
EOF

cat > backend/app/fixtures.py <<'EOF'
"""
Explicit development fixtures.

These IDs are NOT LGD village codes.
No population, crop, competition or infrastructure claims are made.
Replace with verified source records during ingestion.
"""

DEMO_VILLAGES = [
    {
        "id": "demo-nashik-a",
        "name": "Demo village A",
        "district": "Nashik",
        "state": "Maharashtra",
        "lgd_code": None,
        "is_demo": True,
        "source": "Development fixture — not verified geography",
    },
    {
        "id": "demo-nashik-b",
        "name": "Demo village B",
        "district": "Nashik",
        "state": "Maharashtra",
        "lgd_code": None,
        "is_demo": True,
        "source": "Development fixture — not verified geography",
    },
    {
        "id": "demo-jalgaon-a",
        "name": "Demo village A",
        "district": "Jalgaon",
        "state": "Maharashtra",
        "lgd_code": None,
        "is_demo": True,
        "source": "Development fixture — not verified geography",
    },
    {
        "id": "demo-jalgaon-b",
        "name": "Demo village B",
        "district": "Jalgaon",
        "state": "Maharashtra",
        "lgd_code": None,
        "is_demo": True,
        "source": "Development fixture — not verified geography",
    },
]

VILLAGE_BY_ID = {village["id"]: village for village in DEMO_VILLAGES}
EOF

cat > backend/app/schemas.py <<'EOF'
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Skill = Literal[
    "basic_machine_operation",
    "farming",
    "animal_husbandry",
    "tailoring",
    "retail_sales",
    "food_processing",
    "bookkeeping",
]

Language = Literal["en", "mr", "hi"]
Premises = Literal["owned", "rented", "not_arranged"]
Power = Literal["single_phase", "three_phase", "unavailable", "unknown"]


class ProfileCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    applicant_name: str = Field(min_length=2, max_length=100)
    village_id: str = Field(min_length=1, max_length=100)
    preferred_language: Language = "en"

    # Strict prevents JSON strings/floats/bools from becoming money.
    own_capital_paise: int = Field(
        strict=True,
        ge=0,
        le=10_000_000_000,
    )

    skills: list[Skill] = Field(default_factory=list, max_length=7)
    premises: Premises = "not_arranged"
    power: Power = "unknown"

    @field_validator("skills")
    @classmethod
    def deduplicate_skills(cls, value: list[Skill]) -> list[Skill]:
        return list(dict.fromkeys(value))


class VillageOut(BaseModel):
    id: str
    name: str
    district: str
    state: str
    lgd_code: str | None
    is_demo: bool
    source: str


class AssessmentOut(BaseModel):
    id: str
    created_at: datetime
    status: str
    profile: ProfileCreate
    village: VillageOut
EOF

cat > backend/app/routers/villages.py <<'EOF'
from fastapi import APIRouter, Query

from app.fixtures import DEMO_VILLAGES
from app.schemas import VillageOut

router = APIRouter(prefix="/api/villages", tags=["Geography"])


@router.get("", response_model=list[VillageOut])
def list_villages(
    district: str | None = Query(default=None, max_length=100),
    q: str = Query(default="", max_length=100),
):
    records = DEMO_VILLAGES

    if district:
        records = [
            item for item in records
            if item["district"].casefold() == district.casefold()
        ]

    if q.strip():
        term = q.strip().casefold()
        records = [
            item for item in records
            if term in item["name"].casefold()
        ]

    return records
EOF

cat > backend/app/routers/assessments.py <<'EOF'
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.fixtures import VILLAGE_BY_ID
from app.models import Assessment
from app.schemas import AssessmentOut, ProfileCreate

router = APIRouter(prefix="/api/assessments", tags=["Assessments"])


def serialize(assessment: Assessment) -> AssessmentOut:
    village = VILLAGE_BY_ID.get(assessment.profile["village_id"])

    if village is None:
        raise HTTPException(
            status_code=409,
            detail="Assessment geography is no longer available.",
        )

    return AssessmentOut(
        id=assessment.id,
        created_at=assessment.created_at,
        status=assessment.status,
        profile=assessment.profile,
        village=village,
    )


@router.post("", response_model=AssessmentOut, status_code=201)
def create_assessment(
    payload: ProfileCreate,
    db: Session = Depends(get_db),
):
    if payload.village_id not in VILLAGE_BY_ID:
        raise HTTPException(
            status_code=422,
            detail="Choose a village from the available records.",
        )

    assessment = Assessment(profile=payload.model_dump())

    db.add(assessment)
    db.commit()
    db.refresh(assessment)

    return serialize(assessment)


@router.get("/{assessment_id}", response_model=AssessmentOut)
def get_assessment(
    assessment_id: UUID,
    db: Session = Depends(get_db),
):
    assessment = db.get(Assessment, str(assessment_id))

    if assessment is None:
        raise HTTPException(
            status_code=404,
            detail="Assessment not found.",
        )

    return serialize(assessment)
EOF

cat > backend/app/main.py <<'EOF'
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models  # Registers SQLAlchemy models.
from app.db import Base, engine, get_db
from app.routers import assessments, villages


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Development bootstrap only.
    # Replace create_all with Alembic migrations before production.
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()


app = FastAPI(
    title="GraminSetu API",
    version="0.1.0",
    description=(
        "Development MVP. Geography fixtures are explicitly labelled. "
        "No lending decisions are made by this build."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(villages.router)
app.include_router(assessments.router)


@app.get("/api/health", tags=["System"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "connected",
        "version": "0.1.0",
        "geography_mode": "demo_fixtures",
    }
EOF

cat > backend/tests/test_boundaries.py <<'EOF'
import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import ProfileCreate

APP_DIR = Path(__file__).resolve().parents[1] / "app"

FORBIDDEN_IMPORTS = {
    "openai",
    "anthropic",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langgraph",
    "litellm",
    "transformers",
}


def payload(**overrides):
    base = {
        "applicant_name": "Demo Applicant",
        "village_id": "demo-nashik-a",
        "own_capital_paise": 5_000_000,
    }
    return base | overrides


@pytest.mark.parametrize("invalid_money", [12.5, "100", True, -1])
def test_money_rejects_invalid_values(invalid_money):
    with pytest.raises(ValidationError):
        ProfileCreate(**payload(own_capital_paise=invalid_money))


def test_money_is_integer_paise():
    profile = ProfileCreate(**payload())
    assert type(profile.own_capital_paise) is int
    assert profile.own_capital_paise == 5_000_000


def test_skills_are_deduplicated():
    profile = ProfileCreate(
        **payload(skills=["farming", "farming"])
    )
    assert profile.skills == ["farming"]


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        ProfileCreate(**payload(invented_credit_score=720))


def test_finance_and_viability_have_no_direct_llm_imports():
    for module in ("fin", "viability"):
        for path in (APP_DIR / module).rglob("*.py"):
            tree = ast.parse(path.read_text())

            for node in ast.walk(tree):
                roots = []

                if isinstance(node, ast.Import):
                    roots = [
                        alias.name.split(".")[0]
                        for alias in node.names
                    ]

                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots = [node.module.split(".")[0]]

                assert not FORBIDDEN_IMPORTS.intersection(roots), (
                    f"Forbidden LLM import in {path}"
                )
EOF

cat > frontend/package.json <<'EOF'
{
  "name": "graminsetu-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "lucide-react": "^0.468.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.4",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.49",
    "tailwindcss": "^3.4.17",
    "vite": "^6.0.5"
  }
}
EOF

cat > frontend/index.html <<'EOF'
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta
      name="description"
      content="GraminSetu — local business guidance for rural entrepreneurs."
    />
    <meta name="theme-color" content="#176448" />
    <title>GraminSetu | Your village. Your enterprise.</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
EOF

cat > frontend/vite.config.js <<'EOF'
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
EOF

cat > frontend/tailwind.config.js <<'EOF'
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        forest: "#176448",
        ink: "#21392e",
        cream: "#f7f8f2",
        lime: "#dcecaf",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
EOF

cat > frontend/postcss.config.js <<'EOF'
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
EOF

cat > frontend/src/main.jsx <<'EOF'
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
EOF

cat > frontend/src/api.js <<'EOF'
export async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);

  try {
    const response = await fetch(`/api${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
      signal: controller.signal,
    });

    const body = await response.json().catch(() => null);

    if (!response.ok) {
      const detail = body?.detail;

      const message = Array.isArray(detail)
        ? detail
            .map((item) => `${item.loc?.slice(1).join(".")}: ${item.msg}`)
            .join("; ")
        : typeof detail === "string"
          ? detail
          : `Request failed (${response.status}).`;

      throw new Error(message);
    }

    return body;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("The server took too long. Please try again.");
    }

    if (error instanceof TypeError) {
      throw new Error(
        "Cannot reach the backend. Check that FastAPI is running."
      );
    }

    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

// Parse decimal text using integer operations, never parseFloat.
export function rupeesToPaise(input) {
  const value = String(input).trim();

  if (!/^\d{1,9}(\.\d{1,2})?$/.test(value)) {
    throw new Error(
      "Enter capital as a number with up to two decimal places, without commas."
    );
  }

  const [rupees, fraction = ""] = value.split(".");
  const paise =
    BigInt(rupees) * 100n +
    BigInt(fraction.padEnd(2, "0"));

  if (paise > 10_000_000_000n) {
    throw new Error("Capital exceeds the supported MVP limit of ₹10 crore.");
  }

  // This limit is well below JavaScript's maximum safe integer.
  return Number(paise);
}

export function formatMoney(paise) {
  const amount = BigInt(paise);
  const rupees = amount / 100n;
  const fraction = amount % 100n;

  const formatted = new Intl.NumberFormat("en-IN").format(rupees);

  return `₹${formatted}${
    fraction ? `.${fraction.toString().padStart(2, "0")}` : ""
  }`;
}
EOF

cat > frontend/src/styles.css <<'EOF'
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  font-family: Inter, system-ui, sans-serif;
  color: #21392e;
  background: #f7f8f2;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
}

body {
  margin: 0;
  min-width: 320px;
}

button,
input,
select {
  font: inherit;
}

button {
  -webkit-tap-highlight-color: transparent;
}

button:focus-visible,
a:focus-visible {
  outline: 3px solid #8dac56;
  outline-offset: 4px;
}

::selection {
  background: #dcecaf;
}

@layer components {
  .card {
    @apply rounded-3xl border border-stone-200/80 bg-white p-5 shadow-sm sm:p-7;
  }

  .field {
    @apply mt-2 w-full rounded-xl border border-stone-300 bg-white px-4 py-3
      text-sm text-ink outline-none transition
      focus:border-forest focus:ring-2 focus:ring-forest/15
      disabled:bg-stone-100 disabled:text-stone-400;
  }

  .label {
    @apply block text-sm font-semibold text-ink;
  }

  .btn-primary {
    @apply inline-flex min-h-12 items-center justify-center gap-2
      rounded-xl bg-forest px-5 py-3 text-sm font-semibold text-white
      transition hover:bg-[#104e37]
      disabled:cursor-not-allowed disabled:opacity-50;
  }

  .btn-secondary {
    @apply inline-flex min-h-12 items-center justify-center gap-2
      rounded-xl border border-stone-300 bg-white px-5 py-3
      text-sm font-semibold text-ink transition hover:bg-stone-50;
  }

  .eyebrow {
    @apply text-xs font-bold uppercase tracking-[0.18em] text-forest;
  }
}

.hero-pattern {
  background-image:
    radial-gradient(circle at 82% 25%, #dcecaf 0, transparent 33%),
    radial-gradient(circle at 10% 95%, #e1ecdc 0, transparent 38%);
}

.fade-in {
  animation: fade-in 240ms ease-out;
}

@keyframes fade-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .fade-in {
    animation: none;
  }
}
EOF

cat > frontend/src/App.jsx <<'EOF'
import { useEffect, useState } from "react";

import {
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  Building2,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Database,
  FileText,
  IndianRupee,
  Leaf,
  LoaderCircle,
  MapPin,
  RefreshCw,
  ShieldCheck,
  Sprout,
  TrendingUp,
  UserRound,
  Wallet,
} from "lucide-react";

import { api, formatMoney, rupeesToPaise } from "./api";

const SKILLS = [
  ["farming", "Farming"],
  ["basic_machine_operation", "Machine operation"],
  ["animal_husbandry", "Animal husbandry"],
  ["tailoring", "Tailoring"],
  ["retail_sales", "Retail & sales"],
  ["food_processing", "Food processing"],
  ["bookkeeping", "Bookkeeping"],
];

const INITIAL_FORM = {
  applicant_name: "",
  preferred_language: "en",
  capital_rupees: "",
  skills: [],
  premises: "not_arranged",
  power: "unknown",
};

const STEPS = [
  { title: "Your village", note: "Choose your location", icon: MapPin },
  { title: "Your profile", note: "Skills and investment", icon: UserRound },
  { title: "Assessment", note: "Review saved details", icon: FileText },
];

const PREMISES_LABELS = {
  owned: "Owned premises",
  rented: "Rented premises",
  not_arranged: "Not arranged yet",
};

const POWER_LABELS = {
  single_phase: "Single-phase",
  three_phase: "Three-phase",
  unavailable: "No connection",
  unknown: "Needs verification",
};

function readSavedId() {
  try {
    return localStorage.getItem("graminsetu_assessment_id");
  } catch {
    return null;
  }
}

function writeSavedId(id) {
  try {
    if (id) {
      localStorage.setItem("graminsetu_assessment_id", id);
    } else {
      localStorage.removeItem("graminsetu_assessment_id");
    }
  } catch {
    // Storage may be disabled; the current session still works.
  }
}

function App() {
  const [step, setStep] = useState(0);
  const [district, setDistrict] = useState("Nashik");
  const [villageId, setVillageId] = useState("");
  const [villages, setVillages] = useState([]);
  const [form, setForm] = useState(INITIAL_FORM);
  const [assessment, setAssessment] = useState(null);

  const [health, setHealth] = useState("checking");
  const [loading, setLoading] = useState(true);
  const [restoring, setRestoring] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;

    setLoading(true);
    setLoadError("");

    Promise.all([api("/health"), api("/villages")])
      .then(([status, records]) => {
        if (cancelled) return;
        setHealth(status.database === "connected" ? "online" : "offline");
        setVillages(records);
      })
      .catch((err) => {
        if (cancelled) return;
        setHealth("offline");
        setLoadError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  useEffect(() => {
    let cancelled = false;
    const savedId = readSavedId();

    if (!savedId) {
      setRestoring(false);
      return;
    }

    api(`/assessments/${savedId}`)
      .then((saved) => {
        if (cancelled) return;
        setAssessment(saved);
        setStep(2);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(`Could not restore the previous assessment. ${err.message}`);
        }
      })
      .finally(() => {
        if (!cancelled) setRestoring(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const districtVillages = villages.filter(
    (village) => village.district === district
  );

  const selectedVillage = villages.find(
    (village) => village.id === villageId
  );

  function updateForm(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function toggleSkill(skill) {
    setForm((current) => ({
      ...current,
      skills: current.skills.includes(skill)
        ? current.skills.filter((item) => item !== skill)
        : [...current.skills, skill],
    }));
  }

  function startNew() {
    writeSavedId(null);
    setAssessment(null);
    setForm(INITIAL_FORM);
    setVillageId("");
    setError("");
    setStep(0);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function saveProfile(event) {
    event.preventDefault();
    setError("");

    if (!selectedVillage) {
      setError("Choose a village before saving your profile.");
      setStep(0);
      return;
    }

    setSaving(true);

    try {
      const ownCapitalPaise = rupeesToPaise(form.capital_rupees);

      const saved = await api("/assessments", {
        method: "POST",
        body: JSON.stringify({
          applicant_name: form.applicant_name.trim(),
          village_id: villageId,
          preferred_language: form.preferred_language,
          own_capital_paise: ownCapitalPaise,
          skills: form.skills,
          premises: form.premises,
          power: form.power,
        }),
      });

      writeSavedId(saved.id);
      setAssessment(saved);
      setStep(2);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-stone-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4 sm:px-8">
          <a href="/" className="flex items-center gap-3" aria-label="GraminSetu home">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-forest text-lime">
              <Sprout size={25} strokeWidth={1.8} />
            </div>

            <div>
              <div className="text-xl font-extrabold tracking-tight">
                Gramin<span className="text-forest">Setu</span>
              </div>
              <div className="text-[11px] text-stone-500">
                गांव से उद्यम तक
              </div>
            </div>
          </a>

          <div className="flex items-center gap-3">
            <span className="hidden rounded-full bg-stone-100 px-3 py-1.5 text-xs font-medium text-stone-600 sm:block">
              Maharashtra pilot
            </span>

            <span className="flex items-center gap-2 text-xs text-stone-600">
              <span
                className={`h-2 w-2 rounded-full ${
                  health === "online"
                    ? "bg-emerald-500"
                    : health === "offline"
                      ? "bg-red-400"
                      : "bg-amber-400"
                }`}
              />
              <span className="hidden sm:inline">
                {health === "online"
                  ? "Backend connected"
                  : health === "offline"
                    ? "Backend offline"
                    : "Connecting"}
              </span>
              <span className="sm:hidden">
                {health === "online" ? "Online" : "Dev build"}
              </span>
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-8 sm:py-9">
        <section className="hero-pattern relative mb-8 overflow-hidden rounded-[28px] border border-[#e1e7d5] bg-[#edf2e4] p-6 sm:p-9">
          <div className="relative z-10 max-w-2xl">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-forest/15 bg-white/70 px-3 py-1.5 text-xs font-semibold text-forest">
              <Leaf size={14} />
              Local context. Clear next steps.
            </div>

            <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
              Your village.
              <br className="sm:hidden" /> Your next opportunity.
            </h1>

            <p className="mt-3 max-w-xl text-sm leading-7 text-[#526353] sm:text-base">
              Start with your location, skills and available capital.
              Build a business plan grounded in your circumstances.
            </p>

            <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-xs font-medium text-forest">
              <span className="flex items-center gap-1.5">
                <ShieldCheck size={15} /> Transparent assumptions
              </span>
              <span className="flex items-center gap-1.5">
                <IndianRupee size={15} /> No fee in this demo
              </span>
              <span className="flex items-center gap-1.5">
                <MapPin size={15} /> Nashik & Jalgaon
              </span>
            </div>
          </div>

          <Sprout
            className="absolute -bottom-10 right-6 hidden rotate-12 text-forest/10 lg:block"
            size={240}
            strokeWidth={1}
            aria-hidden="true"
          />
        </section>

        <div className="grid items-start gap-7 lg:grid-cols-[260px_minmax(0,1fr)]">
          <aside className="space-y-5">
            <div className="card !p-4 sm:!p-5">
              <p className="mb-5 hidden text-xs font-bold uppercase tracking-widest text-stone-400 lg:block">
                Your assessment
              </p>

              <ol className="grid grid-cols-3 gap-2 lg:grid-cols-1 lg:gap-3">
                {STEPS.map((item, index) => {
                  const Icon = item.icon;
                  const active = step === index;
                  const complete = step > index;

                  return (
                    <li
                      key={item.title}
                      aria-current={active ? "step" : undefined}
                      className={`flex flex-col items-center gap-2 rounded-2xl px-2 py-3 text-center lg:flex-row lg:gap-3 lg:px-3 lg:text-left ${
                        active ? "bg-forest/7" : ""
                      }`}
                    >
                      <div
                        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                          active
                            ? "bg-forest text-white"
                            : complete
                              ? "bg-lime/60 text-forest"
                              : "bg-stone-100 text-stone-400"
                        }`}
                      >
                        {complete ? <Check size={18} /> : <Icon size={18} />}
                      </div>

                      <div>
                        <p
                          className={`text-xs font-semibold lg:text-sm ${
                            active ? "text-forest" : "text-stone-600"
                          }`}
                        >
                          {item.title}
                        </p>
                        <p className="mt-1 hidden text-xs text-stone-400 lg:block">
                          {item.note}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>

            <div className="hidden rounded-2xl border border-stone-200 bg-white/60 p-5 lg:block">
              <CircleHelp size={20} className="mb-3 text-forest" />
              <h3 className="text-sm font-semibold">Designed to explain, not guess.</h3>
              <p className="mt-2 text-xs leading-6 text-stone-500">
                Missing local evidence will be shown as missing—not silently
                converted into a confident recommendation.
              </p>
            </div>

            <div className="hidden px-2 text-xs leading-6 text-stone-400 lg:block">
              Development build 0.1
              <br />
              Profile capture is live.
              <br />
              Advisory modules are coming next.
            </div>
          </aside>

          <div className="min-w-0 space-y-5">
            {(error || loadError) && (
              <div
                role="alert"
                className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
              >
                <p>{error || loadError}</p>

                {loadError && (
                  <button
                    type="button"
                    onClick={() => setReloadKey((value) => value + 1)}
                    className="mt-3 inline-flex items-center gap-2 font-semibold"
                  >
                    <RefreshCw size={15} /> Retry connection
                  </button>
                )}
              </div>
            )}

            {restoring ? (
              <div className="card flex items-center gap-3 text-sm text-stone-500">
                <LoaderCircle className="animate-spin" size={20} />
                Checking for a saved assessment…
              </div>
            ) : (
              <>
                {step === 0 && (
                  <section className="card fade-in">
                    <p className="eyebrow">Step 01 / Location</p>
                    <h2 className="mt-2 text-2xl font-bold tracking-tight">
                      Where will you start?
                    </h2>
                    <p className="mt-2 text-sm leading-6 text-stone-500">
                      Location will anchor the market, input and infrastructure
                      evidence used in your assessment.
                    </p>

                    <div className="my-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-6 text-amber-900">
                      <strong>Demo geography:</strong> the village options below
                      are development fixtures, not verified LGD records.
                      No local market statistics are attached yet.
                    </div>

                    <div className="grid gap-5 sm:grid-cols-2">
                      <div>
                        <label className="label" htmlFor="state">State</label>
                        <input
                          id="state"
                          className="field"
                          value="Maharashtra"
                          disabled
                        />
                      </div>

                      <div>
                        <label className="label" htmlFor="district">District</label>
                        <select
                          id="district"
                          className="field"
                          value={district}
                          onChange={(event) => {
                            setDistrict(event.target.value);
                            setVillageId("");
                          }}
                        >
                          <option>Nashik</option>
                          <option>Jalgaon</option>
                        </select>
                      </div>
                    </div>

                    <fieldset className="mt-6">
                      <legend className="label">Choose a demo village</legend>

                      {loading ? (
                        <div className="mt-4 flex items-center gap-2 text-sm text-stone-500">
                          <LoaderCircle size={17} className="animate-spin" />
                          Loading locations…
                        </div>
                      ) : districtVillages.length === 0 ? (
                        <p className="mt-4 text-sm text-stone-500">
                          No records loaded. Check the backend connection.
                        </p>
                      ) : (
                        <div className="mt-3 grid gap-3 sm:grid-cols-2">
                          {districtVillages.map((village) => {
                            const selected = villageId === village.id;

                            return (
                              <label
                                key={village.id}
                                className={`flex cursor-pointer items-center gap-3 rounded-2xl border p-4 transition ${
                                  selected
                                    ? "border-forest bg-forest/5"
                                    : "border-stone-200 hover:border-forest/40"
                                }`}
                              >
                                <input
                                  type="radio"
                                  name="village"
                                  value={village.id}
                                  checked={selected}
                                  onChange={() => setVillageId(village.id)}
                                  className="h-4 w-4 accent-[#176448]"
                                />

                                <div className="min-w-0 flex-1">
                                  <div className="text-sm font-semibold">
                                    {village.name}
                                  </div>
                                  <div className="mt-1 text-xs text-stone-500">
                                    {village.district} · Demo fixture
                                  </div>
                                </div>

                                <MapPin size={18} className="shrink-0 text-forest" />
                              </label>
                            );
                          })}
                        </div>
                      )}
                    </fieldset>

                    <div className="mt-8 flex justify-end border-t border-stone-100 pt-5">
                      <button
                        type="button"
                        className="btn-primary w-full sm:w-auto"
                        disabled={!selectedVillage || loading}
                        onClick={() => {
                          setError("");
                          setStep(1);
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                      >
                        Continue to your profile <ArrowRight size={17} />
                      </button>
                    </div>
                  </section>
                )}

                {step === 1 && (
                  <form onSubmit={saveProfile} className="card fade-in">
                    <p className="eyebrow">Step 02 / Entrepreneur profile</p>
                    <h2 className="mt-2 text-2xl font-bold tracking-tight">
                      Tell us about your starting point.
                    </h2>
                    <p className="mt-2 text-sm leading-6 text-stone-500">
                      It is okay to start small. Enter what you have today—not
                      what you hope a bank will approve.
                    </p>

                    <div className="mt-5 inline-flex items-center gap-2 rounded-full bg-stone-100 px-3 py-2 text-xs text-stone-600">
                      <MapPin size={14} />
                      {selectedVillage?.name}, {selectedVillage?.district}
                    </div>

                    <div className="mt-6 grid gap-5 sm:grid-cols-2">
                      <div>
                        <label className="label" htmlFor="name">
                          Applicant name
                        </label>
                        <input
                          id="name"
                          className="field"
                          placeholder="Use a demo name for testing"
                          autoComplete="name"
                          required
                          minLength={2}
                          maxLength={100}
                          value={form.applicant_name}
                          onChange={(event) =>
                            updateForm("applicant_name", event.target.value)
                          }
                        />
                      </div>

                      <div>
                        <label className="label" htmlFor="language">
                          Preferred advisory language
                        </label>
                        <select
                          id="language"
                          className="field"
                          value={form.preferred_language}
                          onChange={(event) =>
                            updateForm("preferred_language", event.target.value)
                          }
                        >
                          <option value="en">English</option>
                          <option value="mr">मराठी — Marathi</option>
                          <option value="hi">हिन्दी — Hindi</option>
                        </select>
                        <p className="mt-2 text-xs text-stone-400">
                          Preference saved; translation is not connected yet.
                        </p>
                      </div>

                      <div className="sm:col-span-2">
                        <label className="label" htmlFor="capital">
                          Your own available capital
                        </label>

                        <div className="relative">
                          <span className="pointer-events-none absolute left-4 top-[21px] text-stone-500">
                            ₹
                          </span>
                          <input
                            id="capital"
                            className="field !pl-9"
                            inputMode="decimal"
                            placeholder="50000"
                            required
                            maxLength={12}
                            pattern="[0-9]{1,9}([.][0-9]{1,2})?"
                            title="Enter rupees without commas, with up to two decimal places."
                            value={form.capital_rupees}
                            onChange={(event) =>
                              updateForm("capital_rupees", event.target.value)
                            }
                          />
                        </div>

                        <p className="mt-2 text-xs leading-5 text-stone-500">
                          Savings you can contribute. Exclude loans and expected
                          subsidies. Enter 0 if no funds are available.
                        </p>
                      </div>
                    </div>

                    <fieldset className="mt-6">
                      <legend className="label">Skills you already have</legend>
                      <p className="mt-1 text-xs text-stone-500">
                        Select all that apply. You may leave this empty.
                      </p>

                      <div className="mt-3 flex flex-wrap gap-2">
                        {SKILLS.map(([id, label]) => {
                          const selected = form.skills.includes(id);

                          return (
                            <button
                              key={id}
                              type="button"
                              aria-pressed={selected}
                              onClick={() => toggleSkill(id)}
                              className={`inline-flex min-h-11 items-center gap-2 rounded-xl border px-3 py-2 text-sm transition ${
                                selected
                                  ? "border-forest bg-forest/5 font-medium text-forest"
                                  : "border-stone-200 text-stone-600 hover:border-forest/40"
                              }`}
                            >
                              {selected && <Check size={14} />}
                              {label}
                            </button>
                          );
                        })}
                      </div>
                    </fieldset>

                    <div className="mt-6 grid gap-5 sm:grid-cols-2">
                      <div>
                        <label className="label" htmlFor="premises">
                          Business premises
                        </label>
                        <select
                          id="premises"
                          className="field"
                          value={form.premises}
                          onChange={(event) =>
                            updateForm("premises", event.target.value)
                          }
                        >
                          {Object.entries(PREMISES_LABELS).map(([id, label]) => (
                            <option key={id} value={id}>{label}</option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="label" htmlFor="power">
                          Electricity at business premises
                        </label>
                        <select
                          id="power"
                          className="field"
                          value={form.power}
                          onChange={(event) =>
                            updateForm("power", event.target.value)
                          }
                        >
                          {Object.entries(POWER_LABELS).map(([id, label]) => (
                            <option key={id} value={id}>{label}</option>
                          ))}
                        </select>
                      </div>
                    </div>

                    <div className="mt-6 flex items-start gap-3 rounded-xl bg-stone-50 p-4">
                      <ShieldCheck size={19} className="mt-0.5 shrink-0 text-forest" />
                      <p className="text-xs leading-6 text-stone-500">
                        This local development build has no authentication.
                        Use test information only. We do not need Aadhaar,
                        bank account numbers or credit reports.
                      </p>
                    </div>

                    <div className="mt-7 flex flex-col-reverse gap-3 border-t border-stone-100 pt-5 sm:flex-row sm:justify-between">
                      <button
                        type="button"
                        className="btn-secondary"
                        disabled={saving}
                        onClick={() => {
                          setError("");
                          setStep(0);
                        }}
                      >
                        <ArrowLeft size={16} /> Back
                      </button>

                      <button
                        type="submit"
                        className="btn-primary"
                        disabled={saving}
                      >
                        {saving ? (
                          <>
                            <LoaderCircle size={17} className="animate-spin" />
                            Saving profile…
                          </>
                        ) : (
                          <>
                            Save assessment <ArrowRight size={17} />
                          </>
                        )}
                      </button>
                    </div>
                  </form>
                )}

                {step === 2 && assessment && (
                  <AssessmentSummary
                    assessment={assessment}
                    onStartNew={startNew}
                  />
                )}
              </>
            )}

            <div className="grid gap-3 sm:grid-cols-3">
              <FeatureNote
                icon={MapPin}
                title="Local viability"
                description="Evidence-backed ranking"
              />
              <FeatureNote
                icon={Wallet}
                title="Capital planning"
                description="Affordability before borrowing"
              />
              <FeatureNote
                icon={FileText}
                title="Project report"
                description="Traceable financial assumptions"
              />
            </div>

            <p className="text-center text-[11px] leading-5 text-stone-400">
              The three advisory modules above are planned, not active in this
              build. GraminSetu is not a lender and does not guarantee approval.
            </p>
          </div>
        </div>
      </main>

      <footer className="mx-auto mt-6 flex max-w-7xl flex-col gap-2 border-t border-stone-200 px-4 py-6 text-xs text-stone-400 sm:flex-row sm:justify-between sm:px-8">
        <p>GraminSetu · Built for rural enterprise</p>
        <p>SIH prototype · Development environment · v0.1</p>
      </footer>
    </div>
  );
}

function FeatureNote({ icon: Icon, title, description }) {
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-stone-200/70 bg-white/50 p-4">
      <Icon size={18} className="mt-0.5 shrink-0 text-forest/70" />
      <div>
        <p className="text-xs font-semibold">{title}</p>
        <p className="mt-1 text-[11px] leading-5 text-stone-500">
          {description}
        </p>
      </div>
    </div>
  );
}

function AssessmentSummary({ assessment, onStartNew }) {
  const { profile, village } = assessment;

  const skillNames = profile.skills.map(
    (skill) => SKILLS.find(([id]) => id === skill)?.[1] || skill
  );

  return (
    <section className="card fade-in">
      <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-lime/60 text-forest">
        <CheckCircle2 size={29} />
      </div>

      <p className="eyebrow">Profile saved successfully</p>
      <h2 className="mt-2 text-2xl font-bold tracking-tight">
        Your starting point is ready, {profile.applicant_name}.
      </h2>

      <p className="mt-2 text-sm leading-6 text-stone-500">
        This assessment is stored in PostgreSQL. Refreshing this browser will
        restore it using the saved assessment ID.
      </p>

      <dl className="mt-6 grid gap-4 sm:grid-cols-2">
        <SummaryItem
          icon={MapPin}
          label="Location"
          value={`${village.name}, ${village.district}`}
        />
        <SummaryItem
          icon={IndianRupee}
          label="Own contribution available"
          value={formatMoney(profile.own_capital_paise)}
        />
        <SummaryItem
          icon={Building2}
          label="Premises"
          value={PREMISES_LABELS[profile.premises]}
        />
        <SummaryItem
          icon={BadgeCheck}
          label="Power — self-reported"
          value={POWER_LABELS[profile.power]}
        />
      </dl>

      <div className="mt-4 rounded-2xl border border-stone-200 p-4">
        <p className="text-xs font-medium text-stone-500">Selected skills</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {skillNames.length ? (
            skillNames.map((skill) => (
              <span
                key={skill}
                className="rounded-lg bg-forest/5 px-3 py-1.5 text-xs font-medium text-forest"
              >
                {skill}
              </span>
            ))
          ) : (
            <span className="text-sm text-stone-500">
              No skills selected; this is not a credit rejection.
            </span>
          )}
        </div>
      </div>

      <div className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 p-4">
        <p className="text-sm font-semibold text-amber-900">
          No recommendation has been computed yet.
        </p>
        <p className="mt-2 text-xs leading-6 text-amber-900/80">
          Geography is still demo-only. The next build adds business archetypes,
          evidence-aware viability scoring and then deterministic financing.
          No score, subsidy or loan approval is implied by saving this profile.
        </p>
      </div>

      <div className="mt-6 space-y-3">
        <ModuleStatus
          title="Profile capture & database"
          subtitle="Validated input, persisted assessment"
          ready
        />
        <ModuleStatus
          title="Local evidence & business ranking"
          subtitle="Next implementation batch"
        />
        <ModuleStatus
          title="Finance engine & DPR"
          subtitle="Pending validated assumptions and finance tests"
        />
      </div>

      <div className="mt-6 flex items-start gap-2 rounded-xl bg-stone-50 p-3">
        <Database size={15} className="mt-0.5 shrink-0 text-stone-400" />
        <div className="min-w-0">
          <p className="text-[11px] text-stone-500">Assessment ID</p>
          <code className="break-all text-xs text-stone-600">
            {assessment.id}
          </code>
        </div>
      </div>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-between">
        <button type="button" className="btn-secondary" onClick={onStartNew}>
          Start another assessment
        </button>

        <a
          href="http://localhost:8000/docs"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center justify-center gap-2 px-3 py-3 text-sm font-medium text-forest"
        >
          Explore backend API <ChevronRight size={16} />
        </a>
      </div>
    </section>
  );
}

function SummaryItem({ icon: Icon, label, value }) {
  return (
    <div className="rounded-2xl border border-stone-200 p-4">
      <dt className="flex items-center gap-2 text-xs text-stone-500">
        <Icon size={15} /> {label}
      </dt>
      <dd className="mt-2 text-sm font-semibold">{value}</dd>
    </div>
  );
}

function ModuleStatus({ title, subtitle, ready = false }) {
  return (
    <div className="flex items-center gap-3">
      <div
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${
          ready ? "bg-forest/10 text-forest" : "bg-stone-100 text-stone-400"
        }`}
      >
        {ready ? <Check size={17} /> : <TrendingUp size={17} />}
      </div>

      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-0.5 text-xs text-stone-500">{subtitle}</p>
      </div>

      <span
        className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold ${
          ready ? "bg-forest/10 text-forest" : "bg-stone-100 text-stone-500"
        }`}
      >
        {ready ? "LIVE" : "NEXT"}
      </span>
    </div>
  );
}

export default App;
EOF

echo ""
echo "GraminSetu Batch 1 files created."
echo "Next: start PostgreSQL, install backend/frontend dependencies, run both servers."
