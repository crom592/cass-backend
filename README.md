# TARDIS CASS Backend - Charger After-Service System API

FastAPI-based backend for the TARDIS CASS (Charger After-Service System).

## Tech Stack

- **Framework**: FastAPI 0.104+
- **Database**: PostgreSQL with asyncpg
- **ORM**: SQLAlchemy 2.0 (async)
- **Migration**: Alembic
- **Authentication**: JWT with python-jose
- **File Storage**: AWS S3 / Azure Blob / MinIO
- **Background Tasks**: Celery + Redis (optional)

## Project Structure

```
backend/
├── app/
│   ├── api/v1/          # API endpoints
│   ├── core/            # Core config, database, security
│   ├── models/          # SQLAlchemy models
│   ├── schemas/         # Pydantic schemas
│   ├── services/        # Business logic
│   ├── middleware/      # Custom middleware
│   └── main.py          # FastAPI application
├── alembic/             # Database migrations
├── tests/               # Test files
└── requirements.txt     # Python dependencies
```

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and update values:

```bash
cp .env.example .env
```

Required configuration:
- `DATABASE_URL`: PostgreSQL connection string
- `SECRET_KEY`: JWT secret key
- `CSMS_API_BASE_URL`: CSMS system API URL
- Storage credentials (S3/Azure/MinIO)

### 3. Database Setup

Initialize database and run migrations:

```bash
# Create initial migration (first time only)
alembic revision --autogenerate -m "Initial migration"

# Apply migrations
alembic upgrade head
```

### 4. Run Server

Development:
```bash
uvicorn app.main:app --reload --port 8000
```

Production:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## API Documentation

Once running, access:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Key Features

### Multi-tenancy
All entities are scoped to `tenant_id`. Row-level security ensures data isolation.

### Authentication & RBAC
- JWT-based authentication
- Role-based access control (admin, call_center, as_manager, as_engineer, viewer)
- Token expiration: configurable (default 30 minutes)

### Ticket Management
- Full CRUD operations
- Status state machine with history tracking
- SLA monitoring and breach detection
- Assignment to users or vendors

### CSMS Integration
- Read-only access to charger status
- Event history retrieval
- Firmware job status tracking (CASS tracks, CSMS controls)

### File Attachments
- Presigned URL upload to S3/Azure/MinIO
- Metadata stored in PostgreSQL
- No binary data in database

### Reporting
- Real-time aggregation with date filters
- CSV export
- Pre-computed snapshots for performance (TODO: batch job)

### Audit Logging
- Middleware logs all API requests
- Database audit log for critical changes (TODO: full implementation)

## Database Models

Core entities:
- `Tenant`: Customer organizations
- `User`: System users with roles
- `Site`: Charging station locations
- `Charger`: Individual charging units
- `Ticket`: Service tickets
- `TicketStatusHistory`: State change audit trail
- `Assignment`: Ticket assignments
- `Worklog`: Work logs and notes
- `Attachment`: File metadata
- `CsmsEventRef`: CSMS event references
- `FirmwareJobRef`: Firmware update job tracking
- `SlaPolicy`: SLA rules
- `SlaMeasurement`: SLA measurements per ticket
- `ReportSnapshot`: Pre-computed reports
- `AuditLog`: System audit trail

## Development

### Running Tests

```bash
pytest tests/
```

### Code Formatting

```bash
black app/
```

### Type Checking

```bash
mypy app/
```

## Deployment

See `docker-compose.yml` for containerized deployment with PostgreSQL and Redis.

## TODO / Future Enhancements

- [ ] Background job for SLA calculation
- [ ] Webhook receiver for CSMS events
- [ ] Report snapshot batch job
- [ ] Full audit log implementation
- [ ] Email/SMS notification service
- [ ] Rate limiting
- [ ] OpenAPI client generation
