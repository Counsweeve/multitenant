from datetime import datetime

import pytz
from flask import request
from flask_login import current_user
from flask_restx import Resource, fields, marshal_with, reqparse
from sqlalchemy import select
from sqlalchemy.orm import Session

from configs import dify_config
from constants.languages import supported_language
from controllers.console import api
from controllers.console.auth.error import (
    EmailAlreadyInUseError,
    EmailChangeLimitError,
    EmailCodeError,
    InvalidEmailError,
    InvalidTokenError,
)
from controllers.console.error import AccountInFreezeError, AccountNotFound, EmailSendIpLimitError
from controllers.console.workspace.error import (
    AccountAlreadyInitedError,
    CurrentPasswordIncorrectError,
    InvalidAccountDeletionCodeError,
    InvalidInvitationCodeError,
    RepeatPasswordNotMatchError,
)
from controllers.console.wraps import (
    account_initialization_required,
    cloud_edition_billing_enabled,
    enable_change_email,
    enterprise_license_required,
    only_edition_cloud,
    setup_required,
)
from extensions.ext_database import db
from fields.member_fields import account_fields
from libs.datetime_utils import naive_utc_now
from libs.helper import TimestampField, email, extract_remote_ip, timezone
from libs.login import login_required
from models import AccountIntegrate, InvitationCode
from models.account import Account, Menu, Role, RoleMenu, TenantAccountJoin, AccountRole
from services.account_service import AccountService, TenantService
from services.billing_service import BillingService
from services.errors.account import CurrentPasswordIncorrectError as ServiceCurrentPasswordIncorrectError
from services.menu_service import MenuService


class AccountInitApi(Resource):
    @setup_required
    @login_required
    def post(self):
        account = current_user

        if account.status == "active":
            raise AccountAlreadyInitedError()

        parser = reqparse.RequestParser()

        if dify_config.EDITION == "CLOUD":
            parser.add_argument("invitation_code", type=str, location="json")

        parser.add_argument("interface_language", type=supported_language, required=True, location="json")
        parser.add_argument("timezone", type=timezone, required=True, location="json")
        args = parser.parse_args()

        if dify_config.EDITION == "CLOUD":
            if not args["invitation_code"]:
                raise ValueError("invitation_code is required")

            # check invitation code
            invitation_code = (
                db.session.query(InvitationCode)
                .where(
                    InvitationCode.code == args["invitation_code"],
                    InvitationCode.status == "unused",
                )
                .first()
            )

            if not invitation_code:
                raise InvalidInvitationCodeError()

            invitation_code.status = "used"
            invitation_code.used_at = naive_utc_now()
            invitation_code.used_by_tenant_id = account.current_tenant_id
            invitation_code.used_by_account_id = account.id

        account.interface_language = args["interface_language"]
        account.timezone = args["timezone"]
        account.interface_theme = "light"
        account.status = "active"
        account.initialized_at = naive_utc_now()
        db.session.commit()

        return {"result": "success"}


class AccountProfileApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @marshal_with(account_fields)
    @enterprise_license_required
    def get(self):
        return current_user


class AccountNameApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @marshal_with(account_fields)
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument("name", type=str, required=True, location="json")
        args = parser.parse_args()

        # Validate account name length
        if len(args["name"]) < 3 or len(args["name"]) > 30:
            raise ValueError("Account name must be between 3 and 30 characters.")

        updated_account = AccountService.update_account(current_user, name=args["name"])

        return updated_account


class AccountAvatarApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @marshal_with(account_fields)
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument("avatar", type=str, required=True, location="json")
        args = parser.parse_args()

        updated_account = AccountService.update_account(current_user, avatar=args["avatar"])

        return updated_account


class AccountInterfaceLanguageApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @marshal_with(account_fields)
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument("interface_language", type=supported_language, required=True, location="json")
        args = parser.parse_args()

        updated_account = AccountService.update_account(current_user, interface_language=args["interface_language"])

        return updated_account


class AccountInterfaceThemeApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @marshal_with(account_fields)
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument("interface_theme", type=str, choices=["light", "dark"], required=True, location="json")
        args = parser.parse_args()

        updated_account = AccountService.update_account(current_user, interface_theme=args["interface_theme"])

        return updated_account


class AccountTimezoneApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @marshal_with(account_fields)
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument("timezone", type=str, required=True, location="json")
        args = parser.parse_args()

        # Validate timezone string, e.g. America/New_York, Asia/Shanghai
        if args["timezone"] not in pytz.all_timezones:
            raise ValueError("Invalid timezone string.")

        updated_account = AccountService.update_account(current_user, timezone=args["timezone"])

        return updated_account


class AccountPasswordApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    #@marshal_with(account_fields)
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument("password", type=str, required=False, location="json")
        parser.add_argument("new_password", type=str, required=True, location="json")
        parser.add_argument("repeat_new_password", type=str, required=True, location="json")
        args = parser.parse_args()

        if args["new_password"] != args["repeat_new_password"]:
            raise RepeatPasswordNotMatchError()

        try:
            AccountService.update_account_password(current_user, args["password"], args["new_password"])
        except ServiceCurrentPasswordIncorrectError:
            raise CurrentPasswordIncorrectError()
        return {"result": "success"}


class AccountIntegrateApi(Resource):
    integrate_fields = {
        "provider": fields.String,
        "created_at": TimestampField,
        "is_bound": fields.Boolean,
        "link": fields.String,
    }

    integrate_list_fields = {
        "data": fields.List(fields.Nested(integrate_fields)),
    }

    @setup_required
    @login_required
    @account_initialization_required
    @marshal_with(integrate_list_fields)
    def get(self):
        account = current_user

        account_integrates = db.session.query(AccountIntegrate).where(AccountIntegrate.account_id == account.id).all()

        base_url = request.url_root.rstrip("/")
        oauth_base_path = "/console/api/oauth/login"
        providers = ["github", "google"]

        integrate_data = []
        for provider in providers:
            existing_integrate = next((ai for ai in account_integrates if ai.provider == provider), None)
            if existing_integrate:
                integrate_data.append(
                    {
                        "id": existing_integrate.id,
                        "provider": provider,
                        "created_at": existing_integrate.created_at,
                        "is_bound": True,
                        "link": None,
                    }
                )
            else:
                integrate_data.append(
                    {
                        "id": None,
                        "provider": provider,
                        "created_at": None,
                        "is_bound": False,
                        "link": f"{base_url}{oauth_base_path}/{provider}",
                    }
                )

        return {"data": integrate_data}


class AccountDeleteVerifyApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def get(self):
        account = current_user

        token, code = AccountService.generate_account_deletion_verification_code(account)
        AccountService.send_account_deletion_verification_email(account, code)

        return {"result": "success", "data": token}


class AccountDeleteApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def post(self):
        account = current_user

        parser = reqparse.RequestParser()
        parser.add_argument("token", type=str, required=True, location="json")
        parser.add_argument("code", type=str, required=True, location="json")
        args = parser.parse_args()

        if not AccountService.verify_account_deletion_code(args["token"], args["code"]):
            raise InvalidAccountDeletionCodeError()

        AccountService.delete_account(account)

        return {"result": "success"}


class AccountDeleteUpdateFeedbackApi(Resource):
    @setup_required
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument("email", type=str, required=True, location="json")
        parser.add_argument("feedback", type=str, required=True, location="json")
        args = parser.parse_args()

        BillingService.update_account_deletion_feedback(args["email"], args["feedback"])

        return {"result": "success"}


class EducationVerifyApi(Resource):
    verify_fields = {
        "token": fields.String,
    }

    @setup_required
    @login_required
    @account_initialization_required
    @only_edition_cloud
    @cloud_edition_billing_enabled
    @marshal_with(verify_fields)
    def get(self):
        account = current_user

        return BillingService.EducationIdentity.verify(account.id, account.email)


