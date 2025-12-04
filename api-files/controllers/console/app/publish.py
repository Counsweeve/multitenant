import logging
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, select
from flask_restx import Resource, inputs, reqparse, marshal_with
from werkzeug.exceptions import Forbidden, NotFound, BadRequest

from controllers.console import api
from controllers.console.app.wraps import get_app_model, _load_app_model
from controllers.console.wraps import account_initialization_required, setup_required
from extensions.ext_database import db
from libs.login import current_user, login_required
from models import App, AppModelConfig, AppMode
from models.account import Account
from models.publish import ApplyAppType, PublishApplicationStatus, PublicApplicationAction, PublishWorkflow, \
    PublishApplicationHistory, NotificationMsgType, PublishAppModelConfig, SystemNotification
from services.app_model_config_service import AppModelConfigService
from services.publish_application_service import PublishApplicationService
from services.workflow_service import WorkflowService
from services.app_dsl_service import AppDslService, ImportMode
from fields.app_fields import app_detail_fields_with_site
from models.workflow import Workflow


from typing import cast

logger = logging.getLogger(__name__)

"""
工作流发布模型广场接口
"""
class Published2SquareApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW, AppMode.AGENT_CHAT])
    def post(self, app_model: App):
        """
        Publish workflow to square
        """
        if not isinstance(current_user, Account):
            raise Forbidden()
        # The role of the current user in the ta table must be admin, owner, or editor
        if not current_user.is_editor:
            raise Forbidden()

        parser = reqparse.RequestParser()
        parser.add_argument("apply_app_type", type=str, required=True, location="json")
        parser.add_argument("need_sys_approve", type=inputs.boolean, required=False, location="json")
        parser.add_argument("selected_workflow_agent_id", type=str, required=True, default="", location="json")
        parser.add_argument("tenant_id", type=str, required=False, default="", location="json")

        args = parser.parse_args()

        selected_workflow_agent_id = args["selected_workflow_agent_id"]
        apply_app_type = args["apply_app_type"]

        workflow_service = WorkflowService()
        if apply_app_type == ApplyAppType.WORKFLOW:
            workflow = workflow_service.get_published_workflow_by_id(
                app_model=app_model,
                workflow_id=args["selected_workflow_agent_id"],
            )

            # publish workflow fail
            if not workflow:
                logger.info("Workflow not found with id: %s", selected_workflow_agent_id)
                return {
                    "result": "fail",
                    "message": "选择的历史版本已经被删除了",
                }

        app_model_config_service = AppModelConfigService()
        if apply_app_type == ApplyAppType.AGENT:
            agent = app_model_config_service.get_published_agent_by_id(
                app_model=app_model,
                agent_id=args["selected_workflow_agent_id"],
            )

            if not agent:
                logger.info("Workflow not found with id: %s", selected_workflow_agent_id)
                return {
                    "result": "fail",
                    "message": "选择的历史版本已经被删除了",
                }

        srv = PublishApplicationService()
        with Session(db.engine, expire_on_commit=False) as session:
            application = srv.create(
                session=session,
                account=current_user,
                status=PublishApplicationStatus.APPLYING,
                apply_app_id=app_model.id,
                apply_app_version_id=selected_workflow_agent_id,
                apply_app_type=apply_app_type,
                tenant_id=args.get("tenant_id"),
                need_sys_approve=args.get("need_sys_approve"),
            )
            #记录新增到PublishApplicationHistory历史表
            srv.add_history(
                session=session,
                tenant_id=args.get("tenant_id"),
                application_id=application.id,
                action=PublicApplicationAction.SUBMIT,
                operator_id=current_user.id,
                operator_role="admin",
                from_status=None,
                to_status=str(PublishApplicationStatus.APPLYING),
                reason=args.get("reason"),
            )
            #新增到通知表
            srv.create_notification(
                session=session,
                tenant_id=args.get("tenant_id"),
                role=['admin', 'owner'],
                msg_type=NotificationMsgType.APPROVAL_TODO,
                title="发布到Square审批申请",
                content=f"发布到Square审批申请，发布申请ID：{application.id}",
                application_id=application.id,
                is_deal=False,
            )
            session.commit()

        return {
            "result": "success"
        }


