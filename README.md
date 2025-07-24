# 手机购买事理图谱服务

基于Neo4j的手机购买推荐事理图谱查询服务，以品类为中心，支持智能剪枝和自然语言输出。

## 📁 文件结构

### 核心文件（必需）

1. **`knowledge_graph_service.py`** - 主服务文件
   - 事理图谱查询服务
   - 支持以品类为中心的关系展示
   - 基于query的智能剪枝
   - 自然语言输出格式

2. **`import_data_to_neo4j.py`** - 数据导入脚本
   - 将data.txt中的Cypher语句导入Neo4j
   - 自动数据验证和统计

3. **`test_examples.py`** - 测试示例
   - 包含多个查询示例
   - 展示不同场景的输出格式

### 配置文件

4. **`.env`** - 环境变量配置
   - Neo4j数据库连接信息
   - LLM API配置（OpenRouter + DeepSeek）

5. **`data.txt`** - 原始图谱数据
   - 手机购买决策的完整Cypher语句

6. **`requirements.txt`** & **`pyproject.toml`** - 依赖管理
   - Python依赖包列表
   - uv项目配置

## 🚀 使用方法

### 1. 数据导入
```bash
uv run python import_data_to_neo4j.py
```

### 2. 运行测试
```bash
uv run python test_examples.py
```

### 3. 直接使用服务
```bash
uv run python knowledge_graph_service.py
```

### 4. 作为模块导入
```python
from knowledge_graph_service import KnowledgeGraphService

# 创建服务实例（可配置关系度数）
kg_service = KnowledgeGraphService(max_degree=2)  # 1-3度可选

# 解析查询
parsed = await kg_service.parse_query("适合学生的3000元左右的手机")

# 查询图谱
result = kg_service.query_graph(parsed)

# 生成深度研究报告
response = await kg_service.generate_response(query, result, parsed)

# 关闭连接
kg_service.close()
```

### 5. 配置化度数测试
```bash
# 比较不同度数配置的效果
uv run python test_comprehensive.py
```

## 📊 输出格式

系统生成三层结构的深度研究报告：

```markdown
# 手机购买深度研究报告
**查询**: 适合学生的3000元左右护眼的手机

## 🎯 最相关需求匹配
**学生群体关注点**:
• 长续航、性价比...

**护眼需求相关**:
- 护眼功能: 屏幕材质, 分辨率, 刷新率, 峰值亮度...

## 📊 核心购买决策因子
**性能评估**:
• 电池、屏幕、处理器、内存、存储...

**价格考虑**:
• 性价比、预算范围、促销活动...

## 💡 隐含需求和周边考虑
**售后服务**:
• 保修政策、维修便利、客服质量...

**购买渠道**:
• 渠道可靠性、电商平台、官方渠道...

## 📋 完整关系数据
{包含三层分析结构的JSON数据}
```

## 🎯 核心特性

- **品类中心**: 以手机为起点展示购买决策维度
- **三层需求保留**: 
  - 🎯 最相关需求：与用户明确提到的需求直接匹配
  - 📊 基础需求：手机购买决策中的通用重要因子
  - 💡 隐含需求：基于用户群体和使用场景推断的潜在关注点
- **用户画像**: 根据不同用户群体突出重点关注
- **需求匹配**: 明确需求与相关因子的精准关联
- **智能剪枝**: 宽松保留策略，确保深度研究报告信息完整
- **配置化度数**: 支持1-3度关系查询，平衡信息详细程度和性能
- **自然输出**: 避免Neo4j概念，生成结构化深度研究报告

## 🛠 环境要求

- Python 3.13+
- Neo4j数据库
- uv包管理器

## 📝 支持的查询类型

- 用户群体查询：`适合学生的手机`
- 需求导向查询：`续航好的手机`、`拍照效果好的手机`
- 综合查询：`老年人用的大屏手机，预算2000元以内`
- 性能查询：`游戏性能强的手机`