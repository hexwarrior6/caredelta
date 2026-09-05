# Nightingale 反馈自评与改进计划

> 评估日期：2026-09-05。状态只代表当前仓库中可验证的实现，不代表生产级医疗系统认证。

## 1. 对方真正要求什么

这不是要求提交一页“全部完成”的勾选表，而是要求针对每个场景给出四部分：

1. `SURVIVES / PARTIAL / DOES NOT`：系统能否应对；
2. `Where`：精确到文件、行号或明确说明不存在；
3. `What breaks first`：用户最先看到的失败，以及现有实现以后可能如何失效；
4. `Build it better`：在现有作品上做有证据的改进。

评分重点是诚实、可验证的工程判断。未实现的大功能应明确写成 `DOES NOT`，说明 72 小时范围取舍和下一步，而不是临时做一个没有测试的假功能。

## 2. 面试纪要带来的选择策略

面试官已经明确：不要求做完 16 项，评估的是候选人选择了哪些高优先级问题、为什么这样选，以及能否在已有构建上形成真实迭代。核心判断标准是医疗行业断点的识别、真实临床需求挖掘、接受反馈和围绕失败状态设计。

因此本轮选择四条主线：

1. **诊所隔离的纵深防御：**错误诊所访问属于高影响、可明确测试的安全失败。
2. **LLM 可靠性与可见降级：**保留 30 秒超时和 deterministic fallback，同时让用户知道系统正在等待、何时降级、结果来自哪里。
3. **多人编辑不丢更新：**保留 `expected_version`、409 和版本历史，并诚实说明它不是完整实时协作。
4. **来源变更后的安全失效：**让依赖旧来源的 AI 高亮退出 Glance 并回到人工复核，而不是静默指向新文字。

有界学习继续作为现有亮点演示，但不扩张成未经评估的“自学习模型”。流式 ASR、diarization、完整消息投递和医学参考验证则作为后续设计，因为它们无法在短时间内形成可信的端到端证据。

## 3. 当前结论

- 当前可验证基线：后端 87 项原有测试全部通过，前端 lint 与生产构建通过。
- 本轮优先修复了场景 16：高亮现在绑定来源版本；来源改变时自动退出 Glance、进入复核队列、禁止直接重新接受，并在界面并排显示旧版与当前版本。
- 诊所隔离已下沉到 repository 查询层；即使路由中的显式 scope guard 失效，错误诊所也只能得到 404，不能取得患者记录。
- DeepSeek 保持 30 秒超时；界面会先解释正在等待，超过 8 秒提示将在 30 秒停止等待，超时后明确说明已切换本地规则。
- 修复后新增 2 项场景测试，完整测试数为 89 项。
- 最值得继续投入代码的项目：场景化测试索引、否定/修正/剂量测试，以及清晰的演示证据。
- 不应在截止前仓促实现：真正的流式 ASR、说话人分离、Hokkien 语码转换、WhatsApp/SMS 投递和医学参考库验证。这些需要真实供应商能力与端到端验证。

## 4. 场景 1–16 自评

### 1. 患者没有邮箱 — DOES NOT（真实 onboarding）

- **Where：**`backend/app/auth.py:24-43` 的演示身份不依赖邮箱，但只使用预设患者 ID 和共享式 demo key；这不是健全的真实患者进入机制。
- **What breaks first：**仅存在于 WhatsApp 对话里的新患者没有账号开通、OTP 验证、账户恢复或身份绑定路径，因此无法进入 intake、portal、summary 或 instructions。
- **Build it better：**优先设计 WhatsApp/手机号 OTP：号码归一化、一次性验证码、有效期/重试限制、患者记录绑定与恢复流程。邮箱登录可作为可选渠道，但不能作为无邮箱患者的解决方案。截止前若无法安全接入供应商，应提交流程设计而不是把 demo key 描述为完成。

### 2. 一行代码破坏诊所隔离 — SURVIVES（当前 API 路径）

- **Where：**第一层为 `backend/app/auth.py:60-62` 的显式 `require_clinic_scope`；第二层为 `backend/app/repositories.py` 的 `get_patient_record(patient_id, clinic_id)`，Memory 与 Mongo 查询都会按 clinic 过滤。所有患者路由使用带 clinic 的 repository 查询。`backend/tests/test_rbac_scope.py` 包含“故意关闭路由 guard 后仍无法跨诊所读取”的测试。
- **What breaks first：**当前即使路由 scope guard 一行出错，错误诊所也只能得到 404，暴露患者数为 0。以后若新增路由直接调用未带 `clinic_id` 的 repository 方法，或先执行写入再做 scoped fetch，防线仍可能被绕过。
- **Build it better：**代码评审规则要求所有外部请求只能使用 scoped repository 方法；继续把 clinic 条件加入写操作本身，并用 API 路由清单测试防止新增端点漏检。

