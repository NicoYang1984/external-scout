# LazyMind 当前能力地图与机会搜索矩阵

本文件用于生态扫描、issue 匹配和本地评论草稿。它把 LazyMind 的产品表达转换为可核验的能力、外部痛点和接入动作。仓库代码会变化；每次使用具体能力时，应重新打开列出的关键证据，并记录检查日期与 commit。路径均相对于 LazyMind 仓库根目录。

## 一、判断原则

### 证据等级

按下列顺序判断，不把宣传语直接当成产品事实：

1. **实现并有测试**：存在当前实现和相关自动测试，可作为 `existing` 的主要证据。
2. **实现或可运行包存在**：存在工作流、集成包或产品路径，但未完成本轮端到端验证；通常可标 `existing`，证据等级保持 `source_reviewed` 或 `verification_pending`。
3. **当前文档明确描述**：README 或集成文档描述当前行为，但源码证据尚未核对；只能作为辅助证据。
4. **宣传案例或标题**：只能帮助形成搜索词，不能单独证明速度、质量、兼容性或安装体验。
5. **Roadmap/计划**：不得标为当前能力。

对外建议中必须区分：已经验证的能力、从源码推断的适配、需要对照实验的效果。不得把“有对应工作流”写成“在任何输入下都能稳定产生高质量结果”。

### LazyMind 的核心定位

LazyMind 是面向知识密集型工作的 AI Skill Runtime。它把知识、Skill、工具、状态机、人工确认和 Artifact 组合成可执行、可恢复、可审阅的任务，让 Agent 从一次性回答继续推进到可编辑交付物。

匹配机会时重点看四件事：

- 对方是否已经有 Agent、Skill、Prompt 或脚本，但缺少稳定的运行和交付层。
- 任务是否包含多个阶段、中间产物、人工判断、失败恢复或版本追踪。
- LazyMind 是否已有对应 Workflow、通用运行时或已支持宿主集成。
- 接入是否只需安装、导入、配置、模板化或薄适配。

## 二、平台级能力

### 1. 从回答推进到完整交付

**产品行为**

- 把复杂任务拆成有输入、输出、条件和验收标准的步骤。
- 连续完成资料整理、规划、生成、审阅和最终交付。
- 每个阶段产出 Artifact，而不是只把内容留在聊天消息中。
- 对失败步骤单独重试或回退，保留已经完成的结果。

**适合寻找的痛点**

- Agent 给了建议，但用户仍需手工整理成报告、PPT、PRD 或文件。
- 长任务中断后必须从头开始。
- 多阶段 Prompt 靠人工复制粘贴衔接。
- Agent 宣称完成，但没有可检查的产物和验收依据。
- 执行过程中看不到进度，只能等待最终回答。

**搜索词**

`long-running agent`、`workflow resume`、`agent retry`、`checkpoint`、`human in the loop`、`artifact`、`deliverable`、`agent progress`、`proof of done`、`manual copy paste between agents`。

**证据入口**

- `README.CN.md`：“交付结果，而不只是回复消息”。
- `docs/workflow-format.md`：状态、步骤、输入输出、转移和验收标准。
- `algorithm/lazymind/workflow_toolkit.py`。
- `tests/algorithm/test_workflow_toolkit.py`。

**接入方式**

- 将现有 Skill 或多段 Prompt 转为 Workflow。
- 把关键中间结果声明为 Artifact。
- 在高风险或主观节点加入人工审批。
- 为失败步骤配置重试、恢复或回退路径。

### 2. 可观测状态机、人工审批与恢复

**产品行为**

- 展示当前步骤、可执行步骤和工作流状态。
- 在关键节点等待用户审阅；用户可以继续、停止、重试或回退。
- 将运行状态和产物持久化，使长任务能够恢复。
- 外部 Agent 需要遵守 Core 授权，不能绕过审批节点。

**适合寻找的痛点**

- 自动化流程缺少人工 gate、stop rule 或 escalation。
- 重试会覆盖旧结果，无法比较不同版本。
- 多 Agent 任务没有清晰依赖关系或完成条件。
- 用户无法修改中间结论，只能让 Agent 整体重做。
- Agent 在等待人类输入时仍擅自向后执行。

**搜索词**

`approval gate`、`review checkpoint`、`pause resume`、`rewind`、`retry failed step`、`human approval`、`agent state machine`、`workflow recovery`、`artifact dependency`。

