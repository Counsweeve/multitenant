import enum
import json
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from flask_login import UserMixin
from sqlalchemy import DateTime, String, func, select, Boolean
from sqlalchemy.orm import Mapped, Session, mapped_column, reconstructor

from models.base import Base

from .engine import db
from .types import StringUUID


class TenantAccountRole(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    NORMAL = "normal"
    DATASET_OPERATOR = "dataset_operator"

    @staticmethod
    def is_valid_role(role: str) -> bool:
        if not role:
            return False
        return role in {
            TenantAccountRole.OWNER,
            TenantAccountRole.ADMIN,
            TenantAccountRole.EDITOR,
            TenantAccountRole.NORMAL,
            TenantAccountRole.DATASET_OPERATOR,
        }

    @staticmethod
    def is_privileged_role(role: Optional["TenantAccountRole"]) -> bool:
        if not role:
            return False
        return role in {TenantAccountRole.OWNER, TenantAccountRole.ADMIN}

    @staticmethod
    def is_admin_role(role: Optional["TenantAccountRole"]) -> bool:
        if not role:
            return False
        return role == TenantAccountRole.ADMIN

    @staticmethod
    def is_non_owner_role(role: Optional["TenantAccountRole"]) -> bool:
        if not role:
            return False
        return role in {
            TenantAccountRole.ADMIN,
            TenantAccountRole.EDITOR,
            TenantAccountRole.NORMAL,
            TenantAccountRole.DATASET_OPERATOR,
        }

    @staticmethod
    def is_editing_role(role: Optional["TenantAccountRole"]) -> bool:
        if not role:
            return False
        return role in {TenantAccountRole.OWNER, TenantAccountRole.ADMIN, TenantAccountRole.EDITOR}

    @staticmethod
    def is_dataset_edit_role(role: Optional["TenantAccountRole"]) -> bool:
        if not role:
            return False
        return role in {
            TenantAccountRole.OWNER,
            TenantAccountRole.ADMIN,
            TenantAccountRole.EDITOR,
            TenantAccountRole.DATASET_OPERATOR,
        }


class AccountStatus(enum.StrEnum):
    PENDING = "pending"
    UNINITIALIZED = "uninitialized"
    ACTIVE = "active"
    BANNED = "banned"
    CLOSED = "closed"


class Account(UserMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="account_pkey"),
        sa.Index("account_email_idx", "email"),
        sa.UniqueConstraint("employee_number", name="unique_employee_number")
    )

    id: Mapped[str] = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"))
    user_id: Mapped[str] = mapped_column(String(255))
    employee_number: Mapped[Optional[str]] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    password: Mapped[Optional[str]] = mapped_column(String(255))
    password_salt: Mapped[Optional[str]] = mapped_column(String(255))
    avatar: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    interface_language: Mapped[Optional[str]] = mapped_column(String(255))
    interface_theme: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(255))
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_login_ip: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)
    status: Mapped[str] = mapped_column(String(16), server_default=sa.text("'active'::character varying"))
    initialized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)

    @reconstructor
    def init_on_load(self):
        self.role: Optional[TenantAccountRole] = None
        self._current_tenant: Optional[Tenant] = None

    @property
    def is_password_set(self):
        return self.password is not None

    @property
    def current_tenant(self):
        return self._current_tenant

    @current_tenant.setter
    def current_tenant(self, tenant: "Tenant"):
        with Session(db.engine, expire_on_commit=False) as session:
            tenant_join_query = select(TenantAccountJoin).where(
                TenantAccountJoin.tenant_id == tenant.id, TenantAccountJoin.account_id == self.id
            )
            tenant_join = session.scalar(tenant_join_query)
            tenant_query = select(Tenant).where(Tenant.id == tenant.id)
            # TODO: A workaround to reload the tenant with `expire_on_commit=False`, allowing
            # access to it after the session has been closed.
            # This prevents `DetachedInstanceError` when accessing the tenant outside
            # the session's lifecycle.
            # (The `tenant` argument is typically loaded by `db.session` without the
            # `expire_on_commit=False` flag, meaning its lifetime is tied to the web
            # request's lifecycle.)
            tenant_reloaded = session.scalars(tenant_query).one()

        if tenant_join:
            self.role = TenantAccountRole(tenant_join.role)
            self._current_tenant = tenant_reloaded
            return
        self._current_tenant = None

    @property
    def current_tenant_id(self) -> str | None:
        return self._current_tenant.id if self._current_tenant else None

    def set_tenant_id(self, tenant_id: str):
        query = (
            select(Tenant, TenantAccountJoin)
            .where(Tenant.id == tenant_id)
            .where(TenantAccountJoin.tenant_id == Tenant.id)
            .where(TenantAccountJoin.account_id == self.id)
        )
        with Session(db.engine, expire_on_commit=False) as session:
            tenant_account_join = session.execute(query).first()
            if not tenant_account_join:
                return
            tenant, join = tenant_account_join
            self.role = TenantAccountRole(join.role)
            self._current_tenant = tenant

    @property
    def current_role(self):
        return self.role

    def get_status(self) -> AccountStatus:
        status_str = self.status
        return AccountStatus(status_str)

    @classmethod
    def get_by_openid(cls, provider: str, open_id: str):
        account_integrate = (
            db.session.query(AccountIntegrate)
            .where(AccountIntegrate.provider == provider, AccountIntegrate.open_id == open_id)
            .one_or_none()
        )
        if account_integrate:
            return db.session.query(Account).where(Account.id == account_integrate.account_id).one_or_none()
        return None

    # check current_user.current_tenant.current_role in ['admin', 'owner']
    @property
    def is_admin_or_owner(self):
        return TenantAccountRole.is_privileged_role(self.role)

    @property
    def is_admin(self):
        return TenantAccountRole.is_admin_role(self.role)

    @property
    def is_editor(self):
        return TenantAccountRole.is_editing_role(self.role)

    @property
    def is_dataset_editor(self):
        return TenantAccountRole.is_dataset_edit_role(self.role)

    @property
    def is_dataset_operator(self):
        return self.role == TenantAccountRole.DATASET_OPERATOR

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "avatar": self.avatar,
            "interface_language": self.interface_language,
            "interface_theme": self.interface_theme,
            "timezone": self.timezone,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "last_login_ip": self.last_login_ip,
            "last_active_at": self.last_active_at.isoformat() if self.last_active_at else None,
            "status": self.status,
            "initialized_at": self.initialized_at.isoformat() if self.initialized_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }




