import pytest
from pydantic import ValidationError

from core.workflow.nodes.rag.entities import (
    RagNodeData, 
    RagRequest, 
    RagResponse, 
    RagTag, 
    ContextItem, 
    ResponseTag, 
    RagResponseData
)


def test_rag_node_data_default_values():
    """测试RagNodeData的默认值"""
    node_data = RagNodeData()
    
    assert node_data.title == "RAG节点"
    assert node_data.type == "rag-node"
    assert node_data.ai_flag == 1
    assert node_data.query == ""
    assert node_data.dataset_ids == []
    assert node_data.selected is False
    assert node_data.params == ""
    assert node_data.retrieval_mode == "single"
    assert node_data.user_select_scene == ""
    assert node_data.variables == []
    assert node_data.query_variable_selector == []
    assert node_data.self_build_rag is None
    assert node_data.tag == []
    assert node_data.score_threshold == 0.5
    assert node_data.search_mode == "Approx"
    assert node_data.show_image is True
    assert node_data.top_k == 3


def test_rag_node_data_with_custom_values():
    """测试RagNodeData的自定义值"""
    custom_data = {
        "title": "自定义RAG节点",
        "desc": "这是一个自定义的RAG节点",
        "query": "自定义查询",
        "dataset_ids": ["dataset1", "dataset2"],
        "score_threshold": 0.7,
        "search_mode": "Exact",
        "show_image": False,
        "top_k": 5,
        "tag": [{
            "province_tag": "广东省",
            "scene_tag": "教育",
            "specialty_tag": "计算机"
        }]
    }
    
    node_data = RagNodeData(**custom_data)
    
    assert node_data.title == "自定义RAG节点"
    assert node_data.desc == "这是一个自定义的RAG节点"
    assert node_data.query == "自定义查询"
    assert node_data.dataset_ids == ["dataset1", "dataset2"]
    assert node_data.score_threshold == 0.7
    assert node_data.search_mode == "Exact"
    assert node_data.show_image is False
    assert node_data.top_k == 5
    assert len(node_data.tag) == 1
    assert node_data.tag[0].province_tag == "广东省"
    assert node_data.tag[0].scene_tag == "教育"
    assert node_data.tag[0].specialty_tag == "计算机"


def test_rag_node_data_validation_error():
    """测试RagNodeData的验证错误"""
    # score_threshold应该是浮点数
    invalid_data = {
        "score_threshold": "not_a_float"
    }
    
    with pytest.raises(ValidationError):
        RagNodeData(**invalid_data)


def test_rag_request_creation():
    """测试RagRequest的创建"""
    request = RagRequest(
        ai_flag=1,
        query="测试请求",
        score_threshold=0.6,
        search_mode="Fuzzy",
        show_image=True,
        top_k=10,
        tag=[RagTag(province_tag="北京市")]
    )
    
    assert request.ai_flag == 1
    assert request.query == "测试请求"
    assert request.score_threshold == 0.6
    assert request.search_mode == "Fuzzy"
    assert request.show_image is True
    assert request.top_k == 10
    assert len(request.tag) == 1
    assert request.tag[0].province_tag == "北京市"


def test_rag_response_parsing():
    """测试RagResponse的解析"""
    response_data = {
        "code": "0",
        "status": "SUCCESS",
        "msg": "请求成功",
        "data": {
            "context": [
                {
                    "doc_name": "测试文档",
                    "text": "测试内容",
                    "url": "http://example.com"
                }
            ],
            "query": "测试查询",
            "tag": [
                {
                    "province_tag": "上海市",
                    "scene_tag": "金融",
                    "specialty_tag": "经济"
                }
            ]
        }
    }
    
    response = RagResponse(**response_data)
    
    assert response.code == "0"
    assert response.status == "SUCCESS"
    assert response.msg == "请求成功"
    assert response.data is not None
    assert len(response.data.context) == 1
    assert response.data.context[0].doc_name == "测试文档"
    assert response.data.context[0].text == "测试内容"
    assert response.data.query == "测试查询"
    assert len(response.data.tag) == 1
    assert response.data.tag[0].province_tag == "上海市"
    assert response.data.tag[0].scene_tag == "金融"
    assert response.data.tag[0].specialty_tag == "经济"


def test_context_item_optional_fields():
    """测试ContextItem的可选字段"""
    # 只设置必要字段
    item1 = ContextItem()
    assert item1.doc_name == ""
    assert item1.text == ""
    assert item1.img_url == ""
    assert item1.url == ""
    
    # 设置部分字段
    item2 = ContextItem(
        text="只有文本内容",
        img_url="http://example.com/image.jpg"
    )
    assert item2.text == "只有文本内容"
    assert item2.img_url == "http://example.com/image.jpg"
    assert item2.doc_name == ""
    assert item2.url == ""


def test_response_tag_required_fields():
    """测试ResponseTag的必填字段"""
    # 缺少必填字段应该抛出验证错误
    with pytest.raises(ValidationError):
        ResponseTag()
    
    # 只设置一个必填字段也应该抛出错误
    with pytest.raises(ValidationError):
        ResponseTag(province_tag="广东省")
    
    # 正确设置所有必填字段
    tag = ResponseTag(
        province_tag="广东省",
        scene_tag="教育",
        specialty_tag="计算机"
    )
    assert tag.province_tag == "广东省"
    assert tag.scene_tag == "教育"
    assert tag.specialty_tag == "计算机"