"""flow 模块：声明式测试流程编排。

分层：
  ConditionEvaluator  — 条件求值（rule/context/semantic 三级，branch 和 expect 共用）
  Expectation         — 预期数据结构 + Evaluator（judge: rule/semantic/hybrid）
  FlowNode            — 流程节点（mode: guided/autonomous/wait + branches + loop）
  FlowCase            — 用例（precondition + flow + expect + teardown）
  FlowRunner          — 执行器（DAG 遍历 + loop 回边 + 闭环校验）
  SemanticJudge       — 语义判定器（独立 LLM，与执行 LLM 隔离）
"""