class TenantStatus(enum.StrEnum):
    NORMAL = "normal"
    ARCHIVE = "archive"


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (sa.PrimaryKeyConstraint("id", name="tenant_pkey"),)

    id: Mapped[str] = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"))
    name: Mapped[str] = mapped_column(String(255))
    encrypt_public_key: Mapped[Optional[str]] = mapped_column(sa.Text)
    plan: Mapped[str] = mapped_column(String(255), server_default=sa.text("'basic'::character varying"))
    status: Mapped[str] = mapped_column(String(255), server_default=sa.text("'normal'::character varying"))
    custom_config: Mapped[Optional[str]] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())

    def get_accounts(self) -> list[Account]:
        return (
            db.session.query(Account)
            .where(Account.id == TenantAccountJoin.account_id, TenantAccountJoin.tenant_id == self.id)
            .all()
        )

    @property
    def custom_config_dict(self) -> dict:
        return json.loads(self.custom_config) if self.custom_config else {}

    @custom_config_dict.setter
    def custom_config_dict(self, value: dict):
        self.custom_config = json.dumps(value)


class TenantAccountJoin(Base):
    __tablename__ = "tenant_account_joins"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="tenant_account_join_pkey"),
        sa.Index("tenant_account_join_account_id_idx", "account_id"),
        sa.Index("tenant_account_join_tenant_id_idx", "tenant_id"),
        sa.UniqueConstraint("tenant_id", "account_id", name="unique_tenant_account_join"),
    )

    id: Mapped[str] = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"))
    tenant_id: Mapped[str] = mapped_column(StringUUID)
    account_id: Mapped[str] = mapped_column(StringUUID)
    current: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.text("false"))
    role: Mapped[str] = mapped_column(String(16), server_default="editor")
    #custom_role_id: Mapped[Optional[str]] = mapped_column(StringUUID, nullable=True)  # 关联RBAC角色
    invited_by: Mapped[Optional[str]] = mapped_column(StringUUID)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


    # def get_rbac_role_ids(self) -> list[str]:
    #     """获取用户的所有RBAC角色ID（逗号分隔）"""
    #     if not self.custom_role_id:
    #         return []
    #
    #     # 按逗号分割角色ID，去除空白字符
    #     return [role_id.strip() for role_id in self.custom_role_id.split(',') if role_id.strip()]
    #
    # def set_rbac_role_ids(self, role_ids: list[str]) -> None:
    #     """设置用户的RBAC角色ID（逗号分隔）"""
    #     if not role_ids:
    #         self.custom_role_id = None
    #     else:
    #         # 过滤空字符串并去重
    #         valid_role_ids = list({role_id.strip() for role_id in role_ids if role_id.strip()})
    #         self.custom_role_id = ','.join(valid_role_ids) if valid_role_ids else None
    #
    # def add_rbac_role_id(self, role_id: str) -> None:
    #     """添加一个RBAC角色ID"""
    #     if not role_id or not role_id.strip():
    #         return
    #
    #     current_ids = self.get_rbac_role_ids()
    #     if role_id.strip() not in current_ids:
    #         current_ids.append(role_id.strip())
    #         self.set_rbac_role_ids(current_ids)
    #
    # def remove_rbac_role_id(self, role_id: str) -> None:
    #     """移除一个RBAC角色ID"""
    #     if not role_id or not role_id.strip():
    #         return
    #
    #     current_ids = self.get_rbac_role_ids()
    #     if role_id.strip() in current_ids:
    #         current_ids.remove(role_id.strip())
    #         self.set_rbac_role_ids(current_ids)
    #
    # def get_custom_roles(self) -> list["Role"]:
    #     """获取用户的所有RBAC角色对象"""
    #     role_ids = self.get_rbac_role_ids()
    #     if not role_ids:
    #         return []
    #
    #     return db.session.query(Role).filter(
    #         Role.id.in_(role_ids),
    #         Role.is_active == True
    #     ).all()