"""
系统管理员审批接口
"""
class Published2SquareSysApproveApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def post(self):
        """
        Publish workflow to square
        """
        if not isinstance(current_user, Account):
            raise Forbidden()
        # The role of the current user in the ta table must be admin, owner, or editor
        if not current_user.is_editor:
            raise Forbidden()

        parser = reqparse.RequestParser()
        parser.add_argument("id", type=str, required=True, default="", location="json")
        parser.add_argument("application_id", type=str, required=True, default="", location="json")
        parser.add_argument("approve", type=inputs.boolean, required=True, location="json")
        parser.add_argument("reason", type=str, required=False, location="json")
        args = parser.parse_args()

        # 校验根据application_id找到apply_app_version_id，再根据apply_app_version_id找到workflow
        srv = PublishApplicationService()
        workflow_service = WorkflowService()
        app_model_config_service = AppModelConfigService()
        msg = None
        with Session(db.engine, expire_on_commit=False) as session:
            application = srv.get_by_id(
                session=session,
                application_id=args["application_id"],
            )
            if application is None and msg is None:
                #写入通知表
                srv.create_notification(
                    session=session,
                    role=['admin', 'owner'],
                    tenant_id=current_user.current_tenant.id,
                    msg_type=NotificationMsgType.APPROVAL_RESULT,
                    title="发布到Square审批失败",
                    content=f"发布到Square审批失败，发布申请ID：{args['application_id']}，原因：发布申请不存在",
                    is_deal=False,
                )
                session.commit()
                msg = {
                    "result": "fail",
                    "message": "发布申请不存在",
                }

            app_model = _load_app_model(
                app_id=application.apply_app_id
            )
            if application is None and msg is None:
                #写入通知表
                srv.create_notification(
                    session=session,
                    account_id=[application.applicant_id],
                    tenant_id=current_user.current_tenant.id,
                    msg_type=NotificationMsgType.APPROVAL_RESULT,
                    title="发布到Square审批失败",
                    content=f"发布到Square审批失败，发布申请ID：{args['application_id']}，原因：app不存在",
                    is_deal=False,
                )
                session.commit()
                msg = {
                    "result": "fail",
                    "message": "app不存在",
                }

            #判断apply_app_type是否是工作流
            if application.apply_app_type == ApplyAppType.WORKFLOW and msg is None:
                apply_app_version_id = application.apply_app_version_id
                workflow = workflow_service.get_published_workflow_by_id(
                app_model=app_model,
                workflow_id=apply_app_version_id,
                )
                if not workflow:
                    #写入通知表
                    logger.info("Workflow not found with id: %s", apply_app_version_id)
                    srv.create_notification(
                        session=session,
                        account_id=[application.applicant_id],
                        tenant_id=current_user.current_tenant.id,
                        msg_type=NotificationMsgType.APPROVAL_RESULT,
                        title="发布到Square审批失败",
                        content=f"发布到Square审批失败，发布申请ID：{args['application_id']}，原因：选择的历史版本已经被删除了",
                        is_deal=False,
                    )
                    session.commit()
                    msg = {
                        "result": "fail",
                        "message": "选择的历史版本已经被删除了",
                    }

            #判断apply_app_type是否是智能体
            if application.apply_app_type == ApplyAppType.AGENT and msg is None:
                apply_app_version_id = application.apply_app_version_id
                agent = app_model_config_service.get_published_agent_by_id(
                app_model=app_model,
                agent_id=apply_app_version_id,
                )
                if not agent:
                    #写入通知表
                    logger.info("Agent not found with id: %s", apply_app_version_id)
                    srv.create_notification(
                        session=session,
                        account_id=[application.applicant_id],
                        tenant_id=current_user.current_tenant.id,
                        msg_type=NotificationMsgType.APPROVAL_RESULT,
                        title="发布到Square审批失败",
                        content=f"发布到Square审批失败，发布申请ID：{args['application_id']}，原因：选择的历史版本已经被删除了",
                        is_deal=False,
                    )
                    session.commit()
                    msg = {
                        "result": "fail",
                        "message": "选择的历史版本已经被删除了",
                    }


        # 判断approve审批状态是否通过
        approve = args["approve"]
        if approve and msg is None:

            srv = PublishApplicationService()
            #更新publish_application表状态为已通过
            with Session(db.engine, expire_on_commit=False) as session:
                application=srv.update(
                    session=session,
                    application_id=args["application_id"],
                    status=PublishApplicationStatus.COMPLETED,
                )

                #记录新增到PublishApplicationHistory历史表
                srv.add_history(
                    session=session,
                    tenant_id=application.tenant_id,
                    application_id=args["application_id"],
                    action=PublicApplicationAction.APPROVE,
                    operator_id=current_user.id,
                    operator_role="admin",
                    from_status=None,
                    to_status=str(PublishApplicationStatus.COMPLETED),
                    reason=args.get("reason"),
                )

                #新增到通知表
                srv.create_notification(
                    session=session,
                    tenant_id=application.tenant_id,
                    account_id=[application.applicant_id],
                    msg_type=NotificationMsgType.APPROVAL_RESULT,
                    title="发布到Square审批通过",
                    content=f"发布到Square审批通过，发布申请ID：{args['application_id']}",
                    is_deal=False,
                )
                # 判断apply_app_type是否是工作流,写入publish_workflows表
                if application.apply_app_type == ApplyAppType.WORKFLOW:
                    publish_workflow = PublishWorkflow(
                        app_id=app_model.id,
                        tenant_id=workflow.tenant_id,
                        type=workflow.type,
                        version=workflow.version,
                        marked_name=app_model.name +'_'+workflow.marked_name if workflow.marked_name else app_model.name,
                        marked_comment=workflow.marked_comment,
                        graph=workflow.graph,
                        _features=workflow.features,
                        created_by=application.created_by,
                        updated_by=application.updated_by,
                        icon_type=app_model.icon_type,
                        icon=app_model.icon,
                        icon_background=app_model.icon_background,
                        enable=True,
                        workflow_id=application.apply_app_version_id,
                    )
                    session.add(publish_workflow)
                    #更新workflows表publish_square为True
                    session.query(Workflow).filter(Workflow.id == publish_workflow.workflow_id).update({"publish_square": True})
                # 判断apply_app_type是否是agent,写入publish_app_model_configs表
                if application.apply_app_type == ApplyAppType.AGENT:
                    publish_app_model_config = PublishAppModelConfig(
                        app_id=app_model.id,
                        provider = agent.provider,
                        model_id = agent.model_id,
                        tenant_id = app_model.tenant_id,
                        configs = agent.configs,
                        created_by = application.created_by,
                        updated_by = application.created_by,
                        opening_statement = agent.opening_statement,
                        suggested_questions = agent.suggested_questions,
                        suggested_questions_after_answer = agent.suggested_questions_after_answer,
                        speech_to_text = agent.speech_to_text,
                        text_to_speech = agent.text_to_speech,
                        more_like_this = agent.more_like_this,
                        model = agent.model,
                        user_input_form = agent.user_input_form,
                        dataset_query_variable = agent.dataset_query_variable,
                        pre_prompt = agent.pre_prompt,
                        agent_mode = agent.agent_mode,
                        sensitive_word_avoidance = agent.sensitive_word_avoidance,
                        retriever_resource = agent.retriever_resource,
                        prompt_type = agent.prompt_type,
                        chat_prompt_config = agent.chat_prompt_config,
                        completion_prompt_config = agent.completion_prompt_config,
                        dataset_configs = agent.dataset_configs,
                        external_data_tools = agent.external_data_tools,
                        file_upload = agent.file_upload,
                        icon_type=app_model.icon_type,
                        icon=app_model.icon,
                        icon_background=app_model.icon_background,
                        enable=True,
                        app_model_config_id=application.apply_app_version_id,
                        marked_name=app_model.name + '_' + agent.marked_name if agent.marked_name else app_model.name,
                        marked_comment=agent.marked_comment,
                    )
                    session.add(publish_app_model_config)
                    #更新app_model_configs表publish_square为True
                    session.query(AppModelConfig).filter(AppModelConfig.id == publish_app_model_config.app_model_config_id).update({"publish_square": True})
                session.commit()
                msg = {
                    "result": "success",
                    "message": "操作成功",
                }

        if not approve and msg is None:
            #更新publish_application表状态为已拒绝
            with Session(db.engine, expire_on_commit=False) as session:
                srv.update(
                    session=session,
                    application_id=args["application_id"],
                    status=PublishApplicationStatus.REJECTED,
                )
                #记录新增到PublishApplicationHistory历史表
                srv.add_history(
                    session=session,
                    tenant_id=workflow.tenant_id,
                    application_id=args["application_id"],
                    action=PublicApplicationAction.REJECT,
                    operator_id=current_user.id,
                    operator_role="admin",
                    from_status=None,
                    to_status=str(PublishApplicationStatus.REJECTED),
                    reason=args.get("reason"),
                )
                #新增到通知表
                srv.create_notification(
                    session=session,
                    tenant_id=workflow.tenant_id,
                    account_id=[application.applicant_id],
                    msg_type=NotificationMsgType.APPROVAL_RESULT,
                    title="发布到Square审批拒绝",
                    content=f"发布到Square审批拒绝，发布申请ID：{args['application_id']}",
                    is_deal=False,
                )
                session.commit()
                msg = {
                    "result": "success",
                    "message": "操作成功",
                }
        #更新id
        if args.get('id'):
            # 更新system_notification表中对应id的记录
            notification = srv.get_notification(session=session, notification_id=args['id'])
            if notification:
                notification.is_deal = True
                if current_user.id:
                    notification.updated_by = current_user.id
                session.commit()

        return msg

