from flask import request
from flask_login import current_user
from flask_restx import Resource, reqparse

from controllers.console import api
from controllers.console.wraps import (
    account_initialization_required,
    setup_required,
)
from libs.login import login_required
from services.menu_service import MenuService


class MenuListApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def get(self):
        """获取菜单列表"""
        parser = reqparse.RequestParser()
        parser.add_argument("keyword", type=str, required=False, location="args")
        parser.add_argument("parent_id", type=str, required=False, location="args")
        parser.add_argument("is_active", type=bool, required=False, location="args", default=True)
        parser.add_argument("page", type=int, required=False, location="args", default=1)
        parser.add_argument("page_size", type=int, required=False, location="args", default=50)
        args = parser.parse_args()

        try:
            data = MenuService.list_menus(
                keyword=args.get("keyword"),
                parent_id=args.get("parent_id"),
                is_active=args.get("is_active"),
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
        """创建菜单"""
        try:
            data = request.get_json(force=True) or {}

            # 验证必填字段
            required_fields = ["menu_key", "menu_name", "menu_type" ]
            for field in required_fields:
                if not data.get(field):
                    return {"success": False, "message": f"缺少必填字段: {field}"}, 400

            menu_id = MenuService.create_menu(data)
            return {"success": True, "data": {"id": menu_id}, "message": "菜单创建成功"}, 201
        except ValueError as e:
            return {"success": False, "message": str(e)}, 400
        except Exception as e:
            return {"success": False, "message": f"创建菜单失败: {str(e)}"}, 500


class MenuDetailApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def get(self, menu_id):
        """获取菜单详情"""
        try:
            menu = MenuService.get_menu(menu_id)
            if not menu:
                return {"success": False, "message": "菜单不存在"}, 404

            return {"success": True, "data": menu}
        except Exception as e:
            return {"success": False, "message": str(e)}, 400

    @setup_required
    @login_required
    @account_initialization_required
    def put(self, menu_id):
        """更新菜单"""
        try:
            data = request.get_json(force=True) or {}
            MenuService.update_menu(menu_id, data)
            return {"success": True, "message": "菜单更新成功"}
        except ValueError as e:
            return {"success": False, "message": str(e)}, 400
        except Exception as e:
            return {"success": False, "message": f"更新菜单失败: {str(e)}"}, 500

    @setup_required
    @login_required
    @account_initialization_required
    def delete(self, menu_id):
        """删除菜单"""
        try:
            cascade = request.args.get("cascade", "false").lower() == "true"
            result = MenuService.delete_menu(menu_id, cascade=cascade)
            return {"success": True, "data": result, "message": "菜单删除成功"}
        except ValueError as e:
            return {"success": False, "message": str(e)}, 400
        except Exception as e:
            return {"success": False, "message": f"删除菜单失败: {str(e)}"}, 500


class MenuTreeApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def get(self):
        """获取菜单树"""
        try:
            include_inactive = request.args.get("include_inactive", "false").lower() == "true"
            tree = MenuService.get_menu_tree(include_inactive=include_inactive)
            return {"success": True, "data": tree}
        except Exception as e:
            return {"success": False, "message": str(e)}, 400


class UserMenuApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def get(self):
        """获取当前用户菜单"""
        try:
            tenant_id = current_user.current_tenant.id
            account_id = current_user.id
            include_inactive = request.args.get("include_inactive", "false").lower() == "true"

            menus = MenuService.get_user_menus(tenant_id, account_id, include_inactive=include_inactive)
            return {"success": True, "data": menus}
        except Exception as e:
            return {"success": False, "message": str(e)}, 400


class MenuBatchApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def put(self):
        """批量更新菜单状态"""
        try:
            data = request.get_json(force=True) or {}
            menu_ids = data.get("menu_ids", [])
            is_active = data.get("is_active", True)

            if not menu_ids:
                return {"success": False, "message": "请选择要更新的菜单"}, 400

            result = MenuService.batch_update_menu_status(menu_ids, is_active)
            return {"success": True, "data": result, "message": "批量更新成功"}
        except Exception as e:
            return {"success": False, "message": str(e)}, 400



# 注册路由
api.add_resource(MenuListApi, "/workspaces/current/menus")
api.add_resource(MenuDetailApi, "/workspaces/current/menus/<uuid:menu_id>")
api.add_resource(MenuTreeApi, "/workspaces/current/menus/tree")
api.add_resource(UserMenuApi, "/workspaces/current/menus/user")
api.add_resource(MenuBatchApi, "/workspaces/current/menus/batch")
