from flask import request
from flask_login import current_user
from flask_restx import Resource, marshal, reqparse
from werkzeug.exceptions import Forbidden, InternalServerError, NotFound

import services
from controllers.console import api
from controllers.console.datasets.error import DatasetNameDuplicateError
from controllers.console.wraps import account_initialization_required, setup_required
from fields.dataset_fields import dataset_detail_fields
from libs.login import login_required
from services.dataset_service import DatasetService
from services.external_knowledge_service import ExternalDatasetService
from services.hit_testing_service import HitTestingService
from services.knowledge_service import ExternalDatasetTestService


def _validate_name(name):
    """
    验证名称长度是否符合要求

    Args:
        name (str): 待验证的名称

    Returns:
        str: 验证通过的名称

    Raises:
        ValueError: 名称长度不符合要求时抛出异常
    """
    if not name or len(name) < 1 or len(name) > 100:
        raise ValueError("Name must be between 1 to 100 characters.")
    return name


class ExternalApiTemplateListApi(Resource):
    """
    外部知识API模板列表资源类
    提供外部知识API模板的查询和创建功能
    """

    @setup_required
    @login_required
    @account_initialization_required
    def get(self):
        """
        获取外部知识API模板列表

        Request Args:
            page (int): 页码，默认为1
            limit (int): 每页数量，默认为20
            keyword (str): 搜索关键词，可选

        Returns:
            dict: 包含API模板列表和分页信息的响应数据
        """
        page = request.args.get("page", default=1, type=int)
        limit = request.args.get("limit", default=20, type=int)
        search = request.args.get("keyword", default=None, type=str)

        external_knowledge_apis, total = ExternalDatasetService.get_external_knowledge_apis(
            page, limit, current_user.current_tenant_id, search
        )
        response = {
            "data": [item.to_dict() for item in external_knowledge_apis],
            "has_more": len(external_knowledge_apis) == limit,
            "limit": limit,
            "total": total,
            "page": page,
        }
        return response, 200

    @setup_required
    @login_required
    @account_initialization_required
    def post(self):
        """
        创建新的外部知识API模板

        Request JSON:
            name (str): API模板名称，必填
            settings (dict): API配置信息，必填

        Returns:
            dict: 创建成功的API模板信息

        Raises:
            Forbidden: 用户没有编辑权限
            DatasetNameDuplicateError: 模板名称重复
        """
        parser = reqparse.RequestParser()
        parser.add_argument(
            "name",
            nullable=False,
            required=True,
            help="Name is required. Name must be between 1 to 100 characters.",
            type=_validate_name,
        )
        parser.add_argument(
            "settings",
            type=dict,
            location="json",
            nullable=False,
            required=True,
        )
        args = parser.parse_args()

        ExternalDatasetService.validate_api_list(args["settings"])

        # 验证用户是否有数据集编辑权限
        if not current_user.is_dataset_editor:
            raise Forbidden()

        try:
            external_knowledge_api = ExternalDatasetService.create_external_knowledge_api(
                tenant_id=current_user.current_tenant_id, user_id=current_user.id, args=args
            )
        except services.errors.dataset.DatasetNameDuplicateError:
            raise DatasetNameDuplicateError()

        return external_knowledge_api.to_dict(), 201