class EducationApi(Resource):
    status_fields = {
        "result": fields.Boolean,
        "is_student": fields.Boolean,
        "expire_at": TimestampField,
        "allow_refresh": fields.Boolean,
    }

    @setup_required
    @login_required
    @account_initialization_required
    @only_edition_cloud
    @cloud_edition_billing_enabled
    def post(self):
        account = current_user

        parser = reqparse.RequestParser()
        parser.add_argument("token", type=str, required=True, location="json")
        parser.add_argument("institution", type=str, required=True, location="json")
        parser.add_argument("role", type=str, required=True, location="json")
        args = parser.parse_args()

        return BillingService.EducationIdentity.activate(account, args["token"], args["institution"], args["role"])

    @setup_required
    @login_required
    @account_initialization_required
    @only_edition_cloud
    @cloud_edition_billing_enabled
    @marshal_with(status_fields)
    def get(self):
        account = current_user

        res = BillingService.EducationIdentity.status(account.id)
        # convert expire_at to UTC timestamp from isoformat
        if res and "expire_at" in res:
            res["expire_at"] = datetime.fromisoformat(res["expire_at"]).astimezone(pytz.utc)
        return res


class EducationAutoCompleteApi(Resource):
    data_fields = {
        "data": fields.List(fields.String),
        "curr_page": fields.Integer,
        "has_next": fields.Boolean,
    }

    @setup_required
    @login_required
    @account_initialization_required
    @only_edition_cloud
    @cloud_edition_billing_enabled
    @marshal_with(data_fields)
    def get(self):
        parser = reqparse.RequestParser()
        parser.add_argument("keywords", type=str, required=True, location="args")
        parser.add_argument("page", type=int, required=False, location="args", default=0)
        parser.add_argument("limit", type=int, required=False, location="args", default=20)
        args = parser.parse_args()

        return BillingService.EducationIdentity.autocomplete(args["keywords"], args["page"], args["limit"])


class ChangeEmailSendEmailApi(Resource):
    @enable_change_email
    @setup_required
    @login_required
    @account_initialization_required
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument("email", type=email, required=True, location="json")
        parser.add_argument("language", type=str, required=False, location="json")
        parser.add_argument("phase", type=str, required=False, location="json")
        parser.add_argument("token", type=str, required=False, location="json")
        args = parser.parse_args()

        ip_address = extract_remote_ip(request)
        if AccountService.is_email_send_ip_limit(ip_address):
            raise EmailSendIpLimitError()

        if args["language"] is not None and args["language"] == "zh-Hans":
            language = "zh-Hans"
        else:
            language = "en-US"
        account = None
        user_email = args["email"]
        if args["phase"] is not None and args["phase"] == "new_email":
            if args["token"] is None:
                raise InvalidTokenError()

            reset_data = AccountService.get_change_email_data(args["token"])
            if reset_data is None:
                raise InvalidTokenError()
            user_email = reset_data.get("email", "")

            if user_email != current_user.email:
                raise InvalidEmailError()
        else:
            with Session(db.engine) as session:
                account = session.execute(select(Account).filter_by(email=args["email"])).scalar_one_or_none()
            if account is None:
                raise AccountNotFound()

        token = AccountService.send_change_email_email(
            account=account, email=args["email"], old_email=user_email, language=language, phase=args["phase"]
        )
        return {"result": "success", "data": token}


class ChangeEmailCheckApi(Resource):
    @enable_change_email
    @setup_required
    @login_required
    @account_initialization_required
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument("email", type=email, required=True, location="json")
        parser.add_argument("code", type=str, required=True, location="json")
        parser.add_argument("token", type=str, required=True, nullable=False, location="json")
        args = parser.parse_args()

        user_email = args["email"]

        is_change_email_error_rate_limit = AccountService.is_change_email_error_rate_limit(args["email"])
        if is_change_email_error_rate_limit:
            raise EmailChangeLimitError()

        token_data = AccountService.get_change_email_data(args["token"])
        if token_data is None:
            raise InvalidTokenError()

        if user_email != token_data.get("email"):
            raise InvalidEmailError()

        if args["code"] != token_data.get("code"):
            AccountService.add_change_email_error_rate_limit(args["email"])
            raise EmailCodeError()

        # Verified, revoke the first token
        AccountService.revoke_change_email_token(args["token"])

        # Refresh token data by generating a new token
        _, new_token = AccountService.generate_change_email_token(
            user_email, code=args["code"], old_email=token_data.get("old_email"), additional_data={}
        )

        AccountService.reset_change_email_error_rate_limit(args["email"])
        return {"is_valid": True, "email": token_data.get("email"), "token": new_token}


