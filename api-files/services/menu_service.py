from __future__ import annotations

from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy import delete, or_

from extensions.ext_database import db
from models.account import AccountRole, Menu, Role, RoleMenu


class MenuService:

    @staticmethod
    def create_menu(menu_data:  dict[str, Any]) -> str:
        # 检查菜单key是否存在
        existing = db.session.query(Menu).filter(Menu.menu_key == menu_data['menu_key']).first()
        if existing:
            raise Exception(f"Menu key '{menu_data['menu_key']}' 已存在.")

        if menu_data.get('parent_id'):
            parent = db.session.get(Menu, menu_data['parent_id'])
            if not parent:
                raise ValueError("父菜单不存在")

        menu = Menu(
            menu_key=menu_data['menu_key'],
            menu_name=menu_data['menu_name'],
            parent_id=menu_data.get('parent_id'),
            menu_type=menu_data.get('menu_type', 'menu'),
            description=menu_data.get('description'),
            icon=menu_data.get('icon'),
            path=menu_data.get('path'),
            sort_order=menu_data.get('sort_order', 0),
            is_active=menu_data.get('is_active', True)
        )
        db.session.add(menu)
        db.session.commit()
        return menu.id

    @staticmethod
    def update_menu(menu_id: str, menu_data: dict[str, Any]) -> None:
        menu = db.session.get(Menu, menu_id)
        if not menu:
            raise ValueError("菜单不存在")

        # 检查菜单key是否与其他菜单冲突
        if 'menu_key' in menu_data and menu_data['menu_key'] != menu.menu_key:
            existing = db.session.query(Menu).filter(
                Menu.menu_key == menu_data['menu_key'],
                Menu.id != menu_id
            ).first()
            if existing:
                raise ValueError(f"菜单key '{menu_data['menu_key']}' 已存在")

        # 验证父菜单
        if menu_data.get('parent_id'):
            if menu_data['parent_id'] == menu_id:
                raise ValueError("菜单不能设置自己为父菜单")

            parent = db.session.get(Menu, menu_data['parent_id'])
            if not parent:
                raise ValueError("父菜单不存在")

            # 检查是否会形成循环引用
            if MenuService._would_create_cycle(menu_id, menu_data['parent_id']):
                raise ValueError("设置父菜单会形成循环引用")

        # 更新字段
        for key in ['menu_key', 'menu_name', 'menu_type', 'parent_id', 'icon', 'path', 'sort_order',
                    'is_active', 'description']:
            if key in menu_data:
                setattr(menu, key, menu_data[key])

        db.session.commit()

    @staticmethod
    def _would_create_cycle(menu_id: str, parent_id: str) -> bool:
        current_id = parent_id
        visited = set()
        while current_id and current_id not in visited:
            if current_id == menu_id:
                return True
            visited.add(current_id)
            parent_menu = db.session.get(Menu, current_id)
            current_id = parent_menu.parent_id if parent_menu else None
        return False

    @staticmethod
    def delete_menu(menu_id: str, cascade: bool = False) -> dict[str, Any]:
        """删除菜单"""
        menu = db.session.get(Menu, menu_id)
        if not menu:
            raise ValueError("菜单不存在")

        # 检查是否有子菜单
        children = db.session.query(Menu).filter(Menu.parent_id == menu_id).all()
        if children and not cascade:
            raise ValueError(f"菜单下有 {len(children)} 个子菜单，请先删除子菜单或使用级联删除")

        deleted_count = 0

        if cascade and children:
            # 递归删除子菜单
            for child in children:
                result = MenuService.delete_menu(child.id, cascade=True)
                deleted_count += result['deleted_count']

        # 删除菜单角色关联
        db.session.execute(delete(RoleMenu).where(RoleMenu.menu_id == menu_id))

        # 删除菜单
        db.session.delete(menu)
        deleted_count += 1

        db.session.commit()

        return {
            "deleted_count": deleted_count,
            "menu_name": menu.menu_name
        }

    @staticmethod
    def get_menu(menu_id: str) -> Optional[dict[str, Any]]:
        """获取菜单详情"""
        menu = db.session.get(Menu, menu_id)
        if not menu:
            return None

        menu_dict = menu.to_dict()

        # 获取父菜单信息
        if menu.parent_id:
            parent = db.session.get(Menu, menu.parent_id)
            menu_dict['parent_name'] = parent.menu_name if parent else None

        # 获取子菜单数量
        children_count = db.session.scalar(
            sa.select(sa.func.count(Menu.id)).filter(Menu.parent_id == menu_id)
        ) or 0
        menu_dict['children_count'] = children_count

        # 获取关联的角色数量
        role_count = db.session.scalar(
            sa.select(sa.func.count(RoleMenu.role_id)).filter(RoleMenu.menu_id == menu_id)
        ) or 0
        menu_dict['role_count'] = role_count

        return menu_dict

    @staticmethod
    def list_menus(keyword: Optional[str] = None, parent_id: Optional[str] = None,
                   is_active: Optional[bool] = None, page: int = 1, size: int = 50) -> dict[str, Any]:
        """获取菜单列表（分页）"""
        stmt = sa.select(Menu)

        # 筛选条件
        if keyword:
            like_pattern = f"%{keyword}%"
            stmt = stmt.filter(
                or_(
                    Menu.menu_name.ilike(like_pattern),
                    Menu.menu_key.ilike(like_pattern),
                    Menu.path.ilike(like_pattern)
                )
            )

        if parent_id is not None:
            if parent_id == "":  # 空字符串表示查询根菜单
                stmt = stmt.filter(Menu.parent_id.is_(None))
            else:
                stmt = stmt.filter(Menu.parent_id == parent_id)

        if is_active is not None:
            stmt = stmt.filter(Menu.is_active == is_active)

        # 计算总数
        total = db.session.scalar(sa.select(sa.func.count()).select_from(stmt.subquery())) or 0

        # 分页查询
        menus = db.session.scalars(
            stmt.order_by(Menu.sort_order.asc(), Menu.menu_name.asc())
            .offset((page - 1) * size)
            .limit(size)
        ).all()

        # 构建菜单列表，包含额外信息
        menu_list = []
        for menu in menus:
            menu_dict = menu.to_dict()

            # 获取子菜单数量
            children_count = db.session.scalar(
                sa.select(sa.func.count(Menu.id)).filter(Menu.parent_id == menu.id)
            ) or 0
            menu_dict['children_count'] = children_count

            # 获取关联的角色数量
            role_count = db.session.scalar(
                sa.select(sa.func.count(RoleMenu.role_id)).filter(RoleMenu.menu_id == menu.id)
            ) or 0
            menu_dict['role_count'] = role_count

            # 获取父菜单名称
            if menu.parent_id:
                parent = db.session.get(Menu, menu.parent_id)
                menu_dict['parent_name'] = parent.menu_name if parent else None

            menu_list.append(menu_dict)

        return {
            "total": int(total),
            "page": page,
            "page_size": size,
            "items": menu_list
        }

    @staticmethod
    def get_menu_tree(include_inactive: bool = False) -> list[dict[str, Any]]:
        """获取完整菜单树"""
        # 获取所有菜单
        stmt = sa.select(Menu)
        if not include_inactive:
            stmt = stmt.filter(Menu.is_active == True)

        menus = db.session.scalars(stmt.order_by(Menu.sort_order.asc())).all()
        menu_list = [menu.to_dict() for menu in menus]

        return MenuService.build_menu_tree(menu_list)

    @staticmethod
    def build_menu_tree(menus: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """构建菜单树"""
        menu_dict = {menu['id']: menu for menu in menus}
        tree = []

        # 为每个菜单添加children字段
        for menu in menus:
            menu['children'] = []

        # 构建树形结构
        for menu in menus:
            if menu['parent_id'] and menu['parent_id'] in menu_dict:
                parent = menu_dict[menu['parent_id']]
                parent['children'].append(menu)
            else:
                tree.append(menu)

        # 递归排序
        def sort_tree(nodes):
            nodes.sort(key=lambda x: (x['sort_order'], x['menu_name']))
            for node in nodes:
                if node['children']:
                    sort_tree(node['children'])

        sort_tree(tree)
        return tree

    @staticmethod
    def get_user_menus(tenant_id: str, account_id: str, include_inactive: bool = False) -> list[dict[str, Any]]:
        """获取用户可访问的菜单"""
        # 获取用户所有角色
        user_roles = db.session.query(AccountRole).filter(
            AccountRole.tenant_id == tenant_id,
            AccountRole.account_id == account_id
        ).all()

        if not user_roles:
            return []

        role_ids = [ur.role_id for ur in user_roles]

        # 获取角色关联的所有菜单（去重）
        stmt = sa.select(Menu).join(
            RoleMenu, Menu.id == RoleMenu.menu_id
        ).filter(
            RoleMenu.role_id.in_(role_ids)
        ).distinct()

        if not include_inactive:
            stmt = stmt.filter(Menu.is_active == True)

        menus = db.session.scalars(stmt.order_by(Menu.sort_order)).all()
        menu_list = [menu.to_dict() for menu in menus]

        return MenuService.build_menu_tree(menu_list)

    @staticmethod
    def check_menu_access(tenant_id: str, account_id: str, menu_key: str) -> bool:
        """检查菜单访问权限"""
        # 获取用户所有角色
        user_roles = db.session.query(AccountRole).filter(
            AccountRole.tenant_id == tenant_id,
            AccountRole.account_id == account_id
        ).all()

        if not user_roles:
            return False

        role_ids = [ur.role_id for ur in user_roles]

        # 检查是否有角色关联了该菜单
        role_menu = db.session.query(RoleMenu).join(
            Menu, RoleMenu.menu_id == Menu.id
        ).filter(
            RoleMenu.role_id.in_(role_ids),
            Menu.menu_key == menu_key,
            Menu.is_active == True
        ).first()

        return role_menu is not None

    @staticmethod
    def get_menu_roles(menu_id: str, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        """获取菜单关联的角色"""
        stmt = sa.select(Role).join(
            RoleMenu, Role.id == RoleMenu.role_id
        ).filter(
            RoleMenu.menu_id == menu_id,
            Role.is_active == True
        )

        if tenant_id:
            stmt = stmt.filter(Role.tenant_id == tenant_id)

        roles = db.session.scalars(stmt.order_by(Role.role_name)).all()
        return [role.to_dict() for role in roles]

    @staticmethod
    def batch_update_menu_status(menu_ids: list[str], is_active: bool) -> dict[str, Any]:
        """批量更新菜单状态"""
        if not menu_ids:
            return {"updated_count": 0}

        # 更新菜单状态
        result = db.session.execute(
            sa.update(Menu).where(
                Menu.id.in_(menu_ids)
            ).values(is_active=is_active)
        )

        db.session.commit()

        return {
            "updated_count": result.rowcount,
            "status": "active" if is_active else "inactive"
        }

    @staticmethod
    def search_menus_by_path(path_pattern: str) -> list[dict[str, Any]]:
        """根据路径模式搜索菜单"""
        like_pattern = f"%{path_pattern}%"
        menus = db.session.query(Menu).filter(
            Menu.path.ilike(like_pattern),
            Menu.is_active == True
        ).order_by(Menu.path).all()

        return [menu.to_dict() for menu in menus]

    @staticmethod
    def get_menu_tree_with_authorization(role_id: str, include_inactive: bool = False) -> list[dict[str, Any]]:
        """获取菜单树，并标识已授权的菜单"""
        # 获取所有菜单
        stmt = sa.select(Menu)
        if not include_inactive:
            stmt = stmt.filter(Menu.is_active == True)

        menus = db.session.scalars(stmt.order_by(Menu.sort_order.asc())).all()
        menu_list = [menu.to_dict() for menu in menus]

        # 获取用户已授权的菜单ID集合
        authorized_menu_ids = MenuService.get_user_authorized_menu_ids(role_id, include_inactive)

        # 为每个菜单添加授权状态
        for menu in menu_list:
            menu['is_authorized'] = menu['id'] in authorized_menu_ids

        return MenuService.build_menu_tree(menu_list)

    @staticmethod
    def get_user_authorized_menu_ids(role_id: str, include_inactive: bool = False) -> set[str]:
        """获取用户已授权的菜单ID集合"""


        # 获取角色关联的所有菜单ID（去重）
        stmt = sa.select(RoleMenu.menu_id).filter(
            RoleMenu.role_id == role_id
        ).distinct()

        if not include_inactive:
            # 只获取活跃菜单的授权
            stmt = stmt.join(Menu, RoleMenu.menu_id == Menu.id).filter(
                Menu.is_active == True
            )

        menu_ids = db.session.scalars(stmt).all()
        return set(menu_ids)