**证据入口**

- `backend/core/workflow/`。
- `algorithm/lazymind/workflow_toolkit.py`。
- `tests/algorithm/test_workflow_toolkit.py`。
- `integrations/workflow-agent-core/`。

**边界**

- 不将通用 Workflow 状态机描述为任意多个外部 Agent 之间已经实现的共享状态协议。
- Git worktree 冲突、代码合并和外部任务调度需要单独验证；有 Artifact 依赖不等于已解决代码冲突。

### 3. 可编辑 Artifact、版本与局部修改

**产品行为**

- 保存文本、图片、文件和 JSON 等结构化产物。
- 在审批节点预览和直接修改中间结果。
- 保留版本记录和 Diff，并从选定版本继续执行。
- 支持面向具体 Artifact 或选区的修改，而不是把整项任务全部重做。

**适合寻找的痛点**

- AI 输出只能复制出来再人工编辑。
- 用户只想改一页、一段、一个元素，却被迫重新生成全部内容。
- 没有版本记录，无法知道 Agent 修改了什么。
- 多阶段任务无法确认下游使用了哪一版上游结果。

**搜索词**

`editable artifact`、`partial edit`、`regenerate one slide`、`version diff`、`artifact revision`、`selective rewrite`、`review generated output`。

**证据入口**

- `README.CN.md` 中 Artifact 工作台和版本 Diff。
- `backend/core/workflow/executor/artifact_sink.go`。
- `backend/core/workflow/productstate/`。
- `tests/algorithm/test_workflow_toolkit.py` 中 Artifact 读写接口。

### 4. Skill 安装、执行与 Workflow 化

**产品行为**

- 从公开 GitHub 仓库或仓库子目录安装 Skill。
- 运行 Skill 中的说明、references 和 scripts。
- 把专家方法或现有 Skill 转换为可检查、可调整、可发布的 Workflow。
- 对工作流进行诊断、版本化、发布和回滚。

**适合寻找的痛点**

- Skill 在一次性 Agent 对话中表现不稳定，缺少明确阶段与验收。
- Skill 依赖人类在多个 Prompt 之间手工接力。
- Skill 有脚本和参考资料，但安装、输入绑定或产物交付不清晰。
- 团队无法检查 Skill 每一步做了什么，也无法对中间结果审批。

**搜索词**

`agent skill unreliable`、`skill execution`、`skill dependency`、`skill orchestration`、`SKILL.md workflow`、`agent skill install`、`skill output artifact`。

**证据入口**

- `tests/algorithm/test_github_skill_install.py`。
- `backend/core/skillv2/sourceurl/github_test.go`。
- `tests/algorithm/test_skill_install_execute_flow.py`。
- `backend/core/workflow/conversion_handlers.go`。
- `README.CN.md`：“把专家经验封装成可复用工作流”。

**轻量适配标准**

- 重排 Skill 包目录、增加清单、补输入声明或包装脚本通常可算 `easy_extension`。
- 若必须增加新的核心执行协议、宿主生命周期、数据模型或权限系统，则是 `needs_product_work`。

### 5. 知识库、检索与引用

**产品行为**

- 接入本地目录、对象存储、飞书、Notion 等资料源。
- 解析文档和 PDF，并支持 OCR、Embedding、混合检索和重排。
- 回答和产物可以保留对原始文档的引用。
- 在文档预览中围绕选区、知识切片或当前文档继续追问。

**适合寻找的痛点**

- Agent 每次运行都要重新上传相同资料。
- 研究、投标或产品分析缺少来源追溯。
- 长文档、扫描 PDF、内部资料无法稳定进入 Agent 上下文。
- 生成内容有结论但没有引用，团队无法复核。
- 外部 Agent 已能编码或执行，但缺少组织知识。

**搜索词**

`agent knowledge base`、`RAG citations`、`source traceability`、`PDF OCR agent`、`document grounding`、`internal knowledge agent`、`hybrid retrieval`。

**证据入口**

- `README.CN.md` 中知识底座、知识助手和文档追问章节。
- `algorithm/lazymind/` 中知识和检索实现；使用时进一步定位当前入口。
- `tests/evo/test_evaluation_evidence.py` 等证据与知识约束测试。

**边界**

- 数据源、OCR 引擎和部署方式可能依赖环境配置。未实际运行前不要承诺任意格式、任意规模或绝对检索准确率。