### 3. 日志中的 PHI — PARTIAL

- **Where：**仓库没有自定义日志或崩溃上报 SDK；审计记录仅保存 metadata。`backend/tests/test_revision_history.py:103-130` 和 `backend/tests/test_ai_ingest.py:95-130` 验证原始正文不进入 audit log。
- **What breaks first：**无法从代码仓库证明 Railway、Vercel、MongoDB Atlas、DeepSeek 或 Volcengine 控制台没有保留请求内容；第三方保留期限也未记录。
- **Build it better：**提交前人工搜索实际部署日志和第三方 dashboard；在简报中列出每家供应商传出的字段、区域、保留期和删除方式。没有 dashboard 证据时必须写“未验证”。

### 4. 证明先脱敏后调用模型 — SURVIVES（AI ingest 路径）

- **Where：**`backend/app/routes/patients.py:344-351` 先调用 `redact_phi`，再把 `extraction_source` 交给 `extract_with_fallback`；实际模型调用位于 `backend/app/services/ai_ingest.py:351-368`。`backend/tests/test_ai_ingest.py:57-92` 用捕获 adapter 验证模型收不到姓名、电话、身份证号和邮箱。
- **What breaks first：**新增模型调用路径若绕过此服务，可能失去保证；患者聊天会发送去标识化消息和受控临床上下文，需在数据流图中单独说明。
- **Build it better：**在演示中展示 redaction preview，再运行 ingest，并打开对应自动化测试。

### 5. 第二家诊所上线 — PARTIAL

- **Where：**`Patient`、`TimelineEntry` 与签名 token 都带 `clinic_id`；MongoDB 初始化建立 `patient.clinic_id` 索引。演示身份和 seed 仍硬编码为 `clinic-syn-orchard`（`backend/app/auth.py:23-32`、`backend/app/seed.py:26-27`）。
- **What breaks first：**诊所 B 无法获得身份与 seed；若只复制身份而不强化仓库查询，隔离仍过度依赖路由层。
- **Build it better：**配置变更包括诊所目录、身份供应商、品牌与供应商凭据；数据变更包括新增 clinic/identity membership，现有核心记录已有 clinic 字段，不需要重做整个 patient schema。生产级需要 repository 层复合 scope 查询。

### 6. 一句话混合马来语、英语和福建话 — PARTIAL

- **Where：**当前 Volcengine 大模型 ASR 可处理马来语、英语和普通话输入，但仓库里还没有三语句内混合测试、语言段标记或福建话准确率证据；本地 fallback 规则仍以英文关键词为主（`backend/app/services/ai_ingest.py:250-348`）。
- **What breaks first：**福建话或快速句内切换可能被转错、音译或漏掉；即便云模型转录大致正确，英文 fallback 仍可能漏掉其中的临床事实。
- **Build it better：**准备包含马来语、英语、普通话和福建话的匿名测试集，分别评估转录及下游事实抽取。隐私增强方向可以自部署 Whisper，但必须同时说明模型版本、硬件、延迟、方言准确率、加密和保留策略；“自己部署”本身不等于识别质量更高。

### 7. 第二分钟提到药物过敏 — DOES NOT（实时检测）

- **Where：**当前录音完成或文件上传后才调用 flash ASR，然后人工确认 transcript，再进行 ingest；没有音频 chunk、partial transcript 或实时规则通道。
- **What breaks first：**临床医生在问诊结束前看不到过敏提醒。
- **Build it better：**把现有能力准确命名为 post-consult capture。实时产品需要流式 ASR、增量去重、低延迟安全规则和“暂定/已确认”状态，不能只改按钮文案冒充。

### 8. 模型挂起 45 秒 — PARTIAL

- **Where：**`backend/app/config.py:25-27` 对 DeepSeek 设置显式 30 秒超时；`backend/app/services/ai_ingest.py:351-363` 捕获 timeout 并转 deterministic fallback；前端先显示等待说明，超过 8 秒提示 30 秒后自动降级，最终明确显示 timeout 与本地规则结果。
- **What breaks first：**用户会先经历等待，但不会只看到永久 spinner；AI ingest 在 30 秒后提供规则结果。患者聊天在超时后仍返回 503，ASR 超时仍为 45 秒。
- **Build it better：**演示慢请求提示、timeout 测试和 fallback 标签。后续可为患者聊天提供经过临床审核的静态安全答复，但不要让通用规则生成医疗建议。

