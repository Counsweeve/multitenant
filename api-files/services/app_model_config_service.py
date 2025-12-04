from core.app.apps.agent_chat.app_config_manager import AgentChatAppConfigManager
from core.app.apps.chat.app_config_manager import ChatAppConfigManager
from core.app.apps.completion.app_config_manager import CompletionAppConfigManager
from extensions.ext_database import db
from models.model import AppMode, App, AppModelConfig, Account

from collections.abc import Sequence
from sqlalchemy import select, func
from sqlalchemy.orm import Session
import datetime

from typing import Optional, List, Dict, Any


class AppModelConfigService:
    @classmethod
    def validate_configuration(cls, tenant_id: str, config: dict, app_mode: AppMode) -> dict:
        if app_mode == AppMode.CHAT:
            return ChatAppConfigManager.config_validate(tenant_id, config)
        elif app_mode == AppMode.AGENT_CHAT:
            return AgentChatAppConfigManager.config_validate(tenant_id, config)
        elif app_mode == AppMode.COMPLETION:
            return CompletionAppConfigManager.config_validate(tenant_id, config)
        else:
            raise ValueError(f"Invalid app mode: {app_mode}")

    @classmethod
    def get_published_agent_by_id(cls, app_model: App, agent_id: str) -> Optional[AppModelConfig]:
        app_model_config = (
            db.session.query(AppModelConfig)
            .where(
                AppModelConfig.app_id == app_model.id,
                AppModelConfig.id == agent_id,
            )
            .first()
        )
        if not app_model_config:
            return None
        return app_model_config

    @classmethod
    def get_all_published_agent(
        cls,
        *,
        session: Session,
        app_model: App,
        page: int,
        limit: int,
        user_id: str | None,
        named_only: bool = False,
    ) -> tuple[List[Dict[str, Any]], bool, int]:
        """
        Get published app_model_config with pagination
        """
        if not app_model.app_model_config_id:
            return [], False, 0

        # 为join创建别名
        from sqlalchemy.orm import aliased
        Account2 = aliased(Account)

        # 构建查询条件，关联Account表获取创建者和更新者信息
        base_stmt = select(
            AppModelConfig,
            Account.name.label('created_by_name'),
            Account2.name.label('updated_by_name')
        ).join(
            Account, Account.id == AppModelConfig.created_by, isouter=True
        ).join(
            Account2, Account2.id == AppModelConfig.updated_by, isouter=True
        ).where(AppModelConfig.app_id == app_model.id)

        if user_id:
            base_stmt = base_stmt.where(AppModelConfig.created_by == user_id)

        if named_only:
            base_stmt = base_stmt.where(AppModelConfig.marked_name != "")

        # 计算总记录数 - 只选择AppModelConfig的id来计算
        total_stmt = select(func.count(AppModelConfig.id)).select_from(
            select(AppModelConfig).where(AppModelConfig.app_id == app_model.id)
            .subquery()
        )
        if user_id:
            total_stmt = total_stmt.where(AppModelConfig.created_by == user_id)
        if named_only:
            total_stmt = total_stmt.where(AppModelConfig.marked_name != "")

        total = session.scalar(total_stmt)

        # 获取分页数据
        stmt = base_stmt.order_by(AppModelConfig.created_at.desc()).limit(limit + 1).offset((page - 1) * limit)

        results = session.execute(stmt).all()

        # 处理结果，转换为包含所需信息的字典列表
        app_model_config_list = []
        for result in results:
            app_model_config = result[0]  # AppModelConfig对象
            created_by_name = result[1]  # 创建者名称
            updated_by_name = result[2]  # 更新者名称

            # 构建返回字典
            config_dict = {
                'id': app_model_config.id,
                'app_id': app_model_config.app_id,
                'configs': app_model_config.configs,
                'model': app_model_config.model,
                'provider': app_model_config.provider,
                'model_id': app_model_config.model_id,
                'agent_mode': app_model_config.agent_mode,
                'opening_statement': app_model_config.opening_statement,
                'suggested_questions': app_model_config.suggested_questions,
                'suggested_questions_after_answer': app_model_config.suggested_questions_after_answer,
                'pre_prompt': app_model_config.pre_prompt,
                'prompt_type': app_model_config.prompt_type,
                'chat_prompt_config': app_model_config.chat_prompt_config,
                'completion_prompt_config': app_model_config.completion_prompt_config,
                'retriever_resource': app_model_config.retriever_resource,
                'sensitive_word_avoidance': app_model_config.sensitive_word_avoidance,
                'marked_name': app_model_config.marked_name,
                'marked_comment': app_model_config.marked_comment,
                'created_by': app_model_config.created_by,
                'updated_by': app_model_config.updated_by,
                'created_by_name': created_by_name,
                'updated_by_name': updated_by_name,
                'created_at': app_model_config.created_at.strftime(
                    '%Y-%m-%d %H:%M:%S') if app_model_config.created_at else None,
                'updated_at': app_model_config.updated_at.strftime(
                    '%Y-%m-%d %H:%M:%S') if app_model_config.updated_at else None,
                'publish_square': app_model_config.publish_square,
            }

            # 添加其他可能存在的字段
            if hasattr(app_model_config, 'dataset_configs'):
                config_dict['dataset_configs'] = app_model_config.dataset_configs
            if hasattr(app_model_config, 'external_data_tools'):
                config_dict['external_data_tools'] = app_model_config.external_data_tools
            if hasattr(app_model_config, 'user_input_form'):
                config_dict['user_input_form'] = app_model_config.user_input_form
            if hasattr(app_model_config, 'speech_to_text'):
                config_dict['speech_to_text'] = app_model_config.speech_to_text
            if hasattr(app_model_config, 'text_to_speech'):
                config_dict['text_to_speech'] = app_model_config.text_to_speech
            if hasattr(app_model_config, 'more_like_this'):
                config_dict['more_like_this'] = app_model_config.more_like_this
            if hasattr(app_model_config, 'dataset_query_variable'):
                config_dict['dataset_query_variable'] = app_model_config.dataset_query_variable

            app_model_config_list.append(config_dict)

        has_more = len(app_model_config_list) > limit
        if has_more:
            app_model_config_list = app_model_config_list[:-1]

        return app_model_config_list, has_more, total
