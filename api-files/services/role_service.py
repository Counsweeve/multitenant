from __future__ import annotations

from operator import and_
from typing import Any, Optional, List

import sqlalchemy as sa
from sqlalchemy import delete, or_, distinct

from extensions.ext_database import db
from fields.role_fields import AuthorizedPersonSearchRequest, AuthorizedPersonListResponse, AuthorizedPersonEntity, \
    ResourceAuthorizationResponse, AuthorizedResourceEntity, UnauthorizedResourceEntity, ResourceAuthorizationRequest
from models import TenantAccountJoin, Provider, ProviderModel, Dataset
from models.account import AccountRole, Menu, Role, RoleMenu, Account, RoleResource
from services.menu_service import MenuService


class RoleService:
    """角色管理服务"""

    @staticmethod
    def create_role(tenant_id: str, role_data: dict[str, Any]) -> str:
        """创建角色"""
        # 验证角色名称在租户内唯一性
        existing = db.session.query(Role).filter(
            Role.tenant_id == tenant_id,
            Role.role_key == role_data['role_key']
        ).first()

        if existing:
            raise ValueError(f"角色名称 '{role_data['role_key']}' 在当前租户下已存在")

        role = Role(
            tenant_id=tenant_id,
            role_key=role_data['role_key'],
            role_name=role_data['role_name'],
            description=role_data.get('description'),
            is_active=role_data.get('is_active', True)
        )
        db.session.add(role)
        db.session.commit()
        return role.id

    @staticmethod
    def update_role(tenant_id: str, role_id: str, role_data: dict[str, Any]) -> None:
        """更新角色"""
        role = db.session.get(Role, role_id)
        if not role or role.tenant_id != tenant_id:
            raise ValueError("角色不存在或无权限")

        # 检查角色名称唯一性（如果要修改名称）
        if 'role_name' in role_data and role_data['role_name'] != role.role_name:
            existing = db.session.query(Role).filter(
                Role.tenant_id == tenant_id,
                Role.role_name == role_data['role_name'],
                Role.id != role_id
            ).first()

            if existing:
                raise ValueError(f"角色名称 '{role_data['role_name']}' 在当前租户下已存在")

        # 更新字段
        for key in ['role_name', 'description', 'is_active']:
            if key in role_data:
                setattr(role, key, role_data[key])

        db.session.commit()

    @staticmethod
    def delete_role(tenant_id: str, role_id: str, force: bool = False) -> dict[str, Any]:
        """删除角色"""
        role = db.session.get(Role, role_id)
        if not role or role.tenant_id != tenant_id:
            raise ValueError("角色不存在或无权限")

        # 检查是否有用户使用该角色
        user_count = db.session.scalar(
            sa.select(sa.func.count(AccountRole.account_id)).filter(
                AccountRole.tenant_id == tenant_id,
                AccountRole.role_id == role_id
            )
        ) or 0

        if user_count > 0 and not force:
            raise ValueError(f"角色下有 {user_count} 个用户，请先移除用户或使用强制删除")

        # 删除相关关联关系
        db.session.execute(delete(AccountRole).where(
            AccountRole.tenant_id == tenant_id,
            AccountRole.role_id == role_id
        ))
        db.session.execute(delete(RoleMenu).where(RoleMenu.role_id == role_id))


        # 删除角色
        role_name = role.role_name
        db.session.delete(role)
        db.session.commit()

        return {
            "role_name": role_name,
            "affected_users": user_count,
            "message": f"成功删除角色 '{role_name}'"
        }

    @staticmethod
    def get_role(tenant_id: str, role_id: str, include_stats: bool = False) -> Optional[dict[str, Any]]:
        """获取角色详情"""
        role = db.session.get(Role, role_id)
        if not role or role.tenant_id != tenant_id:
            return None

        role_dict = role.to_dict()

        if include_stats:
            # 获取用户数量
            user_count = db.session.scalar(
                sa.select(sa.func.count(AccountRole.account_id)).filter(
                    AccountRole.tenant_id == tenant_id,
                    AccountRole.role_id == role_id
                )
            ) or 0

            # 获取菜单数量
            menu_count = db.session.scalar(
                sa.select(sa.func.count(RoleMenu.menu_id)).filter(
                    RoleMenu.role_id == role_id
                )
            ) or 0



            role_dict.update({
                "user_count": user_count,
                "menu_count": menu_count
            })

        return role_dict

    @staticmethod
    def batch_delete_roles(tenant_id: str, role_ids: list[str], force: bool = False) -> dict[str, Any]:
        """批量删除角色"""
        if not role_ids:
            return {"deleted_count": 0, "failed_roles": [], "success_roles": []}

        # 验证角色权限
        valid_roles = db.session.query(Role).filter(
            Role.id.in_(role_ids),
            Role.tenant_id == tenant_id
        ).all()

        valid_role_ids = [role.id for role in valid_roles]
        invalid_role_ids = [rid for rid in role_ids if rid not in valid_role_ids]

        deleted_count = 0
        failed_roles = []
        success_roles = []

        # 逐个删除角色（因为需要检查用户关联）
        for role_id in valid_role_ids:
            try:
                result = RoleService.delete_role(tenant_id, role_id, force=force)
                deleted_count += 1
                success_roles.append({
                    "role_id": role_id,
                    "role_name": result.get("role_name", "未知角色")
                })
            except ValueError as e:
                failed_roles.append({
                    "role_id": role_id,
                    "error": str(e)
                })

        return {
            "deleted_count": deleted_count,
            "failed_roles": failed_roles,
            "success_roles": success_roles,
            "invalid_roles": invalid_role_ids
        }

    @staticmethod
    def list_roles(tenant_id: str, keyword: Optional[str] = None,
                  is_active: Optional[bool] = None, page: int = 1, size: int = 20) -> dict[str, Any]:
        """分页查询角色列表"""
        stmt = sa.select(Role).filter(Role.tenant_id == tenant_id)

        # 筛选条件
        if keyword:
            like_pattern = f"%{keyword}%"
            stmt = stmt.filter(
                or_(
                    Role.role_name.ilike(like_pattern),
                    Role.description.ilike(like_pattern)
                )
            )

        if is_active is not None:
            stmt = stmt.filter(Role.is_active == is_active)

        # 计算总数
        total = db.session.scalar(sa.select(sa.func.count()).select_from(stmt.subquery())) or 0

        # 分页查询
        roles = db.session.scalars(
            stmt.order_by(Role.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).all()

        # 构建角色列表，包含统计信息
        role_list = []
        for role in roles:
            role_dict = role.to_dict()

            # 获取用户数量
            user_count = db.session.scalar(
                sa.select(sa.func.count(AccountRole.account_id)).filter(
                    AccountRole.tenant_id == tenant_id,
                    AccountRole.role_id == role.id
                )
            ) or 0

            # 获取菜单数量
            menu_count = db.session.scalar(
                sa.select(sa.func.count(RoleMenu.menu_id)).filter(
                    RoleMenu.role_id == role.id
                )
            ) or 0



            role_dict.update({
                "user_count": user_count,
                "menu_count": menu_count
            })

            role_list.append(role_dict)

        return {
            "total": int(total),
            "page": page,
            "page_size": size,
            "items": role_list
        }

    @staticmethod
    def assign_menus(tenant_id: str, role_id: str, menu_ids: list[str]) -> dict[str, Any]:
        """为角色分配菜单"""
        # 验证角色权限
        role = db.session.get(Role, role_id)
        if not role or role.tenant_id != tenant_id:
            raise ValueError("角色不存在或无权限")

        # 验证菜单是否存在且有效
        valid_menus = db.session.query(Menu).filter(
            Menu.id.in_(menu_ids),
            Menu.is_active == True
        ).all()

        valid_menu_ids = [menu.id for menu in valid_menus]
        invalid_menu_ids = [mid for mid in menu_ids if mid not in valid_menu_ids]

        # 删除现有菜单关联
        db.session.execute(delete(RoleMenu).where(RoleMenu.role_id == role_id))

        # 添加新菜单关联
        success_count = 0
        for menu_id in valid_menu_ids:
            role_menu = RoleMenu(role_id=role_id, menu_id=menu_id)
            db.session.add(role_menu)
            success_count += 1

        db.session.commit()

        return {
            "role_id": str(role_id),
            "role_name": role.role_name,
            "assigned_count": success_count,
            "invalid_menus": invalid_menu_ids,
            "assigned_menus": [{"id": menu.id, "name": menu.menu_name} for menu in valid_menus]
        }

    @staticmethod
    def get_role_menus(tenant_id: str, role_id: str, include_tree: bool = False) -> dict[str, Any]:
        """获取角色菜单"""
        # 验证角色权限
        role = db.session.get(Role, role_id)
        if not role or role.tenant_id != tenant_id:
            raise ValueError("角色不存在或无权限")

        # 获取角色关联的菜单
        menus = db.session.query(Menu).join(
            RoleMenu, Menu.id == RoleMenu.menu_id
        ).filter(
            RoleMenu.role_id == role_id,
            Menu.is_active == True
        ).order_by(Menu.sort_order).all()

        menu_list = [menu.to_dict() for menu in menus]

        result = {
            "role_id": str(role_id),
            "role_name": role.role_name,
            "menu_count": len(menu_list),
            "menus": menu_list
        }

        # 如果需要树形结构
        if include_tree:
            from services.menu_service import MenuService
            result["menu_tree"] = MenuService.build_menu_tree(menu_list)

        return result





    @staticmethod
    def batch_update_role_status(tenant_id: str, role_ids: list[str], is_active: bool) -> dict[str, Any]:
        """批量更新角色状态"""
        if not role_ids:
            return {"updated_count": 0}

        # 验证角色权限
        valid_roles = db.session.query(Role).filter(
            Role.id.in_(role_ids),
            Role.tenant_id == tenant_id
        ).all()

        valid_role_ids = [role.id for role in valid_roles]
        invalid_role_ids = [rid for rid in role_ids if rid not in valid_role_ids]

        # 更新角色状态
        if valid_role_ids:
            db.session.execute(
                sa.update(Role).where(
                    Role.id.in_(valid_role_ids)
                ).values(is_active=is_active)
            )
            db.session.commit()

        return {
            "updated_count": len(valid_role_ids),
            "invalid_roles": invalid_role_ids,
            "status": "active" if is_active else "inactive"
        }

    @staticmethod
    def get_role_statistics(tenant_id: str) -> dict[str, Any]:
        """获取角色统计信息"""
        # 总角色数
        total_roles = db.session.scalar(
            sa.select(sa.func.count(Role.id)).filter(Role.tenant_id == tenant_id)
        ) or 0

        # 活跃角色数
        active_roles = db.session.scalar(
            sa.select(sa.func.count(Role.id)).filter(
                Role.tenant_id == tenant_id,
                Role.is_active == True
            )
        ) or 0

        # 有用户的角色数
        roles_with_users = db.session.scalar(
            sa.select(sa.func.count(sa.distinct(AccountRole.role_id))).filter(
                AccountRole.tenant_id == tenant_id
            )
        ) or 0

        # 无用户的角色数
        roles_without_users = total_roles - roles_with_users

        # 总用户数
        total_users = db.session.scalar(
            sa.select(sa.func.count(sa.distinct(AccountRole.account_id))).filter(
                AccountRole.tenant_id == tenant_id
            )
        ) or 0

        # 平均每个角色的用户数
        avg_users_per_role = total_users / roles_with_users if roles_with_users > 0 else 0

        return {
            "total_roles": total_roles,
            "active_roles": active_roles,
            "inactive_roles": total_roles - active_roles,
            "roles_with_users": roles_with_users,
            "roles_without_users": roles_without_users,
            "total_users": total_users,
            "avg_users_per_role": round(avg_users_per_role, 2)
        }

    @staticmethod
    def get_available_menus_for_role(tenant_id: str, role_id: str) -> list[dict[str, Any]]:
        """获取角色可分配的菜单列表"""
        # 验证角色权限
        role = db.session.get(Role, role_id)
        if not role or role.tenant_id != tenant_id:
            raise ValueError("角色不存在或无权限")

        # 获取所有活跃菜单
        all_menus = db.session.query(Menu).filter(Menu.is_active == True).all()

        # 获取角色已分配的菜单ID
        assigned_menu_ids = db.session.query(RoleMenu.menu_id).filter(
            RoleMenu.role_id == role_id
        ).all()
        assigned_menu_ids = [mid.menu_id for mid in assigned_menu_ids]

        # 构建菜单列表，标记已分配状态
        menu_list = []
        for menu in all_menus:
            menu_dict = menu.to_dict()
            menu_dict['is_assigned'] = menu.id in assigned_menu_ids
            menu_list.append(menu_dict)

        return menu_list

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
        authorized_menu_ids = RoleService.get_user_authorized_menu_ids(role_id, include_inactive)

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

    @staticmethod
    def search_authorized_person(
        tenant_id: str,
        search_request: AuthorizedPersonSearchRequest
    ) -> AuthorizedPersonListResponse:
        """
        通过 `tenant_account_joins` 确定租户成员，再通过 `user_roles` 与 `roles` 获取角色。
        支持按账号、姓名、角色名称模糊查询。
        """
        # 基础子查询
        base_query = (
            db.session.query(Account.id)
            .join(TenantAccountJoin,  TenantAccountJoin.account_id == Account.id)
            .filter(
                TenantAccountJoin.tenant_id == tenant_id
            )
        )
        # 条件：邮箱
        if search_request.email:
            base_query = base_query.filter(
                Account.email.ilike(f"%{search_request.email}%")
            )
        # 条件：姓名
        if search_request.name:
            base_query = base_query.filter(
                Account.name.ilike(f"%{search_request.name}%")
            )
        # 条件：角色
        if search_request.role:
            base_query = (
                base_query.join(AccountRole, AccountRole.account_id == Account.id)
                .join(Role, Role.id == AccountRole.role_id)
                .filter(Role.role_name.ilike(f"%{search_request.role}%"))
            )
        # 统计总数
        distinct_account_ids = base_query.distinct(Account.id).subquery()
        total = db.session.query(distinct_account_ids.c.id).count()
        # 分页后获取账号详情
        offset = (search_request.page - 1) * search_request.page_size
        page_account_ids = (
            db.session.query(distinct_account_ids.c.id)
            .offset(offset)
            .limit(search_request.page_size)
            .all()
        )

        page_account_ids = [row[0] for row in page_account_ids]

        if not page_account_ids:
            return AuthorizedPersonListResponse(
                authorized_persons=[], total=0, page=search_request.page, page_size=search_request.page_size
            )

        accounts = (
            db.session.query(Account)
            .filter(Account.id.in_(page_account_ids))
            .all()
        )

        # 批量查询
        role_rows = (
            db.session.query(Account.id, Role.role_name)
            .join(AccountRole, AccountRole.account_id == Account.id)
            .join(Role, Role.id == AccountRole.role_id)
            .filter(Account.id.in_(page_account_ids))
            .all()
        )
        account_id_to_roles: dict[str, list[str]] = {}
        for account_id, role_name in role_rows:
            account_id_to_roles.setdefault(account_id, []).append(role_name)

        # 构建响应
        authorized_persons: list[AuthorizedPersonEntity] = []
        for account in accounts:
            role_names = account_id_to_roles.get(account.id, [])
            authorized_persons.append(
                AuthorizedPersonEntity(
                    id=account.id,
                    account=account.email,
                    role=",".join(sorted(role_names)),
                    name=account.name or "",
                    tenant_id=tenant_id,
                )
            )

        return AuthorizedPersonListResponse(
            authorized_persons=authorized_persons,
            total=total,
            page=search_request.page,
            page_size=search_request.page_size,
        )

    @staticmethod
    def get_resource_authorization(
        tenant_id: str,
        resource_type: str,
        role_id: str,
    ) -> ResourceAuthorizationResponse:
        """获取角色的资源授权情况"""
        # 获取已经授权的资源
        authorized_resources = RoleService.get_authorized_resources(tenant_id, role_id, resource_type)
        # 获取未授权的资源
        unauthorized_resources = RoleService.get_unauthorized_resources(tenant_id, role_id, resource_type, authorized_resources)

        return ResourceAuthorizationResponse(
            authorized_resources=authorized_resources,
            unauthorized_resources=unauthorized_resources,
            resource_type=resource_type,
        )

    @staticmethod
    def get_authorized_resources(
        tenant_id: str,
        role_id: str,
        resource_type: str,
    ) -> list[AuthorizedResourceEntity]:
        """获取已授权的资源"""
        # 获取角色关联的资源ID集合
        stmt = sa.select(RoleResource.resource_id).filter(
            RoleResource.tenant_id == tenant_id,
            RoleResource.role_id == role_id,
            RoleResource.resource_type == resource_type,
            RoleResource.is_active == True

        )
        resource_ids = db.session.scalars(stmt).all()

        if not resource_ids:
            return []

        if resource_type == "model":
            resources = db.session.query(ProviderModel).filter(
                ProviderModel.id.in_(resource_ids),
                ProviderModel.tenant_id == tenant_id
            ).all()

            return [
                AuthorizedResourceEntity(
                    id=resource.id,
                    name=resource.model_name,
                    type=resource_type,
                    description=f"模型类型: {resource.model_type}"
                )
                for resource in resources
            ]
        elif resource_type == "dataset":
            resources = db.session.query(Dataset).filter(
                Dataset.id.in_(resource_ids),
                Dataset.tenant_id == tenant_id
            ).all()

            return [
                AuthorizedResourceEntity(
                    id=resource.id,
                    name=resource.name,
                    type=resource_type,
                    description=f"知识库类型: {resource.type}"
                )
                for resource in resources
            ]

        return []

    @staticmethod
    def get_unauthorized_resources(
        tenant_id: str,
        role_id: str,
        resource_type: str,
        authorized_resources: list[AuthorizedResourceEntity],
    ) -> list[UnauthorizedResourceEntity]:
        """获取未授权的资源"""
        authorized_resource_ids = [resource.id for resource in authorized_resources]

        if resource_type == "model":
            stmt = sa.select(ProviderModel.id).filter(
                ProviderModel.tenant_id == tenant_id,
                ProviderModel.id.notin_(authorized_resource_ids)
            )
            resources = db.session.scalars(stmt).all()

            if resources:
                resource_objects = db.session.query(ProviderModel).filter(
                    ProviderModel.id.in_(resources)
                ).all()
                return [
                    UnauthorizedResourceEntity(
                        id=resource.id,
                        name=resource.model_name,
                        type=resource_type,
                        description=f"模型类型: {resource.model_type}"
                    )
                    for resource in resource_objects
                ]
            else:
                return []
        elif resource_type == "dataset":
            stmt = sa.select(Dataset.id).filter(
                Dataset.tenant_id == tenant_id,
                Dataset.id.notin_(authorized_resource_ids)
            )
            resources = db.session.scalars(stmt).all()
            if resources:
                resource_objects = db.session.query(Dataset).filter(
                    Dataset.id.in_(resources)
                ).all()
                return [
                    UnauthorizedResourceEntity(
                        id=resource.id,
                        name=resource.name,
                        type=resource_type,
                        description=f"知识库类型: {resource.type}"
                    )
                    for resource in resource_objects
                ]
            else:
                return []

        return []

    @staticmethod
    def update_resource_authorization(
        tenant_id: str,
        request: ResourceAuthorizationRequest,
    ) -> bool:
        """更新资源授权"""
        try:
            # 删除现有的授权关系
            db.session.query(RoleResource).filter(
                RoleResource.tenant_id == tenant_id,
                RoleResource.role_id == request.role_id,
                RoleResource.resource_type == request.resource_type
            ).delete()

            # 新添加授权关系
            for resource_id in request.authorized_resource_ids:
                role_resource = RoleResource(
                    tenant_id=tenant_id,
                    role_id=request.role_id,
                    resource_id=resource_id,
                    resource_type=request.resource_type,
                    is_active=True,
                )
                db.session.add(role_resource)

            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            raise e

    @staticmethod
    def get_resource_list(
        tenant_id: str,
        role_id: str,
        resource_type: str,
        authorized_resources: List[AuthorizedResourceEntity]
    ) -> List[UnauthorizedResourceEntity]:
        """获取未授权的资源"""
        authorized_resource_ids = [resource.id for resource in authorized_resources]

        if resource_type == "model":
            query = db.session.query(ProviderModel).filter(
                ProviderModel.tenant_id == tenant_id
            )
            if authorized_resource_ids:
                query.filter(
                    ProviderModel.id.notin_(authorized_resource_ids)
                )
            resource = query.all()
            return [
                UnauthorizedResourceEntity(
                    id=resource.id,
                    name=resource.model_name,
                    type=resource_type,
                    description=f"模型类型: {resource.model_type}"
                )
                for resource in resource
            ]
        elif resource_type == "dataset":
            query = db.session.query(Dataset).filter(
                Dataset.tenant_id == tenant_id
            )
            if authorized_resource_ids:
                query.filter(
                    Dataset.id.notin_(authorized_resource_ids)
                )
            resource = query.all()
            return [
                UnauthorizedResourceEntity(
                    id=resource.id,
                    name=resource.name,
                    type=resource_type,
                    description=f"知识库类型: {resource.type}"
                )
                for resource in resource
            ]
        return  []

    @staticmethod
    def list_all_roles(tenant_id):
        """
        获取所有角色（无分页）

        Args:
            tenant_id: 租户ID
            keyword: 关键词搜索
            is_active: 是否激活状态

        Returns:
            list: 角色列表
        """
        # 实现获取所有角色的逻辑，不进行分页处理
        stmt = sa.select(Role).filter(
            Role.tenant_id == tenant_id,
            Role.is_active == True
        )
        roles = db.session.scalars(stmt.order_by(Role.created_at.desc())).all()
        # 返回完整的角色数据列表
        role_list = []
        for role in roles:
            role_dict = role.to_dict()
            role_list.append(role_dict)
        return role_list
