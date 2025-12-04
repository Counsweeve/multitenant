from enum import StrEnum


class CreatorUserRole(StrEnum):
    ACCOUNT = "account"
    END_USER = "end_user"


class UserFrom(StrEnum):
    ACCOUNT = "account"
    END_USER = "end-user"


class WorkflowRunTriggeredFrom(StrEnum):
    DEBUGGING = "debugging"
    APP_RUN = "app-run"


class DraftVariableType(StrEnum):
    # node means that the correspond variable
    NODE = "node"
    SYS = "sys"
    CONVERSATION = "conversation"


class MessageStatus(StrEnum):
    """
    Message Status Enum
    """

    NORMAL = "normal"
    ERROR = "error"

class OperationActionType(StrEnum):
    """操作类型枚举"""
    # 工作流相关
    WORKFLOW_CREATE = "workflow_create"
    WORKFLOW_UPDATE = "workflow_update"
    WORKFLOW_DELETE = "workflow_delete"
    WORKFLOW_CLONE = "workflow_clone"
    WORKFLOW_PUBLISH = "workflow_publish"
    WORKFLOW_UNPUBLISH = "workflow_unpublish"

    # Agent相关
    AGENT_CREATE = "agent_create"
    AGENT_UPDATE = "agent_update"
    AGENT_DELETE = "agent_delete"
    AGENT_CLONE = "agent_clone"

    # 查询相关
    SQUARE_QUERY = "square_query"
    KNOWLEDGE_QUERY = "knowledge_query"
    DATASET_QUERY = "dataset_query"

    # 用户管理
    USER_CREATE = "user_create"
    USER_UPDATE = "user_update"
    USER_DELETE = "user_delete"
    USER_ROLE_ASSIGN = "user_role_assign"

    # 系统管理
    SYSTEM_CONFIG_UPDATE = "system_config_update"
    PERMISSION_UPDATE = "permission_update"

    # 其他
    LOGIN = "login"
    LOGOUT = "logout"
    FILE_UPLOAD = "file_upload"
    FILE_DELETE = "file_delete"

    SYSTEM_OPERATION_LOG_ACTION_TYPES_LIST = "system_operation_log_action_types_list"

    @classmethod
    def get_action_name(cls, action: str) -> str:
        """获取操作类型的中文名称"""
        action_names = {
            cls.WORKFLOW_CREATE: "创建工作流",
            cls.WORKFLOW_UPDATE: "修改工作流",
            cls.WORKFLOW_DELETE: "删除工作流",
            cls.WORKFLOW_CLONE: "克隆工作流",
            cls.WORKFLOW_PUBLISH: "发布工作流",
            cls.WORKFLOW_UNPUBLISH: "取消发布工作流",
            cls.AGENT_CREATE: "创建Agent",
            cls.AGENT_UPDATE: "修改Agent",
            cls.AGENT_DELETE: "删除Agent",
            cls.AGENT_CLONE: "克隆Agent",
            cls.SQUARE_QUERY: "广场查询",
            cls.KNOWLEDGE_QUERY: "知识库查询",
            cls.DATASET_QUERY: "数据集查询",
            cls.USER_CREATE: "创建用户",
            cls.USER_UPDATE: "修改用户",
            cls.USER_DELETE: "删除用户",
            cls.USER_ROLE_ASSIGN: "分配角色",
            cls.SYSTEM_CONFIG_UPDATE: "更新系统配置",
            cls.PERMISSION_UPDATE: "更新权限",
            cls.LOGIN: "登录",
            cls.LOGOUT: "登出",
            cls.FILE_UPLOAD: "上传文件",
            cls.FILE_DELETE: "删除文件",
        }
        return action_names.get(action, action)
