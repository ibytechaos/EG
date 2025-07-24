#!/usr/bin/env python3
"""
Neo4j数据导入脚本
将data.txt中的Cypher语句导入到Neo4j数据库中
"""

import os
import sys
import logging
from neo4j import GraphDatabase
from typing import List, Optional
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Neo4jImporter:
    """Neo4j数据导入器"""
    
    def __init__(self, uri: str = "bolt://localhost:7687", 
                 username: str = "neo4j", password: str = "password"):
        """
        初始化Neo4j连接
        
        Args:
            uri: Neo4j连接URI
            username: 用户名
            password: 密码
        """
        self.uri = uri
        self.username = username
        self.password = password
        self.driver = None
        
    def connect(self) -> bool:
        """建立数据库连接"""
        try:
            self.driver = GraphDatabase.driver(
                self.uri, 
                auth=(self.username, self.password)
            )
            # 测试连接
            with self.driver.session() as session:
                result = session.run("RETURN 1 as test")
                test_value = result.single()["test"]
                if test_value == 1:
                    logger.info("成功连接到Neo4j数据库")
                    return True
                else:
                    logger.error("数据库连接测试失败")
                    return False
        except Exception as e:
            logger.error(f"连接Neo4j失败: {e}")
            return False
    
    def close(self):
        """关闭数据库连接"""
        if self.driver:
            self.driver.close()
            logger.info("已关闭数据库连接")
    
    def clear_database(self) -> bool:
        """清空数据库"""
        try:
            with self.driver.session() as session:
                # 删除所有关系
                session.run("MATCH ()-[r]-() DELETE r")
                # 删除所有节点
                session.run("MATCH (n) DELETE n")
                logger.info("已清空数据库")
                return True
        except Exception as e:
            logger.error(f"清空数据库失败: {e}")
            return False
    
    def read_cypher_file(self, file_path: str) -> List[str]:
        """
        读取Cypher文件并解析语句
        
        Args:
            file_path: 文件路径
            
        Returns:
            Cypher语句列表
        """
        statements = []
        current_statement = ""
        
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                for line in file:
                    line = line.strip()
                    
                    # 跳过空行和注释行
                    if not line or line.startswith('//'):
                        continue
                    
                    # 累积语句
                    current_statement += line + " "
                    
                    # 如果以分号结尾，则认为是一个完整的语句
                    if line.endswith(';'):
                        # 移除末尾的分号和多余空格
                        statement = current_statement.strip().rstrip(';')
                        if statement:
                            statements.append(statement)
                        current_statement = ""
                
                # 处理最后一个语句（如果没有分号结尾）
                if current_statement.strip():
                    statement = current_statement.strip()
                    statements.append(statement)
                    
        except FileNotFoundError:
            logger.error(f"文件不存在: {file_path}")
            return []
        except Exception as e:
            logger.error(f"读取文件失败: {e}")
            return []
        
        logger.info(f"从文件中读取了 {len(statements)} 条Cypher语句")
        return statements
    
    def execute_statement(self, statement: str) -> bool:
        """
        执行单个Cypher语句
        
        Args:
            statement: Cypher语句
            
        Returns:
            执行是否成功
        """
        try:
            with self.driver.session() as session:
                result = session.run(statement)
                # 消费结果以确保语句完全执行
                result.consume()
                return True
        except Exception as e:
            logger.error(f"执行语句失败: {statement[:50]}... 错误: {e}")
            return False
    
    def import_statements(self, statements: List[str], batch_size: int = 10) -> bool:
        """
        批量导入Cypher语句
        
        Args:
            statements: Cypher语句列表
            batch_size: 批处理大小
            
        Returns:
            导入是否成功
        """
        total_statements = len(statements)
        success_count = 0
        
        logger.info(f"开始导入 {total_statements} 条语句...")
        
        for i in range(0, total_statements, batch_size):
            batch = statements[i:i + batch_size]
            logger.info(f"处理批次 {i//batch_size + 1}/{(total_statements + batch_size - 1)//batch_size}")
            
            for j, statement in enumerate(batch):
                if self.execute_statement(statement):
                    success_count += 1
                    if (success_count) % 20 == 0:
                        logger.info(f"已成功导入 {success_count}/{total_statements} 条语句")
                else:
                    logger.warning(f"第 {i + j + 1} 条语句执行失败")
        
        logger.info(f"导入完成: {success_count}/{total_statements} 条语句成功")
        return success_count == total_statements
    
    def verify_import(self) -> dict:
        """
        验证导入结果
        
        Returns:
            包含统计信息的字典
        """
        stats = {}
        
        try:
            with self.driver.session() as session:
                # 统计节点数量
                result = session.run("MATCH (n) RETURN count(n) as node_count")
                stats['total_nodes'] = result.single()["node_count"]
                
                # 统计关系数量
                result = session.run("MATCH ()-[r]-() RETURN count(r) as rel_count")
                stats['total_relationships'] = result.single()["rel_count"]
                
                # 统计各类型节点数量
                result = session.run("""
                    MATCH (n) 
                    RETURN labels(n) as labels, count(n) as count 
                    ORDER BY count DESC
                """)
                node_types = {}
                for record in result:
                    labels = record["labels"]
                    count = record["count"]
                    label_str = ":".join(sorted(labels)) if labels else "无标签"
                    node_types[label_str] = count
                stats['node_types'] = node_types
                
                # 统计各类型关系数量
                result = session.run("""
                    MATCH ()-[r]-() 
                    RETURN type(r) as rel_type, count(r) as count 
                    ORDER BY count DESC
                """)
                rel_types = {}
                for record in result:
                    rel_type = record["rel_type"]
                    count = record["count"]
                    rel_types[rel_type] = count
                stats['relationship_types'] = rel_types
                
        except Exception as e:
            logger.error(f"验证导入结果失败: {e}")
            return {}
        
        return stats
    
    def print_statistics(self, stats: dict):
        """打印统计信息"""
        if not stats:
            logger.error("无法获取统计信息")
            return
        
        print("\n" + "="*50)
        print("Neo4j数据库导入统计")
        print("="*50)
        print(f"总节点数: {stats.get('total_nodes', 0)}")
        print(f"总关系数: {stats.get('total_relationships', 0)}")
        
        print(f"\n节点类型分布:")
        node_types = stats.get('node_types', {})
        for label, count in node_types.items():
            print(f"  {label}: {count}")
        
        print(f"\n关系类型分布:")
        rel_types = stats.get('relationship_types', {})
        for rel_type, count in rel_types.items():
            print(f"  {rel_type}: {count}")
        print("="*50)


