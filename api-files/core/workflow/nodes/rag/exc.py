from core.workflow.nodes.base.exc import BaseNodeError


class RagNodeError(BaseNodeError):
    """
    RAG节点异常基类
    """
    pass


class RagRequestError(RagNodeError):
    """
    RAG请求异常
    """
    pass


class RagResponseError(RagNodeError):
    """
    RAG响应异常
    """
    pass


class RagConfigurationError(RagNodeError):
    """
    RAG配置异常
    """
    pass