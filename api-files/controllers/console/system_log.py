from collections.abc import Callable
from functools import wraps
from typing import Any, Optional

from flask import current_app, request
from flask_login import current_user

from extensions.ext_database import db
from models.enums import OperationActionType
from services.operation_log_service import OperationLogService


def operation_log(
    action: str,
    action_name: Optional[str] = None,
    description: Optional[str] = None,
    include_request_data: bool = True,
    include_response_data: bool = False
):
    """
    操作日志装饰器

    Args:
        action: 操作类型
        action_name: 操作类型名称，如果不提供则从枚举中获取
        description: 操作描述
        include_request_data: 是否包含请求数据
        include_response_data: 是否包含响应数据
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 执行原函数
            result = func(*args, **kwargs)
            print("===========================>result: ", result)
            try:
                # 记录操作日志
                _record_operation_log(
                    action=action,
                    action_name=action_name or OperationActionType.get_action_name(action),
                    description=description,
                    include_request_data=include_request_data,
                    include_response_data=include_response_data,
                    result=result
                )
            except Exception as e:
                # 记录日志失败不应该影响主业务逻辑
                current_app.logger.exception("Failed to record operation log")
            return result

        return wrapper

    return decorator


def _record_operation_log(
    action: str,
    action_name: str,
    description: Optional[str] = None,
    include_request_data: bool = True,
    include_response_data: bool = False,
    result: Any = None
):
    """记录操作日志的内部函数"""
    print("===========================>record operation log")
    if not current_user.is_authenticated:
        return

    # 获取请求信息
    ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    user_agent = request.headers.get('User-Agent', '')

    # 构建操作内容
    content = {}
    if include_request_data:
        content['request_data'] = {
            'method': request.method,
            'url': request.url,
            'args': dict(request.args),
            'json': request.get_json() if request.is_json else None,
            'form': dict(request.form) if request.form else None,
        }

    if include_response_data and result:
        content['response_data'] = result

    # 创建操作日志记录
    with db.session.begin():
        log_service = OperationLogService()
        log_service.create_log(
            tenant_id=current_user.current_tenant_id,
            account_id=current_user.id,
            account_email=current_user.email,
            action=action,
            action_name=action_name,
            content=content,
            description=description,
            ip_address=ip_address,
            user_agent=user_agent
        )