class ExternalApiTemplateApi(Resource):
    """
    单个外部知识API模板资源类
    提供外部知识API模板的查询、更新和删除功能
    """

    @setup_required
    @login_required
    @account_initialization_required
    def get(self, external_knowledge_api_id):
        """
        根据ID获取单个外部知识API模板详情

        Args:
            external_knowledge_api_id (uuid): API模板ID

        Returns:
            dict: API模板详细信息

        Raises:
            NotFound: 找不到指定的API模板
        """
        external_knowledge_api_id = str(external_knowledge_api_id)
        external_knowledge_api = ExternalDatasetService.get_external_knowledge_api(external_knowledge_api_id)
        if external_knowledge_api is None:
            raise NotFound("API template not found.")

        return external_knowledge_api.to_dict(), 200

    @setup_required
    @login_required
    @account_initialization_required
    def patch(self, external_knowledge_api_id):
        """
        更新外部知识API模板信息

        Args:
            external_knowledge_api_id (uuid): API模板ID

        Request JSON:
            name (str): API模板名称，必填
            settings (dict): API配置信息，必填

        Returns:
            dict: 更新后的API模板信息
        """
        external_knowledge_api_id = str(external_knowledge_api_id)

        parser = reqparse.RequestParser()
        parser.add_argument(
            "name",
            nullable=False,
            required=True,
            help="type is required. Name must be between 1 to 100 characters.",
            type=_validate_name,
        )
        parser.add_argument(
            "settings",
            type=dict,
            location="json",
            nullable=False,
            required=True,
        )
        args = parser.parse_args()
        ExternalDatasetService.validate_api_list(args["settings"])

        external_knowledge_api = ExternalDatasetService.update_external_knowledge_api(
            tenant_id=current_user.current_tenant_id,
            user_id=current_user.id,
            external_knowledge_api_id=external_knowledge_api_id,
            args=args,
        )

        return external_knowledge_api.to_dict(), 200

    @setup_required
    @login_required
    @account_initialization_required
    def delete(self, external_knowledge_api_id):
        """
        删除外部知识API模板

        Args:
            external_knowledge_api_id (uuid): API模板ID

        Returns:
            dict: 删除成功的结果信息

        Raises:
            Forbidden: 用户没有编辑权限
        """
        external_knowledge_api_id = str(external_knowledge_api_id)

        # 验证用户是否有编辑权限且不是数据集操作员
        if not current_user.is_editor or current_user.is_dataset_operator:
            raise Forbidden()

        ExternalDatasetService.delete_external_knowledge_api(current_user.current_tenant_id, external_knowledge_api_id)
        return {"result": "success"}, 204


class ExternalApiUseCheckApi(Resource):
    """
    外部知识API使用情况检查资源类
    检查指定的外部知识API是否正在被使用
    """

    @setup_required
    @login_required
    @account_initialization_required
    def get(self, external_knowledge_api_id):
        """
        检查外部知识API是否正在使用

        Args:
            external_knowledge_api_id (uuid): API模板ID

        Returns:
            dict: 包含使用状态和使用次数的信息
        """
        external_knowledge_api_id = str(external_knowledge_api_id)

        external_knowledge_api_is_using, count = ExternalDatasetService.external_knowledge_api_use_check(
            external_knowledge_api_id
        )
        return {"is_using": external_knowledge_api_is_using, "count": count}, 200


class ExternalDatasetCreateApi(Resource):
    """
    外部数据集创建资源类
    提供基于外部知识API创建数据集的功能
    """

    @setup_required
    @login_required
    @account_initialization_required
    def post(self):
        """
        创建外部数据集

        Request JSON:
            external_knowledge_api_id (str): 外部知识API ID，必填
            external_knowledge_id (str): 外部知识ID，必填
            name (str): 数据集名称，必填
            description (str): 数据集描述，可选
            external_retrieval_model (dict): 外部检索模型配置，可选

        Returns:
            dict: 创建成功的数据集详细信息

        Raises:
            Forbidden: 用户没有编辑权限
            DatasetNameDuplicateError: 数据集名称重复
        """
        # 验证用户是否有编辑权限
        if not current_user.is_editor:
            raise Forbidden()

        parser = reqparse.RequestParser()
        parser.add_argument("external_knowledge_api_id", type=str, required=True, nullable=False, location="json")
        parser.add_argument("external_knowledge_id", type=str, required=True, nullable=False, location="json")
        parser.add_argument(
            "name",
            nullable=False,
            required=True,
            help="name is required. Name must be between 1 to 100 characters.",
            type=_validate_name,
        )
        parser.add_argument("description", type=str, required=False, nullable=True, location="json")
        parser.add_argument("external_retrieval_model", type=dict, required=False, location="json")

        args = parser.parse_args()

        # 验证用户是否有数据集编辑权限
        if not current_user.is_dataset_editor:
            raise Forbidden()

        try:
            dataset = ExternalDatasetService.create_external_dataset(
                tenant_id=current_user.current_tenant_id,
                user_id=current_user.id,
                args=args,
            )
        except services.errors.dataset.DatasetNameDuplicateError:
            raise DatasetNameDuplicateError()

        return marshal(dataset, dataset_detail_fields), 201


