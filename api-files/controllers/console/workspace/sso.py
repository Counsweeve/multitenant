import uuid
from datetime import UTC, datetime, timedelta

from flask import request
from flask_restx import Resource, reqparse
from werkzeug.exceptions import BadRequest, Unauthorized

from configs import dify_config
from controllers.console import api
from extensions.ext_database import db
from libs.passport import PassportService
from models.account import AccountStatus, Tenant, TenantAccountJoin, TenantAccountRole
from models.model import Account


class SSOLoginApi(Resource):

    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument("sso_token", type=str, required=True, location="json", help="SSO认证token")
        parser.add_argument("redirect_url", type=str, required=False, location="json", help="登录后重定向URL")
        args = parser.parse_args()

        try:
            # 验证SSO token
            sso_data = self._validate_sso_token(args["sso_token"])

            # 获取用户账户
            account = self._get_account(sso_data)

            if account.id:
                join = db.session.query(TenantAccountJoin).where(TenantAccountJoin.account_id == account.id).first()
                if not join:
                    raise Unauthorized("Account not found")

            return {
                "result": "success",
                "data": {
                    "user_id": account.id,
                    "email": account.email,
                    "redirect_url": args.get("redirect_url", "/")
                }
            }

        except Exception as e:
            return {
                "result": "fail",
                "message": str(e)
            }, 401

    def _validate_sso_token(self, sso_token: str) -> dict:
        try:
            # 使用PassportService验证token
            passport_service = PassportService()
            payload = passport_service.verify(sso_token)

            # 检查token类型
            if payload.get("sub") != "SSO Token":
                raise Unauthorized("Invalid token type")

            # 检查token是否过期
            exp = payload.get("exp")
            if exp and datetime.now(UTC).timestamp() > exp:
                raise Unauthorized("Token has expired")

            return payload

        except Exception as e:
            raise Unauthorized(f"Invalid SSO token: {str(e)}")

    def _get_account(self, sso_data: dict) -> Account:
        """根据SSO数据获取用户账户"""
        email = sso_data.get("email")
        if not email:
            raise BadRequest("Email is required in SSO data")

        # 查找现有账户
        account = db.session.query(Account).filter_by(email=email).first()

        if account:
            # 检查账户状态
            if account.status == AccountStatus.BANNED.value:
                raise Unauthorized("Account is banned")

            # 更新最后活跃时间
            account.last_active_at = datetime.now(UTC)
            db.session.commit()

            return account
        else:
            raise BadRequest("Account not found")



class SSOTokenGenerateApi(Resource):
    """SSO token生成API - 为外部系统生成SSO token"""

    def post(self):
        """生成SSO token"""
        parser = reqparse.RequestParser()
        parser.add_argument("email", type=str, required=True, location="json", help="用户邮箱")
        parser.add_argument("name", type=str, required=False, location="json", help="用户姓名")
        parser.add_argument("expires_in",
                            type=int,
                            required=False,
                            default=3600,
                            location="json",
                            help="token过期时间(秒)")
        args = parser.parse_args()

        # 验证请求来源（可以添加API key验证）
        api_key = request.headers.get("X-API-Key")
        if not self._validate_api_key(api_key):
            raise Unauthorized("Invalid API key")

        try:
            # 生成SSO token
            sso_token = self._generate_sso_token(args)

            return {
                "result": "success",
                "data": {
                    "sso_token": sso_token,
                    "expires_in": args["expires_in"],
                    "login_url": f"{request.host_url}sso/login?sso_token={sso_token}"
                }
            }

        except Exception as e:
            return {
                "result": "fail",
                "message": str(e)
            }, 400

    def _validate_api_key(self, api_key: str) -> bool:
        """验证API key（这里简化处理，实际应该从数据库或配置中验证）"""
        # 从环境变量或配置中获取有效的API keys
        valid_api_keys = dify_config.SSO_API_KEYS if hasattr(dify_config, 'SSO_API_KEYS') else []
        return api_key in valid_api_keys

    def _generate_sso_token(self, user_data: dict) -> str:
        """生成SSO token"""
        exp_dt = datetime.now(UTC) + timedelta(seconds=user_data["expires_in"])
        exp = int(exp_dt.timestamp())

        payload = {
            "email": user_data["email"],
            "name": user_data.get("name"),
            "language": user_data.get("language", "en-US"),
            "theme": user_data.get("theme", "light"),
            "timezone": user_data.get("timezone", "UTC"),
            "exp": exp,
            "iss": dify_config.EDITION,
            "sub": "SSO Token",
            "iat": int(datetime.now(UTC).timestamp())
        }

        return PassportService().issue(payload)