### 6. 外部 Agent 插件与同一任务续跑

**产品行为**

- 外部 Agent 可通过 MCP 调用 LazyMind 的 Workflow、Skill、知识库和云文档。
- Codex 插件支持工作流启动、状态读取、Artifact 审阅，以及 Continue、Resume、Retry、Rewind 等生命周期动作。
- DeepSeek Harness 通过专用适配器展示 Workflow，并遵守 Core 的审批、执行授权和产物发布规则。
- 用户可在熟悉的 Agent 对话中使用 LazyMind 的能力，同时在面板查看步骤和结果。

**适合寻找的痛点**

- Codex 或 DeepSeek Harness 能执行任务，但复杂交付需要预览、审批和可编辑产物。
- 外部 Agent 缺少持久知识、Workflow 状态或失败恢复。
- 用户必须离开原会话，重新搭建材料和上下文。
- 插件只能提供工具调用，不能展示长任务的进度和中间结果。

**搜索词**

`Codex plugin workflow`、`MCP workflow UI`、`agent approval panel`、`agent artifact preview`、`DeepSeek Harness plugin`、`external agent resume`、`MCP long running task`。

**证据入口**

- `integrations/codex-workflow/README.md` 和 `integrations/codex-workflow/`。
- `integrations/dsh-workflow/README.md` 和 `integrations/dsh-workflow/`。
- `integrations/workflow-agent-core/`。
- `README.CN.md`：“让外部 Agent 使用同一套知识与能力”。

**宿主支持边界**

- Codex 和 DeepSeek Harness 有明确集成实现，可按各自文档判断。
- README 提到 Cursor、WorkBuddy、TRAE Work 等外部 Agent，但为这些宿主提出具体接入建议前，必须找到当前仓库中的对应实现或完成真实验证。
- 不把某一宿主的 Continue、Resume、Retry、Rewind 生命周期能力自动外推给其他宿主。
- “一键安装”只用于对应文档已经证明的连接路径；不得写成所有 Agent 都可双击安装。

### 7. 能力中心和低门槛复用

**产品行为**

- 按场景、能力类型和技术标签发现 Skill 与 Workflow。
- 展示能力说明、执行步骤、示例输入和结果预览。
- 从模板填入自己的需求和素材后启动任务。
- 精选能力与可运行 Skill 绑定，并在首次使用时按需安装。

**适合寻找的痛点**

- 开源 Skill 很多，但普通用户不知道如何选择和填写输入。
- 仓库有高质量 Prompt/Skill，却缺少产品化入口、案例和预览。
- 用户需要安装说明、模板和结果样例才能成功运行。

**搜索词**

`skill discovery`、`skill marketplace`、`agent template gallery`、`example input`、`skill onboarding`、`one click skill install`。

**证据入口**

- `README.CN.md`：“从能力中心发现开箱即用的场景”。
- 对应能力中心前端和 Skill 安装实现；使用时按具体候选进一步定位。

### 8. 评测驱动的持续改进

**产品行为**

- 收集 badcase，对策略进行评测、诊断和 A/B Test。
- 将可审核的偏好、术语和反馈带入后续任务。
- 在验证后部署改进，并保留回滚能力。

**适合寻找的痛点**

- Skill 偶尔成功但稳定性差，没有重复实验。
- Prompt 更新只凭主观感觉，没有基线和回归测试。
- 团队无法沉淀用户纠正和失败样本。

**搜索词**

`agent eval`、`skill benchmark`、`prompt regression`、`badcase`、`A/B test prompt`、`agent reliability`、`evaluation harness`。

**证据入口**

- `README.CN.md` 中“质量改进”和“AI 成长引擎”。
- `evo/`、`tests/evo/` 及对应评测实现；提出具体方案前确认当前入口和可运行范围。

## 三、已经产品化的交付场景

### 9. PPT：从需求到可局部修改的演示文稿

**可做什么**

- 补齐主题、页数、受众、视觉风格等必要输入。
- 使用用户输入、上传文件、LazyMind 知识库、Web 搜索和 AI 配图作为素材。
- 生成并允许修改资料、大纲、逐页计划、页面内容和演讲稿。
- 调整页面顺序，批量移动或删除页面。
- 对单页文字、元素、前景图、背景和局部样式发出自然语言修改要求。
- 导出 PDF、图片版 PPTX 和包含可编辑元素的 PPTX；具体格式以当前运行结果为准。

