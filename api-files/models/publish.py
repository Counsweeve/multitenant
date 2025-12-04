from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime

from libs.datetime_utils import naive_utc_now

if TYPE_CHECKING:
    pass

from enum import IntEnum
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from sqlalchemy.dialects.postgresql import ARRAY
from .types import StringUUID


class ApplyAppType(IntEnum):
    WORKFLOW = "1"
    AGENT = "2"


class PublishApplicationStatus(IntEnum):
    APPLYING = 1 # 申请中
    REGION_APPROVING = 2 # 区域管理员审批中
    SYS_APPROVING = 3 # 系统管理员审批中
    COMPLETED = 4 # 审批完成
    REJECTED = 5 # 审批驳回


class PublishApplication(Base):
    __tablename__ = "publish_application"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="publish_application_pkey"),
        sa.Index("publish_application_applicant_id_idx", "applicant_id"),
        sa.Index("publish_application_tenant_id_idx", "tenant_id"),
    )

    id = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"))
    applicant_id = mapped_column(StringUUID, nullable=False)
    applicant_area = mapped_column(String(100), nullable=True)
    tenant_id = mapped_column(String(100), nullable=True)
    status: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    need_sys_approve: Mapped[bool] = mapped_column(sa.Boolean, nullable=True)
    region_admin_id: Mapped[str] = mapped_column(StringUUID, nullable=True)
    sys_admin_id: Mapped[str] = mapped_column(StringUUID, nullable=True)
    apply_app_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    apply_app_version_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    apply_app_type: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    created_by = mapped_column(StringUUID, nullable=True)
    created_at = mapped_column(sa.DateTime, nullable=False, server_default=func.current_timestamp())
    updated_by = mapped_column(StringUUID, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, server_default=func.current_timestamp())

class PublicApplicationAction(StrEnum):
    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    REJECT = "REJECT"

class PublishApplicationHistory(Base):
    __tablename__ = "publish_application_history"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="publish_application_history_pkey"),
        sa.Index("publish_application_history_application_id_idx", "application_id"),
        sa.Index("publish_application_history_tenant_id_idx", "tenant_id"),
    )

    id = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"))
    application_id = mapped_column(StringUUID, nullable=False)
    tenant_id = mapped_column(String(100), nullable=True)
    action = mapped_column(String(100), nullable=True)
    operator_id: Mapped[str] = mapped_column(StringUUID, nullable=True)
    operator_role = mapped_column(String(100), nullable=True)
    from_status = mapped_column(String(100), nullable=True)
    to_status = mapped_column(String(100), nullable=True)
    reason: Mapped[str] = mapped_column(sa.Text, server_default=sa.text("''::character varying"))
    created_at = mapped_column(sa.DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, server_default=func.current_timestamp())


class NotificationMsgType(IntEnum):
    SYSTEM = "1" # 系统通知
    APPROVAL_TODO = "2" # 审批待办
    APPROVAL_RESULT = "3" # 审批结果


class NotificationSourceType(IntEnum):
    SYSTEM = "1"
    PUBLISH = "2"


class SystemNotification(Base):
    __tablename__ = "system_notification"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="system_notification_pkey"),
        sa.Index("system_notification_tenant_id_idx", "tenant_id"),
    )

    id = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"))
    tenant_id = mapped_column(String(100), nullable=True)
    title = mapped_column(String(100), nullable=True)
    content: Mapped[str] = mapped_column(sa.Text, server_default=sa.text("''::character varying"))
    msg_type: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    source_type: Mapped[int] = mapped_column(sa.Integer, nullable=True)
    source_id = mapped_column(String(100), nullable=True)
    created_by = mapped_column(StringUUID, nullable=True)
    created_at = mapped_column(sa.DateTime, nullable=False, server_default=func.current_timestamp())
    updated_by = mapped_column(StringUUID, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, server_default=func.current_timestamp())
    account_id = mapped_column(ARRAY(StringUUID), nullable=True)
    role = mapped_column(ARRAY(String(100)), nullable=True)
    is_deal: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.text("false"))
    application_id = mapped_column(String(100), nullable=True)