class SSOSyncUserApi(Resource):
    """同步用户信息API: 创建或更新单个用户"""

    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument("email", type=str, required=True, location="json", help="用户邮箱")
        parser.add_argument("name", type=str, required=True, location="json", help="用户姓名")
        parser.add_argument("language", type=str, required=False, default="en-US", location="json", help="用户语言")
        parser.add_argument("theme", type=str, required=False, default="light", location="json", help="用户主题")
        parser.add_argument("timezone", type=str, required=False, default="UTC", location="json", help="用户时区")

        # 租户绑定
        parser.add_argument("tenant_name", type=str, required=True, location="json", help="租户名称(不存在则创建)")
        parser.add_argument(
            "role",
            type=str,
            required=False,
            default=TenantAccountRole.NORMAL.value,
            location="json",
            help=f"one of {list(TenantAccountRole)}"
        )
        parser.add_argument("set_current", type=bool, required=False, default=True, location="json",
                            help="设置为当前租户")

        parser.add_argument(
            "status",
            type=str,
            required=False,
            default=AccountStatus.ACTIVE.value,
            location="json",
            help=f"one of {[s.value for s in AccountStatus]}",
        )

        args = parser.parse_args()

        api_key = request.headers.get("X-API-Key")
        if not self._validate_api_key(api_key):
            raise Unauthorized("Invalid API key")
        email = args["email"].strip().lower()
        name = args.get("name")
        language = args.get("language")
        theme = args.get("theme")
        timezone = args.get("timezone")
        status = (args.get("status") or AccountStatus.ACTIVE.value).lower()

        valid_status_values = {s.value for s in AccountStatus}
        if status not in valid_status_values:
            return {"result": "fail", "message": "invalid status"}

        now = datetime.now(UTC)
        account = db.session.query(Account).filter_by(email=email).first()
        created = False

        if account:
            # 更新
            account.name = name
            account.interface_language = language
            account.interface_theme = theme
            account.timezone = timezone
            account.status = status
            account.updated_at = now
        else:
            # 创建
            account = Account(
                id=str(uuid.uuid4()),
                email=email,
                name=name,
                interface_language=language,
                interface_theme=theme,
                timezone=timezone,
                status=status,
                last_login_at=None,
                last_active_at=now,
                created_at=now,
                updated_at=now,
            )
            db.session.add(account)
            created = True

        tenant_name = (args.get("tenant_name") or "").strip()
        role = (args.get("role") or TenantAccountRole.NORMAL.value).lower()
        set_current = bool(args.get("set_current", True))

        tenant = None
        if tenant_name:
            if role and not TenantAccountRole.is_valid_role(role):
                return {"result": "fail", "message": "invalid role"}


            tenant = db.session.query(Tenant).where(Tenant.name == tenant_name).one_or_none()
            if not tenant:
                tenant = Tenant(name=tenant_name, created_at=now, updated_at=now)
                db.session.add(tenant)
                db.session.flush()

            if tenant:
                join = (
                    db.session.query(TenantAccountJoin)
                    .where(TenantAccountJoin.tenant_id == tenant.id)
                    .where(TenantAccountJoin.account_id == account.id)
                    .one_or_none()
                )
                if not join:
                    join = TenantAccountJoin(
                        tenant_id=tenant.id,
                        account_id=str(account.id),
                        current=set_current
                    )
                    db.session.add(join)
                else:
                    join.role = role or join.role
                    join.current = set_current if set_current is not None else join.current

        db.session.commit()
        return {
            "result": "success",
            "data": {
                "created": created,
                "account_id": account.id,
                "email": account.email,
                "status": account.status,
                "tenant_id": tenant.id if tenant else None,
            },
        }
    def _validate_api_key(self, api_key):
        valid_api_keys = dify_config.SSO_API_KEYS if hasattr(dify_config, "SSO_API_KEYS") else []
        return api_key in valid_api_keys


