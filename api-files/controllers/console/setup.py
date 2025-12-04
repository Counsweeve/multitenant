from flask import request
from flask_restx import Resource, reqparse

from configs import dify_config
from libs.helper import StrLen, email, extract_remote_ip
from libs.password import valid_password
from models.model import DifySetup, db
from services.account_service import RegisterService, TenantService

from . import api
from .error import AlreadySetupError, NotInitValidateError
from .init_validate import get_init_validate_status
from .wraps import only_edition_self_hosted


class SetupApi(Resource):
    def get(self):
        # 获取系统设置状态
        if dify_config.EDITION == "SELF_HOSTED":
            setup_status = get_setup_status()
            if setup_status:
                return {"step": "finished", "setup_at": setup_status.setup_at.isoformat()}
            return {"step": "not_started"}
        return {"step": "finished"}

    @only_edition_self_hosted
    def post(self):
        # 检查是否已经完成设置
        if get_setup_status():
            raise AlreadySetupError()

        # 检查是否已创建租户
        tenant_count = TenantService.get_tenant_count()
        if tenant_count > 0:
            raise AlreadySetupError()

        # 检查初始化验证状态
        if not get_init_validate_status():
            raise NotInitValidateError()

        # 解析请求参数
        parser = reqparse.RequestParser()
        parser.add_argument("email", type=email, required=True, location="json")
        parser.add_argument("name", type=StrLen(30), required=True, location="json")
        parser.add_argument("password", type=valid_password, required=True, location="json")
        args = parser.parse_args()

        # 执行设置流程
        RegisterService.setup(
            email=args["email"], name=args["name"], password=args["password"], ip_address=extract_remote_ip(request)
        )

        return {"result": "success"}, 201


def get_setup_status():
    # 根据部署版本获取设置状态
    if dify_config.EDITION == "SELF_HOSTED":
        return db.session.query(DifySetup).first()
    else:
        return True


api.add_resource(SetupApi, "/setup")