class PublishWorkflow(Base):
    __tablename__ = "publish_workflows"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="publish_workflows_pkey"),
        sa.Index("publish_workflows_version_idx", "tenant_id", "app_id", "version"),
        sa.Index("publish_workflows_tenant_id_idx", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"))
    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    app_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    type: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(255), nullable=False)
    marked_name: Mapped[str] = mapped_column(default="", server_default="")
    marked_comment: Mapped[str] = mapped_column(default="", server_default="")
    graph: Mapped[str] = mapped_column(sa.Text)
    _features: Mapped[str] = mapped_column("features", sa.TEXT)
    created_by: Mapped[str] = mapped_column(StringUUID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_by: Mapped[Optional[str]] = mapped_column(StringUUID)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=naive_utc_now(),
        server_onupdate=func.current_timestamp(),
    )
    _environment_variables: Mapped[str] = mapped_column(
        "environment_variables", sa.Text, nullable=False, server_default="{}"
    )
    _conversation_variables: Mapped[str] = mapped_column(
        "conversation_variables", sa.Text, nullable=False, server_default="{}"
    )
    icon_type: Mapped[Optional[str]] = mapped_column(String(255))  # image, emoji
    icon = mapped_column(String(255))
    icon_background: Mapped[Optional[str]] = mapped_column(String(255))
    enable: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.text("true"))
    workflow_id: Mapped[str] = mapped_column(StringUUID, nullable=True)


class PublishAppModelConfig(Base):
    __tablename__ = "publish_app_model_configs"
    __table_args__ = (sa.PrimaryKeyConstraint("id", name="publish_app_model_configs_pkey"),
                      sa.Index("publish_app_app_id_idx", "app_id"),
                      sa.Index("publish_app_tenant_id_idx", "tenant_id"),
    )

    id = mapped_column(StringUUID, server_default=sa.text("uuid_generate_v4()"))
    app_id = mapped_column(StringUUID, nullable=False)
    provider = mapped_column(String(255), nullable=True)
    model_id = mapped_column(String(255), nullable=True)
    tenant_id = mapped_column(String(100), nullable=True)
    configs = mapped_column(sa.JSON, nullable=True)
    created_by = mapped_column(StringUUID, nullable=True)
    created_at = mapped_column(sa.DateTime, nullable=False, server_default=func.current_timestamp())
    updated_by = mapped_column(StringUUID, nullable=True)
    updated_at = mapped_column(sa.DateTime, nullable=False, server_default=func.current_timestamp())
    opening_statement = mapped_column(sa.Text)
    suggested_questions = mapped_column(sa.Text)
    suggested_questions_after_answer = mapped_column(sa.Text)
    speech_to_text = mapped_column(sa.Text)
    text_to_speech = mapped_column(sa.Text)
    more_like_this = mapped_column(sa.Text)
    model = mapped_column(sa.Text)
    user_input_form = mapped_column(sa.Text)
    dataset_query_variable = mapped_column(String(255))
    pre_prompt = mapped_column(sa.Text)
    agent_mode = mapped_column(sa.Text)
    sensitive_word_avoidance = mapped_column(sa.Text)
    retriever_resource = mapped_column(sa.Text)
    prompt_type = mapped_column(String(255), nullable=False, server_default=sa.text("'simple'::character varying"))
    chat_prompt_config = mapped_column(sa.Text)
    completion_prompt_config = mapped_column(sa.Text)
    dataset_configs = mapped_column(sa.Text)
    external_data_tools = mapped_column(sa.Text)
    file_upload = mapped_column(sa.Text)
    marked_name: Mapped[str] = mapped_column(default="", server_default="")
    marked_comment: Mapped[str] = mapped_column(default="", server_default="")
    icon_type: Mapped[Optional[str]] = mapped_column(String(255))  # image, emoji
    icon = mapped_column(String(255))
    icon_background: Mapped[Optional[str]] = mapped_column(String(255))
    enable: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.text("true"))
    app_model_config_id: Mapped[str] = mapped_column(StringUUID, nullable=True)
