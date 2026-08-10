import json

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.system_config import SystemConfig
from app.services import dmxapi_service


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[SystemConfig.__table__])
    return sessionmaker(bind=engine)()


def test_legacy_model_config_encrypts_keys_and_never_returns_them(monkeypatch):
    db = _database()
    monkeypatch.setattr(
        "app.services.model_governance_service.settings.MODEL_CREDENTIAL_ENCRYPTION_KEY",
        Fernet.generate_key().decode(),
    )
    secret = "legacy-plain-secret"

    dmxapi_service.set_model_config(db, [{
        "id": "legacy-image",
        "name": "Legacy image",
        "type": "image",
        "api_key": secret,
        "api_base_url": "https://provider.example",
    }])

    stored = db.query(SystemConfig).filter_by(config_key="model_legacy-image").one()
    assert secret not in stored.config_value
    assert "api_key_ciphertext" in json.loads(stored.config_value)
    assert dmxapi_service._resolve_model_config(db, "legacy-image")["api_key"] == secret

    public = next(item for item in dmxapi_service.get_available_models(db) if item["id"] == "legacy-image")
    assert public["api_key"] == ""
    assert public["api_key_configured"] is True
    assert public["api_key_masked"].endswith(secret[-4:])


def test_blank_legacy_model_update_preserves_existing_encrypted_key(monkeypatch):
    db = _database()
    monkeypatch.setattr(
        "app.services.model_governance_service.settings.MODEL_CREDENTIAL_ENCRYPTION_KEY",
        Fernet.generate_key().decode(),
    )
    secret = "preserve-this-secret"
    base = {
        "id": "legacy-image",
        "name": "Legacy image",
        "type": "image",
        "api_key": secret,
        "api_base_url": "https://provider.example",
    }
    dmxapi_service.set_model_config(db, [base])

    dmxapi_service.set_model_config(db, [{**base, "name": "Renamed", "api_key": ""}])

    assert dmxapi_service._resolve_model_config(db, "legacy-image")["api_key"] == secret
    stored = db.query(SystemConfig).filter_by(config_key="model_legacy-image").one()
    assert secret not in stored.config_value


def test_plaintext_legacy_rows_are_migrated_in_place(monkeypatch):
    db = _database()
    monkeypatch.setattr(
        "app.services.model_governance_service.settings.MODEL_CREDENTIAL_ENCRYPTION_KEY",
        Fernet.generate_key().decode(),
    )
    secret = "database-legacy-secret"
    db.add(SystemConfig(
        config_key="model_old-chat",
        config_value=json.dumps({
            "id": "old-chat",
            "name": "Old chat",
            "type": "chat",
            "api_key": secret,
            "api_base_url": "https://provider.example",
        }),
    ))
    db.commit()

    result = dmxapi_service.migrate_legacy_model_credentials(db)

    stored = db.query(SystemConfig).filter_by(config_key="model_old-chat").one()
    assert result == {"migrated": 1, "failed": 0}
    assert secret not in stored.config_value
    assert dmxapi_service._resolve_model_config(db, "old-chat")["api_key"] == secret
