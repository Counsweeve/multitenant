import logging
from collections.abc import Mapping
from typing import Any, Optional

import httpx
from core.workflow.entities.node_entities import NodeRunResult
from core.workflow.entities.workflow_node_execution import WorkflowNodeExecutionStatus
from core.workflow.nodes.base import BaseNode
from core.workflow.nodes.enums import ErrorStrategy, NodeType
from core.workflow.utils import variable_template_parser

from .entities import (
    RagNodeData,
    RagRequest,
    RagResponse,
    RagTag,
)
from .exc import RagNodeError, RagRequestError, RagResponseError

logger = logging.getLogger(__name__)


class RagNode(BaseNode):
    """
    RAG节点类，用于处理RAG相关的工作流操作
    """
    _node_type = NodeType.RAG  # 使用RAG节点类型

    _node_data: RagNodeData

    def init_node_data(self, data: Mapping[str, Any]) -> None:
        """
        初始化节点数据
        """
        self._node_data = RagNodeData.model_validate(data)

    def _get_error_strategy(self) -> Optional[ErrorStrategy]:
        """
        获取错误处理策略
        """
        return self._node_data.error_strategy

    def _get_retry_config(self) -> dict[str, Any]:
        """
        获取重试配置
        """
        return self._node_data.retry_config

    def _get_title(self) -> str:
        """
        获取节点标题
        """
        return self._node_data.title

    def _get_description(self) -> Optional[str]:
        """
        获取节点描述
        """
        return self._node_data.desc

    def _get_default_value_dict(self) -> dict[str, Any]:
        """
        获取默认值字典
        """
        return self._node_data.default_value_dict

    def get_base_node_data(self) -> RagNodeData:
        """
        获取基础节点数据
        """
        return self._node_data

    @classmethod
    def get_default_config(cls, filters: Optional[dict[str, Any]] = None) -> dict:
        """
        获取默认配置
        """
        return {
            "type": "rag-node",
            "config": {
                "ai_flag": 1,
                "retrieval_mode": "single",
            },
            "retry_config": {
                "max_retries": 3,
                "retry_interval": 1.0,
                "retry_enabled": True,
            },
        }

    @classmethod
    def version(cls) -> str:
        """
        获取节点版本
        """
        return "1"

    def _run(self) -> NodeRunResult:
        """
        运行节点逻辑
        """
        process_data = {}
        try:
            # 构建RAG请求
            rag_request = self._build_rag_request()
            process_data["request"] = rag_request.model_dump()

            # 发送RAG请求
            response = self._send_rag_request(rag_request)
            
            # 处理响应
            if response.status != "SUCCESS":
                if self.continue_on_error or self.retry:
                    return NodeRunResult(
                        status=WorkflowNodeExecutionStatus.FAILED,
                        outputs={
                            "status": response.status,
                            "msg": response.msg,
                            "data": response.data.model_dump() if response.data else None,
                        },
                        process_data=process_data,
                        error=response.msg,
                        error_type="RagResponseError",
                    )
                raise RagResponseError(response.msg)

            # 成功响应
            return NodeRunResult(
                status=WorkflowNodeExecutionStatus.SUCCEEDED,
                outputs={
                    "status": response.status,
                    "msg": response.msg,
                    "data": response.data.model_dump() if response.data else None,
                    "context": [item.model_dump() for item in response.data.context] if response.data else [],
                },
                process_data=process_data,
            )
        except RagNodeError as e:
            logger.warning("RAG node %s failed to run: %s", self.node_id, e)
            return NodeRunResult(
                status=WorkflowNodeExecutionStatus.FAILED,
                error=str(e),
                process_data=process_data,
                error_type=type(e).__name__,
            )
        except Exception as e:
            logger.error("Unexpected error in RAG node %s: %s", self.node_id, e)
            return NodeRunResult(
                status=WorkflowNodeExecutionStatus.FAILED,
                error=f"Unexpected error: {str(e)}",
                process_data=process_data,
                error_type="UnexpectedError",
            )

    def _build_rag_request(self) -> RagRequest:
        """
        构建RAG请求对象
        """
        # 使用变量池解析查询内容
        query = self.graph_runtime_state.variable_pool.convert_template(self._node_data.query).text
        
        # 构建标签列表
        tags = []
        # 从self_build_rag中获取tag信息
        if self._node_data.self_build_rag and 'tag' in self._node_data.self_build_rag:
            tag_data_list = self._node_data.self_build_rag['tag']
            # 确保tag_data_list是一个列表
            if not isinstance(tag_data_list, list):
                tag_data_list = [tag_data_list]
            
            # 遍历标签数据列表
            for tag_data in tag_data_list:
                # 创建RagTag对象
                tag = RagTag(
                    chi_pro=self._resolve_template(tag_data.get('chi_pro') if isinstance(tag_data, dict) else None),
                    chi_scene=self._resolve_template(tag_data.get('chi_scene') if isinstance(tag_data, dict) else None),
                    chi_spe=self._resolve_template(tag_data.get('chi_spe') if isinstance(tag_data, dict) else None),
                    chi_spec=self._resolve_template(tag_data.get('chi_spec') if isinstance(tag_data, dict) and 'chi_spec' in tag_data else None),
                    province_tag=self._resolve_template(tag_data.get('province_tag') if isinstance(tag_data, dict) else None),
                    scene_tag=self._resolve_template(tag_data.get('scene_tag') if isinstance(tag_data, dict) else None),
                    specialty_tag=self._resolve_template(tag_data.get('specialty_tag') if isinstance(tag_data, dict) else None),
                )
                tags.append(tag)

        return RagRequest(
            ai_flag=self._node_data.ai_flag,
            query=query,
            score_threshold=self._node_data.score_threshold,
            search_mode=self._node_data.search_mode,
            show_image=self._node_data.show_image,
            tag=tags,
            top_k=self._node_data.top_k,
        )

    def _resolve_template(self, template: Optional[str]) -> Optional[str]:
        """
        解析模板中的变量
        """
        if not template:
            return template
        return self.graph_runtime_state.variable_pool.convert_template(template).text

    def _send_rag_request(self, rag_request: RagRequest) -> RagResponse:
        """
        发送RAG请求到指定的URL
        """
        url = "http://10.141.179.170:20028/bm/query/kg/trag"
        
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    url,
                    json=rag_request.model_dump(mode='json'),
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                
                # 解析响应
                response_data = response.json()
                return RagResponse(**response_data)
        except httpx.HTTPError as e:
            raise RagRequestError(f"HTTP request failed: {str(e)}")
        except ValueError as e:
            raise RagResponseError(f"Failed to parse response: {str(e)}")

    @classmethod
    def _extract_variable_selector_to_variable_mapping(
        cls,
        *, 
        graph_config: Mapping[str, Any],
        node_id: str,
        node_data: Mapping[str, Any],
    ) -> Mapping[str, list[str]]:
        """
        提取变量选择器到变量的映射
        """
        # 创建类型化的NodeData
        typed_node_data = RagNodeData.model_validate(node_data)

        selectors = []
        # 从查询中提取选择器
        selectors += variable_template_parser.extract_selectors_from_template(typed_node_data.query)
        
        # 从标签中提取选择器
        for tag in typed_node_data.tag:
            for field in ['chi_pro', 'chi_scene', 'chi_spe', 'chi_spec', 'province_tag', 'scene_tag', 'specialty_tag']:
                value = getattr(tag, field)
                if value:
                    selectors += variable_template_parser.extract_selectors_from_template(value)

        # 构建映射
        mapping = {}
        for selector in selectors:
            mapping[node_id + "." + selector.variable] = selector.value_selector

        return mapping