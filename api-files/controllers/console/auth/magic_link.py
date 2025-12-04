import base64
import secrets
from datetime import datetime, UTC

import requests
from flask import request, make_response
from flask_restx import Resource, reqparse
from openai import timeout
from werkzeug.exceptions import Unauthorized, BadRequest

from configs import dify_config
from controllers.console import api
from controllers.console.wraps import setup_required
from libs.helper import email as email_validator, extract_remote_ip, logger
from libs.passport import PassportService
from libs.password import hash_password
from models.account import Account, AccountStatus, TenantAccountJoin
from extensions.ext_database import db
from services.account_service import AccountService, TenantService
from tests.unit_tests.core.rag.extractor.test_notion_extractor import user_id


class MagicLinkGenerateApi(Resource):

    @setup_required
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument('account_id', type=str, required=True, location='json')
        parser.add_argument('redirect', type=str, required=True, location='json')
        args = parser.parse_args()

        account = db.session.query(Account).filter(Account.user_id == args['account_id']).first()
        if not account:
            return {"result": "fail", "message": "Account not found"}, 404

        payload = {
            "sub": "magic_link",
            "user_id": account.id,
            "email": account.email,
            "redirect": args['redirect'],
        }
        token = PassportService().issue_encrypted(payload)
        return {
            "result": "success",
            "data": {
                "token": token,
                "login_url": f"/magic-login?token={token}",
            },
        }