class SSOBatchSyncUsersApi(Resource):
    """批量同步用户信息API: 创建或更新多个用户"""
    def post(self):
        api_key = request.headers.get("X-API-Key")
        if not self._validate_api_key(api_key):
            raise Unauthorized("Invalid API key")
        json_body = request.get_json(silent=True) or {}
        users = json_body.get("users", [])
        if not isinstance(users, list) or not users:
            return {"result": "fail", "message": "users must be a non-empty list"}

        results = []
        created_count = 0
        updated_count = 0
        for item in users:
            try:
                email = (item.get("email") or "").strip().lower()
                if not email:
                    results.append({"email": None, "result": "fail", "message": "email required"})
                    continue

                name = item.get("name")
                language = item.get("language", "en-US")
                theme = item.get("theme", "light")
                timezone = item.get("timezone", "UTC")
                status = (item.get("status") or AccountStatus.ACTIVE.value).lower()
                valid_status_values = {s.value for s in AccountStatus}
                if status not in valid_status_values:
                    results.append({"email": email, "result": "fail", "message": "invalid status"})
                    continue

                now = datetime.now(UTC)
                account = db.session.query(Account).filter_by(email=email).first()

                if account:
                    account.name = name
                    account.interface_language = language
                    account.interface_theme = theme
                    account.timezone = timezone
                    account.status = status
                    account.updated_at = now
                    updated_count += 1
                else:
                    account = Account(
                        id=str(uuid.uuid4()),
                        email=email,
                        name=name,
                        interface_language=language,
                        interface_theme=theme,
                        timezone=timezone,
                        status=status,
                        last_login_at=None,
                        last_active_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    db.session.add(account)
                    created_count += 1

                item_tenant_name = (item.get("tenant_name") or "").strip()
                item_role= (item.get("role") or TenantAccountRole.NORMAL.value).lower()
                item_set_current = bool(item.get("set_current", True))

                tenant_obj = None
                if item_tenant_name:
                    if item_role and not TenantAccountRole.is_valid_role(item_role):
                        results.append({"email": email, "result": "fail", "message": "invalid role"})
                        continue
                    if item_tenant_name:
                        tenant_obj = db.session.query(Tenant).where(Tenant.name == item_tenant_name).one_or_none()
                        if not tenant_obj:
                            tenant_obj = Tenant(name=item_tenant_name, created_at=now, updated_at=now)
                            db.session.add(tenant_obj)
                            db.session.flush()
                    if tenant_obj:
                        join_obj = (
                            db.session.query(Tenant, TenantAccountJoin)
                            .where(TenantAccountJoin.tenant_id == tenant_obj.id)
                            .where(TenantAccountJoin.account_id == account.id)
                            .one_or_none()
                        )
                        if not join_obj:
                            join_obj = TenantAccountJoin(
                                tenant_id=tenant_obj.id,
                                account_id=str(account.id),
                                role=item_role,
                                current=item_set_current
                            )
                            db.session.add(join_obj)
                        else:
                            join_obj.role = item_role or join_obj.role
                            join_obj.current = item_set_current if item_set_current is not None else join_obj.current
                results.append({"email": email, "result": "success"})
            except Exception as e:
                results.append({"email": item.get("email"), "result": "fail", "message": str(e)})

        db.session.commit()
        return {
            "result": "success",
            "data": {
                "created_count": created_count,
                "updated_count": updated_count,
                "total": len(users),
                "details": results,
            },
        }

    def _validate_api_key(self, api_key: str) -> bool:
        valid_api_keys = dify_config.SSO_API_KEYS if hasattr(dify_config, "SSO_API_KEYS") else []
        return api_key in valid_api_keys


# SSO登录接口
api.add_resource(SSOLoginApi, "/sso/login")
# 生成SSO token
api.add_resource(SSOTokenGenerateApi, "/sso/generate-token")
# 门户同步接口
api.add_resource(SSOSyncUserApi, "/sso/sync/user")
# 批量同步用户
api.add_resource(SSOBatchSyncUsersApi, "/sso/sync/users")