class ChangeEmailResetApi(Resource):
    @enable_change_email
    @setup_required
    @login_required
    @account_initialization_required
    @marshal_with(account_fields)
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument("new_email", type=email, required=True, location="json")
        parser.add_argument("token", type=str, required=True, nullable=False, location="json")
        args = parser.parse_args()

        if AccountService.is_account_in_freeze(args["new_email"]):
            raise AccountInFreezeError()

        if not AccountService.check_email_unique(args["new_email"]):
            raise EmailAlreadyInUseError()

        reset_data = AccountService.get_change_email_data(args["token"])
        if not reset_data:
            raise InvalidTokenError()

        AccountService.revoke_change_email_token(args["token"])

        old_email = reset_data.get("old_email", "")
        if current_user.email != old_email:
            raise AccountNotFound()

        updated_account = AccountService.update_account_email(current_user, email=args["new_email"])

        AccountService.send_change_email_completed_notify_email(
            email=args["new_email"],
        )

        return updated_account


class CheckEmailUnique(Resource):
    @setup_required
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument("email", type=email, required=True, location="json")
        args = parser.parse_args()
        if AccountService.is_account_in_freeze(args["email"]):
            raise AccountInFreezeError()
        if not AccountService.check_email_unique(args["email"]):
            raise EmailAlreadyInUseError()
        return {"result": "success"}

class AccountCreateApi(Resource):
    """
    创建账户接口
    根据用户名、邮箱和密码创建新用户
    """

    @setup_required
    @login_required
    @account_initialization_required
    def post(self):
        # 解析创建账户所需参数
        parser = reqparse.RequestParser()
        parser.add_argument("email", type=email, required=True, location="json")
        parser.add_argument("password", type=str, required=True, location="json")
        parser.add_argument("name", type=str, required=True, location="json")
        parser.add_argument("role_id", type=str, required=True, location="json")
        parser.add_argument("data_role", type=str, required=False, location="json")
        args = parser.parse_args()


        # 检查邮箱是否已被使用
        if not AccountService.check_email_unique(args["email"]):
            raise EmailAlreadyInUseError()

        # 检查账户是否被冻结
        if AccountService.is_account_in_freeze(args["email"]):
            raise AccountInFreezeError()

        # 设置默认界面语言
        interface_language = "zh-Hans"

        role_id = args["role_id"]
        data_role = args["data_role"]
        account = AccountService.create_account(
            email=args["email"],
            password=args["password"],
            name=args["name"],
            interface_language=interface_language,
            is_setup=True
        )
        tenant_id = current_user.current_tenant_id
        TenantService.create_owner_tenant_if_not_exist2(account=account,is_setup=True, role_id=role_id, tenant_id=tenant_id, data_role=data_role)
        # 在account_roles表中为用户添加角色
        if role_id:
            TenantAccountRoleService.add_account_role(tenant_id, account.id, role_id)

        return {"result": "success", "data": account.to_dict()}

