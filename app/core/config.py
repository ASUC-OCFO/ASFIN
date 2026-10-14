from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://asfint:asfint@localhost:5432/asfint"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