"""
分页审批记录查询接口
"""
class PublishedApplicationHistoryListApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def post(self):
        """
        Get application history list with pagination
        """
        if not isinstance(current_user, Account):
            raise Forbidden()

        parser = reqparse.RequestParser()
        parser.add_argument("application_id", type=str, required=True, location="json")
        parser.add_argument("page", type=int, required=False, default=1, location="json")
        parser.add_argument("limit", type=int, required=False, default=999, location="json")
        args = parser.parse_args()

        application_id = args["application_id"]
        page = max(1, args["page"])
        limit = max(1, min(100, args["limit"]))
        offset = (page - 1) * limit

        srv = PublishApplicationService()
        with Session(db.engine, expire_on_commit=False) as session:
            # 验证应用是否存在
            application = srv.get_by_id(session=session, application_id=application_id)
            if not application:
                return {
                    "result": "fail",
                    "message": "发布申请不存在"
                }

            # 验证权限
            if current_user.id != application.applicant_id and not current_user.is_editor:
                return {
                    "result": "fail",
                    "message": "无权限查看该应用的历史记录"
                }

            # 查询历史记录
            history_list = srv.list_history_by_application(
                session=session,
                application_id=application_id,
                limit=limit,
                offset=offset
            )

            # 查询总记录数
            stmt = select(func.count()).where(PublishApplicationHistory.application_id == application_id)
            total = session.scalar(stmt)

            # 格式化返回结果
            results = []
            for history in history_list:
                results.append({
                    "id": history.id,
                    "application_id": history.application_id,
                    "action": history.action,
                    "operator_id": history.operator_id,
                    "operator_role": history.operator_role,
                    "from_status": history.from_status,
                    "to_status": history.to_status,
                    "reason": history.reason,
                    "created_at": history.created_at.isoformat() if history.created_at else None
                })

        return {
            "result": "success",
            "data": {
                "total": total,
                "page": page,
                "limit": limit,
                "items": results
            }
        }


