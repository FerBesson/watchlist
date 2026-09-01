import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

load_dotenv()

# Si se define DATABASE_URL (ej. en la nube con PostgreSQL / Neon / Supabase), la usamos.
# Si no, usamos SQLite local ("watchlists.db").
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./watchlists.db")

# Corregir compatibilidad para URLs tipo postgres:// a postgresql:// si aplica
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
engine_kwargs = {}

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    # Optimización para PostgreSQL en la nube (Neon / Supabase / Render)
    engine_kwargs.update({
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
        "pool_recycle": 300,
        "pool_timeout": 30
    })

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

