from re import search

from flask import request
from flask_login import current_user
from flask_restx import Resource, reqparse

from controllers.console import api
from controllers.console.wraps import (
    account_initialization_required,
    setup_required,
)
from fields.role_fields import AuthorizedPersonSearchRequest, ResourceAuthorizationRequest
from libs.login import login_required
from services.role_account_service import RoleAccountService
from services.role_service import RoleService


class RoleListApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def get(self):
        """获取角色列表"""
        parser = reqparse.RequestParser()
        parser.add_argument("keyword", type=str, required=False, location="args")
        parser.add_argument("is_active", type=bool, required=False, location="args")
        parser.add_argument("page", type=int, required=False, location="args", default=1)
        parser.add_argument("page_size", type=int, required=False, location="args", default=20)
        args = parser.parse_args()

        try:
            tenant_id = current_user.current_tenant.id
            data = RoleService.list_roles(
                tenant_id=tenant_id,
                keyword=args.get("keyword"),
                is_active=args.get("is_active", True),
                page=args["page"],
                size=args["page_size"]
            )
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "message": str(e)}, 400

    @setup_required
    @login_required
    @account_initialization_required
    def post(self):
        """创建角色"""
        try:
            tenant_id = current_user.current_tenant.id
            data = request.get_json(force=True) or {}

            # 验证必填字段
            if not data.get("role_name"):
                return {"success": False, "message": "角色名称不能为空"}, 400

            role_id = RoleService.create_role(tenant_id, data)
            return {"success": True, "data": {"id": role_id}, "message": "角色创建成功"}, 201
        except ValueError as e:
            return {"success": False, "message": str(e)}, 400
        except Exception as e:
            return {"success": False, "message": f"创建角色失败: {str(e)}"}, 500


class RoleAllListApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def get(self):
        """获取所有角色列表（无分页）"""


        try:
            tenant_id = current_user.current_tenant.id
            # 调用 RoleService 的新方法获取所有角色
            data = RoleService.list_all_roles(
                tenant_id=tenant_id
            )
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "message": str(e)}, 400

class RoleDetailApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def get(self, role_id):
        """获取角色详情"""
        try:
            tenant_id = current_user.current_tenant.id
            include_stats = request.args.get("include_stats", "false").lower() == "true"

            role = RoleService.get_role(tenant_id, role_id, include_stats=include_stats)
            if not role:
                return {"success": False, "message": "角色不存在"}, 404

            return {"success": True, "data": role}
        except Exception as e:
            return {"success": False, "message": str(e)}, 400

    @setup_required
    @login_required
    @account_initialization_required
    def put(self, role_id):
        """更新角色"""
        try:
            tenant_id = current_user.current_tenant.id
            data = request.get_json(force=True) or {}

            RoleService.update_role(tenant_id, role_id, data)
            return {"success": True, "message": "角色更新成功"}
        except ValueError as e:
            return {"success": False, "message": str(e)}, 400
        except Exception as e:
            return {"success": False, "message": f"更新角色失败: {str(e)}"}, 500

    @setup_required
    @login_required
    @account_initialization_required
    def delete(self, role_id):
        """删除角色"""
        try:
            tenant_id = current_user.current_tenant.id
            force = request.args.get("force", "false").lower() == "true"

            result = RoleService.delete_role(tenant_id, role_id, force=force)
            return {"success": True, "data": result, "message": "角色删除成功"}
        except ValueError as e:
            return {"success": False, "message": str(e)}, 400
        except Exception as e:
            return {"success": False, "message": f"删除角色失败: {str(e)}"}, 500


class RoleMenusApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def get(self, role_id):
        """获取角色菜单"""
        try:
            include_tree = request.args.get("include_tree", "false").lower() == "true"
            data = RoleService.get_menu_tree_with_authorization(role_id, include_tree)
            return {"success": True, "data": data}
        except ValueError as e:
            return {"success": False, "message": str(e)}, 400
        except Exception as e:
            return {"success": False, "message": str(e)}, 400

    @setup_required
    @login_required
    @account_initialization_required
    def put(self, role_id):
        """为角色分配菜单"""
        try:
            tenant_id = current_user.current_tenant.id
            data = request.get_json(force=True) or {}
            menu_ids = data.get("menu_ids", [])

            result = RoleService.assign_menus(tenant_id, role_id, menu_ids)
            return {"success": True, "data": result, "message": "菜单分配成功"}
        except ValueError as e:
            return {"success": False, "message": str(e)}, 400
        except Exception as e:
            return {"success": False, "message": f"分配菜单失败: {str(e)}"}, 500


class RoleUsersApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def get(self, role_id):
        """获取角色用户"""
        parser = reqparse.RequestParser()
        parser.add_argument("keyword", type=str, required=False, location="args", default="")
        parser.add_argument("page", type=int, required=False, location="args", default=1)
        parser.add_argument("page_size", type=int, required=False, location="args", default=20)
        args = parser.parse_args()

        try:
            tenant_id = current_user.current_tenant.id
            print("role_id", role_id)
            print("tenant_id", tenant_id)
            print("args", args)
            data = RoleAccountService.get_role_accounts(
                tenant_id=tenant_id,
                role_id=role_id,
                keyword=args.get("keyword"),
                page=args["page"],
                page_size=args["page_size"]
            )
            return {"success": True, "data": data}
        except ValueError as e:
            return {"success": False, "message": str(e)}, 400
        except Exception as e:
            return {"success": False, "message": str(e)}, 400

    @setup_required
    @login_required
    @account_initialization_required
    def put(self, role_id):
        """为角色分配用户"""
        try:
            tenant_id = current_user.current_tenant.id
            data = request.get_json(force=True) or {}
            account_ids = data.get("account_ids", [])

            result = RoleAccountService.assign_accounts_to_role(tenant_id, role_id, account_ids)
            return {"success": True, "data": result, "message": "用户分配成功"}
        except ValueError as e:
            return {"success": False, "message": str(e)}, 400
        except Exception as e:
            return {"success": False, "message": f"分配用户失败: {str(e)}"}, 500


class RoleUserApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def post(self, role_id, account_id):
        """添加用户到角色"""
        try:
            tenant_id = current_user.current_tenant.id
            result = RoleAccountService.add_account_to_role(tenant_id, role_id, account_id)

            if result["success"]:
                return {"success": True, "data": result, "message": result["message"]}
            else:
                return {"success": False, "message": result["message"]}, 400
        except ValueError as e:
            return {"success": False, "message": str(e)}, 400
        except Exception as e:
            return {"success": False, "message": str(e)}, 400

    @setup_required
    @login_required
    @account_initialization_required
    def delete(self, role_id, account_id):
        """从角色中移除用户"""
        try:
            tenant_id = current_user.current_tenant.id
            result = RoleAccountService.remove_user_from_role(tenant_id, role_id, account_id)

            if result["success"]:
                return {"success": True, "data": result, "message": result["message"]}
            else:
                return {"success": False, "message": result["message"]}, 400
        except ValueError as e:
            return {"success": False, "message": str(e)}, 400
        except Exception as e:
            return {"success": False, "message": str(e)}, 400





class RoleBatchApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def put(self):
        """批量更新角色状态"""
        try:
            tenant_id = current_user.current_tenant.id
            data = request.get_json(force=True) or {}

            role_ids = data.get("role_ids", [])
            is_active = data.get("is_active", True)

            if not role_ids:
                return {"success": False, "message": "请选择要更新的角色"}, 400

            result = RoleService.batch_update_role_status(tenant_id, role_ids, is_active)
            return {"success": True, "data": result, "message": "批量更新成功"}
        except Exception as e:
            return {"success": False, "message": str(e)}, 400

    @setup_required
    @login_required
    @account_initialization_required
    def delete(self):
        """批量删除角色"""
        try:
            tenant_id = current_user.current_tenant.id
            data = request.get_json(force=True) or {}

            role_ids = data.get("role_ids", [])
            force = data.get("force", False)

            if not role_ids:
                return {"success": False, "message": "请选择要删除的角色"}, 400

            result = RoleService.batch_delete_roles(tenant_id, role_ids, force=force)

            # 构建响应消息
            deleted_count = result.get("deleted_count", 0)
            failed_count = len(result.get("failed_roles", []))
            invalid_count = len(result.get("invalid_roles", []))

            if deleted_count > 0 and failed_count == 0 and invalid_count == 0:
                message = f"成功删除 {deleted_count} 个角色"
            elif deleted_count > 0:
                message = f"成功删除 {deleted_count} 个角色"
                if failed_count > 0:
                    message += f"，{failed_count} 个角色删除失败"
                if invalid_count > 0:
                    message += f"，{invalid_count} 个角色无效"
            else:
                message = "没有角色被删除"
                if failed_count > 0:
                    message += f"，{failed_count} 个角色删除失败"
                if invalid_count > 0:
                    message += f"，{invalid_count} 个角色无效"

            return {"success": True, "data": result, "message": message}
        except Exception as e:
            return {"success": False, "message": f"批量删除角色失败: {str(e)}"}, 500


class RoleAvailableMenusApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def get(self, role_id):
        """获取角色可分配的菜单"""
        try:
            tenant_id = current_user.current_tenant.id
            menus = RoleService.get_available_menus_for_role(tenant_id, role_id)
            return {"success": True, "data": menus}
        except ValueError as e:
            return {"success": False, "message": str(e)}, 400
        except Exception as e:
            return {"success": False, "message": str(e)}, 400


class RoleAvailableUsersApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def get(self, role_id):
        """获取角色可分配的用户（未拥有该角色的用户）"""
        parser = reqparse.RequestParser()
        parser.add_argument("keyword", type=str, required=False, location="args")
        parser.add_argument("page", type=int, required=False, location="args", default=1)
        parser.add_argument("page_size", type=int, required=False, location="args", default=20)
        args = parser.parse_args()

        try:
            tenant_id = current_user.current_tenant.id
            data = RoleAccountService.get_accounts_without_role(
                tenant_id=str(tenant_id),
                role_id=str(role_id),
                keyword=args.get("keyword"),
                page=args["page"],
                size=args["page_size"]
            )
            return {"success": True, "data": data}
        except ValueError as e:
            return {"success": False, "message": str(e)}, 400
        except Exception as e:
            return {"success": False, "message": str(e)}, 400


# 用户角色管理接口
class UserRoleListApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def get(self, account_id):
        """获取用户角色"""
        try:
            tenant_id = current_user.current_tenant.id
            roles = RoleAccountService.get_account_roles(tenant_id, account_id)
            return {"success": True, "data": roles}
        except Exception as e:
            return {"success": False, "message": str(e)}, 400

    @setup_required
    @login_required
    @account_initialization_required
    def put(self, account_id):
        """为用户分配角色"""
        try:
            tenant_id = current_user.current_tenant.id
            data = request.get_json(force=True) or {}
            role_ids = data.get("role_ids", [])

            result = RoleAccountService.assign_roles_to_user(tenant_id, account_id, role_ids)
            return {"success": True, "data": result, "message": "角色分配成功"}
        except ValueError as e:
            return {"success": False, "message": str(e)}, 400
        except Exception as e:
            return {"success": False, "message": f"分配角色失败: {str(e)}"}, 500


class AuthorizedPersonListApi(Resource):
    """被授权人列表API"""

    @setup_required
    @login_required
    def get(self):
        """获取被授权人列表"""
        parser = reqparse.RequestParser()
        parser.add_argument("email", type=str, required=False, location="args")
        parser.add_argument("role", type=int, required=False, location="args")
        parser.add_argument("name", type=str, required=False, location="args")
        parser.add_argument("page", type=int, required=False, location="args", default=1)
        parser.add_argument("page_size", type=int, required=False, location="args", default=20)

        args = parser.parse_args()

        search_request = AuthorizedPersonSearchRequest(
            email=args.get("email"),
            role=args.get("role"),
            name=args.get("name"),
            page=args["page"],
            page_size=args["page_size"]
        )

        result = RoleService.search_authorized_person(
            tenant_id=current_user.current_tenant.id,
            search_request=search_request
        )

        return {"success": True, "data": result.model_dump()}