"""
通知消息查询接口
"""
class SystemNotificationListApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def post(self):
        """
        Get system notifications with pagination
        """
        if not isinstance(current_user, Account):
            raise Forbidden()

        parser = reqparse.RequestParser()
        parser.add_argument("page", type=int, required=False, default=1, location="json")
        parser.add_argument("limit", type=int, required=False, default=999, location="json")
        parser.add_argument("role", type=list, required=False, default=None, location="json")
        parser.add_argument("msg_type", type=list, required=False, default=None, location="json")
        parser.add_argument("is_deal", type=bool, required=False, default=None, location="json")
        args = parser.parse_args()

        page = max(1, args["page"])
        limit = max(1, min(999, args["limit"]))
        offset = (page - 1) * limit
        role=args["role"]
        is_deal = args["is_deal"]
        msg_type = args["msg_type"]


        srv = PublishApplicationService()
        with Session(db.engine, expire_on_commit=False) as session:
            # 查询通知列表
            # 确保role参数是字符串列表，从字典中提取id字段
            if role and isinstance(role[0], dict):
                role = [r['id'] for r in role]

            notifications = srv.list_notifications_by_account(
                session=session,
                account_id=[current_user.id],
                msg_type=msg_type,
                role=role,
                limit=limit,
                offset=offset,
                is_deal=is_deal  # 过滤掉已处理的通知
            )

            # 查询总记录数
            if role:
                stmt = select(func.count()).where(
                    or_(
                        SystemNotification.account_id.contains([current_user.id]),
                        SystemNotification.role.contains(role)
                    )
                )
            else:
                stmt = select(func.count()).where(
                    SystemNotification.account_id.contains([current_user.id])
                )
            if is_deal is not None:
                stmt = stmt.where(SystemNotification.is_deal == is_deal)

            if msg_type is not None:
                stmt = stmt.where(SystemNotification.msg_type.in_(msg_type))

            total = session.scalar(stmt)

            # 格式化返回结果
            results = []
            for notification in notifications:
                results.append({
                    "id": notification.id,
                    "account_id": notification.account_id,
                    "title": notification.title,
                    "content": notification.content,
                    "msg_type": notification.msg_type,
                    "source_type": notification.source_type,
                    "source_id": notification.source_id,
                    "created_at": notification.created_at.isoformat() if notification.created_at else None,
                    "application_id": notification.application_id,
                    "is_deal": notification.is_deal
                })

        return {
            "result": "success",
            "data": {
                "total": total,
                "page": page,
                "limit": limit,
                "items": results
            }
        }

