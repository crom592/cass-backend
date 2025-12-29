from typing import List, Union, Optional
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )

    # Application
    APP_NAME: str = "CASS"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"

    # Database
    DATABASE_URL: str

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS
    BACKEND_CORS_ORIGINS: List[Union[str, AnyHttpUrl]] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # File Storage
    STORAGE_TYPE: str = "s3"  # s3, azure, minio
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "ap-northeast-2"
    S3_BUCKET_NAME: str = "cass-attachments"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # CSMS Integration
    CSMS_API_BASE_URL: str
    CSMS_API_KEY: str
    CSMS_WEBHOOK_SECRET: str

    # Notification Settings
    NOTIFICATION_ENABLED: bool = True

    # Email/SMTP Settings
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "CASS Notifications"
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_TIMEOUT: int = 30

    # SMS Settings
    SMS_PROVIDER: str = "twilio"  # twilio, aws_sns
    SMS_API_KEY: str = ""
    SMS_API_SECRET: str = ""
    SMS_FROM_NUMBER: str = ""

    # Twilio-specific settings
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""

    # AWS SNS-specific settings
    AWS_SNS_REGION: str = ""
    AWS_SNS_ACCESS_KEY: str = ""
    AWS_SNS_SECRET_KEY: str = ""

    # Notification URLs (for links in emails/SMS)
    FRONTEND_BASE_URL: str = "http://localhost:3000"

    # Monitoring & Performance Settings
    SLOW_QUERY_THRESHOLD_MS: float = 100.0  # Log queries slower than this (milliseconds)
    SLOW_REQUEST_THRESHOLD_MS: float = 1000.0  # Log requests slower than this (milliseconds)
    ENABLE_STRUCTURED_LOGGING: bool = True  # Use JSON structured logging
    ENABLE_PROMETHEUS_METRICS: bool = True  # Enable Prometheus metrics collection
    METRICS_INCLUDE_PATH_PARAMS: bool = False  # Include path params in metrics (can cause cardinality issues)

    @property
    def email_enabled(self) -> bool:
        """Check if email notifications are configured."""
        return bool(self.SMTP_HOST and self.SMTP_USER and self.SMTP_PASSWORD)

    @property
    def sms_enabled(self) -> bool:
        """Check if SMS notifications are configured."""
        if self.SMS_PROVIDER == "twilio":
            return bool(self.TWILIO_ACCOUNT_SID and self.TWILIO_AUTH_TOKEN)
        elif self.SMS_PROVIDER == "aws_sns":
            return bool(self.AWS_SNS_ACCESS_KEY and self.AWS_SNS_SECRET_KEY)
        return False


settings = Settings()