class ResourceAuthorizationApi(Resource):
    """资源授权API"""

    @setup_required
    @login_required
    @account_initialization_required
    def get(self, role_id: str):
        """获取角色的资源授权情况"""
        parser = reqparse.RequestParser()
        parser.add_argument("resource_type", type=str, required=True, location="args")

        args = parser.parse_args()

        resource_type = args.get("resource_type")

        if resource_type not in ["model", "dataset"]:
            return {"success": False, "message": "无效的资源类型"}, 400

        result = RoleService.get_resource_authorization(
            tenant_id=current_user.current_tenant.id,
            role_id=role_id,
            resource_type=resource_type
        )
        return {"success": True, "data": result.model_dump()}

    @setup_required
    @login_required
    def post(self, role_id: str):
        """为角色授权资源"""
        try:
            data = request.get_json()
            if not data:
                return {"success": False, "message": "无效的请求数据"}, 400
            # 验证请求数据
            if 'resource_type' not in data:
                return {"success": False, "message": "resource_type is required"}, 400
            if data['resource_type'] not in ['model', 'dataset']:
                return {"success": False, "message": "无效的资源类型"}, 400

            request_data = ResourceAuthorizationRequest(
                role_id=str(role_id),
                resource_type=data['resource_type'],
                authorized_resource_ids=data.get('authorized_resource_ids', []),
                unauthorized_resource_ids=data.get('unauthorized_resource_ids', [])
            )

            success = RoleService.update_resource_authorization(
                tenant_id=current_user.current_tenant.id,
                request=request_data)
            if success:
                return {"success": True, "message": "授权成功"}
            else:
                return {"success": False, "message": "授权失败"}, 500
        except Exception as e:
            return {"success": False, "message": str(e)}, 500

class ResourceListApi(Resource):
    """资源列表API"""

    @setup_required
    @login_required
    def get(self):
        """获取所有可用的资源"""
        parser = reqparse.RequestParser()
        parser.add_argument("resource_type", type=str, required=True, location="args")

        args = parser.parse_args()
        resource_type = args["resource_type"]
        result = RoleService.get_resource_list(
            tenant_id=current_user.current_tenant.id,
            role_id="", # 空字符串 即获取所有资源
            resource_type=resource_type,
            authorized_resources=[] # 空列表即获取所有资源
        )
        serialized_result = [item.model_dump() for item in result] if result else []
        return {"success": True, "data": {
            "resource_type": resource_type,
            "resources": serialized_result
        }}




# 注册角色管理路由
api.add_resource(RoleListApi, "/workspaces/current/roles")
api.add_resource(RoleDetailApi, "/workspaces/current/roles/<uuid:role_id>")
api.add_resource(RoleMenusApi, "/workspaces/current/roles/<uuid:role_id>/menus")
api.add_resource(RoleUsersApi, "/workspaces/current/roles/<uuid:role_id>/users")
api.add_resource(RoleUserApi, "/workspaces/current/roles/<uuid:role_id>/users/<uuid:account_id>")
api.add_resource(RoleBatchApi, "/workspaces/current/roles/batch")
api.add_resource(RoleAvailableMenusApi, "/workspaces/current/roles/<uuid:role_id>/available-menus")
api.add_resource(RoleAvailableUsersApi, "/workspaces/current/roles/<uuid:role_id>/available-users")

api.add_resource(AuthorizedPersonListApi, "/workspaces/current/role/accounts")
api.add_resource(ResourceAuthorizationApi, "/workspaces/current/roles/<uuid:role_id>/resource-authorization")
api.add_resource(ResourceListApi, "/workspaces/current/resources")
api.add_resource(RoleAllListApi, "/workspaces/current/roles/all")


# 注册用户角色管理路由
api.add_resource(UserRoleListApi, "/workspaces/current/users/<uuid:account_id>/roles")
