# FACTOR SYSTEM INTEGRATION AUDIT

|模块|现状|是否复用|修改方式|
|-|-|-|-|
|Market Data|Binance/OKX public clients, MarketState, kline normalizers|是|只读复用；不做 fallback 修改|
|Feature|universe/features vectors|是|不改；factor 独立计算|
|Memory|AIExperienceMemory + ai_trade_episodes|是|factor_analysis metadata 复用|
|Research|research/ + ai_research_lab|是|research_type=factor_analysis 复用|
|LLM|llm/context.py + llm_chief/context.py|是|context 增加 factor snapshot 字段|
|Decision|ai_decision + llm_chief|否|不修改决策格式|
|Risk|risk V3 + portfolio_risk|否|不改|
|Execution|ExecutionAuthority + execution_intelligence|否|不改|