class TenantAccountRoleService:
    """租户账户角色管理服务"""

    @staticmethod
    def add_role_to_user(tenant_id: str, account_id: str, role_id: str) -> bool:
        """为用户添加角色"""
        tenant_join = db.session.query(TenantAccountJoin).filter(
            TenantAccountJoin.tenant_id == tenant_id,
            TenantAccountJoin.account_id == account_id
        ).first()

        if not tenant_join:
            return False

        # 验证角色是否存在且属于该租户
        role = db.session.query(Role).filter(
            Role.id == role_id,
            Role.tenant_id == tenant_id,
            Role.is_active == True
        ).first()

        if not role:
            return False

        # 添加角色ID
        tenant_join.add_rbac_role_id(role_id)
        db.session.commit()
        return True

    @staticmethod
    def add_account_role(tenant_id: str, account_id: str, role_id: str) -> bool:
        """在account_roles表中为用户添加角色"""
        # 验证角色是否存在且属于该租户
        role = db.session.query(Role).filter(
            Role.id == role_id,
            Role.tenant_id == tenant_id,
            Role.is_active == True
        ).first()

        if not role:
            return False

        # 检查是否已存在相同的角色关联
        existing_role = db.session.query(AccountRole).filter(
            AccountRole.tenant_id == tenant_id,
            AccountRole.account_id == account_id,
            AccountRole.role_id == role_id
        ).first()

        if existing_role:
            return True  # 角色已存在，直接返回成功

        # 创建新的角色关联
        account_role = AccountRole(
            tenant_id=tenant_id,
            account_id=account_id,
            role_id=role_id
        )
        db.session.add(account_role)
        db.session.commit()
        return True

    @staticmethod
    def remove_role_from_user(tenant_id: str, account_id: str, role_id: str) -> bool:
        """移除用户角色"""
        tenant_join = db.session.query(TenantAccountJoin).filter(
            TenantAccountJoin.tenant_id == tenant_id,
            TenantAccountJoin.account_id == account_id
        ).first()

        if not tenant_join:
            return False

        # 移除角色ID
        tenant_join.remove_rbac_role_id(role_id)
        db.session.commit()
        return True

    @staticmethod
    def set_user_roles(tenant_id: str, account_id: str, role_ids: list[str]) -> bool:
        """设置用户的所有角色"""
        tenant_join = db.session.query(TenantAccountJoin).filter(
            TenantAccountJoin.tenant_id == tenant_id,
            TenantAccountJoin.account_id == account_id
        ).first()

        if not tenant_join:
            return False

        # 验证所有角色是否存在且属于该租户
        if role_ids:
            valid_roles = db.session.query(Role).filter(
                Role.id.in_(role_ids),
                Role.tenant_id == tenant_id,
                Role.is_active == True
            ).all()

            if len(valid_roles) != len(role_ids):
                return False

        # 设置角色ID列表
        tenant_join.set_rbac_role_ids(role_ids)
        db.session.commit()
        return True