**适合寻找的痛点**

- “AI 做 PPT 有明显 AI 味”，需要大量人工重排和改写。
- 生成 PPT 时只能盲等，无法先确认资料和大纲。
- 修改一页导致整套幻灯片重做。
- Agent 能写大纲，但无法形成可编辑、可导出的成稿。
- 现有 PPT Skill 有输出，却没有演讲稿、引用或页面级编辑。

**搜索词**

`AI slides edit`、`PPT agent`、`presentation workflow`、`regenerate single slide`、`editable PPTX`、`slide outline approval`、`speaker notes AI`、`AI presentation layout`。

**证据入口**

- `workflows/ppt-workflow/workflow.yaml`。
- `workflows/ppt-workflow/scenario/state.yml`。
- `workflows/ppt-workflow/scripts/tools.py`。
- `workflows/ppt-workflow/scripts/tests/test_partial_edit.py`。
- `workflows/ppt-workflow/scripts/tests/test_style_flow.py`。
- `README.CN.md`：“从想法到可编辑演示文稿”。

**验证指标**

- 是否在生成前完成需求和大纲确认。
- 是否能只修改指定页或元素。
- 是否保留未受影响页面。
- 导出文件能否正常打开，文字、图片、图形和演讲稿是否符合目标。
- 与原 Skill 相比，人工修改次数和整套重生成次数是否下降。

### 10. AI Image、梗图与动态表情

**可做什么**

- 理解图像需求、收集参考、形成和修改生成 Prompt。
- 生成或编辑图片，并保留过程产物。
- 支持静态 meme、动态 GIF 表情和多项表情包等路线；以当前工作流配置和模型能力为准。
- 用户不满意时可基于已有结果继续修改，而不是重新描述全部上下文。

**适合寻找的痛点**

- 图像 Skill 缺少参考图、Prompt 和成品之间的可追溯过程。
- 生成结果不满意时只能整体重来。
- 制作成套表情包时角色、风格或文本不一致。
- 动图生成、格式转换和交付分散在多个脚本中。

**搜索词**

`sticker generator agent`、`animated GIF workflow`、`meme pack`、`consistent character images`、`image generation approval`、`edit generated image`。

**证据入口**

- `workflows/image-workflow-v2/workflow.yaml`。
- `workflows/image-workflow-v2/scenario/state.yml`。
- `workflows/image-workflow-v2/scripts/`。
- `tests/algorithm/chat/test_image_workflow_v2_baoyu.py`。
- `tests/algorithm/chat/test_image_workflow_v2_tools.py`。
- `tests/algorithm/chat/workflows/test_image_workflow_v2_contract.py`。

**边界**

- “1 分钟完成”属于特定案例表现。没有同输入、模型、机器和网络条件下的计时记录，不把它写成通用保证。

### 11. 产品方向、竞品、方案、PRD、原型与研发交付

**可做什么**

- 从模糊产品目标开始追问必要信息，也能从用户指定的中间阶段进入。
- 在同一产品项目中分阶段生成产品方向、竞品与生态位、产品方案、PRD、交互原型、方案评审和研发交付文档。
- 保留阶段之间的精确版本关系、证据缺口、关键决定和用户授权。
- 支持对已有阶段正文进行修订，继续沿用未受影响的材料和结论。
- 同步交付 HTML 与 Markdown，并对内容和质量评估分别版本化。

**适合寻找的痛点**

- 产品经理需要在多个 Agent/模板之间搬运上下文。
- 从想法到 PRD 的各阶段互相脱节，竞品结论不能追溯。
- 生成的 PRD 看似完整，但关键业务判断是模型编造的。
- 产品方案改动后，原型和研发交付文档无法基于准确版本更新。
- 开源产品 Skill 只覆盖一个阶段，缺少连续交付和审阅。

**搜索词**

`product manager agent`、`idea to PRD`、`competitive analysis workflow`、`product design skill`、`interactive prototype agent`、`PRD review`、`product handoff`、`multi-stage product workflow`。

**证据入口**

- `workflows/product_solution_delivery/workflow.yaml`。
- `workflows/product_solution_delivery/scenario/scenario.md`。
- `workflows/product_solution_delivery/scenario/state.yml`。
- `workflows/product_solution_delivery/scripts/`。
- `workflows/product_solution_delivery/SOURCE.md`。

