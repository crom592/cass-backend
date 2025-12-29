"""
Tests for Authentication and Authorization

Tests cover:
- User login with credentials
- JWT token generation and validation
- Token expiration handling
- Current user retrieval
- Role-based access control
- Invalid credential handling
- Inactive user access denial
"""
import pytest
from datetime import datetime, timedelta
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt

from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    decode_access_token
)
from app.core.config import settings
from app.models.user import User, UserRole
from tests.conftest import UserFactory, TenantFactory


# -----------------------------------------------------------------------------
# Password Hashing Tests
# -----------------------------------------------------------------------------

class TestPasswordHashing:
    """Tests for password hashing and verification."""

    def test_password_hash_creates_different_hash(self):
        """Test that hashing the same password creates different hashes."""
        password = "testpassword123"
        hash1 = get_password_hash(password)
        hash2 = get_password_hash(password)

        # Hashes should be different (salt-based)
        assert hash1 != hash2

    def test_verify_password_correct(self):
        """Test that correct password verifies successfully."""
        password = "testpassword123"
        hashed = get_password_hash(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test that incorrect password fails verification."""
        password = "testpassword123"
        hashed = get_password_hash(password)

        assert verify_password("wrongpassword", hashed) is False

    def test_verify_password_empty(self):
        """Test that empty password fails verification."""
        password = "testpassword123"
        hashed = get_password_hash(password)

        assert verify_password("", hashed) is False


# -----------------------------------------------------------------------------
# JWT Token Tests
# -----------------------------------------------------------------------------

class TestJWTTokens:
    """Tests for JWT token creation and validation."""

    def test_create_access_token_default_expiry(self):
        """Test creating token with default expiry."""
        data = {"sub": "user123", "email": "test@example.com"}
        token = create_access_token(data)

        assert token is not None
        assert isinstance(token, str)

        # Decode and verify
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "user123"
        assert payload["email"] == "test@example.com"

    def test_create_access_token_custom_expiry(self):
        """Test creating token with custom expiry."""
        data = {"sub": "user123"}
        expires_delta = timedelta(hours=1)
        token = create_access_token(data, expires_delta=expires_delta)

        payload = decode_access_token(token)
        assert payload is not None

        # Check expiry is within expected range
        exp_timestamp = payload["exp"]
        exp_datetime = datetime.fromtimestamp(exp_timestamp)
        expected = datetime.utcnow() + timedelta(hours=1)

        # Allow 1 minute tolerance
        assert abs((exp_datetime - expected).total_seconds()) < 60

    def test_decode_expired_token(self):
        """Test that expired tokens return None."""
        data = {"sub": "user123"}
        expires_delta = timedelta(seconds=-10)  # Already expired

        token = create_access_token(data, expires_delta=expires_delta)
        payload = decode_access_token(token)

        assert payload is None

    def test_decode_invalid_token(self):
        """Test that invalid tokens return None."""
        payload = decode_access_token("invalid.token.here")

        assert payload is None

    def test_decode_tampered_token(self):
        """Test that tampered tokens return None."""
        data = {"sub": "user123"}
        token = create_access_token(data)

        # Tamper with the token
        tampered_token = token[:-5] + "XXXXX"
        payload = decode_access_token(tampered_token)

        assert payload is None

    def test_token_contains_role(self):
        """Test that token includes role information."""
        data = {"sub": "user123", "role": "admin"}
        token = create_access_token(data)

        payload = decode_access_token(token)
        assert payload["role"] == "admin"


# -----------------------------------------------------------------------------
# Login Endpoint Tests
# -----------------------------------------------------------------------------

class TestLoginEndpoint:
    """Tests for the login endpoint."""

    @pytest.mark.asyncio
    async def test_login_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant
    ):
        """Test successful login with valid credentials."""
        # Create a user with known password
        user = await UserFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            email="logintest@test.com",
            password="correctpassword",
            role=UserRole.ADMIN
        )

        response = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "logintest@test.com",
                "password": "correctpassword"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant
    ):
        """Test login with wrong password."""
        await UserFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            email="wrongpass@test.com",
            password="correctpassword"
        )

        response = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "wrongpass@test.com",
                "password": "wrongpassword"
            }
        )

        assert response.status_code == 401
        assert "Incorrect email or password" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_user_not_found(
        self,
        client: AsyncClient
    ):
        """Test login with non-existent user."""
        response = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "nonexistent@test.com",
                "password": "somepassword"
            }
        )

        assert response.status_code == 401
        assert "Incorrect email or password" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_inactive_user(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant
    ):
        """Test login with inactive user account."""
        await UserFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            email="inactive@test.com",
            password="correctpassword",
            is_active=False
        )

        response = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "inactive@test.com",
                "password": "correctpassword"
            }
        )

        assert response.status_code == 403
        assert "inactive" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_login_empty_password(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant
    ):
        """Test login with empty password."""
        await UserFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            email="emptypass@test.com",
            password="correctpassword"
        )

        response = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "emptypass@test.com",
                "password": ""
            }
        )

        assert response.status_code == 401


# -----------------------------------------------------------------------------
# Current User Endpoint Tests
# -----------------------------------------------------------------------------

class TestCurrentUserEndpoint:
    """Tests for the /me endpoint."""

    @pytest.mark.asyncio
    async def test_get_current_user(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        admin_user: User
    ):
        """Test getting current user profile."""
        response = await client.get(
            "/api/v1/auth/me",
            headers=auth_headers_admin
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == admin_user.id
        assert data["email"] == admin_user.email
        assert data["role"] == admin_user.role.value

    @pytest.mark.asyncio
    async def test_get_current_user_unauthorized(
        self,
        client: AsyncClient
    ):
        """Test /me without authentication."""
        response = await client.get("/api/v1/auth/me")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_invalid_token(
        self,
        client: AsyncClient
    ):
        """Test /me with invalid token."""
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"}
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_expired_token(
        self,
        client: AsyncClient,
        admin_user: User
    ):
        """Test /me with expired token."""
        # Create an expired token
        expired_token = create_access_token(
            data={"sub": admin_user.id},
            expires_delta=timedelta(seconds=-10)
        )

        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"}
        )

        assert response.status_code == 401


# -----------------------------------------------------------------------------
# Role-Based Access Tests
# -----------------------------------------------------------------------------

class TestRoleBasedAccess:
    """Tests for role-based access control."""

    @pytest.mark.asyncio
    async def test_admin_role_in_token(
        self,
        admin_token: str
    ):
        """Test that admin token contains admin role."""
        payload = decode_access_token(admin_token)
        assert payload["role"] == "admin"

    @pytest.mark.asyncio
    async def test_engineer_role_in_token(
        self,
        engineer_token: str
    ):
        """Test that engineer token contains engineer role."""
        payload = decode_access_token(engineer_token)
        assert payload["role"] == "as_engineer"

    @pytest.mark.asyncio
    async def test_viewer_role_in_token(
        self,
        viewer_token: str
    ):
        """Test that viewer token contains viewer role."""
        payload = decode_access_token(viewer_token)
        assert payload["role"] == "viewer"

    @pytest.mark.asyncio
    async def test_all_roles_can_access_me(
        self,
        client: AsyncClient,
        auth_headers_admin: dict,
        auth_headers_engineer: dict,
        auth_headers_viewer: dict
    ):
        """Test that all roles can access their profile."""
        for headers in [auth_headers_admin, auth_headers_engineer, auth_headers_viewer]:
            response = await client.get(
                "/api/v1/auth/me",
                headers=headers
            )
            assert response.status_code == 200


# -----------------------------------------------------------------------------
# Token Validation Edge Cases
# -----------------------------------------------------------------------------

class TestTokenValidationEdgeCases:
    """Tests for edge cases in token validation."""

    @pytest.mark.asyncio
    async def test_token_with_missing_sub(
        self,
        client: AsyncClient
    ):
        """Test token without subject claim."""
        # Create a token without 'sub' field
        token = jwt.encode(
            {"email": "test@example.com", "exp": datetime.utcnow() + timedelta(hours=1)},
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM
        )

        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_token_for_deleted_user(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant
    ):
        """Test token for a user that no longer exists."""
        # Create and delete a user
        user = await UserFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            email="deleted@test.com"
        )

        token = create_access_token(
            data={"sub": user.id, "email": user.email, "role": user.role.value}
        )

        # Delete the user
        await db_session.delete(user)
        await db_session.commit()

        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_token_with_bearer_prefix_variations(
        self,
        client: AsyncClient,
        admin_token: str
    ):
        """Test various Bearer prefix formats."""
        # Correct format
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

        # Missing Bearer prefix
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": admin_token}
        )
        assert response.status_code == 401

        # Wrong prefix
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Token {admin_token}"}
        )
        assert response.status_code == 401


# -----------------------------------------------------------------------------
# User State Tests
# -----------------------------------------------------------------------------

class TestUserStateValidation:
    """Tests for user state validation during authentication."""

    @pytest.mark.asyncio
    async def test_deactivated_user_after_token_issued(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant
    ):
        """Test that deactivated user cannot access API even with valid token."""
        # Create an active user
        user = await UserFactory.create(
            db_session,
            tenant_id=test_tenant.id,
            email="willbedeactivated@test.com",
            is_active=True
        )

        token = create_access_token(
            data={"sub": user.id, "email": user.email, "role": user.role.value}
        )

        # Verify token works initially
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200

        # Deactivate the user
        user.is_active = False
        await db_session.commit()

        # Token should now be rejected
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_different_user_roles_login(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant
    ):
        """Test that users with different roles can login successfully."""
        roles = [
            UserRole.ADMIN,
            UserRole.TENANT_ADMIN,
            UserRole.CALL_CENTER,
            UserRole.AS_MANAGER,
            UserRole.AS_ENGINEER,
            UserRole.VIEWER
        ]

        for role in roles:
            email = f"{role.value}@test.com"
            user = await UserFactory.create(
                db_session,
                tenant_id=test_tenant.id,
                email=email,
                password="password123",
                role=role
            )

            response = await client.post(
                "/api/v1/auth/login",
                data={
                    "username": email,
                    "password": "password123"
                }
            )

            assert response.status_code == 200, f"Login failed for role {role.value}"
            data = response.json()
            assert "access_token" in data

            # Verify the token contains the correct role
            payload = decode_access_token(data["access_token"])
            assert payload["role"] == role.value
