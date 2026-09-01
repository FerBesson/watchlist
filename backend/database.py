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
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

