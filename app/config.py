from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379"

    nodemcu_ip: str = ""
    nodemcu_poll_interval: int = 10  # seconds
    nodemcu_auth_user: str = ""
    nodemcu_auth_password: str = ""

    stream_max_len: int = 10000

    model_config = {"env_file": ".env"}


settings = Settings()