**边界**

- 不声称代替组织审批、用户研究、付费资料访问、生产代码开发、技术架构或研发排期。
- 缺少事实时应保留缺口，不能为了生成“完整全案”而编造依据。

### 12. 调研、评审与学术研究

**可做什么**

- 组合内部知识与外部来源，形成可追溯报告。
- 把研究过程拆为检索、筛选、对比、综合、审阅与导出。
- 对学术任务保存研究参数、引用和手稿产物。

**适合寻找的痛点**

- Deep Research 输出缺少内部资料，或引用无法追溯。
- 系统综述 Skill 有方法但执行链过长，容易漏步骤。
- 多个研究 Agent 产生重复、冲突或无法合并的证据。
- 研究报告生成后缺少人工复核和可编辑交付。

**搜索词**

`research agent citations`、`systematic review skill`、`evidence synthesis agent`、`literature review workflow`、`research artifact`、`source verification`。

**证据入口**

- `workflows/academic_research_pipeline/`。
- `README.CN.md` 中“调研与评审”。
- 知识库、引用和 Artifact 相关实现。

### 13. AI Writer 与知识型文档

**可做什么**

- 整理素材、生成大纲、分章节写作、修改和终审。
- 保留可编辑文档与版本，而不是只产生一次性消息。
- 其他工作流可以复用 Writer 完成结构化长文档交付。

**适合寻找的痛点**

- 长文生成前后结构不一致。
- 修改一个章节导致全文漂移。
- 写作 Skill 缺少大纲审批、版本和引用。
- 其他垂直 Skill 已有领域方法，却缺少可靠文档生产层。

**搜索词**

`long form writing agent`、`outline approval`、`section rewrite`、`document artifact`、`AI writer workflow`、`citation aware writing`。

**证据入口**

- `workflows/writer-workflow/`。
- `README.CN.md` 中 AI Writer 场景。
- `workflows/product_solution_delivery/scripts/writer_bridge.py` 展示其他场景对 Writer 的复用。

### 14. 投标与专业方案写作

**可做什么**

- 将投标或技术方案任务组织为可执行工作流。
- 使用知识资料、结构化步骤和可编辑产物支撑专业交付。

**适合寻找的痛点**

- 标书内容依赖大量内部资料和重复模板。
- 生成文本缺少证据、审核节点和最终文件整理。
- 团队在不同项目中反复搭建同一套写作流程。

**搜索词**

`proposal writing agent`、`RFP response workflow`、`bid document AI`、`technical proposal skill`、`proposal knowledge base`。

**证据入口**

- `workflows/bid_tech_proposal_writer/`。
- 使用前检查该工作流的当前输入、输出和测试覆盖，不从目录名推断完整能力。

## 四、宣传主题如何转成检索方向

| 宣传主题 | 应解释为的当前能力 | 优先寻找的问题 | 不应直接声称 |
| --- | --- | --- | --- |
| “让 AI 从给出答案走到完成交付” | 状态机、Artifact、审批、恢复和文件交付 | Agent 只回复文本、长任务中断、没有 proof-of-done | 所有任务都能无人值守完成 |
| “AI 干完活，怎么加班的还是我” | 中间结果可改、局部重跑、版本与模板复用 | 人工复制整理、全量返工、不可编辑结果 | 完全消除人工审核 |
| “把 AI Agent 请进工作流” | 外部 Agent 调用 LazyMind Workflow/Skill/知识 | Agent 有工具但缺少流程、状态和审批 | 任意 Agent 已经零代码兼容 |
| “动态表情包只花 1 分钟” | 图片、GIF、表情包路线和迭代修改 | 图像流程分散、风格不一致、修改成本高 | 普遍固定耗时 1 分钟 |
| “AI PPT 摆脱人工反复修改” | 大纲确认、页面级修改、局部重跑、可编辑导出 | AI 味、盲等、整套重做、PPTX 不可编辑 | 首次生成永远无需人工修改 |
| “给 DeepSeek Harness 接插件” | 已实现的 DSH 适配和 Workflow 面板 | DSH 缺少复杂交付的审阅和恢复层 | 其他 Harness 自动获得同等能力 |
| “一个想法跑出产品全案” | 七阶段产品工作流和精确阶段衔接 | idea→PRD→prototype 断裂、版本混乱 | 替代用户研究与组织决策 |
| “Codex 做 PPT 不再盲等” | Codex 插件、PPT Workflow、进度与 Artifact 审阅 | Codex 长任务无预览、结果难以局部改 | Codex 原生所有任务都由 LazyMind 接管 |

