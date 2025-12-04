from collections.abc import Sequence
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from core.workflow.nodes.base import BaseNodeData


class RagTag(BaseModel):
    """RAG节点的标签结构"""
    chi_pro: Optional[str] = Field(default="", description="中文省份")
    chi_scene: Optional[str] = Field(default="", description="中文场景")
    chi_spe: Optional[str] = Field(default="", description="中文专业")
    chi_spec: Optional[str] = Field(default="", description="中文规格")
    province_tag: Optional[str] = Field(default="", description="省份标签")
    scene_tag: Optional[str] = Field(default="", description="场景标签")
    specialty_tag: Optional[str] = Field(default="", description="专业标签")


class RagNodeData(BaseNodeData):
    """
    RAG节点数据结构
    """
    title: str = Field(default="RAG节点", description="节点标题")
    desc: Optional[str] = Field(default="", description="节点描述")
    type: str = Field(default="rag-node", description="节点类型")
    ai_flag: int = Field(default=1, description="AI标志")
    query: str = Field(default="", description="查询内容")
    dataset_ids: List[str] = Field(default_factory=list, description="数据集ID列表")
    selected: bool = Field(default=False, description="是否选中")
    params: str = Field(default="", description="参数")
    retrieval_mode: str = Field(default="single", description="检索模式")
    user_select_scene: str = Field(default="", description="用户选择场景")
    variables: List[Any] = Field(default_factory=list, description="变量列表")
    query_variable_selector: List[Any] = Field(default_factory=list, description="查询变量选择器")
    self_build_rag: Optional[Dict[str, Any]] = Field(default=None, description="自建RAG配置")
    tag: List[RagTag] = Field(default_factory=list, description="标签列表")
    score_threshold: float = Field(default=0.5, description="分数阈值")
    search_mode: str = Field(default="Approx", description="搜索模式")
    show_image: bool = Field(default=True, description="是否显示图片")
    top_k: int = Field(default=3, description="返回结果数量")


class RagRequest(BaseModel):
    """
    RAG节点请求结构
    """
    ai_flag: int
    query: str
    score_threshold: float = Field(default=0.5, description="分数阈值")
    search_mode: str = Field(default="Approx", description="搜索模式")
    show_image: bool = Field(default=True, description="是否显示图片")
    tag: List[RagTag] = Field(default_factory=list, description="标签列表")
    top_k: int = Field(default=3, description="返回结果数量")


class ContextItem(BaseModel):
    """
    上下文项结构
    """
    doc_name: Optional[str] = Field(default="", description="文档名称")
    text: Optional[str] = Field(default="", description="文本内容")
    img_url: Optional[str] = Field(default="", description="图片URL")
    url: Optional[str] = Field(default="", description="URL链接")


class ResponseTag(BaseModel):
    """
    响应标签结构
    """
    province_tag: str
    scene_tag: str
    specialty_tag: str


class RagResponseData(BaseModel):
    """
    RAG节点响应数据结构
    """
    context: List[ContextItem] = Field(default_factory=list, description="上下文列表")
    query: str = Field(default="", description="查询内容")
    tag: List[ResponseTag] = Field(default_factory=list, description="标签列表")


class RagResponse(BaseModel):
    """
    RAG节点响应结构
    """
    code: str = Field(default="", description="响应代码")
    data: Optional[RagResponseData] = Field(default=None, description="响应数据")
    msg: str = Field(default="", description="响应消息")
    status: str = Field(default="", description="响应状态")