"""
清空系统消息接口
"""
class SystemNotificationClearApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def post(self):
        """
        批量将指定消息类型的通知标记为已处理
        """
        if not isinstance(current_user, Account):
            raise Forbidden()

        parser = reqparse.RequestParser()
        parser.add_argument("msg_types", type=list, required=True, location="json")
        parser.add_argument("role", type=list, required=True, location="json")
        parser.add_argument("tenant_id", type=str, required=True, location="json")
        args = parser.parse_args()

        msg_types = args["msg_types"]
        role = args["role"]
        tenant_id = args["tenant_id"]

        # 验证msg_types是否为字符串列表
        if not all(isinstance(msg_type, str) for msg_type in msg_types):
            return {"result": "error", "message": "msg_types must be a list of strings"}, 400
        # 验证tenant_id
        if not tenant_id:
            return {"result": "error", "message": "tenant_id is required"}, 400

        srv = PublishApplicationService()
        with Session(db.engine, expire_on_commit=False) as session:
            # 批量更新通知状态
            updated_count = srv.batch_update_notifications_to_deal(
                session=session,
                account_id=[current_user.id],
                role=role,
                tenant_id=tenant_id,
                msg_types=msg_types,
                updated_by=current_user.id
            )
            session.commit()

        return {
            "result": "success",
            "data": {
                "updated_count": updated_count
            }
        }

