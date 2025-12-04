from datetime import datetime

from flask_restx import Resource, reqparse

from controllers.console import api
from controllers.console.system_log import operation_log
from controllers.console.wraps import account_initialization_required, setup_required
from libs.login import current_user, login_required
from models.enums import OperationActionType
from services.operation_log_service import OperationLogService


class SystemOperationLogApi(Resource):
    """系统操作日志API"""

    @setup_required
    @login_required
    @account_initialization_required
    #@marshal_with(system_operation_log_list_fields)
    def get(self):
        """获取操作日志列表"""
        parser = reqparse.RequestParser()
        parser.add_argument('account_email', type=str, location='args')
        parser.add_argument('action', type=str, location='args')
        parser.add_argument('start_time', type=str, location='args')
        parser.add_argument('end_time', type=str, location='args')
        parser.add_argument('page', type=int, default=1, location='args')
        parser.add_argument('page_size', type=int, default=10, location='args')
        args = parser.parse_args()

        # 解析时间参数
        start_time = None
        end_time = None
        if args['start_time']:
            start_time = datetime.fromisoformat(args['start_time'])
        if args['end_time']:
            end_time = datetime.fromisoformat(args['end_time'])

        service = OperationLogService()
        result = service.get_logs(
            tenant_id=current_user.current_tenant_id,
            account_email=args['account_email'],
            action=args['action'],
            start_time=start_time,
            end_time=end_time,
            page=args['page'],
            page_size=args['page_size']
        )

        return result


class SystemOperationLogActionTypesApi(Resource):
    """操作类型列表API"""

    @setup_required
    @login_required
    @account_initialization_required
    @operation_log(
        action=OperationActionType.SYSTEM_OPERATION_LOG_ACTION_TYPES_LIST,
        description="查看操作类型列表"
    )
    def get(self):
        """获取所有操作类型"""
        service = OperationLogService()
        return service.get_action_types()

api.add_resource(SystemOperationLogApi, "/workspaces/system_logs")
api.add_resource(SystemOperationLogActionTypesApi, "/workspaces/system_log_action_types")