def main():
    """主函数"""
    # 从环境变量读取配置
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
    DATA_FILE = os.path.join(os.path.dirname(__file__), "data.txt")
    
    logger.info(f"连接配置: URI={NEO4J_URI}, 用户名={NEO4J_USERNAME}")
    
    # 检查数据文件是否存在
    if not os.path.exists(DATA_FILE):
        logger.error(f"数据文件不存在: {DATA_FILE}")
        sys.exit(1)
    
    # 创建导入器实例
    importer = Neo4jImporter(NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD)
    
    try:
        # 连接数据库
        if not importer.connect():
            logger.error("无法连接到Neo4j数据库，请检查连接配置")
            sys.exit(1)
        
        # 清空数据库
        logger.info("清空现有数据库...")
        if not importer.clear_database():
            logger.error("清空数据库失败")
            sys.exit(1)
        
        # 读取Cypher语句
        statements = importer.read_cypher_file(DATA_FILE)
        if not statements:
            logger.error("没有读取到有效的Cypher语句")
            sys.exit(1)
        
        # 导入数据
        success = importer.import_statements(statements)
        
        if success:
            logger.info("数据导入成功!")
        else:
            logger.warning("部分语句导入失败，请检查日志")
        
        # 验证并显示统计信息
        stats = importer.verify_import()
        importer.print_statistics(stats)
        
    except KeyboardInterrupt:
        logger.info("用户中断操作")
    except Exception as e:
        logger.error(f"导入过程中出现错误: {e}")
    finally:
        importer.close()


if __name__ == "__main__":
    main()