"""
编辑工作流模型广场
"""
class UpdatePublishWorkflowApi(Resource):
    @login_required
    def post(self, workflow_id: str):
        """更新发布的工作流

        更新发布到模型广场的工作流信息
        """
        try:
            parser = reqparse.RequestParser()
            parser.add_argument("marked_name", type=str, required=False, location="json")
            parser.add_argument("marked_comment", type=str, required=False, location="json")
            parser.add_argument("icon", type=str, required=False, location="json")
            parser.add_argument("icon_type", type=str, required=False, location="json")
            parser.add_argument("icon_background", type=str, required=False, location="json")
            args = parser.parse_args()

            # 过滤掉None值，只保留有值的字段
            update_fields = {k: v for k, v in args.items() if v is not None}

            # 调用服务层更新工作流
            with Session(db.engine, expire_on_commit=False) as session:
                srv = PublishApplicationService()
                updated_workflow = srv.update_publish_workflow(
                    session=session,
                    workflow_id=workflow_id,
                    updated_by=current_user.id,
                    **update_fields
                )
                session.commit()

            return {
                "result": "success",
                "data": {
                    "id": updated_workflow.id,
                    "marked_name": updated_workflow.marked_name,
                    "marked_comment": updated_workflow.marked_comment,
                    "icon": updated_workflow.icon,
                    "icon_type": updated_workflow.icon_type,
                    "icon_background": updated_workflow.icon_background,
                    "updated_at": updated_workflow.updated_at.isoformat()
                }
            }
        except ValueError as e:
            if str(e) == "publish_workflow not found":
                raise NotFound(str(e))
            raise BadRequest(str(e))
        except Exception as e:
            logger.exception("Failed to update publish workflow")
            raise Forbidden(str(e))

"""
编辑智能体模型广场
"""
class UpdatePublishAppModelConfigApi(Resource):
    @login_required
    def post(self, config_id: str):
        """更新发布的智能体模型配置

        更新发布到模型广场的智能体模型配置信息
        """
        try:
            parser = reqparse.RequestParser()
            parser.add_argument("marked_name", type=str, required=False, location="json")
            parser.add_argument("marked_comment", type=str, required=False, location="json")
            parser.add_argument("icon", type=str, required=False, location="json")
            parser.add_argument("icon_type", type=str, required=False, location="json")
            parser.add_argument("icon_background", type=str, required=False, location="json")
            args = parser.parse_args()

            # 过滤掉None值，只保留有值的字段
            update_fields = {k: v for k, v in args.items() if v is not None}

            # 调用服务层更新配置
            with Session(db.engine, expire_on_commit=False) as session:
                srv = PublishApplicationService()
                updated_config = srv.update_publish_app_model_config(
                    session=session,
                    config_id=config_id,
                    updated_by=current_user.id,
                    **update_fields
                )
                session.commit()

            return {
                "result": "success",
                "data": {
                    "id": updated_config.id,
                    "marked_name": updated_config.marked_name,
                    "marked_comment": updated_config.marked_comment,
                    "icon": updated_config.icon,
                    "icon_type": updated_config.icon_type,
                    "icon_background": updated_config.icon_background,
                    "updated_at": updated_config.updated_at.isoformat()
                }
            }
        except ValueError as e:
            if str(e) == "publish_app_model_config not found":
                raise NotFound(str(e))
            raise BadRequest(str(e))
        except Exception as e:
            logger.exception("Failed to update publish app model config")
            raise Forbidden(str(e))

"""
启用禁用智能体模型广场
"""
class UpdatePublishAppModelConfigEnableApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @get_app_model(mode=[AppMode.AGENT_CHAT])
    def post(self, app_model: App):
        """
        Update publish app model config enable status
        """
        if not isinstance(current_user, Account):
            raise Forbidden()
        # The role of the current user in the ta table must be admin, owner, or editor
        if not current_user.is_editor:
            raise Forbidden()

        parser = reqparse.RequestParser()
        parser.add_argument("config_id", type=str, required=True, location="json")
        parser.add_argument("enable", type=inputs.boolean, required=True, location="json")

        args = parser.parse_args()

        try:
            with Session(db.engine, expire_on_commit=False) as session:
                publish_application_service = PublishApplicationService()
                # Update publish app model config enable status
                updated_config = publish_application_service.update_publish_app_model_config(
                    session=session,
                    config_id=args["config_id"],
                    updated_by=current_user.id,
                    enable=args["enable"]
                )
                session.commit()

                return {
                    "result": True,
                    "config_id": updated_config.id,
                    "enable": updated_config.enable
                }
        except ValueError as e:
            logger.exception("Failed to update publish app model config enable status")
            raise NotFound(str(e))
        except Exception as e:
            logger.exception("Failed to update publish app model config enable status")
            raise Forbidden(str(e))