class AccountTenantInfoApi(Resource):
    """
    用户租户获和权限信息接口
    获取当前登陆用户所属租户以及账户信息包括角色和授权的菜单列表
    """

    # 定义返回字段结构
    tenant_info_fields = {
        "id": fields.String,
        "name": fields.String,
        "plan": fields.String,
        "status": fields.String,
        "created_at": TimestampField,
        "updated_at": TimestampField,
    }

    role_fields = {
        "id": fields.String,
        "role_name": fields.String,
        "description": fields.String,
        "is_active": fields.Boolean,
        # "created_at": TimestampField,
        # "updated_at": TimestampField,
    }

    menu_item_fields = {
        "id": fields.String,
        "menu_key": fields.String,
        "menu_name": fields.String,
        "parent_id": fields.String,
        "icon": fields.String,
        "path": fields.String,
        "sort_order": fields.Integer,
        "is_active": fields.Boolean,
        "children": fields.List(fields.Raw),
    }

    account_tenant_info_fields = {
        "account": fields.Nested(account_fields),
        "tenant": fields.Nested(tenant_info_fields),
        "roles": fields.List(fields.Nested(role_fields)),
        "menus": fields.List(fields.Nested(menu_item_fields)),
        "menu_key": fields.List(fields.String),
        "roles_admin": fields.List(fields.String),
    }

    @setup_required
    @login_required
    @account_initialization_required
    @marshal_with(account_tenant_info_fields)
    def get(self):
        """获取当前用户的租户信息、绑定的角色和角色绑定的菜单集合"""
        try:
            # 获取当前用户
            account = current_user

            # 获取当前租户信息
            tenant = account.current_tenant
            if not tenant:
                return {"result":"fail", "error": "用户未加入任何租户"}, 404

            # 查询用户绑定的RBAC角色（支持多角色，逗号分隔）
            # tenant_join = db.session.query(TenantAccountJoin).filter(
            #     TenantAccountJoin.tenant_id == tenant.id,
            #     TenantAccountJoin.account_id == account.id
            # ).first()

            account_role = db.session.query(AccountRole).filter(
                AccountRole.account_id == account.id,
                AccountRole.tenant_id == tenant.id
            ).first()

            roles = []
            role_ids = []

            if account_role and account_role.role_id:
                # 获取逗号分隔的角色ID列表
                role_id_list = account_role.get_role_ids()

                if role_id_list:
                    # 查询所有角色信息
                    rbac_roles = db.session.query(Role).filter(
                        Role.id.in_(role_id_list),
                        Role.is_active == True
                    ).all()

                    # 构建角色信息列表
                    for role in rbac_roles:
                        role_dict = role.to_dict()
                        # 第一个角色设为主要角色
                        role_dict['is_primary'] = (role.id == role_id_list[0])
                        roles.append(role_dict)
                        role_ids.append(role.id)

            # 查询角色绑定的菜单
            menus = []
            if role_ids:
                # 获取角色关联的所有菜单（去重）
                role_menus = db.session.query(Menu).join(
                    RoleMenu, Menu.id == RoleMenu.menu_id
                ).filter(
                    RoleMenu.role_id.in_(role_ids),
                    Menu.is_active == True
                ).distinct().order_by(Menu.sort_order).all()

                # 转换为字典格式
                menu_list = [menu.to_dict() for menu in role_menus]
                # 构建菜单树
                menus = MenuService.build_menu_tree(menu_list)

            # 构建租户信息
            tenant_info = {
                "id": tenant.id,
                "name": tenant.name,
                "plan": tenant.plan,
                "status": tenant.status,
                "created_at": tenant.created_at,
                "updated_at": tenant.updated_at,
            }

            # 辅助函数：递归收集所有menu_key
            def collect_menu_keys(menu_list):
                menu_keys = []
                for menu in menu_list:
                    if 'menu_key' in menu:
                        menu_keys.append(menu['menu_key'])
                    if 'children' in menu and menu['children']:
                        menu_keys.extend(collect_menu_keys(menu['children']))
                return menu_keys

            # 收集所有menu_key
            menu_keys = collect_menu_keys(menus)

            # 从roles中收集menu_key（如果roles中有menu_key字段）
            for role in roles:
                if 'menu_key' in role:
                    menu_keys.append(role['menu_key'])
                # 如果roles中也有children字段，递归收集
                if 'children' in role and role['children']:
                    menu_keys.extend(collect_menu_keys(role['children']))

            # 去重，确保返回的menu_key数组中没有重复值
            menu_keys = list(set(menu_keys))

            #添加roles_admin
            # 查询tenant_account_joins表中符合条件的记录
            tenant_account_joins = db.session.query(TenantAccountJoin).filter(
                TenantAccountJoin.account_id == account.id,
                TenantAccountJoin.tenant_id == tenant.id
            ).all()

            # 提取role字段值并放入集合
            roles_admin = list({join.role for join in tenant_account_joins if hasattr(join, 'role') and join.role})

            return {
                "result": "success",
                "account": account,
                "tenant": tenant_info,
                "roles": roles,
                "menus": menus,
                "menu_key": menu_keys,
                "roles_admin": roles_admin
            }

        except Exception as e:
            return {"error": f"获取用户信息失败: {str(e)}"}, 500


