import json
import logging
from typing import cast

from flask import request
from flask_login import current_user
from flask_restx import Resource, marshal_with, reqparse, inputs

from controllers.console import api
from controllers.console.app.wraps import get_app_model
from controllers.console.wraps import account_initialization_required, setup_required
from core.agent.entities import AgentToolEntity
from core.tools.tool_manager import ToolManager
from core.tools.utils.configuration import ToolParameterConfigurationManager
from events.app_event import app_model_config_was_updated
from extensions.ext_database import db
from libs.login import login_required
from models.model import AppMode, AppModelConfig
from services.app_model_config_service import AppModelConfigService

from models import App
from models.account import Account

from werkzeug.exceptions import Forbidden
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ModelConfigResource(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @get_app_model(mode=[AppMode.AGENT_CHAT, AppMode.CHAT, AppMode.COMPLETION])
    def post(self, app_model):
        """Modify app model config"""
        # validate config
        model_configuration = AppModelConfigService.validate_configuration(
            tenant_id=current_user.current_tenant_id,
            config=cast(dict, request.json),
            app_mode=AppMode.value_of(app_model.mode),
        )

        new_app_model_config = AppModelConfig(
            app_id=app_model.id,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        new_app_model_config = new_app_model_config.from_model_config_dict(model_configuration)

        if app_model.mode == AppMode.AGENT_CHAT.value or app_model.is_agent:
            # get original app model config
            original_app_model_config = (
                db.session.query(AppModelConfig).where(AppModelConfig.id == app_model.app_model_config_id).first()
            )
            if original_app_model_config is None:
                raise ValueError("Original app model config not found")
            agent_mode = original_app_model_config.agent_mode_dict
            # decrypt agent tool parameters if it's secret-input
            parameter_map = {}
            masked_parameter_map = {}
            tool_map = {}
            for tool in agent_mode.get("tools") or []:
                if not isinstance(tool, dict) or len(tool.keys()) <= 3:
                    continue

                agent_tool_entity = AgentToolEntity(**tool)
                # get tool
                try:
                    tool_runtime = ToolManager.get_agent_tool_runtime(
                        tenant_id=current_user.current_tenant_id,
                        app_id=app_model.id,
                        agent_tool=agent_tool_entity,
                    )
                    manager = ToolParameterConfigurationManager(
                        tenant_id=current_user.current_tenant_id,
                        tool_runtime=tool_runtime,
                        provider_name=agent_tool_entity.provider_id,
                        provider_type=agent_tool_entity.provider_type,
                        identity_id=f"AGENT.{app_model.id}",
                    )
                except Exception:
                    continue

                # get decrypted parameters
                if agent_tool_entity.tool_parameters:
                    parameters = manager.decrypt_tool_parameters(agent_tool_entity.tool_parameters or {})
                    masked_parameter = manager.mask_tool_parameters(parameters or {})
                else:
                    parameters = {}
                    masked_parameter = {}

                key = f"{agent_tool_entity.provider_id}.{agent_tool_entity.provider_type}.{agent_tool_entity.tool_name}"
                masked_parameter_map[key] = masked_parameter
                parameter_map[key] = parameters
                tool_map[key] = tool_runtime

            # encrypt agent tool parameters if it's secret-input
            agent_mode = new_app_model_config.agent_mode_dict
            for tool in agent_mode.get("tools") or []:
                agent_tool_entity = AgentToolEntity(**tool)

                # get tool
                key = f"{agent_tool_entity.provider_id}.{agent_tool_entity.provider_type}.{agent_tool_entity.tool_name}"
                if key in tool_map:
                    tool_runtime = tool_map[key]
                else:
                    try:
                        tool_runtime = ToolManager.get_agent_tool_runtime(
                            tenant_id=current_user.current_tenant_id,
                            app_id=app_model.id,
                            agent_tool=agent_tool_entity,
                        )
                    except Exception:
                        continue

                manager = ToolParameterConfigurationManager(
                    tenant_id=current_user.current_tenant_id,
                    tool_runtime=tool_runtime,
                    provider_name=agent_tool_entity.provider_id,
                    provider_type=agent_tool_entity.provider_type,
                    identity_id=f"AGENT.{app_model.id}",
                )
                manager.delete_tool_parameters_cache()

                # override parameters if it equals to masked parameters
                if agent_tool_entity.tool_parameters:
                    if key not in masked_parameter_map:
                        continue

                    for masked_key, masked_value in masked_parameter_map[key].items():
                        if (
                            masked_key in agent_tool_entity.tool_parameters
                            and agent_tool_entity.tool_parameters[masked_key] == masked_value
                        ):
                            agent_tool_entity.tool_parameters[masked_key] = parameter_map[key].get(masked_key)

                # encrypt parameters
                if agent_tool_entity.tool_parameters:
                    tool["tool_parameters"] = manager.encrypt_tool_parameters(agent_tool_entity.tool_parameters or {})

            # update app model config
            new_app_model_config.agent_mode = json.dumps(agent_mode)

        db.session.add(new_app_model_config)
        db.session.flush()

        app_model.app_model_config_id = new_app_model_config.id
        db.session.commit()

        app_model_config_was_updated.send(app_model, app_model_config=new_app_model_config)

        return {"result": "success"}


"""
智能体历史版本
"""
class PublishedAllAgentApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW, AppMode.AGENT_CHAT])
    def post(self, app_model: App):
        """
        Get published agent
        """

        if not isinstance(current_user, Account):
            raise Forbidden()
        if not current_user.is_editor:
            raise Forbidden()

        parser = reqparse.RequestParser()
        parser.add_argument("page", type=inputs.int_range(1, 99999), required=False, default=1, location="json")
        parser.add_argument("limit", type=inputs.int_range(1, 999), required=False, default=999, location="json")
        parser.add_argument("user_id", type=str, required=False, location="json")
        parser.add_argument("named_only", type=inputs.boolean, required=False, default=False, location="json")
        args = parser.parse_args()
        page = int(args.get("page", 1))
        limit = int(args.get("limit", 999))
        user_id = args.get("user_id")
        named_only = args.get("named_only", False)

        if user_id:
            if user_id != current_user.id:
                raise Forbidden()
            user_id = cast(str, user_id)

        app_model_config_service = AppModelConfigService()
        with Session(db.engine) as session:
            config, has_more, total = app_model_config_service.get_all_published_agent(
                session=session,
                app_model=app_model,
                page=page,
                limit=limit,
                user_id=user_id,
                named_only=named_only,
            )

            # 添加日志记录以便调试
            logger.info(
                f"获取到的分页参数: page={page}, limit={limit}, user_id={user_id}, named_only={named_only}, total={total}")

        # 导入jsonable_encoder用于序列化AppModelConfig对象
        from core.model_runtime.utils.encoders import jsonable_encoder

        # 将AppModelConfig对象序列化为可JSON序列化的字典
        serialized_config = jsonable_encoder(config)

        return {
            "items": serialized_config,
            "page": page,
            "limit": limit,
            "has_more": has_more,
            "total": total
        }