"""
启用禁用工作流模型广场
"""
class UpdatePublishWorkflowEnableApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @get_app_model(mode=[AppMode.WORKFLOW])
    def post(self, app_model: App):
        """
        Update publish workflow enable status
        """
        if not isinstance(current_user, Account):
            raise Forbidden()
        # The role of the current user in the ta table must be admin, owner, or editor
        if not current_user.is_editor:
            raise Forbidden()

        parser = reqparse.RequestParser()
        parser.add_argument("workflow_id", type=str, required=True, location="json")
        parser.add_argument("enable", type=inputs.boolean, required=True, location="json")

        args = parser.parse_args()

        try:
            with Session(db.engine, expire_on_commit=False) as session:
                publish_application_service = PublishApplicationService()
                # Update publish workflow enable status
                updated_workflow = publish_application_service.update_publish_workflow(
                    session=session,
                    workflow_id=args["workflow_id"],
                    updated_by=current_user.id,
                    enable=args["enable"]
                )
                session.commit()

                return {
                    "result": True,
                    "workflow_id": updated_workflow.id,
                    "enable": updated_workflow.enable
                }
        except ValueError as e:
            logger.exception("Failed to update publish workflow enable status")
            raise NotFound(str(e))
        except Exception as e:
            logger.exception("Failed to update publish workflow enable status")
            raise Forbidden(str(e))

"""
模型广场查询接口
"""
class SquareListApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    def post(self):
        """
        Get square list by type and marked name
        """
        if not isinstance(current_user, Account):
            raise Forbidden()

        parser = reqparse.RequestParser()
        parser.add_argument("type", type=str, required=False, location="json", choices=["workflow", "agent-chat"])
        parser.add_argument("marked_name", type=str, required=False, location="json")
        parser.add_argument("page", type=int, required=False, default=1, location="json")
        parser.add_argument("limit", type=int, required=False, default=999, location="json")

        args = parser.parse_args()

        try:
            with Session(db.engine, expire_on_commit=False) as session:
                # 处理分页参数
                page = max(1, args["page"])
                limit = max(1, min(args["limit"], 100))  # 限制最大查询数量

                # 获取所有符合条件的项目
                all_items = []

                # 查询工作流
                if args["type"] in [None, "workflow"]:
                    query = session.query(PublishWorkflow)
                    if args["marked_name"]:
                        query = query.filter(PublishWorkflow.marked_name.ilike(f"%{args['marked_name']}%"))

                    workflow_results = query.all()
                    all_items.extend([
                        {
                            "id": wf.id,
                            "app_id": wf.app_id,
                            "marked_name": wf.marked_name,
                            "marked_comment": wf.marked_comment,
                            "icon_type":wf.icon_type,
                            "icon": wf.icon,
                            "icon_background": wf.icon_background,
                            "tenant_id": wf.tenant_id,
                            "workflow_or_agent_id": wf.workflow_id,
                            "enable": wf.enable,
                            "type": "workflow",  # 添加类型标识
                            "created_at": wf.created_at
                        }
                        for wf in workflow_results
                    ])

                # 查询智能体
                if args["type"] in [None, "agent-chat"]:
                    query = session.query(PublishAppModelConfig)
                    if args["marked_name"]:
                        query = query.filter(PublishAppModelConfig.marked_name.ilike(f"%{args['marked_name']}%"))

                    agent_results = query.all()
                    all_items.extend([
                        {
                            "id": config.id,
                            "app_id": config.app_id,
                            "marked_name": config.marked_name,
                            "marked_comment": config.marked_comment,
                            "icon_type":config.icon_type,
                            "icon":config.icon,
                            "icon_background":config.icon_background,
                            "tenant_id":config.tenant_id,
                            "workflow_or_agent_id":config.app_model_config_id,
                            "enable": config.enable,
                            "type": "agent-chat",  # 添加类型标识
                            "created_at": config.created_at
                        }
                        for config in agent_results
                    ])

                # 按created_at倒序排序
                all_items.sort(key=lambda x: x["created_at"], reverse=True)

                # 应用分页
                offset = (page - 1) * limit
                paged_items = all_items[offset:offset + limit]

                # 格式化返回结果，将created_at转换为ISO格式字符串
                formatted_items = [
                    {
                        **item,
                        "created_at": item["created_at"].isoformat() if item["created_at"] else None
                    }
                    for item in paged_items
                ]

                return {
                    "result": "success",
                    "data":{
                        "items": formatted_items,
                        "total": len(all_items),
                        "page": page,
                        "limit": limit
                    }
                }
        except Exception as e:
            logger.exception("Failed to get square list")
            raise Forbidden(str(e))

