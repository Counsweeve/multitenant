from __future__ import annotations

from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy import delete, or_

from extensions.ext_database import db
from models.account import Account, AccountRole, Role, TenantAccountJoin


class RoleAccountService:

    """
    角色用户关联服务
    """

    @staticmethod
    def get_tenant_accounts(tenant_id: str, keyword: Optional[str] = None,
                            page: int = 1, page_size: int = 10) -> dict[str, Any]:
        stmt = sa.select(Account).join(
            TenantAccountJoin, Account.id == TenantAccountJoin.account_id
        ).filter(TenantAccountJoin.tenant_id == tenant_id)

        if keyword:
            stmt = stmt.where(
                or_(
                    Account.name.like(f"%{keyword}%"),
                    Account.email.like(f"%{keyword}%"),
                )
            )

        total = db.session.scalar(sa.select(sa.func.count()).select_from(stmt.subquery())) or 0

        accounts = db.session.scalar(
            stmt.order_by(Account.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars().all()

        account_list = []
        for account in accounts:
            user_roles = RoleAccountService.get_account_roles(tenant_id, account.id)
            account_list.append({
                "id": account.id,
                "name": account.name,
                "email": account.email,
                "avatar": account.avatar,
                "roles": user_roles,
                "role_count": len(user_roles)
            })

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "data": account_list
        }

    @staticmethod
    def get_account_roles(tenant_id: str, account_id: str) -> list[dict[str, Any]]:

       tenant_join = db.session.query(TenantAccountJoin).filter(
           TenantAccountJoin.tenant_id == tenant_id,
           TenantAccountJoin.account_id == account_id
        ).first()

       if not tenant_join:
           return []

       roles = db.session.query(Role).join(
           AccountRole, Role.id == AccountRole.role_id
        ).filter(
           AccountRole.tenant_id == tenant_id,
           AccountRole.account_id == account_id,
           Role.is_active == True
        ).order_by(Role.role_name.asc()).all()

       return [
           role.to_dict() for role in roles
       ]

    @staticmethod
    def get_role_accounts(tenant_id: str, role_id: str, keyword: Optional[str] = None,
                          page: int = 1, page_size: int = 10) -> dict[str, Any]:
        role = db.session.get(Role, role_id)
        if not role or role.tenant_id != tenant_id:
            raise ValueError("角色不存在或无权限")

        stmt = sa.select(Account).join(
            AccountRole, Account.id == AccountRole.account_id
        ).filter(
            AccountRole.tenant_id == tenant_id,
            AccountRole.role_id == role_id
        )

        if keyword:
            like_pattern = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    Account.name.ilike(like_pattern),
                    Account.email.ilike(like_pattern),
                )
            )

        total = db.session.scalar(sa.select(sa.func.count()).select_from(stmt.subquery())) or 0

        print("total:", total)

        scalars_result = db.session.scalars(
            stmt.order_by(Account.created_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        if scalars_result is None:
            accounts = []
        else:
            accounts = scalars_result.all()

        account_list = []
        for account in accounts:
            join_info = db.session.query(AccountRole).filter(
                AccountRole.tenant_id == tenant_id,
                AccountRole.account_id == account.id,
                AccountRole.role_id == role_id
            ).first()

            account_list.append({
                "id": account.id,
                "name": account.name,
                "email": account.email,
                "avatar": account.avatar,
                "assigned_at": join_info.created_at.isoformat() if join_info else None
            })

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "data": account_list
        }

    @staticmethod
    def assign_accounts_to_role(tenant_id: str, role_id: str, account_ids: list[str]) -> dict[str, Any]:
        """为角色分配用户批量"""
        role = db.session.get(Role, role_id)
        if not role or role.tenant_id != tenant_id:
            raise ValueError("角色不存在或无权限")

        valid_accounts = db.session.query(Account.id).join(
            TenantAccountJoin, Account.id == TenantAccountJoin.account_id
        ).filter(
            TenantAccountJoin.tenant_id == tenant_id,
            Account.id.in_(account_ids)
        ).all()

        valid_account_ids = [acc.id for acc in valid_accounts]

        invalid_count_ids = [aid for aid in account_ids if aid not in valid_account_ids]

        if invalid_count_ids:
            raise ValueError(f"以下用户不存在或不属于当前租户：{','.join(invalid_count_ids)}")

        # 删除角色现有的用户关系
        db.session.execute(delete(AccountRole).where(
            AccountRole.tenant_id == tenant_id,
            AccountRole.role_id == role_id
        ))

        success_count = 0
        for account_id in valid_account_ids:
            db.session.add(AccountRole(
                tenant_id=tenant_id,
                role_id=role_id,
                account_id=account_id
            ))
            success_count += 1
        db.session.commit()

        return {
            "role_id": str(role_id),
            "role_name": role.role_name,
            "assigned_count": success_count,
            "invalid_users": invalid_count_ids
        }


    @staticmethod
    def assign_roles_to_user(tenant_id: str, account_id: str, role_ids: list[str]) -> dict[str, Any]:
        """ 为用户分配角色 """
        # 验证用户师傅属于该租户
        tenant_join = db.session.query(TenantAccountJoin).filter(
            TenantAccountJoin.tenant_id == tenant_id,
            TenantAccountJoin.account_id == account_id
        ).first()
        if not tenant_join:
            raise ValueError("用户不存在当前租户")

        valid_roles = db.session.query(Role).filter(
            Role.id.in_(role_ids),
            Role.tenant_id == tenant_id,
            Role.is_active == True
        ).all()

        valid_role_ids = [role.id for role in valid_roles]
        invalid_role_ids = [rid for rid in role_ids if rid not in valid_role_ids]

        if invalid_role_ids:
            raise ValueError(f"以下角色不存在或不属于当前租户：{','.join(invalid_role_ids)}")

        # 删除洪湖现有的角色关联
        db.session.execute(delete(AccountRole).where(
            AccountRole.tenant_id == tenant_id,
            AccountRole.account_id == account_id
        ))
        # 添加新的角色关联
        success_count = 0
        for role_id in valid_role_ids:
            user_role = AccountRole(
                tenant_id=tenant_id,
                account_id=account_id,
                role_id=role_id
            )
            db.session.add(user_role)
            success_count += 1

        db.session.commit()

        # 获取用户信息
        account = db.session.get(Account, account_id)

        return {
            "account_id": account_id,
            "account_name": account.name if account else "未知用户",
            "assigned_count": success_count,
            "invalid_roles": invalid_role_ids,
            "assigned_roles": [{"id": role.id, "name": role.role_name} for role in valid_roles]
        }

    @staticmethod
    def add_account_to_role(tenant_id: str, role_id: str, account_id: str) -> dict[str, Any]:
        """添加单个用户到角色"""
        # 验证角色是否属于该租户
        role = db.session.get(Role, role_id)
        if not role or role.tenant_id != tenant_id:
            raise ValueError("角色不存在或无权限")

        # 验证用户是否属于该租户
        tenant_join = db.session.query(TenantAccountJoin).filter(
            TenantAccountJoin.tenant_id == tenant_id,
            TenantAccountJoin.account_id == account_id
        ).first()

        if not tenant_join:
            raise ValueError("用户不属于当前租户")

        # 检查是否已存在关联
        existing = db.session.query(AccountRole).filter(
            AccountRole.tenant_id == tenant_id,
            AccountRole.account_id == account_id,
            AccountRole.role_id == role_id
        ).first()

        if existing:
            return {
                "success": False,
                "message": "用户已拥有该角色",
                "role_name": role.role_name
            }

            # 删除account_id和tenant_id AccountRole表数据
        db.session.execute(delete(AccountRole).where(
            AccountRole.tenant_id == tenant_id,
            AccountRole.account_id == account_id
        ))
        db.session.commit()

        # 添加用户角色关联
        user_role = AccountRole(
            tenant_id=tenant_id,
            account_id=account_id,
            role_id=role_id
        )


        db.session.add(user_role)
        db.session.commit()




        # 获取用户信息
        account = db.session.get(Account, account_id)

        return {
            "success": True,
            "message": "用户角色分配成功",
            "role_name": role.role_name,
            "account_name": account.name if account else "未知用户"
        }

    @staticmethod
    def remove_user_from_role(tenant_id: str, role_id: str, account_id: str) -> dict[str, Any]:
        """从角色中移除单个用户"""
        # 验证角色是否属于该租户
        role = db.session.get(Role, role_id)
        if not role or role.tenant_id != tenant_id:
            raise ValueError("角色不存在或无权限")

        # 删除用户角色关联
        result = db.session.execute(
            delete(AccountRole).where(
                AccountRole.tenant_id == tenant_id,
                AccountRole.account_id == account_id,
                AccountRole.role_id == role_id
            )
        )

        db.session.commit()

        # 获取用户信息
        account = db.session.get(Account, account_id)

        if result.rowcount > 0:
            return {
                "success": True,
                "message": "用户角色移除成功",
                "role_name": role.role_name,
                "account_name": account.name if account else "未知用户"
            }
        else:
            return {
                "success": False,
                "message": "用户未拥有该角色",
                "role_name": role.role_name,
                "account_name": account.name if account else "未知用户"
            }

    @staticmethod
    def batch_assign_role_to_users(tenant_id: str, role_id: str, account_ids: list[str]) -> dict[str, Any]:
        """批量为用户分配角色（增量添加，不删除现有关联）"""
        # 验证角色是否属于该租户
        role = db.session.get(Role, role_id)
        if not role or role.tenant_id != tenant_id:
            raise ValueError("角色不存在或无权限")

        # 验证所有用户都属于该租户
        valid_accounts = db.session.query(Account.id, Account.name).join(
            TenantAccountJoin, Account.id == TenantAccountJoin.account_id
        ).filter(
            TenantAccountJoin.tenant_id == tenant_id,
            Account.id.in_(account_ids)
        ).all()

        valid_account_ids = [acc.id for acc in valid_accounts]
        invalid_account_ids = [aid for aid in account_ids if aid not in valid_account_ids]

        # 获取已存在的关联
        existing_relations = db.session.query(AccountRole.account_id).filter(
            AccountRole.tenant_id == tenant_id,
            AccountRole.role_id == role_id,
            AccountRole.account_id.in_(valid_account_ids)
        ).all()

        existing_account_ids = [rel.account_id for rel in existing_relations]

        # 需要新增的用户
        new_account_ids = [aid for aid in valid_account_ids if aid not in existing_account_ids]

        # 添加新的用户角色关联
        success_count = 0
        for account_id in new_account_ids:
            user_role = AccountRole(
                tenant_id=tenant_id,
                account_id=account_id,
                role_id=role_id
            )
            db.session.add(user_role)
            success_count += 1

        db.session.commit()

        return {
            "role_id": role_id,
            "role_name": role.role_name,
            "total_requested": len(account_ids),
            "newly_assigned": success_count,
            "already_assigned": len(existing_account_ids),
            "invalid_users": invalid_account_ids,
            "valid_users": len(valid_account_ids)
        }

    @staticmethod
    def get_accounts_without_role(tenant_id: str, role_id: str, keyword: Optional[str] = None,
                               page: int = 1, size: int = 20) -> dict[str, Any]:
        """获取未拥有指定角色的租户用户"""
        # 验证角色是否属于该租户
        role = db.session.get(Role, role_id)
        if not role or role.tenant_id != tenant_id:
            raise ValueError("角色不存在或无权限")

        # 获取已拥有该角色的用户ID
        existing_user_ids = db.session.query(AccountRole.account_id).filter(
            AccountRole.tenant_id == tenant_id,
            AccountRole.role_id == role_id
        ).subquery()

        # 构建查询：获取租户下未拥有该角色的用户
        stmt = sa.select(Account).join(
            TenantAccountJoin, Account.id == TenantAccountJoin.account_id
        ).filter(
            TenantAccountJoin.tenant_id == tenant_id,
            ~Account.id.in_(sa.select(existing_user_ids.c.account_id))
        )

        # 关键词搜索
        if keyword:
            like_pattern = f"%{keyword}%"
            stmt = stmt.filter(
                or_(
                    Account.name.ilike(like_pattern),
                    Account.email.ilike(like_pattern)
                )
            )

        # 计算总数
        total = db.session.scalar(sa.select(sa.func.count()).select_from(stmt.subquery())) or 0

        # 分页查询
        accounts = db.session.scalars(
            stmt.order_by(Account.name.asc())
            .offset((page - 1) * size)
            .limit(size)
        ).all()

        # 构建用户列表
        user_list = []
        for account in accounts:
            user_list.append({
                "id": account.id,
                "name": account.name,
                "email": account.email,
                "avatar": account.avatar
            })

        return {
            "role_id": role_id,
            "role_name": role.role_name,
            "total": int(total),
            "page": page,
            "page_size": size,
            "items": user_list
        }

