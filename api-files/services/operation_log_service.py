from datetime import datetime
from typing import Any, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from extensions.ext_database import db
from models.enums import OperationActionType
from models.model import OperationLog


class OperationLogService:

    def create_log(self,
                   tenant_id: str,
                   account_id: str,
                   account_email: str,
                   action: str,
                   action_name: str,
                   content: Optional[dict[str, Any]] = None,
                   description: Optional[str] = None,
                   ip_address: str = "",
                   user_agent: Optional[str] = None
                   ) -> OperationLog:

        with Session(db.engine) as session:
            log = OperationLog(
                tenant_id=tenant_id,
                account_id=account_id,
                account_email=account_email,
                action=action,
                action_name=action_name,
                content=content,
                description=description,
                ip_address=ip_address,
                user_agent=user_agent
            )
            session.add(log)
            session.commit()
            return log


    def get_logs(self,
                 tenant_id: str,
                 account_email: Optional[str] = None,
                 action: Optional[str] = None,
                 start_time: Optional[datetime] = None,
                 end_time: Optional[datetime] = None,
                 page: int = 1,
                 page_size: int = 10
                 ) -> dict[str, Any]:
        with Session(db.engine) as session:
            query = session.query(OperationLog).filter(OperationLog.tenant_id == tenant_id)

            if account_email:
                query = query.filter(OperationLog.account_email.ilike(f"%{account_email}%"))

            if action:
                query = query.filter(OperationLog.action == action)

            if start_time:
                query = query.filter(OperationLog.created_at >= start_time)

            if end_time:
                query = query.filter(OperationLog.created_at <= end_time)

            total = query.count()

            logs = query.order_by(desc(OperationLog.created_at)) \
                .offset((page - 1) * page_size) \
                .limit(page_size) \
                .all()

            logs_list = []
            for log in logs:
                logs_list.append(log.to_dict())

            return {
                'data': logs_list,
                'total': total,
                'page': page,
                'page_size': page_size
            }

    def get_action_types(self) -> list[dict[str, str]]:
        """获取所有操作类型"""
        return [
            {'value': action.value, 'name': OperationActionType.get_action_name(action.value)}
            for action in OperationActionType
        ]
