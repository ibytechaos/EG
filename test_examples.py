#!/usr/bin/env python3
"""
简洁的知识图谱测试工具 - 指定查询和深度即可
"""

import asyncio
from knowledge_graph_service import KnowledgeGraphService

async def test_query(query: str, degree: int):
    """测试指定查询和深度的知识图谱服务
    
    Args:
        query: 用户查询语句
        degree: 关系深度 (1-3)
    """
    
    print(f"\n{'='*80}")
    print(f"🔍 测试查询: {query}")
    print(f"🔗 关系深度: {degree}度")
    print('='*80)
    
    kg_service = KnowledgeGraphService(max_degree=degree)
    
    try:
        # === 第1步：解析查询 ===
        print("\n📋 第1步：LLM解析用户查询")
        parsed_query = await kg_service.parse_query(query)
        print("✅ 解析成功，提取到以下信息:")
        for key, value in parsed_query.items():
            if value:
                print(f"  • {key}: {value}")
        
        # === 第2步：图谱查询 ===
        print(f"\n🗄️ 第2步：Neo4j图谱查询 ({degree}度关系)")
        query_result = kg_service.query_graph(parsed_query)
        print(f"✅ 查询完成: 找到 {len(query_result.nodes)} 个节点, {len(query_result.relations)} 个关系")
        
        # === 第3步：智能剪枝 ===
        print("\n✂️ 第3步：智能剪枝 (三层需求保留)")
        all_relations = kg_service._organize_relations_by_category(query_result.relations)
        relevant_relations = await kg_service._prune_relations(query, all_relations, parsed_query)
        print(f"✅ 剪枝完成: 从 {len(all_relations)} 类减少到 {len(relevant_relations)} 类")
        print(f"  保留的类别: {list(relevant_relations.keys())}")
        
        # === 第4步：生成报告 ===
        print("\n📝 第4步：生成深度研究报告")
        response = await kg_service.generate_response(query, query_result, parsed_query)
        print(f"✅ 报告生成完成: 总长度 {len(response)} 字符")
        
        # === 最终结果 ===
        print(f"\n{'='*60}")
        print(f"📊 最终结果 ({degree}度关系)")
        print('='*60)
        print(response)
        
        # === 统计信息 ===
        print(f"\n{'='*60}")  
        print("📈 统计信息")
        print('='*60)
        print(f"关系深度: {degree}度")
        print(f"原始数据: {len(query_result.nodes)}节点, {len(query_result.relations)}关系")
        print(f"剪枝结果: {len(relevant_relations)}类别")
        print(f"报告长度: {len(response)}字符")
        
        # 统计各层信息分布
        lines = response.split('\n')
        most_relevant = len([line for line in lines if '🎯' in line])
        core_factors = len([line for line in lines if '📊' in line])  
        implicit = len([line for line in lines if '💡' in line])
        print(f"信息分层: 最相关{most_relevant}项, 核心因子{core_factors}项, 隐含需求{implicit}项")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        kg_service.close()
        print("\n🔒 数据库连接已关闭")

if __name__ == "__main__":
    # ========== 配置区域 ==========
    # 在这里修改你想测试的查询和深度
    TEST_QUERY = "适合学生的3000元左右护眼的手机"
    TEST_DEGREE = 3  # 1, 2, 或 3
    # =============================
    
    asyncio.run(test_query(TEST_QUERY, TEST_DEGREE))