"""
智能体历史版本重命名
"""


class AppModelConfigByIdApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW, AppMode.AGENT_CHAT])
    def post(self, app_model: App, config_id: str):
        """
        Update app model config attributes
        """
        if not isinstance(current_user, Account):
            raise Forbidden()
        # Check permission
        if not current_user.is_editor:
            raise Forbidden()

        parser = reqparse.RequestParser()
        parser.add_argument("marked_name", type=str, required=False, location="json")
        parser.add_argument("marked_comment", type=str, required=False, location="json")
        args = parser.parse_args()

        # Validate name and comment length
        if args.marked_name and len(args.marked_name) > 30:
            raise ValueError("Marked name cannot exceed 30 characters")
        if args.marked_comment and len(args.marked_comment) > 100:
            raise ValueError("Marked comment cannot exceed 100 characters")

        # Get app model config
        app_model_config_service = AppModelConfigService()
        app_model_config = app_model_config_service.get_published_agent_by_id(app_model=app_model, agent_id=config_id)

        if not app_model_config:
            raise Forbidden("App model config not found")

        # Prepare update data
        update_data = {}
        if args.get("marked_name") is not None:
            update_data["marked_name"] = args["marked_name"]
        if args.get("marked_comment") is not None:
            update_data["marked_comment"] = args["marked_comment"]

        if not update_data:
            return {"message": "No valid fields to update"}, 400

        # Update app model config
        for key, value in update_data.items():
            setattr(app_model_config, key, value)

        db.session.commit()

        return {"result": "success"}


api.add_resource(ModelConfigResource, "/apps/<uuid:app_id>/model-config")

api.add_resource(PublishedAllAgentApi, "/apps/<uuid:app_id>/app-model-config")

api.add_resource(AppModelConfigByIdApi, "/apps/<uuid:app_id>/app-model-config/<string:config_id>")