## 五、仓库和 issue 搜索矩阵

每轮应在下列路线中轮换，避免长期只找到“工作流”类问题：

| 路线 | 目标仓库/issue | 典型信号 | LazyMind 介入方式 |
| --- | --- | --- | --- |
| Skill 运行增强 | Agent Skills、Prompt/脚本集合 | 步骤多、依赖人工接力、输出不稳定 | 导入 Skill，转 Workflow，补 Artifact/审批 |
| 外部 Agent 增强 | Codex、DSH、MCP、Agent UI 项目 | 长任务盲等、缺状态、缺可编辑结果 | 使用已有插件或 MCP；新宿主须重新判级 |
| PPT | Slides、PPTX、presentation Agent | 难修改、整套重做、无大纲确认 | 复用 PPT Workflow 或做薄输入适配 |
| 图片与表情 | Image、meme、sticker、GIF 工具 | 多脚本拼接、风格不一致、难返修 | 复用 Image Workflow 和 Artifact 审阅 |
| 产品工作 | PM、PRD、prototype、competitive intel Skills | 阶段割裂、依据缺失、版本混乱 | 复用产品方案七阶段 Workflow |
| 研究与知识 | Deep Research、RAG、文献 Skill | 引用弱、内部资料难接入、步骤易漏 | 接知识库、引用和研究 Workflow |
| 写作和专业交付 | Writer、RFP、报告工具 | 大纲/正文割裂、修订成本高 | 复用 Writer/投标 Workflow |
| 质量与评测 | Agent eval、prompt eval 项目 | 无回归、没有 badcase 闭环 | 使用现有评测能力；先验证集成成本 |

候选发现时至少保存：命中的能力编号、原始问题链接、问题触发条件、当前 LazyMind 证据、最小接入动作、预期交付物、验证指标和排除边界。

## 六、适合推广与不适合推广的判定

### 可直接提出 LazyMind 的情况

- 对方已有 Skill/Prompt/Agent，但缺少可观测执行、审批、Artifact、恢复或最终文件交付。
- 对方问题恰好对应 LazyMind 已有 PPT、Image、产品、研究、Writer 或投标 Workflow。
- 对方使用 Codex 或 DeepSeek Harness，需求落在当前适配器已经支持的生命周期内。
- 接入仅需安装、导入、配置知识源、绑定输入或很薄的格式转换。
- 可以给出一个小型本地复现和明确验收标准。

### 只记录为产品线索的情况

- 需要为新的外部 Agent 编写完整宿主适配器。
- 需要新增跨 Agent 协议、全新权限模型、核心状态机能力或新的 Artifact 类型。
- 问题本质是对方项目中的算法 bug、崩溃、安全漏洞或性能回归。
- 只有宏观愿景相似，没有可运行路径或证据。
- 价值完全依赖尚未发布的 roadmap。

### 评论草稿的表达顺序

1. 先复述对方的具体问题和触发条件。
2. 给出不依赖 LazyMind 的最小解决思路，证明评论本身有技术价值。
3. 再说明 LazyMind 当前哪项能力可以提供可运行补充，并链接具体证据。
4. 列出对方最少需要做的接入动作和可验证结果。
5. 明确关联关系、未验证部分和限制。

不得只留下产品链接、品牌口号或“我们也支持”式评论。

## 七、当前不得外推的承诺

- 不保证 Codex 能检测用户或机器“空闲”；调度只能按用户配置的定时或手动触发。
- 不保证所有第三方 Skill 导入后都会比原生运行更好；必须经过相同输入、模型、工具权限和重复次数的对照。
- 不保证任意 Agent、IDE 或 Harness 已支持 LazyMind 完整生命周期。
- 不保证所有工作流都能无人值守完成；审批和事实确认本来就是产品能力的一部分。
- 不保证固定生成时间、零人工修改、绝对准确率或零失败。
- 不把 README 提到的方向当成已跑通集成；具体宿主和场景必须有实现或实测证据。
- 未经用户明确授权，不对外发表评论、提交 PR、安装插件或联系维护者。
