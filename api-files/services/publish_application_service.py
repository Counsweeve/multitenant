from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from models.account import Account
from models.publish import (
    PublishApplication,
    PublishApplicationHistory,
    PublishApplicationStatus,
    PublishAppModelConfig,
    PublishWorkflow,
    SystemNotification,
)


class PublishApplicationService:
    """CRUD service for publish_application and its history."""

    # Create
    def create(
        self,
        *,
        session: Session,
        account: Account,
        status: int,
        apply_app_id: str,
        apply_app_version_id: str,
        apply_app_type: int,
        tenant_id: Optional[str] = None,
        need_sys_approve: Optional[bool] = None,
    ) -> PublishApplication:
        # validate status
        try:
            PublishApplicationStatus(int(status))
        except ValueError:
            raise ValueError("invalid status")
        application = PublishApplication(
            applicant_id=account.id,
            applicant_area=None,
            tenant_id=tenant_id,
            status=status,
            need_sys_approve=need_sys_approve,
            region_admin_id=None,
            sys_admin_id=None,
            apply_app_id=apply_app_id,
            apply_app_version_id=apply_app_version_id,
            apply_app_type=apply_app_type,
            created_by=account.id,
            updated_by=account.id,
        )
        session.add(application)
        session.flush()  # 确保生成ID
        return application

    # Read
    def get_by_id(self, *, session: Session, application_id: str) -> Optional[PublishApplication]:
        stmt = select(PublishApplication).where(PublishApplication.id == application_id)
        return session.scalar(stmt)

    def list_by_applicant(
        self,
        *,
        session: Session,
        applicant_id: str,
        limit: int = 999,
        offset: int = 0,
    ) -> list[PublishApplication]:
        stmt = (
            select(PublishApplication)
            .where(PublishApplication.applicant_id == applicant_id)
            .offset(offset)
            .limit(limit)
        )
        return list(session.scalars(stmt).all())

    # Update (partial)
    def update(
        self,
        *,
        session: Session,
        application_id: str,
        updated_by: Optional[str] = None,
        **fields: Any,
    ) -> PublishApplication:
        application = self.get_by_id(session=session, application_id=application_id)
        if application is None:
            raise ValueError("publish_application not found")

        for key, value in fields.items():
            if not hasattr(application, key):
                raise ValueError(f"invalid field: {key}")
            setattr(application, key, value)

        if updated_by is not None:
            application.updated_by = updated_by
        return application

    # =========================
    # System Notification CRUD
    # =========================
    def create_notification(
        self,
        *,
        session: Session,
        account_id: Optional[list[str]] = None,
        role: Optional[list[str]] = None,
        msg_type: int,
        tenant_id: Optional[str] = None,
        title: Optional[str] = None,
        content: Optional[str] = None,
        source_type: Optional[int] = None,
        source_id: Optional[str] = None,
        created_by: Optional[str] = None,
        application_id: Optional[str] = None,
        is_deal: Optional[bool],
    ) -> SystemNotification:
        notification = SystemNotification(
            account_id=account_id,
            role=role,
            title=title,
            tenant_id=tenant_id,
            content=content or "",
            msg_type=int(msg_type),
            source_type=source_type if source_type is None else int(source_type),
            source_id=source_id or None,
            created_by=created_by or account_id[0] if account_id else None,
            updated_by=created_by or account_id[0] if account_id else None,
            is_deal= is_deal,
            application_id=application_id,
        )
        session.add(notification)
        return notification

    def get_notification(self, *, session: Session, notification_id: str) -> Optional[SystemNotification]:
        stmt = select(SystemNotification).where(SystemNotification.id == notification_id)
        return session.scalar(stmt)

    def list_notifications_by_account(
        self,
        *,
        session: Session,
        account_id: list[str],
        role: Optional[list[str]] = None,
        msg_type: Optional[list[str]] = None,
        limit: int = 999,
        offset: int = 0,
        is_deal: Optional[bool] = None,
    ) -> list[SystemNotification]:
        # 创建基础查询
        stmt = select(SystemNotification)

        # 如果提供了role参数，则构建OR关系的查询条件
        if role:
            stmt = stmt.where(
                or_(
                    SystemNotification.account_id.contains(account_id),
                    SystemNotification.role.contains(role)
                )
            )
        else:
            # 否则只使用account_id条件
            stmt = stmt.where(SystemNotification.account_id.contains(account_id))

        # 添加is_deal过滤条件（如果提供）
        if is_deal is not None:
            stmt = stmt.where(SystemNotification.is_deal == is_deal)

        # 添加msg_type过滤条件（如果提供）
        if msg_type is not None:
            stmt = stmt.where(SystemNotification.msg_type.in_(msg_type))

        # 添加分页
        stmt = stmt.offset(offset).limit(limit)
        return list(session.scalars(stmt).all())

    def update_notification(
        self,
        *,
        session: Session,
        notification_id: str,
        updated_by: Optional[str] = None,
        **fields: Any,
    ) -> SystemNotification:
        notification = self.get_notification(session=session, notification_id=notification_id)
        if notification is None:
            raise ValueError("system_notification not found")

        for key, value in fields.items():
            if not hasattr(notification, key):
                raise ValueError(f"invalid field: {key}")
            setattr(notification, key, value)

        if updated_by is not None:
            notification.updated_by = updated_by
        return notification

    def delete_notification(self, *, session: Session, notification_id: str) -> None:
        notification = self.get_notification(session=session, notification_id=notification_id)
        if notification is None:
            return
        session.delete(notification)

    def batch_update_notifications_to_deal(self,
        *, session: Session,
        account_id: list[str],
        role: list[str],
        msg_types: list[str],
        updated_by: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> int:
        """
        批量将通知标记为已处理

        Args:
            session: 数据库会话
            account_id: 账户ID列表
            msg_types: 消息类型列表
            updated_by: 更新者ID

        Returns:
            更新的记录数
        """
        # 构建查询条件
        stmt = select(SystemNotification).where(
            SystemNotification.account_id.contains(account_id),
            SystemNotification.msg_type.in_(msg_types),
            SystemNotification.is_deal == False
        )

        stmt = select(SystemNotification)

        if role:
            stmt = stmt.where(
                or_(
                    SystemNotification.account_id.contains(account_id),
                    SystemNotification.role.contains(role)
                )
            )
        else:
            # 否则只使用account_id条件
            stmt = stmt.where(SystemNotification.account_id.contains(account_id))


        stmt = stmt.where(SystemNotification.msg_type.in_(msg_types),
                          SystemNotification.is_deal == False,
                          SystemNotification.tenant_id == tenant_id)


        # 执行查询并更新
        notifications = session.scalars(stmt).all()
        count = 0

        for notification in notifications:
            notification.is_deal = True
            if updated_by is not None:
                notification.updated_by = updated_by
            count += 1

        return count

    # Delete
    def delete(self, *, session: Session, application_id: str) -> None:
        application = self.get_by_id(session=session, application_id=application_id)
        if application is None:
            return
        session.delete(application)

    # =========================
    # Publish Workflow CRUD
    # =========================
    def get_publish_workflow(self, *, session: Session, workflow_id: str) -> Optional[PublishWorkflow]:
        """获取发布的工作流

        Args:
            session: 数据库会话
            workflow_id: 工作流ID

        Returns:
            PublishWorkflow对象，如果不存在则返回None
        """
        stmt = select(PublishWorkflow).where(PublishWorkflow.id == workflow_id)
        return session.scalar(stmt)

    def update_publish_workflow(
        self,
        *,
        session: Session,
        workflow_id: str,
        updated_by: Optional[str] = None,
        **fields: Any,
    ) -> PublishWorkflow:
        """更新发布的工作流

        Args:
            session: 数据库会话
            workflow_id: 工作流ID
            updated_by: 更新者ID
            **fields: 要更新的字段

        Returns:
            更新后的PublishWorkflow对象

        Raises:
            ValueError: 当工作流不存在或字段无效时
        """
        workflow = self.get_publish_workflow(session=session, workflow_id=workflow_id)
        if workflow is None:
            raise ValueError("publish_workflow not found")

        for key, value in fields.items():
            if not hasattr(workflow, key):
                raise ValueError(f"invalid field: {key}")
            setattr(workflow, key, value)

        if updated_by is not None:
            workflow.updated_by = updated_by

        return workflow

    def get_publish_app_model_config(self, *, session: Session, config_id: str) -> Optional[PublishAppModelConfig]:
        """获取发布的应用模型配置

        Args:
            session: 数据库会话
            config_id: 配置ID

        Returns:
            PublishAppModelConfig对象，如果不存在则返回None
        """
        # 使用SQLAlchemy的select查询语法
        # 检查session对象是否支持execute方法
        # 尝试使用execute方法执行select查询
        stmt = select(PublishAppModelConfig).where(PublishAppModelConfig.id == config_id)
        return session.scalar(stmt)

    def update_publish_app_model_config(
        self,
        *,
        session: Session,
        config_id: str,
        updated_by: Optional[str] = None,
        **fields: Any,
    ) -> PublishAppModelConfig:
        """更新发布的应用模型配置

        Args:
            session: 数据库会话
            config_id: 配置ID
            updated_by: 更新者ID
            **fields: 要更新的字段

        Returns:
            更新后的PublishAppModelConfig对象

        Raises:
            ValueError: 当配置不存在或字段无效时
        """
        config = self.get_publish_app_model_config(session=session, config_id=config_id)
        if config is None:
            raise ValueError("publish_app_model_config not found")

        for key, value in fields.items():
            if not hasattr(config, key):
                raise ValueError(f"invalid field: {key}")
            setattr(config, key, value)

        if updated_by is not None:
            config.updated_by = updated_by

        return config

    # History helpers
    def add_history(
        self,
        *,
        session: Session,
        application_id: str,
        tenant_id: Optional[str] = None,
        action: Optional[str] = None,
        operator_id: Optional[str] = None,
        operator_role: Optional[str] = None,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> PublishApplicationHistory:
        history = PublishApplicationHistory(
            application_id=application_id,
            tenant_id=tenant_id,
            action=action,
            operator_id=operator_id,
            operator_role=operator_role,
            from_status=from_status,
            to_status=to_status,
            reason=reason or "",
        )
        session.add(history)
        return history

    def list_history_by_application(
        self,
        *,
        session: Session,
        application_id: str,
        limit: int = 999,
        offset: int = 0,
    ) -> list[PublishApplicationHistory]:
        """分页查询指定应用的发布历史记录。

        Args:
            session: 数据库会话
            application_id: 应用ID
            limit: 每页记录数，默认为50
            offset: 偏移量，默认为0

        Returns:
            PublishApplicationHistory对象列表
        """
        stmt = (
            select(PublishApplicationHistory)
            .where(PublishApplicationHistory.application_id == application_id)
            .order_by(PublishApplicationHistory.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(session.scalars(stmt).all())

    def change_status(
        self,
        *,
        session: Session,
        application_id: str,
        to_status: int,
        operator_id: Optional[str] = None,
        operator_role: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> PublishApplication:
        application = self.get_by_id(session=session, application_id=application_id)
        if application is None:
            raise ValueError("publish_application not found")

        # validate to_status
        try:
            PublishApplicationStatus(int(to_status))
        except ValueError:
            raise ValueError("invalid status")

        from_status_value = str(application.status) if application.status is not None else None
        application.status = to_status
        if operator_id is not None:
            application.updated_by = operator_id

        self.add_history(
            session=session,
            application_id=application_id,
            action="change_status",
            operator_id=operator_id,
            operator_role=operator_role,
            from_status=from_status_value,
            to_status=str(to_status),
            reason=reason,
        )
        return application