class TenantUsersApi(Resource):
    """
    当前租户用户列表接口
    返回当前登录用户所在租户下的所有用户，包含基础信息与RBAC角色
    """

    user_role_fields = {
        "id": fields.String,
        "role_name": fields.String,
    }

    user_item_fields = {
        "id": fields.String,
        "name": fields.String,
        "email": fields.String,
        "last_active_at": TimestampField,
        "status": fields.String,
        "role": fields.String,
        "roles": fields.List(fields.Nested(user_role_fields)),
    }

    user_list_fields = {
        "data": fields.List(fields.Nested(user_item_fields)),
    }

    @setup_required
    @login_required
    @account_initialization_required
    @marshal_with(user_list_fields)
    def get(self):
        """获取当前租户的用户列表"""
        account = current_user
        tenant = account.current_tenant
        if not tenant:
            return {"data": []}

        # 查询当前租户下的所有账号及其关联记录（包括没有角色的账号）
        # 通过tenantaccountjoin表关联筛选tenantid
        rows = (
            db.session.query(Account, AccountRole, TenantAccountJoin)
            .join(
                TenantAccountJoin,
                TenantAccountJoin.account_id == Account.id
            )
            .outerjoin(
                AccountRole,
                db.and_(
                    AccountRole.tenant_id == tenant.id,
                    AccountRole.account_id == Account.id
                )
            )
            .where(TenantAccountJoin.tenant_id == tenant.id)
            .all()
        )

        users: list[dict] = []
        for acc, accRole, tenantJoin in rows:
            # 获取自定义RBAC角色（可能为空）
            roles = []
            try:
                # 只有当accRole不为None时才查询角色信息
                if accRole and hasattr(accRole, 'role_id') and accRole.role_id:
                    # 从Role表中查询id等于accRole.role_id的记录
                    role = db.session.query(Role).filter(Role.id == accRole.role_id).first()
                    if role:
                        roles = [{"id": role.id, "role_name": role.role_name}]
            except Exception:
                roles = []
            print(f"  Account ID: {acc.id}")
            print(f"  Account Name: {acc.name}")
            print(f"  Account Email: {acc.email}")
            print(f"  AccountRole: {accRole.role_id if accRole else 'None'}")
            print(f"  TenantAccountJoin Role: {tenantJoin.role if tenantJoin else 'None'}")
            users.append(
                {
                    "id": acc.id,
                    "name": acc.name,
                    "email": acc.email,
                    "last_active_at": acc.last_active_at,
                    "status": acc.status,
                    "role": tenantJoin.role if tenantJoin else None,
                    "roles": roles,
                }
            )

        return {"data": users}


# Register API resources
api.add_resource(AccountInitApi, "/account/init")
api.add_resource(AccountProfileApi, "/account/profile")
api.add_resource(AccountNameApi, "/account/name")
api.add_resource(AccountAvatarApi, "/account/avatar")
api.add_resource(AccountInterfaceLanguageApi, "/account/interface-language")
api.add_resource(AccountInterfaceThemeApi, "/account/interface-theme")
api.add_resource(AccountTimezoneApi, "/account/timezone")
api.add_resource(AccountPasswordApi, "/account/password")
api.add_resource(AccountIntegrateApi, "/account/integrates")
api.add_resource(AccountDeleteVerifyApi, "/account/delete/verify")
api.add_resource(AccountDeleteApi, "/account/delete")
api.add_resource(AccountDeleteUpdateFeedbackApi, "/account/delete/feedback")
api.add_resource(EducationVerifyApi, "/account/education/verify")
api.add_resource(EducationApi, "/account/education")
api.add_resource(EducationAutoCompleteApi, "/account/education/autocomplete")
# Change email
api.add_resource(ChangeEmailSendEmailApi, "/account/change-email")
api.add_resource(ChangeEmailCheckApi, "/account/change-email/validity")
api.add_resource(ChangeEmailResetApi, "/account/change-email/reset")
api.add_resource(CheckEmailUnique, "/account/change-email/check-email-unique")
api.add_resource(AccountCreateApi, "/account/create")
api.add_resource(AccountTenantInfoApi, "/account/tenant-info")
api.add_resource(TenantUsersApi, "/account/tenant/users")
# api.add_resource(AccountEmailApi, '/account/email')
# api.add_resource(AccountEmailVerifyApi, '/account/email-verify')
