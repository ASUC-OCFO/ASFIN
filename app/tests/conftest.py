import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.main as api_main
from app.api.main import app
from app.core.database import Base, get_db


@pytest.fixture(scope="function")
def db():
    # StaticPool ensures all threads (including the ASGI background thread used
    # by TestClient) share the same in-memory SQLite connection.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db, monkeypatch):
    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    monkeypatch.setattr(api_main, "engine", db.get_bind())
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