### 9. 模型供应商一小时 503 — PARTIAL

- **Where：**AI ingest 在模型不可用、无效 JSON、超时和 provenance 不可解析时都会走本地规则（`backend/app/services/ai_ingest.py:351-368`）；`backend/tests/test_ai_ingest.py:95-197` 验证降级结果仍有 timeline entry 和来源高亮。
- **What breaks first：**患者 AI assistant 返回 503；ASR 无本地转录 fallback。规则提取主要覆盖英文关键词，召回有限。
- **Build it better：**把“ingest 可降级”与“chat/ASR 不可降级”分开描述；不要泛称全系统离线可用。

### 10. 两人同时编辑 — PARTIAL

- **Where：**所有编辑携带 `expected_version`；MongoDB 使用原子条件更新，过期写入返回 409（`backend/app/repositories.py:495-533`、`backend/app/routes/patients.py:980-1026`）。`backend/tests/test_concurrent_edits.py:69-87` 验证同一记录的第二次旧版本写入被拒绝。
- **What breaks first：**09:15 数据库保留先成功的版本，后提交者看到冲突错误；但没有 WebSocket 实时提示、字段级合并或自动重载对比。
- **Build it better：**演示两个浏览器窗口和 409。简报明确“防止 lost update”已实现，“real-time collaborative editing”未完整实现。

### 11. 预约链接生成但未送达 — DOES NOT

- **Where：**系统只有预约相关 task 与 timeline 文本，没有 SMS、WhatsApp、邮件发送、delivery receipt 或 retry worker。
- **What breaks first：**工作人员在 CareDelta 中看到任务，但患者手机不会收到任何链接；失败假设是“创建任务等同于完成送达”。
- **Build it better：**文档诚实说明缺失。生产方案需 outbox、provider message ID、sent/delivered/failed 状态、重试与人工回拨队列。

### 12. 患者摘要中一个剂量错误 — PARTIAL

- **Where：**患者看不到 raw AI、未审核/冲突高亮或内部记录（`backend/app/services/patient_records.py:88-192`）；clinician/admin 可接受或拒绝候选（`backend/app/routes/patients.py:555-634`）。当前不存在自动生成并外发患者摘要的完整链路。
- **What breaks first：**如果未来直接复用 AI chat 文本发送，当前系统没有剂量 reference check、发送前审批对象、已发送副本版本或撤回/更正机制。
- **Build it better：**新增独立 `PatientCommunication` 状态机：draft → reviewed → approved → sent → corrected；剂量必须结构化对照来源并由临床医生确认。截止前以设计和失败边界说明为主。

### 13. 护士与患者过敏陈述冲突 — PARTIAL

- **Where：**seed 已包含青霉素冲突、Glance/review queue 和关联任务；`backend/app/services/conflict_detection.py:30-97` 生成来源绑定 conflict；冲突信号被 abstain，不会作为已确认事实进入顶部卡片。
- **What breaks first：**当前检测是范围有限的关键词启发式，只覆盖 allergy、medication 和 task；复杂否定、时间关系或同义药物可能漏检/误检。
- **Build it better：**演示现有 allergy conflict；补充 “no known allergies” 对比 “penicillin allergy” 的明确场景测试，并在简报承认规则边界。

### 14. 一个有意义的数字 — SURVIVES（importance score）

- **Where：**`backend/app/services/delta_engine.py` 根据 risk、category 与 extraction confidence 计算 0–100 importance，并设置高风险下限与 abstention；UI 同时显示风险、置信度、importance 的文字原因。相关测试位于 `backend/tests/test_delta_engine.py:48-126`。
- **What breaks first：**该分数是排序启发式，不是疾病概率，也没有前瞻性临床校准；若文案把它叫“风险概率”就会误导。
- **Build it better：**演示时明确说“排序分数，不是临床概率”；展示一个低置信度或冲突信号如何进入 review queue。

### 15. 从临床人员操作中学习 — PARTIAL

- **Where：**`backend/app/services/self_learning.py:6-83` 将事件限制在单个 signal，并把正向调整限制为 +12、负向为 -8；高风险、冲突和未解决信号不接受负向学习。测试位于 `backend/tests/test_self_learning_importance.py`。
- **What breaks first：**系统只看到已展示项的操作，没有未展示项标签或 exposure-bias 评估；当前调整按当前 actor 的事件计算，也不是完整的 clinic-scoped learning model。
- **Build it better：**可以可信地说“bounded interaction adjustment”，不能说“经过验证的自学习”。保留安全下限，并把未曝光样本审计、离线评估和诊所级版本化模型列为生产扩展。