class ExternalKnowledgeHitTestingApi(Resource):
    """
    外部知识命中测试资源类
    提供对外部知识库进行检索测试的功能
    """

    @setup_required
    @login_required
    @account_initialization_required
    def post(self, dataset_id):
        """
        对外部知识库进行检索测试

        Args:
            dataset_id (uuid): 数据集ID

        Request JSON:
            query (str): 查询语句
            external_retrieval_model (dict): 外部检索模型配置，可选
            metadata_filtering_conditions (dict): 元数据过滤条件，可选

        Returns:
            dict: 检索结果

        Raises:
            NotFound: 找不到指定的数据集
            Forbidden: 用户没有访问权限
            InternalServerError: 服务器内部错误
        """
        dataset_id_str = str(dataset_id)
        dataset = DatasetService.get_dataset(dataset_id_str)
        if dataset is None:
            raise NotFound("Dataset not found.")

        try:
            DatasetService.check_dataset_permission(dataset, current_user)
        except services.errors.account.NoPermissionError as e:
            raise Forbidden(str(e))

        parser = reqparse.RequestParser()
        parser.add_argument("query", type=str, location="json")
        parser.add_argument("external_retrieval_model", type=dict, required=False, location="json")
        parser.add_argument("metadata_filtering_conditions", type=dict, required=False, location="json")
        args = parser.parse_args()

        HitTestingService.hit_testing_args_check(args)

        try:
            response = HitTestingService.external_retrieve(
                dataset=dataset,
                query=args["query"],
                account=current_user,
                external_retrieval_model=args["external_retrieval_model"],
                metadata_filtering_conditions=args["metadata_filtering_conditions"],
            )

            return response
        except Exception as e:
            raise InternalServerError(str(e))


class BedrockRetrievalApi(Resource):
    """
    Bedrock检索测试资源类
    仅供内部测试使用的API
    """

    # this api is only for internal testing
    def post(self):
        """
        执行Bedrock知识检索测试

        Request JSON:
            retrieval_setting (dict): 检索设置，必填
            query (str): 查询语句，必填
            knowledge_id (str): 知识ID，必填

        Returns:
            dict: 检索结果
        """
        parser = reqparse.RequestParser()
        parser.add_argument("retrieval_setting", nullable=False, required=True, type=dict, location="json")
        parser.add_argument(
            "query",
            nullable=False,
            required=True,
            type=str,
        )
        parser.add_argument("knowledge_id", nullable=False, required=True, type=str)
        args = parser.parse_args()

        # 调用知识检索服务
        result = ExternalDatasetTestService.knowledge_retrieval(
            args["retrieval_setting"], args["query"], args["knowledge_id"]
        )
        return result, 200


api.add_resource(ExternalKnowledgeHitTestingApi, "/datasets/<uuid:dataset_id>/external-hit-testing")
api.add_resource(ExternalDatasetCreateApi, "/datasets/external")
api.add_resource(ExternalApiTemplateListApi, "/datasets/external-knowledge-api")
api.add_resource(ExternalApiTemplateApi, "/datasets/external-knowledge-api/<uuid:external_knowledge_api_id>")
api.add_resource(ExternalApiUseCheckApi, "/datasets/external-knowledge-api/<uuid:external_knowledge_api_id>/use-check")
# this api is only for internal test
api.add_resource(BedrockRetrievalApi, "/test/retrieval")