class AccountIntegrate(Base):
    __tablename__ = "account_integrates"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="account_integrate_pkey"),
        sa.UniqueConstraint("account_id", "provider", name="unique_account_provider"),
        sa.UniqueConstraint("provider", "open_id", name="unique_provider_open_id"),
    )

    id: Mapped[str] = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"))
    account_id: Mapped[str] = mapped_column(StringUUID)
    provider: Mapped[str] = mapped_column(String(16))
    open_id: Mapped[str] = mapped_column(String(255))
    encrypted_token: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class InvitationCode(Base):
    __tablename__ = "invitation_codes"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="invitation_code_pkey"),
        sa.Index("invitation_codes_batch_idx", "batch"),
        sa.Index("invitation_codes_code_idx", "code", "status"),
    )

    id: Mapped[int] = mapped_column(sa.Integer)
    batch: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), server_default=sa.text("'unused'::character varying"))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    used_by_tenant_id: Mapped[Optional[str]] = mapped_column(StringUUID)
    used_by_account_id: Mapped[Optional[str]] = mapped_column(StringUUID)
    deprecated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=sa.text("CURRENT_TIMESTAMP(0)"))


class TenantPluginPermission(Base):
    class InstallPermission(enum.StrEnum):
        EVERYONE = "everyone"
        ADMINS = "admins"
        NOBODY = "noone"

    class DebugPermission(enum.StrEnum):
        EVERYONE = "everyone"
        ADMINS = "admins"
        NOBODY = "noone"

    __tablename__ = "account_plugin_permissions"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="account_plugin_permission_pkey"),
        sa.UniqueConstraint("tenant_id", name="unique_tenant_plugin"),
    )

    id: Mapped[str] = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"))
    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    install_permission: Mapped[InstallPermission] = mapped_column(String(16), nullable=False, server_default="everyone")
    debug_permission: Mapped[DebugPermission] = mapped_column(String(16), nullable=False, server_default="noone")