### 16. 来源后来被编辑 — SURVIVES（本轮修复后的内部可编辑来源）

- **Where：**`backend/app/models.py:109-121` 的 provenance pointer 绑定 source entry version；`backend/app/services/patient_records.py:37-72` 比较版本和原始 span，变化后标记 stale、转为 needs review 并退出 Glance；`backend/app/routes/patients.py:555-590` 阻止重新接受 stale 高亮；前端在 `frontend/components/patient-record.tsx:1250-1280` 并排展示原版本和当前版本。测试为 `backend/tests/test_highlight_provenance.py:62-105`。
- **What breaks first：**外部源在 CareDelta 之外修改而没有同步版本事件时，系统无法知道；历史迁移数据若没有准确 source version，只能使用兼容默认值。
- **Build it better：**演示编辑 staff note 后高亮从 Glance 消失、进入 Review Queue，再点击查看旧/新版本。外部 EHR 集成以后需要 immutable source revision ID 或内容 hash。

## 5. 总体能力清单的诚实映射

| 对方能力项 | 当前状态 | 应对方式 |
|---|---|---|
| 实时问诊音频 / 嘈杂环境 ASR | DOES NOT | 当前是录完/上传后 ASR；文档说明与演示现有边界 |
| 说话人归属与 diarization | DOES NOT | 无 speaker segment 数据结构或测试 |
| 单句话 code-switching | PARTIAL | 云端大模型支持多语言，但缺三语/福建话系统测试 |
| 多语言下游处理 | PARTIAL | LLM 路径可能处理多语言；英文 fallback 尚不支持 |
| 医疗术语与剂量确认 | DOES NOT | 需要 reference service + 人工 gate |
| 不可变、版本绑定 provenance | SURVIVES（内部来源） | 本轮已实现 stale invalidation 和版本对比 |
| 否定、修正、冲突下事实提取 | PARTIAL | 有有限否定与三类冲突规则，缺系统语料评估 |
| 不丢更新的实时协同编辑 | PARTIAL | 乐观锁防丢失，但无实时同步/合并 |
| AI 重生成保留人工状态 | PARTIAL | ingest 幂等，当前没有正式 regeneration 工作流 |
| 人/患者/AI 矛盾处理 | PARTIAL | 显式 conflict + review，但规则范围有限 |
| clinician/staff/patient 不同输出 | SURVIVES（访问范围） | 服务端 RBAC 与过滤已实现；语言可读性生成未实现 |
| 诊所范围、可审计、抗疲劳的学习 | PARTIAL | 有界且可解释，尚无完整 clinic model 与 exposure evaluation |

## 6. 截止前建议顺序

### P0：必须完成

1. 将本文件中的英文状态矩阵压缩进 `docs/TECHNICAL_BRIEF.md`，确保最终仍控制在 2–3 页。
2. 为场景 1–16 建立“场景 → 测试文件/演示步骤”索引；无法自动化的场景标为 manual/unsupported。
3. 录制演示：跨诊所 404、脱敏 preview、LLM 慢请求提示与 timeout fallback、并发 409、过敏冲突、importance 解释、来源修改后 stale；无邮箱登录作为明确缺口和后续设计说明。
4. 人工核查 Railway/Vercel/第三方日志及保留策略；没有权限看到的内容写“未验证”。

### P1：低风险代码改进

1. repository 写操作继续加入 `clinic_id`，让读写两侧都有纵深隔离。
2. 增加否定/修正/剂量/三语 transcript 的失败测试，即便测试明确标记当前不支持，也能证明你理解边界。
3. 为 WhatsApp/手机号 OTP 形成可实施的身份绑定与账户恢复设计。

### P2：只写设计，不建议截止前硬做

- streaming ASR、diarization、WhatsApp/SMS delivery、医学 reference validation、真正的 clinic-scoped learning、external EHR immutable revision integration。

## 7. 提交注意事项

- 原反馈列出场景 1–16，但技术简报要求写“1–17”；建议邮件确认第 17 项是否指后面的 overall build list。
- 已确认截止时间为 **2026-09-06（星期日）12:00 SGT**；原文中的 Thursday 是笔误。
- 最终提交前重新运行：`backend/.venv/bin/python -m pytest`、`npm run lint`、`npm run build`。