"""
克隆
"""
class AppCopyApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @marshal_with(app_detail_fields_with_site)
    def post(self):
        """Copy app"""
        # The role of the current user in the ta table must be admin, owner, or editor
        if not current_user.is_editor:
            raise Forbidden()

        parser = reqparse.RequestParser()
        parser.add_argument("marked_name", type=str, location="json")
        parser.add_argument("marked_comment", type=str, location="json")
        parser.add_argument("icon_type", type=str, location="json")
        parser.add_argument("icon", type=str, location="json")
        parser.add_argument("icon_background", type=str, location="json")
        parser.add_argument("tenant_id", type=str, location="json")
        parser.add_argument("type", type=str, location="json")
        parser.add_argument("id", type=str, location="json")
        parser.add_argument("app_id", type=str, location="json")
        parser.add_argument("workflow_or_agent_id", type=str, location="json")

        args = parser.parse_args()

        # 根据入参创建App对象
        app_model = App(
            name=args.get("marked_name"),
            description=args.get("marked_comment"),
            mode=args.get("type"),
            icon_type=args.get("icon_type"),
            icon=args.get("icon"),
            icon_background=args.get("icon_background"),
            tenant_id=args.get("tenant_id"),
            id=args.get("app_id"),
        )
        if args.get("type") in {AppMode.ADVANCED_CHAT, AppMode.WORKFLOW}:
            app_model.workflow_id=args.get("workflow_or_agent_id")
        else:
            app_model.app_model_config_id=args.get("workflow_or_agent_id")

        with Session(db.engine, expire_on_commit=False) as session:
            import_service = AppDslService(session)
            yaml_content = import_service.export_dsl(app_model=app_model, include_secret=True)
            account = cast(Account, current_user)
            result = import_service.import_app(
                account=account,
                import_mode=ImportMode.YAML_CONTENT.value,
                yaml_content=yaml_content,
                name=args.get("marked_name"),
                description=args.get("marked_comment"),
                icon_type=args.get("icon_type"),
                icon=args.get("icon"),
                icon_background=args.get("icon_background"),
            )
            session.commit()

            stmt = select(App).where(App.id == result.app_id)
            app = session.scalar(stmt)

        return app, 201



api.add_resource(
    Published2SquareApi,
    "/apps/<uuid:app_id>/publish/square/submit",
)

api.add_resource(
    Published2SquareSysApproveApi,
    "/apps/publish/square/sys-approve",
)

api.add_resource(
    PublishedApplicationHistoryListApi,
    "/apps/publish/application-history/page-list",
)

api.add_resource(
    SystemNotificationListApi,
    "/apps/publish/notification/list",
)

# 清除系统通知
api.add_resource(
    SystemNotificationClearApi,
    "/apps/publish/notification/clear",
)

api.add_resource(
    UpdatePublishWorkflowApi,
    "/apps/publish/workflow/update/<uuid:workflow_id>",
)

api.add_resource(
    UpdatePublishAppModelConfigApi,
    "/apps/publish/app-model-config/update/<uuid:config_id>",
)

api.add_resource(
    UpdatePublishAppModelConfigEnableApi,
    "/apps/<uuid:app_id>/publish/app-model-config/enable",
)

api.add_resource(
    UpdatePublishWorkflowEnableApi,
    "/apps/<uuid:app_id>/publish/workflow/enable",
)

api.add_resource(
    SquareListApi,
    "/apps/publish/square/list",
)

api.add_resource(
    AppCopyApi,
    "/apps/publish/copy",
)