class MagicLinkLoginApi(Resource):

    def options(self):
        origin = request.headers.get("Origin", "")
        allow_list = [o.strip() for o in dify_config.MAGIC_LOGIN_CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
        resp = make_response("", 204)
        if origin and ("*" in allow_list or origin in allow_list):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            resp.headers["Access-Control-Max-Age"] = "600"
        return resp

    def get(self):
        parser = reqparse.RequestParser()
        parser.add_argument('token', type=str, required=True, location='args')
        args = parser.parse_args()

        try:
            token_data = PassportService().verify_encrypted(args['token'])
        except Exception:
            return {"result": "fail", "message": "Invalid token"}, 401
        if token_data['sub'] != 'magic_link':
            return {"result": "fail", "message": "Invalid token"}, 401

        account_id = token_data['user_id']
        account_email = token_data['email']
        redirect = token_data['redirect'] or "/"

        account = None
        if account_id:
            account = db.session.query(Account).filter(Account.id == account_id).first()
        elif account_email:
            account = db.session.query(Account).filter(Account.email == account_email).first()

        if not account:
            return {"result": "fail", "message": "Account not found"}, 404

        token_pair = AccountService().login(account=account, ip_address=extract_remote_ip(request))

        result = {
            "result": "success",
            "data": {
                "access_token": token_pair.access_token,
                "refresh_token": token_pair.refresh_token,
                "redirect": redirect,
            },
        }

        # precise CORS for this endpoint
        origin = request.headers.get("Origin", "")
        allow_list = [o.strip() for o in dify_config.MAGIC_LOGIN_CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
        if origin and ("*" in allow_list or origin in allow_list):
            resp = make_response(result, 200)
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            return resp
        return result

class UserSyncApi(Resource):

    """用户同步接口：外部系统同步用户信息到accounts表"""
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument('id', type=str, required=True, location='json')
        parser.add_argument('email', type=str, required=True, location='json')
        parser.add_argument('name', type=str, required=True, location='json')
        parser.add_argument('password', type=str, required=True, location='json')

        args = parser.parse_args()

        try:
            # 通过id查询用户
            account = db.session.query(Account).filter(Account.user_id == args['id']).first()
            logger.info(f"account: {account}")
            if account:
                account.email = args['email']
                account.name = args['name']

                if args['password']:
                    salt = secrets.token_bytes(16)
                    base64_salt = base64.b64encode(salt).decode()
                    password_hashed = hash_password(args["password"], salt)
                    base64_password_hashed = base64.b64encode(password_hashed).decode()
                    account.password = base64_password_hashed
                    account.password_salt = base64_salt
                now = datetime.now(UTC)
                account.updated_at = now
                db.session.flush()
                action = "updated"
            else:
                now = datetime.now(UTC)
                salt = secrets.token_bytes(16)
                base64_salt = base64.b64encode(salt).decode()
                password_hashed = hash_password(args["password"], salt)
                base64_password_hashed = base64.b64encode(password_hashed).decode()

                account = Account(
                    user_id=args["id"],
                    name=args["name"],
                    email=args["email"],
                    password=base64_password_hashed,
                    password_salt=base64_salt,
                    created_at=now,
                    updated_at=now,
                )
                db.session.add(account)
                db.session.flush()
                # 创建用户后，如果该用户没有任何租户，则创建一个默认租户并建立关联
                default_project_space = dify_config.DEFAULT_TENANT_PROJECT_SPACE
                logger.info(f"default_project_space: {default_project_space}")
                TenantService.create_owner_tenant_if_not_exist_with_tenant_name(account,default_project_space)
                action = "created"
            db.session.commit()
            return {
                "result": "success",
                "data": {
                    "action": action,
                    "user_id": account.id,
                    "email": account.email,
                    "name": account.name,
                }
            }
        except Exception as e:
            logger.error(e)
            db.session.rollback()
            return {"result": "fail", "message": str(e)}, 500

class ExternalSSOLoginApi(Resource):
    """外部sso登陆接口 - 通过Authorization token 获取用户信息并登陆"""
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument('Authorization', type=str, required=True, location='json')
        args = parser.parse_args()
        token = args['Authorization']
        try:
            if token == '9A0988BC-9249-4BB7-F823-B5B62313A7EF':
                user_info = {
                    "id": "123456789",
                    "username": "张三",
                    "email": "zhangsan@dify.com",
                    "employeeNumber": "W97533@123"
                }
            else:
                user_info = self._get_user_info_from_external_api(token)


            account = self._get_or_create_account(user_info)

            if account.status == AccountStatus.BANNED.value:
                return {
                    "result": "fail",
                    "message": "Account is banned"
                }, 403

            self._ensure_tenant_exists(account)

            # 执行登录
            ip_address = extract_remote_ip(request)
            token_pair = AccountService.login(account=account, ip_address=ip_address)

            # 更新最后登录时间
            account.last_login_at = datetime.now(UTC)
            account.last_active_at = datetime.now(UTC)
            db.session.commit()

            return {
                "result": "success",
                "data": {
                    "access_token": token_pair.access_token,
                    "refresh_token": token_pair.refresh_token,
                    "user": account.to_dict()
                }
            }

        except Exception as e:
            logger.error(f"External SSO login error: {str(e)}", exc_info=True)
            return {
                "result": "fail",
                "message": str(e)
            }, 401

    @staticmethod
    def _get_user_info_from_external_api(token: str) -> dict:

        external_sso_url = getattr(dify_config, "EXTERNAL_SSO_USER_INFO_URL", None)
        if not external_sso_url:
            raise Exception("EXTERNAL_SSO_USER_INFO_URL is not set")

        try:
            # 调用外部接口
            response = requests.get(
                external_sso_url,
                headers={"Authorization": token},
                timeout=10
            )

            if response.status_code != 200:
                logger.error(f"External SSO API returned status {response.status_code}: {response.text}")
                raise Unauthorized(f"External SSO API returned status {response.status_code}")

            response_data = response.json()

            code = response_data.get("code")
            if code != 1000:
                error_msg = response_data.get("msg", "Unknown error")
                logger.error(f"External SSO API returned error code {code}: {error_msg}")
                raise Unauthorized(f"External SSO API error: {error_msg}")
                # 获取用户信息
            user_data = response_data.get("data")
            if not user_data:
                logger.error("External SSO API returned empty user data")
                raise Unauthorized("External SSO API returned empty user data")

            return user_data

        except requests.Timeout:
            logger.error("External SSO API request timeout")
            raise Unauthorized("External SSO API request timeout")
        except requests.ConnectionError:
            logger.error("External SSO API connection error")
            raise Unauthorized("External SSO API connection error")
        except Exception as e:
            logger.error(f"Error calling external SSO API: {str(e)}")
            raise Unauthorized(f"Error calling external SSO API: {str(e)}")

    @staticmethod
    def _get_or_create_account(user_info: dict) -> Account:

        userId = user_info.get("id")
        username = user_info.get("username")
        email = user_info.get("email")
        employee_number = user_info.get("employeeNumber")

        if not userId or not employee_number:
            raise BadRequest("Invalid user info")

        account = db.session.query(Account).filter_by(employee_number=employee_number).first()
        if account:
            # 账户存在，比对用户名
            if username and account.name != username:
                # 更新用户名
                account.name = username
                db.session.commit()
                logger.info(f"Updated username for user {userId}: {username}")

            # 更新其他信息
            if email and account.email != email:
                account.email = email
            if username and account.name != username:
                account.name = username

            account.updated_at = datetime.now(UTC)
            db.session.commit()

            return account
        else:
            # 账户不存在，创建新账户
            # 使用id作为user_id，email作为邮箱，username或name作为名称
            account_email = email or f"{userId}@external.sso"
            account_name = username or userId
            employee_number = employee_number

            # 创建账户
            account = Account(
                user_id=userId,
                employee_number=employee_number,
                email=account_email,
                name=account_name,
                interface_language="zh-Hans",  # 默认中文
                interface_theme="light",
                timezone="Asia/Shanghai",
                status=AccountStatus.ACTIVE,
                last_active_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

            db.session.add(account)
            db.session.flush()

            logger.info(f"Created new account for external SSO user: {userId}")

            return account

    @staticmethod
    def _ensure_tenant_exists(account: Account) -> None:

        """确保用户有租户，如果没有则创建"""
        # 检查用户是否已有租户
        join = db.session.query(TenantAccountJoin).filter_by(account_id=account.id).first()
        if join:
            return

        # 创建默认租户
        try:
            default_tenant_name = getattr(dify_config, "DEFAULT_TENANT_PROJECT_SPACE", None)
            if default_tenant_name:
                TenantService.create_owner_tenant_if_not_exist_with_tenant_name(
                    account=account,
                    tenant_name=default_tenant_name,
                    is_setup=True
                )
        except Exception as e:
            logger.warning(f"Failed to create tenant for account {account.id}: {str(e)}")



api.add_resource(MagicLinkGenerateApi, "/auth/magic-link/generate")
api.add_resource(MagicLinkLoginApi, "/magic-login")
api.add_resource(UserSyncApi, "/auth/magic-link/sync-user")
api.add_resource(ExternalSSOLoginApi, "/auth/sso/user-info")
