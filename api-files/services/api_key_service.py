import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from flask_login import current_user
from flask_sqlalchemy.pagination import Pagination
from sqlalchemy import and_, or_, desc, asc

from extensions.ext_database import db
from models.model import App, AppMode, ApiKey, ApiKeyUsageLog
from services.errors.api_key import (
    ApiKeyNotFoundError,
    ApiKeyExpiredError,
    ApiKeyInactiveError,
    InvalidResourceTypeError,
    DuplicateApiKeyError
)

logger = logging.getLogger(__name__)

class ApiKeyService:

    @staticmethod
    def create_api_key(self,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        resource_name: str,
        validity_type: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        authorized_person: str = "",
        description: str = "",
        created_by: str = "") -> ApiKey:

        """新建密钥"""

        if resource_type not in ["agent-chat", "workflow"]:
            raise InvalidResourceTypeError(f"Invalid resource type: {resource_type}")

        self._validate_resource_exist(tenant_id, resource_type, resource_id)

        key = self._generate_unique_key()

        api_key = ApiKey(
            tenant_id=tenant_id,
            key=key,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            validity_type=validity_type,
            start_date=start_date,
            end_date=end_date,
            authorized_person=authorized_person,
            description=description,
            created_by=created_by or current_user.id,
            updated_by=created_by or current_user.id
        )

        db.session.add(api_key)
        db.session.commit()
        logger.info(f"Created API key: {api_key.id} for {resource_type} {resource_id}")
        return api_key

    @staticmethod
    def get_api_keys(tenant_id: str,
                     page: int = 1,
                     per_page: int = 10,
                     resource_type: Optional[str] = None,
                     resource_name: Optional[str] = None,
                     authorized_person: Optional[str] = None,
                     status: Optional[str] = None
                     ) -> Pagination:

        """
        分页获取密钥列表
        """

        query = db.session.query(ApiKey).filter(ApiKey.tenant_id == tenant_id)

        if resource_type:
            query = query.filter(ApiKey.resource_type == resource_type)

        if resource_name:
            query = query.filter(ApiKey.resource_name.ilike(f"%{resource_name}%"))

        if authorized_person:
            query = query.filter(ApiKey.authorized_person.ilike(f"%{authorized_person}%"))

        if status:
            if status == "active":
                query = query.filter(and_(ApiKey.end_date >= datetime.utcnow(), ApiKey.is_active == True))
            elif status == "expired":
                query = query.filter(
                    and_(
                        ApiKey.validity_type == "limited",
                        ApiKey.end_date < datetime.utcnow()
                    )
                )
            elif status == "inactive":
                query = query.filter(ApiKey.is_active == False)

        query = query.order_by(desc(ApiKey.created_at))

        return db.paginate(query, page=page, per_page=per_page, error_out=False)

    @staticmethod
    def get_api_key(self, tenant_id: str, api_key_id: str) -> ApiKey:

        """
        获取单个密钥详情
        """

        api_key = db.session.query(ApiKey).filter(
            and_(
                ApiKey.tenant_id == tenant_id,
                ApiKey.id == api_key_id
            )
        ).first()

        if not api_key:
            raise ApiKeyNotFoundError(f"API key {api_key_id} not found")

        return api_key

    @staticmethod
    def get_api_key_by_key(self, key: str) -> ApiKey:

        api_key = db.session.query(ApiKey).filter(ApiKey.key == key).first()

        if not api_key:
            raise ApiKeyNotFoundError("API key not found")

        return api_key

    @staticmethod
    def update_api_key(
        self,
        tenant_id: str,
        api_key_id: str,
        **kwargs
    ) -> ApiKey:

        api_key = self.get_api_key(tenant_id, api_key_id)

        # Update fields
        for field, value in kwargs.items():
            if hasattr(api_key, field):
                setattr(api_key, field, value)

        api_key.updated_by = current_user.id
        api_key.updated_at = datetime.utcnow()

        db.session.commit()

        logger.info(f"Updated API key {api_key_id}")
        return api_key

    @staticmethod
    def delete_api_key(self, tenant_id: str, api_key_id: str) -> bool:

        api_key = self.get_api_key(tenant_id, api_key_id)

        db.session.delete(api_key)
        db.session.commit()

        logger.info(f"Deleted API key {api_key_id}")
        return True

    @staticmethod
    def toggle_api_key_status(self, tenant_id: str, api_key_id: str) -> ApiKey:

        api_key = self.get_api_key(tenant_id, api_key_id)
        api_key.is_active = not api_key.is_active
        api_key.updated_by = current_user.id
        api_key.updated_at = datetime.utcnow()

        db.session.commit()

        logger.info(f"Toggled API key {api_key_id} status to {api_key.is_active}")
        return api_key

    @staticmethod
    def validate_api_key(self, key: str) -> ApiKey:

        api_key = self.get_api_key_by_key(key)

        if not api_key.is_active:
            raise ApiKeyInactiveError(f"API key {api_key.id} is inactive")

        if api_key.is_expired:
            raise ApiKeyExpiredError(f"API key {api_key.id} is expired")

        return api_key

    @staticmethod
    def get_resources_for_selection(self, tenant_id: str, resource_type: str) -> List[Dict[str, Any]]:

        resources = []

        if resource_type == "agent-chat":

            apps = db.session.query(App).filter(
                and_(
                    App.tenant_id == tenant_id,
                    App.mode == AppMode.AGENT_CHAT.value
                )
            ).all()

            for app in apps:
                resources.append({
                    "id": app.id,
                    "name": app.name,
                    "description": app.description
                })

        elif resource_type == "workflow":
            # Get workflow apps
            apps = db.session.query(App).filter(
                and_(
                    App.tenant_id == tenant_id,
                    App.mode == AppMode.WORKFLOW.value
                )
            ).all()

            for app in apps:
                resources.append({
                    "id": app.id,
                    "name": app.name,
                    "description": app.description
                })

        return resources

    @staticmethod
    def log_api_key_usage(
        self,
        api_key_id: str,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        request_method: str,
        request_path: str,
        response_status: int,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> None:

        usage_log = ApiKeyUsageLog(
            api_key_id=api_key_id,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            request_method=request_method,
            request_path=request_path,
            response_status=response_status,
            user_agent=user_agent,
            ip_address=ip_address
        )

        db.session.add(usage_log)
        db.session.commit()

    @staticmethod
    def _validate_resource_exists(self, tenant_id: str, resource_type: str, resource_id: str) -> None:

        """
        严重应用是否存在
        """

        if resource_type == "agent":
            app = db.session.query(App).filter(
                and_(
                    App.id == resource_id,
                    App.tenant_id == tenant_id,
                    App.mode == AppMode.AGENT_CHAT.value
                )
            ).first()
            if not app:
                raise InvalidResourceTypeError(f"Agent {resource_id} not found")

        elif resource_type == "workflow":
            app = db.session.query(App).filter(
                and_(
                    App.id == resource_id,
                    App.tenant_id == tenant_id,
                    App.mode == AppMode.WORKFLOW.value
                )
            ).first()
            if not app:
                raise InvalidResourceTypeError(f"Workflow {resource_id} not found")

    @staticmethod
    def _generate_unique_key(self) -> str:

        max_attempts = 10
        for _ in range(max_attempts):
            key = ApiKey.generate_key()
            existing = db.session.query(ApiKey).filter(ApiKey.key == key).first()
            if not existing:
                return key

        raise DuplicateApiKeyError("Failed to generate unique API key")
