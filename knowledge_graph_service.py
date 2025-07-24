#!/usr/bin/env python3
"""
优化版事理图谱MCP服务
专注于品类中心的关系展示，避免Neo4j概念，实现智能剪枝
"""

import asyncio
import json
import logging
import os
import re
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass

from neo4j import GraphDatabase
import httpx
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class GraphNode:
    """图谱节点"""
    id: str
    name: str
    labels: List[str]
    properties: Dict[str, Any]


@dataclass
class GraphRelation:
    """图谱关系"""
    from_node: str
    to_node: str
    relation_type: str
    properties: Dict[str, Any]


@dataclass
class QueryResult:
    """查询结果"""
    nodes: List[GraphNode]
    relations: List[GraphRelation]
    context: str


class KnowledgeGraphService:
    """事理图谱服务"""
    
    def __init__(self, max_degree: int = 2):
        # 从环境变量读取Neo4j配置
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USERNAME", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        
        self.driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        
        # 从环境变量读取LLM配置
        self.llm_api_key = os.getenv("LLM_API_KEY")
        self.llm_base_url = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
        self.llm_model = os.getenv("LLM_MODEL", "deepseek/deepseek-chat-v3-0324:free")
        
        # 配置关系度数
        self.max_degree = max_degree
        logger.info(f"设置最大关系度数为: {max_degree}")
        
    def close(self):
        """关闭数据库连接"""
        if self.driver:
            self.driver.close()

    async def parse_query(self, query: str) -> Dict[str, Any]:
        """使用大模型解析用户查询，提取关键信息"""
        
        # 首先尝试大模型解析
        llm_result = await self._llm_parse_query(query)
        if llm_result:
            return llm_result
        
        # 大模型失败时降级到简单规则解析
        logger.warning("大模型解析失败，使用简单规则解析")
        return self._simple_fallback_parse(query)

    async def _llm_parse_query(self, query: str) -> Dict[str, Any]:
        """使用大模型解析查询"""
        prompt = f"""
请分析以下手机购买查询，提取关键信息。请返回JSON格式，字段必须完全按照以下格式：

查询：{query}

请返回JSON格式：
{{
    "product_category": "手机",
    "price_range": "价格范围（如：3000元左右、2000-3000元）",
    "user_groups": ["用户群体列表，如：学生、上班族、老年人、游戏玩家、摄影爱好者、商务人士"],
    "explicit_needs": ["明确提到的需求，如：续航、拍照、性能、大屏、护眼、轻薄、性价比"],
    "implicit_needs": ["可能的隐含需求，基于用户群体推断"],
    "usage_scenarios": ["使用场景，如：办公、学习、游戏、拍照"]
}}

注意：
1. 如果没有相关信息就返回空数组[]或空字符串""
2. 用户群体要准确识别：学生、上班族、老年人、游戏玩家、摄影爱好者、商务人士
3. 明确需求要从查询中直接提取
4. 隐含需求要合理推断，比如学生关注性价比和续航
5. 必须返回有效的JSON格式
"""
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                headers = {
                    "Authorization": f"Bearer {self.llm_api_key}",
                    "Content-Type": "application/json"
                }
                
                data = {
                    "model": self.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 800,
                    "temperature": 0.1
                }
                
                response = await client.post(
                    f"{self.llm_base_url}/chat/completions",
                    headers=headers,
                    json=data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    content = result["choices"][0]["message"]["content"].strip()
                    
                    # 尝试提取JSON
                    json_start = content.find('{')
                    json_end = content.rfind('}') + 1
                    if json_start >= 0 and json_end > json_start:
                        json_str = content[json_start:json_end]
                        parsed_result = json.loads(json_str)
                        
                        # 验证结果格式
                        if self._validate_parse_result(parsed_result):
                            logger.info(f"大模型解析成功: {parsed_result}")
                            return parsed_result
                        else:
                            logger.warning("大模型返回格式不正确")
                            return None
                    else:
                        logger.warning("大模型返回中未找到JSON")
                        return None
                else:
                    logger.error(f"大模型API调用失败: {response.status_code}")
                    return None
                    
        except json.JSONDecodeError as e:
            logger.error(f"大模型返回JSON解析失败: {e}")
            return None
        except Exception as e:
            logger.error(f"大模型API调用异常: {e}")
            return None

    def _validate_parse_result(self, result: Dict[str, Any]) -> bool:
        """验证解析结果格式"""
        required_fields = [
            "product_category", "price_range", "user_groups", 
            "explicit_needs", "implicit_needs", "usage_scenarios"
        ]
        
        for field in required_fields:
            if field not in result:
                logger.warning(f"缺少必需字段: {field}")
                return False
        
        # 检查数组字段
        array_fields = ["user_groups", "explicit_needs", "implicit_needs", "usage_scenarios"]
        for field in array_fields:
            if not isinstance(result[field], list):
                logger.warning(f"字段 {field} 应该是数组")
                return False
        
        return True

    def _simple_fallback_parse(self, query: str) -> Dict[str, Any]:
        """简单的降级解析（保底方案）"""
        result = {
            "product_category": "手机",
            "price_range": "",
            "user_groups": [],
            "explicit_needs": [],
            "implicit_needs": [],
            "usage_scenarios": []
        }
        
        # 简单的价格提取
        price_match = re.search(r'(\d+)元', query)
        if price_match:
            result["price_range"] = f"{price_match.group(1)}元左右"
        
        # 简单的用户群体识别
        if "学生" in query:
            result["user_groups"].append("学生")
            result["implicit_needs"].extend(["性价比", "续航"])
        if "老年" in query or "老人" in query:
            result["user_groups"].append("老年人")
            result["implicit_needs"].extend(["大屏", "简单易用"])
        if "游戏" in query:
            result["user_groups"].append("游戏玩家")
            result["implicit_needs"].extend(["性能", "散热"])
        
        # 简单的需求提取
        need_keywords = ["续航", "拍照", "性能", "大屏", "护眼", "轻薄", "性价比"]
        for keyword in need_keywords:
            if keyword in query:
                result["explicit_needs"].append(keyword)
        
        return result

    def query_graph(self, parsed_query: Dict[str, Any]) -> QueryResult:
        """查询图谱数据，以品类为中心获取相关关系"""
        
        with self.driver.session() as session:
            all_nodes = {}
            all_relations = []
            
            # 1. 首先获取手机购物决策的核心关系
            phone_relations = self._get_phone_category_relations(session)
            all_nodes.update(phone_relations['nodes'])
            all_relations.extend(phone_relations['relations'])
            
            # 2. 默认检索产品分类相关的关系
            product_category = parsed_query.get("product_category", "手机")
            if product_category:
                category_relations = self._get_product_category_relations(session, product_category)
                all_nodes.update(category_relations['nodes'])
                all_relations.extend(category_relations['relations'])
            
            # 3. 获取用户群体相关的关系
            for user_group in parsed_query.get("user_groups", []):
                user_group_name = self._map_user_group(user_group)
                if user_group_name:
                    user_relations = self._get_node_relations(session, user_group_name)
                    all_nodes.update(user_relations['nodes'])
                    all_relations.extend(user_relations['relations'])
            
            # 4. 获取明确需求相关的关系
            for need in parsed_query.get("explicit_needs", []):
                need_nodes = self._find_need_nodes(session, need)
                for need_node in need_nodes:
                    need_relations = self._get_node_relations(session, need_node)
                    all_nodes.update(need_relations['nodes'])
                    all_relations.extend(need_relations['relations'])
        
        return QueryResult(
            nodes=list(all_nodes.values()),
            relations=all_relations,
            context=""
        )
    
    def _get_phone_category_relations(self, session) -> Dict[str, Any]:
        """获取手机品类相关的核心关系"""
        nodes = {}
        relations = []
        
        # 根据度数配置调整查询限制
        limit = 30 if self.max_degree <= 2 else 50
        
        # 查询手机购物决策的主要阶段和因子
        query_cypher = f"""
        MATCH (root:Decision {{name: "手机购物决策"}})-[:INCLUDES]->(stage:Stage)-[:CONTAINS]->(factor:Factor)
        RETURN root, stage, factor
        LIMIT {limit}
        """
        
        result = session.run(query_cypher)
        
        for record in result:
            root = record["root"]
            stage = record["stage"]  
            factor = record["factor"]
            
            if root and stage and factor:
                # 添加节点
                root_node = GraphNode(
                    id=str(root.element_id),
                    name=root.get('name', ''),
                    labels=list(root.labels),
                    properties=dict(root)
                )
                stage_node = GraphNode(
                    id=str(stage.element_id),
                    name=stage.get('name', ''),
                    labels=list(stage.labels),
                    properties=dict(stage)
                )
                factor_node = GraphNode(
                    id=str(factor.element_id),
                    name=factor.get('name', ''),
                    labels=list(factor.labels),
                    properties=dict(factor)
                )
                
                nodes[root_node.id] = root_node
                nodes[stage_node.id] = stage_node
                nodes[factor_node.id] = factor_node
                
                # 添加关系
                relation1 = GraphRelation(
                    from_node="手机",
                    to_node=stage_node.name,
                    relation_type="需要关注",
                    properties={}
                )
                relation2 = GraphRelation(
                    from_node=stage_node.name,
                    to_node=factor_node.name,
                    relation_type="涉及",
                    properties={}
                )
                
                relations.extend([relation1, relation2])
        
        return {"nodes": nodes, "relations": relations}
    
    def _get_product_category_relations(self, session, product_category: str) -> Dict[str, Any]:
        """获取产品分类相关的关系"""
        nodes = {}
        relations = []
        
        # 查询与产品分类相关的所有Factor节点（如：手机相关的品牌、型号等）
        query_cypher = f"""
        MATCH (factor:Factor)
        WHERE factor.name CONTAINS '{product_category}' 
           OR factor.name IN ['品牌知名度', '品牌口碑', '技术实力', '生态系统', 
                              '处理器性能', '内存配置', '存储容量', '系统优化',
                              '价格区间', '性价比', '优惠活动', '购买时机']
        OPTIONAL MATCH (factor)-[r]-(related)
        RETURN factor, r, related
        LIMIT 50
        """
        
        result = session.run(query_cypher)
        
        for record in result:
            factor = record["factor"]
            rel = record.get("r")
            related = record.get("related")
            
            if factor:
                # 添加产品分类相关的Factor节点
                factor_node = GraphNode(
                    id=str(factor.element_id),
                    name=factor.get('name', ''),
                    labels=list(factor.labels),
                    properties=dict(factor)
                )
                nodes[factor_node.id] = factor_node
                
                # 添加相关节点和关系
                if rel and related:
                    related_node = GraphNode(
                        id=str(related.element_id),
                        name=related.get('name', ''),
                        labels=list(related.labels),
                        properties=dict(related)
                    )
                    nodes[related_node.id] = related_node
                    
                    relation = GraphRelation(
                        source=factor_node.id,
                        target=related_node.id,
                        type=rel.type,
                        properties=dict(rel)
                    )
                    relations.append(relation)
        
        return {"nodes": nodes, "relations": relations}
    
    def _get_node_relations(self, session, node_name: str) -> Dict[str, Any]:
        """获取特定节点的多度关系"""
        nodes = {}
        relations = []
        
        # 根据max_degree构建不同的查询
        if self.max_degree == 1:
            query_cypher = """
            MATCH (center {name: $node_name})-[r]-(neighbor)
            RETURN center, r, neighbor, 1 as degree
            LIMIT 10
            """
        elif self.max_degree == 2:
            query_cypher = """
            MATCH p = (center {name: $node_name})-[*1..2]-(neighbor)
            WHERE length(p) <= 2
            WITH center, relationships(p)[-1] as r, neighbor, length(p) as degree
            RETURN DISTINCT center, r, neighbor, degree
            LIMIT 15
            """
        else:  # max_degree >= 3
            query_cypher = """
            MATCH p = (center {name: $node_name})-[*1..3]-(neighbor)
            WHERE length(p) <= $max_degree
            WITH center, relationships(p)[-1] as r, neighbor, length(p) as degree
            RETURN DISTINCT center, r, neighbor, degree
            LIMIT 20
            """
        
        # 执行查询
        params = {"node_name": node_name}
        if self.max_degree >= 3:
            params["max_degree"] = self.max_degree
            
        result = session.run(query_cypher, **params)
        
        for record in result:
            center = record["center"]
            r = record["r"]
            neighbor = record["neighbor"]
            degree = record.get("degree", 1)
            
            if center is not None and r is not None and neighbor is not None:
                # 添加节点
                center_node = GraphNode(
                    id=str(center.element_id),
                    name=center.get('name', ''),
                    labels=list(center.labels), 
                    properties=dict(center)
                )
                neighbor_node = GraphNode(
                    id=str(neighbor.element_id),
                    name=neighbor.get('name', ''),
                    labels=list(neighbor.labels),
                    properties=dict(neighbor)
                )
                
                nodes[center_node.id] = center_node
                nodes[neighbor_node.id] = neighbor_node
                
                # 添加关系（包含度数信息）
                relation_name = self._simplify_relation_type(r.type)
                relation = GraphRelation(
                    from_node=center_node.name,
                    to_node=neighbor_node.name,
                    relation_type=f"{relation_name}({degree}度)",
                    properties=dict(r)
                )
                relations.append(relation)
        
        logger.info(f"节点 {node_name} 的 {self.max_degree} 度关系: {len(relations)} 个关系")
        return {"nodes": nodes, "relations": relations}
    
    def _map_user_group(self, user_group: str) -> str:
        """映射用户群体名称"""
        mapping = {
            "学生": "学生群体",
            "老年人": "老年人",
            "游戏玩家": "游戏玩家", 
            "摄影爱好者": "摄影爱好者",
            "上班族": "上班族",
            "商务人士": "商务人士"
        }
        return mapping.get(user_group, user_group)
    
    def _find_need_nodes(self, session, need: str) -> List[str]:
        """查找需求相关的节点"""
        query_cypher = """
        MATCH (n:Factor)
        WHERE n.name CONTAINS $need
        RETURN n.name as name
        LIMIT 5
        """
        
        result = session.run(query_cypher, need=need)
        return [record["name"] for record in result]
    
    def _simplify_relation_type(self, relation_type: str) -> str:
        """简化关系类型名称"""
        mapping = {
            "INCLUDES": "包含",
            "CONTAINS": "涉及", 
            "RELATES_TO": "关联",
            "REQUIRES": "需要",
            "KNOWN_FOR": "擅长",
            "TYPICALLY_INCLUDES": "通常包含"
        }
        return mapping.get(relation_type, relation_type)

    async def generate_response(self, query: str, query_result: QueryResult, 
                              parsed_query: Dict[str, Any]) -> str:
        """生成三层需求的深度研究报告"""
        
        # 1. 先获取所有关系，然后剪枝
        all_relations = self._organize_relations_by_category(query_result.relations)
        
        # 2. 基于query进行剪枝
        relevant_relations = await self._prune_relations(query, all_relations, parsed_query)
        
        # 3. 生成分层的自然语言描述
        response_parts = []
        response_parts.append(f"# 手机购买深度研究报告")
        response_parts.append(f"**查询**: {query}")
        
        # === 第一层：最相关需求 ===
        response_parts.append(f"\n## 🎯 最相关需求匹配")
        
        # 用户群体特别关注
        user_groups = parsed_query.get("user_groups", [])
        for user_group in user_groups:
            if user_group in relevant_relations:
                group_concerns = relevant_relations[user_group]
                if group_concerns:
                    response_parts.append(f"\n**{user_group}群体关注点**:")
                    for concern in group_concerns[:8]:  # 增加显示数量
                        response_parts.append(f"• {concern}")
        
        # 明确需求匹配
        explicit_needs = parsed_query.get("explicit_needs", [])
        for need in explicit_needs:
            # 寻找相关类别
            related_categories = []
            for category, items in relevant_relations.items():
                if need in category or any(need in item for item in items):
                    related_categories.append(category)
            
            if related_categories:
                response_parts.append(f"\n**{need}需求相关**:")
                for category in related_categories[:3]:  # 最多显示3个相关类别
                    if category in relevant_relations:
                        items = relevant_relations[category][:6]
                        response_parts.append(f"  - {category}: {', '.join(items)}")
        
        # === 第二层：基础购买决策因子 ===
        response_parts.append(f"\n## 📊 核心购买决策因子")
        
        core_categories = ["性能评估", "价格考虑", "外观设计", "品牌选择"]
        for category in core_categories:
            if category in relevant_relations:
                items = relevant_relations[category]
                if items:
                    response_parts.append(f"\n**{category}**:")
                    for item in items[:10]:  # 增加显示数量
                        response_parts.append(f"• {item}")
        
        # === 第三层：隐含和周边因子 ===
        response_parts.append(f"\n## 💡 隐含需求和周边考虑")
        
        # 显示其他重要类别
        other_categories = []
        shown_categories = set(core_categories + [ug for ug in user_groups if ug in relevant_relations])
        
        for category in relevant_relations:
            if category not in shown_categories and category != "手机":
                other_categories.append(category)
        
        for category in other_categories[:5]:  # 显示更多其他类别
            items = relevant_relations[category]
            if items:
                response_parts.append(f"\n**{category}**:")
                for item in items[:8]:
                    response_parts.append(f"• {item}")
        
        # === 结构化数据 ===
        response_parts.append(f"\n## 📋 完整关系数据")
        response_parts.append("```json")
        structured_data = {
            "query": query,
            "analysis_layers": {
                "most_relevant": {
                    "user_groups": user_groups,
                    "explicit_needs": explicit_needs
                },
                "core_factors": core_categories,
                "implicit_factors": other_categories[:5]
            },
            "relevant_aspects": relevant_relations
        }
        response_parts.append(json.dumps(structured_data, ensure_ascii=False, indent=2))
        response_parts.append("```")
        
        return '\n'.join(response_parts)

    def _organize_relations_by_category(self, relations: List[GraphRelation]) -> Dict[str, List[str]]:
        """按类别组织关系"""
        organized = {}
        
        for relation in relations:
            from_node = relation.from_node
            to_node = relation.to_node
            
            if from_node not in organized:
                organized[from_node] = []
            
            organized[from_node].append(to_node)
        
        return organized

    async def _prune_relations(self, query: str, all_relations: Dict[str, List[str]], 
                             parsed_query: Dict[str, Any]) -> Dict[str, List[str]]:
        """基于query智能剪枝关系"""
        
        # 先尝试使用大模型进行智能剪枝
        try:
            llm_pruned = await self._llm_prune_relations(query, all_relations, parsed_query)
            if llm_pruned:
                logger.info("使用大模型剪枝成功")
                return llm_pruned
        except Exception as e:
            logger.warning(f"大模型剪枝失败: {e}")
        
        # 降级到规则剪枝
        logger.info("使用规则剪枝")
        return self._rule_based_prune(query, all_relations, parsed_query)

    async def _llm_prune_relations(self, query: str, all_relations: Dict[str, List[str]], 
                                 parsed_query: Dict[str, Any]) -> Dict[str, List[str]]:
        """使用大模型进行智能剪枝 - 支持三层需求保留"""
        
        # 构建剪枝提示
        relations_summary = {}
        for category, items in all_relations.items():
            relations_summary[category] = items[:15]  # 增加分析的因子数量
        
        prompt = f"""
你正在为用户生成手机购买的深度研究报告，需要从事理图谱中收集全面的信息。请基于以下三个层次的需求来筛选因子：

1. **最相关需求**：与用户明确提到的需求直接匹配
2. **基础需求**：手机购买决策中的通用重要因子（性能、价格、续航、拍照等）
3. **隐含需求**：基于用户群体和使用场景推断的潜在关注点

用户查询：{query}

解析的用户需求：
- 用户群体：{parsed_query.get('user_groups', [])}
- 明确需求：{parsed_query.get('explicit_needs', [])} 
- 隐含需求：{parsed_query.get('implicit_needs', [])}
- 价格范围：{parsed_query.get('price_range', '')}
- 使用场景：{parsed_query.get('usage_scenarios', [])}

所有相关因子：
{json.dumps(relations_summary, ensure_ascii=False, indent=2)}

筛选原则（宽松保留）：
✅ **必须保留**：
- 与明确需求直接相关的因子
- 手机购买的核心决策因子（性能、价格、续航、拍照、屏幕、外观、品牌等）
- 用户群体特征相关的因子
- 使用场景相关的因子

⚠️ **谨慎保留**：
- 与查询有间接关联的因子
- 可能影响购买决策的周边因子

❌ **可以移除**：
- 与手机购买完全无关的因子
- 过于细节且不影响决策的技术参数

请返回JSON格式，每个类别保留8-12个因子（比之前更宽松）：
{{
    "类别名": ["因子1", "因子2", "...更多因子"]
}}

记住：这是为深度研究报告收集信息，宁可多保留也不要遗漏重要因子。
"""
        
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                headers = {
                    "Authorization": f"Bearer {self.llm_api_key}",
                    "Content-Type": "application/json"
                }
                
                data = {
                    "model": self.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1000,
                    "temperature": 0.2
                }
                
                response = await client.post(
                    f"{self.llm_base_url}/chat/completions",
                    headers=headers,
                    json=data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    content = result["choices"][0]["message"]["content"].strip()
                    
                    # 提取JSON
                    json_start = content.find('{')
                    json_end = content.rfind('}') + 1
                    if json_start >= 0 and json_end > json_start:
                        json_str = content[json_start:json_end]
                        pruned_result = json.loads(json_str)
                        
                        # 验证和清理结果
                        cleaned_result = {}
                        for category, items in pruned_result.items():
                            if isinstance(items, list) and items:
                                # 确保项目存在于原始数据中
                                valid_items = []
                                for item in items:
                                    if category in all_relations and item in all_relations[category]:
                                        valid_items.append(item)
                                if valid_items:
                                    cleaned_result[category] = valid_items
                        
                        return cleaned_result
                    else:
                        logger.warning("大模型剪枝返回中未找到有效JSON")
                        return None
                else:
                    logger.error(f"大模型剪枝API调用失败: {response.status_code}")
                    return None
                    
        except json.JSONDecodeError as e:
            logger.error(f"大模型剪枝JSON解析失败: {e}")
            return None
        except Exception as e:
            logger.error(f"大模型剪枝调用异常: {e}")
            return None

    def _rule_based_prune(self, query: str, all_relations: Dict[str, List[str]], 
                         parsed_query: Dict[str, Any]) -> Dict[str, List[str]]:
        """基于规则的剪枝（降级方案）- 三层需求保留策略"""
        
        # 构建三层关键词集合
        # 第一层：最相关需求
        high_priority_keywords = set()
        high_priority_keywords.update(parsed_query.get("explicit_needs", []))
        
        # 第二层：基础需求（手机购买核心因子）
        core_keywords = {
            "性能", "价格", "续航", "拍照", "屏幕", "电池", "处理器", "内存", "存储", 
            "外观", "品牌", "系统", "网络", "充电", "散热", "音质", "材质", "尺寸"
        }
        
        # 第三层：隐含需求
        context_keywords = set()
        context_keywords.update(parsed_query.get("user_groups", []))
        context_keywords.update(parsed_query.get("implicit_needs", []))
        context_keywords.update(parsed_query.get("usage_scenarios", []))
        
        pruned_relations = {}
        
        # 定义重要类别（必须保留）
        important_categories = [
            "手机", "性能评估", "价格考虑", "外观设计", "品牌选择", 
            "购买渠道", "明确需求", "用户体验", "技术参数"
        ]
        
        # 处理所有类别，使用更宽松的策略
        for category, items in all_relations.items():
            pruned_items = []
            
            # 对每个项目计算综合相关性分数
            for item in items:
                score = 0
                
                # 最相关需求匹配（权重最高）
                for keyword in high_priority_keywords:
                    if keyword in item or keyword in category:
                        score += 10
                
                # 核心购买因子匹配（权重中等）
                for keyword in core_keywords:
                    if keyword in item or keyword in category:
                        score += 5
                
                # 上下文相关匹配（权重较低）
                for keyword in context_keywords:
                    if keyword in item or keyword in category:
                        score += 3
                
                # 重要类别自动保留部分项目
                if category in important_categories:
                    score += 2
                
                # 保留策略：有任何相关性的都考虑保留
                if score > 0:
                    pruned_items.append((item, score))
            
            # 按分数排序，保留更多项目
            pruned_items.sort(key=lambda x: x[1], reverse=True)
            
            # 根据类别重要性决定保留数量
            if category in important_categories:
                max_items = 12  # 重要类别保留更多
            elif category in parsed_query.get("user_groups", []):
                max_items = 8   # 用户群体相关保留中等数量
            else:
                max_items = 6   # 其他类别保留基本数量
            
            if pruned_items:
                # 至少保留3个项目，确保基础信息完整
                min_items = min(3, len(items))
                final_count = max(min_items, min(len(pruned_items), max_items))
                pruned_relations[category] = [item for item, _ in pruned_items[:final_count]]
        
        # 确保核心决策类别不丢失
        for category in important_categories:
            if category in all_relations and category not in pruned_relations:
                # 即使没有直接匹配，也保留一些基础项目
                pruned_relations[category] = all_relations[category][:5]
        
        return pruned_relations

# 可以作为独立服务使用
if __name__ == "__main__":
    # 简单测试不同度数配置
    async def test():
        query = "适合学生的3000元左右的手机"
        degree = 3
        print(f"\n{'='*60}")
        print(f"测试 {degree} 度关系配置")
        print('='*60)
        
        kg_service = KnowledgeGraphService(max_degree=degree)
        try:
            parsed = await kg_service.parse_query(query)
            result = kg_service.query_graph(parsed)
            response = await kg_service.generate_response(query, result, parsed)
            print(f"\n{degree}度关系结果:")
            print(f"节点数: {len(result.nodes)}, 关系数: {len(result.relations)}")
            print(response[:500] + "..." if len(response) > 500 else response)
        finally:
            kg_service.close()
            
    
    asyncio.run(test())