class TenantPluginAutoUpgradeStrategy(Base):
    class StrategySetting(enum.StrEnum):
        DISABLED = "disabled"
        FIX_ONLY = "fix_only"
        LATEST = "latest"

    class UpgradeMode(enum.StrEnum):
        ALL = "all"
        PARTIAL = "partial"
        EXCLUDE = "exclude"

    __tablename__ = "tenant_plugin_auto_upgrade_strategies"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="tenant_plugin_auto_upgrade_strategy_pkey"),
        sa.UniqueConstraint("tenant_id", name="unique_tenant_plugin_auto_upgrade_strategy"),
    )

    id: Mapped[str] = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"))
    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    strategy_setting: Mapped[StrategySetting] = mapped_column(String(16), nullable=False, server_default="fix_only")
    upgrade_time_of_day: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)  # seconds of the day
    upgrade_mode: Mapped[UpgradeMode] = mapped_column(String(16), nullable=False, server_default="exclude")
    exclude_plugins: Mapped[list[str]] = mapped_column(sa.ARRAY(String(255)), nullable=False)  # plugin_id (author/name)
    include_plugins: Mapped[list[str]] = mapped_column(sa.ARRAY(String(255)), nullable=False)  # plugin_id (author/name)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())

class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="role_pkey"),
        sa.Index("idx_roles_tenant", "tenant_id"),
        sa.Index("idx_roles_active", "is_active"),
        sa.UniqueConstraint("tenant_id", "role_name", name="uk_roles_tenant_name"),
    )

    id: Mapped[str] = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    role_key: Mapped[str] = mapped_column(String(255), nullable=False)
    role_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.text("true"))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "role_key": self.role_key,
            "role_name": self.role_name,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "is_active": self.is_active,
        }


class Menu(Base):
    __tablename__ = "menus"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="menu_pkey"),
        sa.Index("idx_menus_parent", "parent_id"),
        sa.Index("idx_menus_sort", "sort_order"),
        sa.Index("idx_menus_active", "is_active"),
        sa.Index("idx_menus_key", "menu_key"),
    )

    id: Mapped[str] = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"), primary_key=True)
    menu_key: Mapped[str] = mapped_column(String(255), nullable=False)
    menu_name: Mapped[str] = mapped_column(String(255), nullable=False)
    menu_type: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(StringUUID, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.text("true"))
    description:  Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "menu_key": self.menu_key,
            "menu_name": self.menu_name,
            "menu_type": self.menu_type,
            "parent_id": self.parent_id,
            "icon": self.icon,
            "path": self.path,
            "sort_order": self.sort_order,
            "is_active": self.is_active,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class AccountRole(Base):
    __tablename__ = "account_roles"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="account_role_pkey"),
        sa.Index("idx_account_roles_tenant", "tenant_id"),
        sa.Index("idx_account_roles_account", "account_id"),
        sa.Index("idx_account_roles_role", "role_id"),
        sa.UniqueConstraint("tenant_id", "account_id", "role_id", name="uk_user_roles_tenant_account_role"),
    )

    id: Mapped[str] = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    account_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    role_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())


    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "role_id": self.role_id,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

    def get_role_ids(self) -> list[str]:
     """获取用户的所有RBAC角色ID（逗号分隔）"""
     if not self.role_id:
         return []

     # 按逗号分割角色ID，去除空白字符
     return [rid.strip() for rid in self.role_id.split(',') if rid.strip()]


class RoleMenu(Base):
    __tablename__ = "role_menus"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="role_menu_pkey"),
        sa.Index("idx_role_menus_role", "role_id"),
        sa.Index("idx_role_menus_menu", "menu_id"),
        sa.UniqueConstraint("role_id", "menu_id", name="uk_role_menus_role_menu"),
    )

    id: Mapped[str] = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"), primary_key=True)
    role_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    menu_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())


    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "role_id": self.role_id,
            "menu_id": self.menu_id,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class RoleResource(Base):
    """角色资源关系表 - 角色对资源的授权（支持模型提供方和知识库）"""
    __tablename__ = "role_resources"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="role_resource_pkey"),
        sa.Index("idx_role_resources_tenant", "tenant_id"),
        sa.Index("idx_role_resources_role", "role_id"),
        sa.Index("idx_role_resources_resource", "resource_id"),
        sa.Index("idx_role_resources_type", "resource_type"),
        sa.UniqueConstraint("tenant_id", "role_id", "resource_id", "resource_type",
                            name="uk_role_resources_tenant_role_resource"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_role_resources_role_id"),
    )

    id: Mapped[str] = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"))
    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    role_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    resource_id: Mapped[str] = mapped_column(StringUUID, nullable=False)  # 资源ID（可能是provider_model_id或dataset_id）
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 资源类型：'model' 或 'dataset'
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sa.text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "role_id": self.role_id,
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

