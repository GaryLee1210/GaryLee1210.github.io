---
layout: post
title: "Jev：System One 模型与具身导航"
date:   2026-09-25
tags: [Jev, System One, VLN, Embodied Navigation, Calibration, Robotics]
categories: blog
comments: true
author: Tingde Liu
toc: true
excerpt: "TypeSafe AI 发布的 Jev 自称首个“System One 模型”：不生成文本，只对状态上的类型化问题一次性返回带校准概率的选择、评分或是非判断。本文先讲清 Jev 是什么、为什么快、如何用 RLCD 训练、独立评测说了什么；再梳理它原生不支持多模态之后社区与 arXiv 上长出的派生模型——Laya、AnyJev、Open-Jev、Laya Vision、Visual Jev、PixelJev、PlayJev 等；最后结合 ROS 2 导航 demo 与近期导航论文，讨论这一类模型在具身导航栈中的位置、已有 demo 的证据等级，以及一套可复现的 latency–accuracy–safety 评测方案。"
---

* 目录
{:toc}

## 1. 引言

过去两年，VLN 社区在“大模型该在导航里做什么”这个问题上逐渐收敛出一个共识：**不要让语言模型直接输出坐标、角度或连续控制量**，而是让它在控制器构造好的候选之间做比较，把几何、执行和安全交回确定性代码。

一旦大模型在导航栈里只剩下“在几个选项里挑一个”“判断是否该停”这类**短、频繁、有界**的判断，一个问题就变得很自然：这件事还需要一个会写文章的生成式模型吗？

2026-09-15，TypeSafe AI 发布的 **Jev** 恰好给出了另一种答案：一个**不生成任何文本**、只返回带概率的类型化决策的模型。它发布后迅速在社区引发大量复刻与派生——有人用开源模型重现它，有人给它装上视觉编码器，有人把它接进无人机和机械臂。

本文按三步展开：

1. **Jev 是什么**：接口、速度来源、训练方法、独立评测与失效模式；
2. **派生模型**：Jev 原生只收文本，社区如何复刻它、如何让它“看见”和“听见”；
3. **具身导航**：这一类 System One 模型应该放在导航栈的哪一层，已有证据有多硬，该如何验证。

<!-- more -->

## 2. Jev 是什么

### 2.1 从 System 1 / System 2 说起

“System One”一词借自 Kahneman：**系统 1** 是快速、直觉式的判断，**系统 2** 是缓慢、逐步的推理。TypeSafe 的立场是，今天的 LLM 本质上都是“系统 2 形态”——无论问题多简单，都要一个 token 一个 token 地把答案“写”出来；而软件里大量的调用其实只需要一个判断：这封邮件是不是投诉、这条工单该派给谁、这个候选动作安不安全。

TypeSafe AI 是一家位于旧金山的实验室，2026-09-15 带着 4000 万美元种子轮走出隐身状态，Jev 是其首个公开模型；创始人此前在 OpenAI 工作，参与过 ChatGPT 与 RLHF 相关工作。[TypeSafe 发布文](https://typesafe.ai/blog/introducing-system-one-models-and-jev)；[MindStudio 解读](https://www.mindstudio.ai/blog/jev-system-one-model-launch)

官方对 Jev 的一句话定义是：**前沿智能的函数调用——非结构化状态进，类型化概率决策出**。

### 2.2 接口：状态 + 类型化问题 → 有界概率决策

调用 Jev 需要两样东西：

- **`state`**：一段文本，或含文本字段的 JSON，描述“当前情况”；
- **一组类型化问题**：每个问题事先声明好答案空间。

Jev 对每个问题返回一个答案及其概率。公开的原语只有三种：[官方 Primitives](https://docs.typesafe.ai/primitives)

| 原语 | 答案空间 | 返回 | 示例 |
|---|---|---|---|
| `Choice` | 2–255 个离散选项 | 选中项、各项概率、confidence | 这条工单属于哪个部门？ |
| `Score` | 有序等级（rubric） | 等级、各级概率、confidence | 这段回复的礼貌程度是 1–5 中哪一级？ |
| `Noul` | 是 / 否 | 命题为真的概率 | 用户是否在要求退款？ |

一个请求的形态大致如下（示意，字段名以官方文档为准）：

```json
{
  "model": "jev-1.13.0",
  "state": "机器人位于走廊尽头，左侧是开着门的卧室，右侧是楼梯。指令：去二楼的书房。",
  "questions": [
    {"type": "choice", "question": "下一步应前往哪个候选？",
     "options": ["左侧卧室门口", "右侧楼梯口", "原地转身回看"]},
    {"type": "noul",  "question": "机器人是否已到达目标房间？"}
  ]
}
```

返回的是每个问题的答案与概率分布，而不是一段话。图 1 把这一次调用从输入到“代码怎么用”完整画了出来：

<div align="center">
<svg viewBox="0 0 780 420" width="100%" style="max-width:780px;font-family:sans-serif" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="jevA2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#64748b"/></marker></defs>
  <rect width="780" height="420" rx="12" fill="#f8fafc" stroke="#e2e8f0" stroke-width="1.5"/>
  <text x="390" y="28" text-anchor="middle" font-size="14" font-weight="bold" fill="#1e293b">一次 Jev 调用：输入、输出与代码分支（数值为示意）</text>
  <rect x="20" y="48" width="240" height="150" rx="8" fill="#fff7ed" stroke="#f59e0b" stroke-width="1.5"/>
  <text x="34" y="70" font-size="12" font-weight="bold" fill="#92400e">state（文本 / JSON）</text>
  <text x="34" y="94" font-size="11" fill="#78350f">位置：走廊尽头</text>
  <text x="34" y="114" font-size="11" fill="#78350f">左侧：开着门的卧室</text>
  <text x="34" y="134" font-size="11" fill="#78350f">右侧：楼梯</text>
  <text x="34" y="154" font-size="11" fill="#78350f">指令：去二楼的书房</text>
  <text x="34" y="174" font-size="11" fill="#78350f">已行进：12 m，转向 3 次</text>
  <rect x="20" y="212" width="240" height="130" rx="8" fill="#f5f3ff" stroke="#7c3aed" stroke-width="1.5"/>
  <text x="34" y="234" font-size="12" font-weight="bold" fill="#4c1d95">questions（预先声明答案空间）</text>
  <text x="34" y="260" font-size="11" fill="#5b21b6">Q1 Choice：下一步去哪个候选？</text>
  <text x="34" y="284" font-size="11" fill="#5b21b6">Q2 Score：当前风险属 1–5 哪级？</text>
  <text x="34" y="308" font-size="11" fill="#5b21b6">Q3 Noul：是否已到达目标？</text>
  <text x="34" y="330" font-size="10" fill="#7c3aed">三个问题相互独立、并行求值</text>
  <line x1="262" y1="123" x2="300" y2="180" stroke="#64748b" stroke-width="1.5" marker-end="url(#jevA2)"/>
  <line x1="262" y1="277" x2="300" y2="220" stroke="#64748b" stroke-width="1.5" marker-end="url(#jevA2)"/>
  <rect x="302" y="165" width="100" height="70" rx="10" fill="#dbeafe" stroke="#2563eb" stroke-width="2"/>
  <text x="352" y="196" text-anchor="middle" font-size="15" font-weight="bold" fill="#1e3a8a">Jev</text>
  <text x="352" y="216" text-anchor="middle" font-size="10" fill="#1e40af">一次前向</text>
  <line x1="404" y1="185" x2="438" y2="105" stroke="#64748b" stroke-width="1.5" marker-end="url(#jevA2)"/>
  <line x1="404" y1="200" x2="438" y2="215" stroke="#64748b" stroke-width="1.5" marker-end="url(#jevA2)"/>
  <line x1="404" y1="215" x2="438" y2="305" stroke="#64748b" stroke-width="1.5" marker-end="url(#jevA2)"/>
  <rect x="440" y="48" width="320" height="112" rx="8" fill="#ffffff" stroke="#3b82f6"/>
  <text x="452" y="68" font-size="12" font-weight="bold" fill="#1e40af">Q1 Choice：分布 + confidence</text>
  <text x="452" y="92" font-size="11" fill="#334155">左侧卧室门口</text>
  <rect x="560" y="82" width="23" height="13" rx="2" fill="#93c5fd"/><text x="590" y="93" font-size="10" fill="#475569">0.12</text>
  <text x="452" y="116" font-size="11" font-weight="bold" fill="#1e3a8a">右侧楼梯口</text>
  <rect x="560" y="106" width="154" height="13" rx="2" fill="#2563eb"/><text x="720" y="117" font-size="10" font-weight="bold" fill="#1e3a8a">0.81</text>
  <text x="452" y="140" font-size="11" fill="#334155">原地转身回看</text>
  <rect x="560" y="130" width="13" height="13" rx="2" fill="#93c5fd"/><text x="580" y="141" font-size="10" fill="#475569">0.07</text>
  <rect x="440" y="170" width="320" height="100" rx="8" fill="#ffffff" stroke="#3b82f6"/>
  <text x="452" y="190" font-size="12" font-weight="bold" fill="#1e40af">Q2 Score：各等级概率</text>
  <line x1="470" y1="250" x2="740" y2="250" stroke="#cbd5e1"/>
  <rect x="480" y="241" width="30" height="9" fill="#93c5fd"/><rect x="535" y="206" width="30" height="44" fill="#2563eb"/><rect x="590" y="228" width="30" height="22" fill="#93c5fd"/><rect x="645" y="243" width="30" height="7" fill="#93c5fd"/><rect x="700" y="247" width="30" height="3" fill="#93c5fd"/>
  <text x="495" y="264" text-anchor="middle" font-size="10" fill="#475569">1</text><text x="550" y="264" text-anchor="middle" font-size="10" font-weight="bold" fill="#1e3a8a">2</text><text x="605" y="264" text-anchor="middle" font-size="10" fill="#475569">3</text><text x="660" y="264" text-anchor="middle" font-size="10" fill="#475569">4</text><text x="715" y="264" text-anchor="middle" font-size="10" fill="#475569">5</text>
  <rect x="440" y="280" width="320" height="62" rx="8" fill="#ffffff" stroke="#3b82f6"/>
  <text x="452" y="300" font-size="12" font-weight="bold" fill="#1e40af">Q3 Noul：p(命题为真)</text>
  <rect x="452" y="314" width="240" height="14" rx="7" fill="#e2e8f0"/>
  <rect x="452" y="314" width="19" height="14" rx="7" fill="#2563eb"/>
  <text x="700" y="325" font-size="11" font-weight="bold" fill="#1e3a8a">0.08</text>
  <rect x="20" y="356" width="740" height="52" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="34" y="377" font-size="12" font-weight="bold" fill="#14532d">你的代码：</text>
  <text x="110" y="377" font-size="11" fill="#166534">若 p(Q1) ≥ τ 且 Q2 ≤ 2 且几何安全检查通过 → 前往右侧楼梯口；Q3 低 → 继续导航</text>
  <text x="110" y="397" font-size="11" fill="#166534">否则：回看 / 升级到 VLM / 请求人工 —— 阈值 τ 需在目标任务上用少量标注校准</text>
</svg>
<figcaption>图 1　Jev 的输出不是“一句话”，而是三组可以直接写进 if 语句的概率</figcaption>
</div>

几个设计要点：

- **同一请求中的多个问题共享同一 `state`、彼此独立、并行求值**；
- 官方建议把复杂问题拆成原子判断，再由调用方代码组合，而不是让模型自己做长链规划；
- Jev **不接受微调或 LoRA**，定制只能通过 `state` 与问题描述完成。[官方 Models](https://docs.typesafe.ai/models)

### 2.3 为什么快：不做自回归生成

LLM 回答一个选择题，至少要经历“读完输入 → 逐 token 生成答案（往往还有推理链）→ 调用方解析字符串”三步；推理模型的前两步可能长达数秒到数分钟。

Jev 的做法是 **非自回归**：读完 `state` 与问题后，**一次性并行地**给出所有问题的类型化输出，不存在“生成”这一步，也就不需要解析。官方称之为“并行采样（parallel sampling）”。

<div align="center">
<svg viewBox="0 0 760 300" width="100%" style="max-width:760px;font-family:sans-serif" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="jevA1" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#64748b"/></marker></defs>
  <rect width="760" height="300" rx="12" fill="#f8fafc" stroke="#e2e8f0" stroke-width="1.5"/>
  <text x="380" y="28" text-anchor="middle" font-size="14" font-weight="bold" fill="#1e293b">同一组选择题：自回归 LLM vs. Jev</text>
  <text x="24" y="92" font-size="13" font-weight="bold" fill="#475569">自回归 LLM</text>
  <rect x="130" y="68" width="105" height="40" rx="6" fill="#e2e8f0" stroke="#94a3b8"/>
  <text x="182" y="93" text-anchor="middle" font-size="11" fill="#334155">读入 prompt</text>
  <rect x="245" y="68" width="245" height="40" rx="6" fill="#f1f5f9" stroke="#94a3b8" stroke-dasharray="4"/>
  <g fill="#cbd5e1"><rect x="255" y="80" width="14" height="16" rx="2"/><rect x="274" y="80" width="14" height="16" rx="2"/><rect x="293" y="80" width="14" height="16" rx="2"/><rect x="312" y="80" width="14" height="16" rx="2"/><rect x="331" y="80" width="14" height="16" rx="2"/><rect x="350" y="80" width="14" height="16" rx="2"/></g>
  <text x="425" y="93" text-anchor="middle" font-size="11" fill="#475569">思考 token × N</text>
  <rect x="500" y="68" width="80" height="40" rx="6" fill="#e2e8f0" stroke="#94a3b8"/>
  <text x="540" y="93" text-anchor="middle" font-size="11" fill="#334155">答案 token</text>
  <rect x="590" y="68" width="150" height="40" rx="6" fill="#fef2f2" stroke="#ef4444" stroke-dasharray="4"/>
  <text x="665" y="86" text-anchor="middle" font-size="11" fill="#991b1b">解析字符串</text>
  <text x="665" y="101" text-anchor="middle" font-size="10" fill="#b91c1c">可能格式错误、需重试</text>
  <text x="435" y="130" text-anchor="middle" font-size="11" fill="#64748b">每个 token 都要一次前向，严格串行；问题越多、推理越长，越慢</text>
  <line x1="20" y1="148" x2="740" y2="148" stroke="#e2e8f0"/>
  <text x="24" y="204" font-size="13" font-weight="bold" fill="#1d4ed8">Jev</text>
  <rect x="130" y="168" width="140" height="64" rx="6" fill="#dbeafe" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="200" y="195" text-anchor="middle" font-size="11" fill="#1e3a8a">读入 state + 全部问题</text>
  <text x="200" y="212" text-anchor="middle" font-size="11" font-weight="bold" fill="#1e3a8a">一次前向</text>
  <line x1="272" y1="200" x2="300" y2="200" stroke="#64748b" stroke-width="1.5" marker-end="url(#jevA1)"/>
  <rect x="305" y="166" width="150" height="20" rx="4" fill="#eff6ff" stroke="#3b82f6"/>
  <text x="380" y="180" text-anchor="middle" font-size="10" fill="#1e40af">Q1 Choice → 分布</text>
  <rect x="305" y="190" width="150" height="20" rx="4" fill="#eff6ff" stroke="#3b82f6"/>
  <text x="380" y="204" text-anchor="middle" font-size="10" fill="#1e40af">Q2 Score → 分布</text>
  <rect x="305" y="214" width="150" height="20" rx="4" fill="#eff6ff" stroke="#3b82f6"/>
  <text x="380" y="228" text-anchor="middle" font-size="10" fill="#1e40af">Q3 Noul → 概率</text>
  <line x1="458" y1="200" x2="490" y2="200" stroke="#64748b" stroke-width="1.5" marker-end="url(#jevA1)"/>
  <rect x="495" y="176" width="150" height="48" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="570" y="197" text-anchor="middle" font-size="11" fill="#14532d">代码直接使用</text>
  <text x="570" y="213" text-anchor="middle" font-size="10" fill="#166534">无需解析，类型必然合法</text>
  <text x="435" y="252" text-anchor="middle" font-size="11" fill="#64748b">所有问题共享同一 state，并行给出类型化结果；没有“生成”这一步</text>
  <rect x="120" y="264" width="520" height="24" rx="6" fill="#fff7ed" stroke="#fdba74"/>
  <text x="380" y="280" text-anchor="middle" font-size="11" fill="#9a3412">延迟：前沿 LLM 3–329 s（厂商口径）· Jev 70–500 ms · 第三方测得服务端约 105 ms</text>
</svg>
<figcaption>图 2　Jev 省掉的不是“思考”，而是“把答案写出来”这整条串行链路</figcaption>
</div>

据此，官方宣称：

- 端到端响应 **70–500 ms**，而前沿 LLM 为 3–329 s，对“System One 形态的问题”快 **40–200 倍**；
- 因为没有逐 token 生成，**输出免费**，只按输入计费。

[TypeSafe 发布文](https://typesafe.ai/blog/introducing-system-one-models-and-jev)

官方没有公开网络结构与参数规模。但从接口形态和社区复刻（见第 3 节）来看，一种合理的理解是：**一个编码器读入“状态 + 问题 + 候选”，一次前向传播后由类型化输出头直接给出每个问题在其答案空间上的分布**——这是推测，而非官方描述。

### 2.4 怎么训练：RLCD 与“校准”

官方披露的训练信息只有一个名字和一个目标：

- 方法叫 **RLCD（Reinforcement Learning for Calibrated Decisions）**，被刻意拿来与 LLM 的 RLHF 对照；
- 目标是 **校准的决策**：概率“针对真实结果优化，以反映不确定性”，即“认识论上诚实的概率”。[官方 System One](https://docs.typesafe.ai/concepts/system-one)

这里的关键词是**校准（calibration）**。RLHF 优化的是“人类更喜欢哪个回答”，这会让模型倾向于说得自信、说得好听；RLCD 优化的是“说 70% 的时候是否真有七成是对的”。衡量校准常用两个指标。设有 $n$ 个预测，按置信度分成 $M$ 个桶：

$$
\mathrm{ECE} = \sum_{m=1}^{M} \frac{|B_m|}{n}\,\bigl|\mathrm{acc}(B_m) - \mathrm{conf}(B_m)\bigr|
$$

$$
\mathrm{Brier} = \frac{1}{n}\sum_{i=1}^{n} (p_i - y_i)^2
$$

ECE 衡量“置信度与实际正确率的平均偏差”，Brier 分数是概率预测的均方误差，两者都越低越好。把每个置信度桶的实际正确率画出来，就得到**可靠性图（reliability diagram）**：

<div align="center">
<svg viewBox="0 0 660 390" width="100%" style="max-width:660px;font-family:sans-serif" xmlns="http://www.w3.org/2000/svg">
  <rect width="660" height="390" rx="12" fill="#f8fafc" stroke="#e2e8f0" stroke-width="1.5"/>
  <text x="330" y="26" text-anchor="middle" font-size="14" font-weight="bold" fill="#1e293b">可靠性图：什么叫“校准”（示意）</text>
  <rect x="70" y="50" width="340" height="280" fill="#ffffff" stroke="#cbd5e1"/>
  <g stroke="#f1f5f9"><line x1="138" y1="50" x2="138" y2="330"/><line x1="206" y1="50" x2="206" y2="330"/><line x1="274" y1="50" x2="274" y2="330"/><line x1="342" y1="50" x2="342" y2="330"/><line x1="70" y1="274" x2="410" y2="274"/><line x1="70" y1="218" x2="410" y2="218"/><line x1="70" y1="162" x2="410" y2="162"/><line x1="70" y1="106" x2="410" y2="106"/></g>
  <line x1="70" y1="330" x2="410" y2="50" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="6 4"/>
  <g stroke="#ef4444" stroke-width="1.2" stroke-dasharray="3 3"><line x1="189" y1="268" x2="189" y2="232"/><line x1="257" y1="232" x2="257" y2="176"/><line x1="325" y1="190" x2="325" y2="120"/><line x1="393" y1="145" x2="393" y2="64"/></g>
  <polyline points="121,302 189,268 257,232 325,190 393,145" fill="none" stroke="#ef4444" stroke-width="2.5"/>
  <g fill="#ef4444"><circle cx="121" cy="302" r="4"/><circle cx="189" cy="268" r="4"/><circle cx="257" cy="232" r="4"/><circle cx="325" cy="190" r="4"/><circle cx="393" cy="145" r="4"/></g>
  <polyline points="121,291 189,229 257,182 325,114 393,70" fill="none" stroke="#2563eb" stroke-width="2.5"/>
  <g fill="#2563eb"><circle cx="121" cy="291" r="4"/><circle cx="189" cy="229" r="4"/><circle cx="257" cy="182" r="4"/><circle cx="325" cy="114" r="4"/><circle cx="393" cy="70" r="4"/></g>
  <g font-size="10" fill="#64748b" text-anchor="middle"><text x="70" y="346">0</text><text x="138" y="346">0.2</text><text x="206" y="346">0.4</text><text x="274" y="346">0.6</text><text x="342" y="346">0.8</text><text x="410" y="346">1.0</text></g>
  <g font-size="10" fill="#64748b" text-anchor="end"><text x="62" y="334">0</text><text x="62" y="278">0.2</text><text x="62" y="222">0.4</text><text x="62" y="166">0.6</text><text x="62" y="110">0.8</text><text x="62" y="54">1.0</text></g>
  <text x="240" y="370" text-anchor="middle" font-size="12" fill="#334155">模型给出的置信度</text>
  <text x="24" y="190" text-anchor="middle" font-size="12" fill="#334155" transform="rotate(-90 24 190)">该桶的实际正确率</text>
  <line x1="430" y1="70" x2="460" y2="70" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="6 4"/>
  <text x="468" y="74" font-size="11" fill="#334155">理想校准：说 70% 就对 70%</text>
  <line x1="430" y1="108" x2="460" y2="108" stroke="#ef4444" stroke-width="2.5"/>
  <text x="468" y="104" font-size="11" fill="#991b1b">过度自信：置信度高于</text>
  <text x="468" y="120" font-size="11" fill="#991b1b">实际正确率（RLHF 常见）</text>
  <line x1="430" y1="150" x2="460" y2="150" stroke="#2563eb" stroke-width="2.5"/>
  <text x="468" y="146" font-size="11" fill="#1e3a8a">校准良好：贴着对角线</text>
  <text x="468" y="162" font-size="11" fill="#1e3a8a">（RLCD 的优化目标）</text>
  <line x1="438" y1="190" x2="438" y2="214" stroke="#ef4444" stroke-width="1.2" stroke-dasharray="3 3"/>
  <text x="450" y="200" font-size="11" fill="#334155">红色虚线长度按样本数</text>
  <text x="450" y="216" font-size="11" fill="#334155">加权平均 ≈ ECE</text>
  <rect x="428" y="238" width="216" height="88" rx="8" fill="#fff7ed" stroke="#fdba74"/>
  <text x="440" y="258" font-size="11" font-weight="bold" fill="#9a3412">对机器人意味着什么</text>
  <text x="440" y="278" font-size="11" fill="#9a3412">只有校准好，“p ≥ 0.9 才执行”</text>
  <text x="440" y="296" font-size="11" fill="#9a3412">这类阈值规则才有意义；</text>
  <text x="440" y="314" font-size="11" fill="#9a3412">换任务就要重新画这张图</text>
</svg>
<figcaption>图 3　RLHF 优化“回答让人满意”，RLCD 优化“概率与现实对得上”</figcaption>
</div>

能让模型在最优时如实报告概率的奖励函数叫**严格恰当评分规则（strictly proper scoring rule）**，对数损失与 Brier 分数都属于此类。

官方**没有**公开的内容包括：基座模型、参数规模、训练数据、RLCD 的奖励设计与优化算法、权重、技术报告。发布文只说明训练数据不是为了让自家模型占优而专门构造的。因此，“新架构 + 新训练法”目前应视为**厂商技术主张**，外部无法复现。

一个有用的参照来自开源复刻 Laya（见 3.2）：它把 RLCD 具体实现为“**以严格恰当评分规则为奖励、用 GRPO 式策略梯度训练**”，再做分题型的温度缩放校准。这是社区对 RLCD 的一种可运行解读，不代表 TypeSafe 的实际做法，但足以说明这条路线在工程上是走得通的。[Laya](https://github.com/NandhaKishorM/laya)

### 2.5 规格与价格

| 项 | 值 |
|---|---|
| 版本 | `jev-1.13.0`（别名 `jev-latest`、`jev-preview` 当前均指向它） |
| 上下文 | 请求总计 64k；`state + 最长问题` 不超过 32k |
| 模态 | **仅文本**，不支持图像、音频、视频 |
| 语言 | 英文最佳；中日韩等语言可处理但效果不及英文 |
| 价格 | 输入 $0.042 / 百万 token，输出免费 |
| 限流 | 250k tokens/s，1,200 requests/min |

[官方 Models](https://docs.typesafe.ai/models)

两个工程细节值得记住：别名会随版本移动，**若在机器人系统中使用校准阈值，必须固定版本号并记录每次返回的 model ID**；中文效果不及英文，**中文指令场景需要单独评测**。

### 2.6 证据：厂商数字与独立评测

**厂商数字。** 官网最醒目的 **193.6× faster / 444.6× cheaper** 来自公司自己的四个业务 workflow eval，示例汇总为 TypeSafe 0.114 s / $0.000081 对比 LLM 8.566 s / $0.013880。[TypeSafe 首页](https://typesafe.ai/) 官方同时坦率列出了偏差：这是现实收益的**高端值**；workflow 由自家团队制作；参考标签不是人类真值，而是 GPT-6 Astra 与 Claude Fable 5.1 高思考输出的平均；对比 LLM 经过 TypeSafe 自己的结构化适配器；演示特意采用**短、密集**的 `state`，这种输入让 Jev 占优。[Workflow eval 方法](https://evals.typesafe.ai/)

**独立评测。** 发布十天内社区已出现一批第三方评测，结论并不一致，恰好说明“Jev 好不好”高度依赖任务：

| 评测 | 任务 | 报告结果 |
|---|---|---|
| [八天独立测试](https://dev.to/aws-builders/jev-after-eight-days-of-independent-tests-level-with-mid-price-llms-behind-the-frontier-1c60) | 多个公开基准，共 23,703 次调用 | 均值 72.5%，与中档 LLM 持平、落后前沿 6.5–11.5 分；零非法输出；相同请求重复调用有 1.33–2.2% 答案改变；**仅交换选项名称就改变 32.5% 的答案**；开箱 ECE 中位 0.071，50–300 条标注拟合温度后降 74%；服务端延迟约 105 ms |
| [Convex Decision Evals](https://github.com/get-convex/convex-evals) | 108 道四选一平台问答，打乱选项跑 3 次 | 84.6% ± 0.7，中位 199 ms；每轮 $0.0088，对比最强模型 $1.59 |
| [Jev vs Laya 对照](https://anth.us/blog/jev-vs-laya/) | 600 条留出情感样本，同标签同问题 | Jev 76.8% / ECE 0.151，Laya 72.2% / ECE 0.107；用同样 140 条标注微调 Laya 后达 89.6% |
| [Nautilus 校准研究](https://github.com/chunxiaoxx/nautilus-compass) | 240 道带种子的问题，公开原始数据 | 准确率 92.2%，Brier 0.048，ECE 0.041 |
| [Laya 对比](https://github.com/NandhaKishorM/laya) | 2,000 个类型化决策 | Jev 准确率 0.727，ECE 0.246；77 类高基数选择上 Jev 0.870 |
| [jev-orderby-bench](https://github.com/yodablocks/jev-orderby-bench) | 用 Score 做排序 | 20 Newsgroups 通过；306 对人工标注购物相关性中 6 项检验挂 4 项 |
| [Jev Does Not Play Dice](https://github.com/KantaHayashiAI/jev-does-not-play-dice) | 已知概率的骰子 / 硬币 / 转盘 | 概率输出与真实随机分布明显不符 |

可以读出四点：

1. **速度优势基本被独立复现**：服务端约 0.1 s，含网络的中位延迟多在 0.2–0.3 s；
2. **准确率是“中档 LLM”水平**：与 Kimi K3、MiniMax M3、DeepSeek V4.1 Flash 一档，落后前沿模型；
3. **校准因任务而异**：ECE 从 0.04 到 0.25 不等，而且误差方向随数据改变；少量标注拟合温度是必要步骤，“calibrated”不能默认成立；
4. **对表面形式敏感**：选项改名改变三分之一答案、非英文掉分、在缺乏支撑证据时仍给出高置信——这对导航中“候选怎么命名”有直接影响。另外，它的概率是“判断置信度”，不是世界模型：面对真正的随机事件，它不会给出正确的分布。

### 2.7 学术论文中的 Jev

发布两周内，arXiv 上已出现一批把 Jev 当作“System One 决策层”的论文，它们共同的结构是**Jev 做高频有界判断，强 LLM 只在需要时出场**：

| 论文 | 领域 | Jev 负责什么 | 主要结果 |
|---|---|---|---|
| [Jev-Mem](https://arxiv.org/abs/2609.23986)（UT Dallas） | Agent 长期记忆 | 记忆类型判定、关系构建、查询路由、证据充分性判断与自适应停止；强 LLM 只做最终回答 | LoCoMo 上 LLM-judge 0.777（最佳基线 0.700）；构建时间快 6.6 倍；查询延迟降 36.7% |
| [REFLEX](https://arxiv.org/abs/2609.26532) | LLM Agent 选择性控制 | 动作选择；置信度低或需要生成时升级到强模型 | 100 个任务成功率 95%，强模型调用减少 72.7%；但当廉价生成式级联已很准时优势有限 |
| [渗透测试 Harness](https://arxiv.org/abs/2609.28940) | 自动化渗透测试 | 漏洞确认、严重度重评、子 Agent 剪枝、确认循环（SPRT 边界） | Jev p50 236–276 ms，Laya 33–40 ms，LLM 1.5–3 s；单次运行，作者承认收益部分来自 harness 修复 |

渗透测试这篇有两点值得借鉴到机器人上：

- **加性架构**：System One 层只能降低置信度或标记复核，**不能推翻确定性校验器的否决**——最坏情况等同于没有它。这与导航里“安全盾可否决决策头”是同一原则；
- 它把 RLCD 明确解读为“**以 Brier 分数等恰当评分规则为奖励**，校准由构造保证”，与 RLHF、RLAIF 对照，并提出用校验器判决作为训练信号的 RLHV 变体。

REFLEX 的负面结论同样重要：**如果一个廉价的生成式级联已经足够准，Jev 的额外收益会很小**。这提示导航评测里必须包含“小 LLM 级联”这一基线。

### 2.8 失效模式与“零幻觉”

官方宣传的“零幻觉”只应理解为 **不会返回 schema 之外的字符串或类型错误**，不代表判断正确。官方 Jaggedness 文档列出了明确的弱项：字面理解、多跳推理、**数字精度**、日期、**长且无关的状态**、对抗内容、互相矛盾的条件。[官方 Jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)

对机器人应用而言，其中两条几乎就是设计约束：**不要把原始坐标交给它，也不要把完整历史塞给它**。

## 3. 原生不支持多模态：Jev 的派生模型

Jev 只接受文本。对需要“看”的任务，社区走出了两条路：

- **外挂感知**：视觉 / 语音模型先把观测转成文本或结构化状态，Jev 只做语义判断；
- **原生多模态派生**：抛开托管的 Jev，用开源 VLM / 音频编码器复刻“单次前向 + 类型化输出头 + 校准”这一 System One 形态。

后一条路的前提，是 System One 形态本身能被开源模型复现。所以先看文本复刻。

### 3.1 总览

按“能处理什么模态”和“需要多少训练”两个维度，可以把目前的派生模型放进一张图里：

<div align="center">
<svg viewBox="0 0 780 400" width="100%" style="max-width:780px;font-family:sans-serif" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="jevA4" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#64748b"/></marker></defs>
  <rect width="780" height="400" rx="12" fill="#f8fafc" stroke="#e2e8f0" stroke-width="1.5"/>
  <text x="390" y="26" text-anchor="middle" font-size="14" font-weight="bold" fill="#1e293b">Jev 派生模型全景：模态 × 训练程度</text>
  <g font-size="12" font-weight="bold" text-anchor="middle"><text x="285" y="52" fill="#1e40af">文本</text><text x="505" y="52" fill="#9a3412">视觉</text><text x="690" y="52" fill="#6b21a8">语音</text></g>
  <g fill="#ffffff" stroke="#e2e8f0"><rect x="190" y="60" width="190" height="66" rx="6"/><rect x="390" y="60" width="230" height="66" rx="6"/><rect x="630" y="60" width="130" height="66" rx="6"/><rect x="190" y="134" width="190" height="66" rx="6"/><rect x="390" y="134" width="230" height="66" rx="6"/><rect x="630" y="134" width="130" height="66" rx="6"/><rect x="190" y="208" width="190" height="66" rx="6"/><rect x="390" y="208" width="230" height="66" rx="6"/><rect x="630" y="208" width="130" height="66" rx="6"/><rect x="190" y="282" width="190" height="66" rx="6"/><rect x="390" y="282" width="230" height="66" rx="6"/><rect x="630" y="282" width="130" height="66" rx="6"/></g>
  <g font-size="11" fill="#334155"><text x="40" y="89" font-weight="bold">托管 Jev</text><text x="40" y="105">+ 外挂感知</text><text x="40" y="163" font-weight="bold">零训练读出</text><text x="40" y="179">开源模型 + 去偏</text><text x="40" y="237" font-weight="bold">冻结骨干 + 小头</text><text x="40" y="253">或 LoRA 微调</text><text x="40" y="311" font-weight="bold">完整训练</text><text x="40" y="327">专用决策模型</text></g>
  <line x1="24" y1="70" x2="24" y2="340" stroke="#64748b" stroke-width="1.5" marker-end="url(#jevA4)"/>
  <g font-size="10.5">
    <rect x="200" y="76" width="170" height="34" rx="6" fill="#2563eb"/><text x="285" y="91" text-anchor="middle" fill="#ffffff" font-weight="bold">Jev（官方，仅文本）</text><text x="285" y="104" text-anchor="middle" fill="#dbeafe">零样本泛化最强</text>
    <rect x="400" y="68" width="210" height="22" rx="5" fill="#ffedd5" stroke="#f59e0b"/><text x="505" y="83" text-anchor="middle" fill="#7c2d12">jev-vision（YOLO → Jev）</text>
    <rect x="400" y="96" width="210" height="22" rx="5" fill="#ffedd5" stroke="#f59e0b"/><text x="505" y="111" text-anchor="middle" fill="#7c2d12">computer-use（OCR → Jev）</text>
    <rect x="640" y="82" width="110" height="22" rx="5" fill="#f3e8ff" stroke="#a855f7"/><text x="695" y="97" text-anchor="middle" fill="#581c87">jev-canvas（ASR）</text>
    <rect x="200" y="156" width="170" height="22" rx="5" fill="#dbeafe" stroke="#3b82f6"/><text x="285" y="171" text-anchor="middle" fill="#1e3a8a">AnyJev（Nokia）</text>
    <rect x="400" y="156" width="210" height="22" rx="5" fill="#ffedd5" stroke="#f59e0b"/><text x="505" y="171" text-anchor="middle" fill="#7c2d12">PixelJev 冻结模式</text>
    <text x="695" y="171" text-anchor="middle" fill="#94a3b8">—</text>
    <rect x="200" y="216" width="80" height="22" rx="5" fill="#dbeafe" stroke="#3b82f6"/><text x="240" y="231" text-anchor="middle" fill="#1e3a8a">minojev</text>
    <rect x="290" y="216" width="80" height="22" rx="5" fill="#dbeafe" stroke="#3b82f6"/><text x="330" y="231" text-anchor="middle" fill="#1e3a8a">Open-Jev</text>
    <rect x="400" y="216" width="100" height="22" rx="5" fill="#ffedd5" stroke="#f59e0b"/><text x="450" y="231" text-anchor="middle" fill="#7c2d12">Visual Jev</text>
    <rect x="510" y="216" width="100" height="22" rx="5" fill="#ffedd5" stroke="#f59e0b"/><text x="560" y="231" text-anchor="middle" fill="#7c2d12">PixelJev LoRA</text>
    <rect x="640" y="230" width="110" height="22" rx="5" fill="#f3e8ff" stroke="#a855f7"/><text x="695" y="245" text-anchor="middle" fill="#581c87">Prosodia</text>
    <text x="285" y="258" text-anchor="middle" fill="#64748b">Qwen3-1.7B / 4B 骨干</text>
    <text x="505" y="258" text-anchor="middle" fill="#64748b">Qwen3-VL-4B / Qwen3.5</text>
    <rect x="200" y="304" width="170" height="22" rx="5" fill="#dbeafe" stroke="#3b82f6"/><text x="285" y="319" text-anchor="middle" fill="#1e3a8a">Laya（ModernBERT 421M）</text>
    <rect x="400" y="290" width="100" height="22" rx="5" fill="#ffedd5" stroke="#f59e0b"/><text x="450" y="305" text-anchor="middle" fill="#7c2d12">Laya Vision</text>
    <rect x="510" y="290" width="100" height="22" rx="5" fill="#ffedd5" stroke="#f59e0b"/><text x="560" y="305" text-anchor="middle" fill="#7c2d12">PlayJev</text>
    <rect x="400" y="318" width="210" height="22" rx="5" fill="#fee2e2" stroke="#ef4444"/><text x="505" y="333" text-anchor="middle" fill="#7f1d1d">decider-2b-vision（已接入 ROS 2 导航）</text>
    <text x="695" y="319" text-anchor="middle" fill="#94a3b8">—</text>
  </g>
  <rect x="190" y="358" width="570" height="30" rx="6" fill="#fff7ed" stroke="#fdba74"/>
  <text x="475" y="378" text-anchor="middle" font-size="11" fill="#9a3412">越往下：本地延迟越低（30–65 ms）、可机载、但越依赖领域数据；越往上：零样本越强、依赖网络</text>
</svg>
<figcaption>图 4　托管 Jev 只占左上角一格；视觉一列是具身导航最需要、也最活跃的方向</figcaption>
</div>

| 类别 | 代表 | 骨干 | 是否训练 | 模态 |
|---|---|---|---|---|
| 从头训练的开源替代 | Laya | ModernBERT-large（421M） | RLCD + 温度校准 | 文本 |
| 零训练读出 | AnyJev（Nokia） | 任意开源 LLM（示例为 Qwen3） | 否（可选轻量校准） | 文本 |
| 冻结骨干 + 小头 | minojev | Qwen3-1.7B（冻结）+ 约 0.8M 头 | 只训头 | 文本 |
| 解码器读出 + 微调（论文） | Open-Jev | Qwen3-4B + LoRA | CE + Brier 损失 + 温度 | 文本 |
| 视觉派生 | Laya Vision | SmolVLM-256M | RLCD + 温度校准 | 图像 + 文本 |
| 视觉派生（论文） | Visual Jev（CMU） | Qwen3-VL-4B + LoRA | 答案监督 | 图像 + 多问题 |
| 视觉派生（论文） | PixelJev（MSRA） | Qwen3.5-2B / 4B | 冻结 / 少样本 LoRA / 温度 | 图像 + 候选 |
| 视觉策略派生 | PlayJev | Qwen3.5-0.8B | 行为克隆 + DAgger | 图像（游戏帧） |
| 视觉导航派生 | decider-2b-vision | 未公开（约 2B，BF16 4.1 GB） | 未公开 | 相机图像 |
| 语音派生 | Prosodia | Whisper 编码器（冻结） | 训头 | 语音 |
| 外挂感知 | jev-vision 等 | YOLO / OCR / ASR + 托管 Jev | 否 | 经由文本 |

以下均为社区独立项目，与 TypeSafe 无隶属关系，数字为项目自报。

### 3.2 文本复刻：System One 形态可以用开源模型做出来

**Laya：从头训练的开源替代。** Laya 由 Convai Innovations 以 Apache-2.0 发布，结构是 **ModernBERT-large 编码器 + 2 层 Transformer 决策头**，共 421M 参数，另有基于 mmBERT-base 的 322M 多语言版本和一个按文字脚本自动分发的 Router。候选项与问题和状态一起编码，输出头分别对应 choice / score / noul。训练采用前述“严格恰当评分规则 + GRPO 式策略梯度”的 RLCD 解读，再按题型和选项数分桶做温度缩放。[Laya](https://github.com/NandhaKishorM/laya)

它的自报结果很有信息量：

- 在 2,000 个类型化决策上，领域微调后的 Laya 准确率 0.766，高于 Jev 的 0.727；ECE 0.081，而 Jev 为 0.246；
- 但在 77 类高基数选择上，Laya 只有 0.425，Jev 为 0.870；
- **未微调的基础 checkpoint 零样本接近随机**，且出厂时严重过度自信（ECE 0.466，重拟合温度后降到 0.081）；
- T4 上单问题 32.8 ms，批量 10 题时每题 7.2 ms。

这说明：**一个 4 亿参数的编码器在窄领域内可以追平甚至超过 Jev，但通用零样本能力是 Jev 真正的护城河。**

**AnyJev：零训练地把任意 LLM 变成 Jev。** AnyJev 由 Nokia 应用研究团队以 Apache-2.0 开源。[MarkTechPost](https://www.marktechpost.com/2026/09/23/nokia-open-sources-anyjev-a-training-free-layer-that-turns-any-open-llm-into-a-calibrated-decision-model/) 它不训练模型，而是从开源 LLM **单次 prefill 的下一 token 分布**里读出答案：把选项标成字母，只在这些字母 token 上做 softmax。关键问题是**位置偏差**——同一道题换个选项顺序，答案就可能翻转。它的处理分几级：[AnyJev](https://github.com/MorrisZJ/AnyJev)

- **L0（零标注）**：对 K 个选项做 K 次循环移位，把位置偏差平均掉，并除去标签先验；
- **L1（100–500 条标注）**：在 L0 上加温度缩放；
- **L2（100–300 条标注）**：在中间层隐状态上闭式求解一个线性头。

在 Qwen3-8B / BANKING77 上，选项顺序翻转率从 0.230 降到 0.073，准确率从 0.747 升到 0.807，ECE 从 0.240 降到 0.095；在风险 ≤ 5% 的约束下可自动决策的样本比例从 7.7% 升到 52.0%。局限在于其准确率是相对教师 LLM 而非人类真值，字母读出最多 26 个选项。

**minojev：冻结骨干 + 小决策头。** minojev 冻结 Qwen3-1.7B，只训练一个约 0.8M 参数的决策头：每条“状态 + 问题 + 候选”路径前向一次并缓存末层隐状态，由“共享打分器 + 集合注意力”读出分布，再按原语拟合温度。在 120 个平衡决策上，准确率 95.8%（同骨干生成式基线 80.0%），ECE 0.024，p95 延迟约 0.6 s（基线约 3.3 s）。但在**未见过的领域上只有 31.7%，低于生成式基线的 40%**——作者的总结是“训练头带来专精，不能替代数据广度”。[minojev](https://github.com/zeredy879/minojev)

**Open-Jev：一篇把话说透的论文。** Scam.ai 团队在 CallScreenBench（每轮来电者发言后重新判断是否诈骗，41 个留出场景、577 个决策）上，用 LoRA 微调 Qwen3-4B，**只在声明的答案标签上**施加交叉熵与 Brier 损失，读出首个位置的标签 logits，再做温度缩放。结果：三种子集成 AUROC 97.4%（LLM 判官 94.7%），ECE 5.2%，合法来电误报 0%（判官 17.7%），中位延迟 64.5 ms（判官 1,946 ms），比同骨干生成式训练快 4.9 倍。作者的核心结论是 **“买到准确率的是微调，不是接口”**；并承认配方选择接触过测试集、同等辅助监督的 ModernBERT 编码器并不显著更差、对改写攻击与选项顺序敏感。[Open-Jev, arXiv:2609.23959](https://arxiv.org/abs/2609.23959)

四者合起来说明：**System One 的核心形态——单次前向、候选集读出、事后校准——可以在开源模型上复现；差距主要在零样本泛化，而不在架构。**

### 3.3 视觉派生：让 System One 模型“看见”

**Laya Vision：把文本编码器换成 VLM。** Laya Vision 是 Laya 的独立 fork，把 ModernBERT 换成 **SmolVLM-256M**（推荐 checkpoint 只保留 30 层语言层中的 20 层），输入为“图像 + 可选文本 + 问题”，一次前向返回 choice / noul / score。训练数据包括 The Cauldron 的 19 个子集、4 个 rubric 评分集和游戏帧，沿用 RLCD 目标与温度校准。[Laya Vision](https://github.com/r33drichards/laya-vision)

- 34 个验证集、59,427 个问题上总体准确率 69.1%，ECE 0.041；
- L4 GPU 上中位延迟约 **34 ms**；
- 直接看游戏画面做决策：ViZDoom 0.99、Atari Freeway 0.81（0 为随机、1 为专家），但 Breakout 只有 0.20、Snake 0.17；
- 作者观察到：**训练视觉塔能提升游戏表现，但会损害视觉推理**；
- 权重因训练数据许可为 CC BY-NC-SA 4.0，**不可商用**。

**PlayJev：视觉 System One 策略。** PlayJev 基于 **Qwen3.5-0.8B-Base**，输入一张 448 px 游戏帧和可选动作列表（2–7 个），输出动作上的概率分布。训练数据为 11,416 局、217 万个决策，流程是：[PlayJev](https://github.com/OmniJev/PlayJev)

1. 从教师策略做行为克隆（注入 2–30% 随机动作）；
2. 三轮 DAgger，用模型自己玩出来的状态请教师重新标注；
3. 回放阶段混入 20% 通用图像问答与 20% 文本数据，防止遗忘；**每个样本都打乱动作顺序**，使位置不携带信息。

结果：H200 上 **43 ms / 步**；十个游戏平均达到教师水平的 0.57（Space Invaders、Racer 追平教师，Tetris 仅 0.37）；低置信度时交给人类接管可达到教师水平。它最值得注意的地方是**置信度有意义**：模型越确定，与教师动作一致的比例越高。

**Visual Jev（论文）：一张图、多道题、只编码一次。** CMU 的 Visual Jev 针对“同一张图要回答多个独立的选择题”这一场景：图像只编码一次并缓存 KV，各问题的后缀作为一个批次并行执行，从语言模型头上对合法选项做归一化读出概率；在 Qwen3-VL-4B 上做答案监督的 LoRA 微调。[Visual Jev, arXiv:2609.25845](https://arxiv.org/abs/2609.25845)

- GQA、SNLI-VE、TextVQA、TallyQA 四个基准宏平均准确率从 0.706 提升到 0.761（后两者为留出任务）；
- 每张图 32 个问题时，比串行执行快 **8.9 倍**（摊销每题 5.7 ms），比不复用前缀的批处理快 3.4 倍，峰值显存从 8.40 GiB 增至 10.10 GiB；
- 一个很关键的对照：**专门的类型化输出头相对 LM 头读出并无一致优势**。

**PixelJev（论文）：视觉选择到底从哪里获益。** MSRA 与南京大学的研究把 Qwen3.5 2B / 4B 包装成“图像 + 指令 + 候选 schema → 选择 + 候选条件概率”的接口，分别评测冻结推理、少样本 LoRA 与温度校准三种模式。[PixelJev, arXiv:2609.29283](https://arxiv.org/abs/2609.29283)

- Pets 从冻结 2B 的 60.13% 提升到适配后的 92.40%，EuroSAT 从 49.63% 到 88.31%，但专门的 DINOv2 探针仍更强（Pets 95.67%）；
- 冻结的 4B 在若干迁移任务上优于适配后的 2B；
- 匹配的“只改 prompt”对照显示：**Pets 上的收益完全来自 adapter，而不是读出方式**；ScienceQA 上直接读出只比生成高 1.88 个点，主要因为强制了合法输出；
- 温度校准并未在所有留出集上改善指标，**准确率提升不保证目标域概率校准**；接口没有学习到的拒识选项，也未评测动作选择。

**Jev Visual** 则是工程实现：用 MLX 上的 Qwen VLM 共享图像上下文、对候选逐一打分，作者明确说明其概率未经校准。[Jev Visual](https://github.com/hr98w/jev-visual)

**decider-2b-vision：已经被接进导航。** Mapika 发布的 decider-2b-vision 是一个不生成文本、通过 `prepare()` / `slot_logits()` 直接读出候选槽位概率的视觉决策模型（BF16 权重约 4.1 GB，Apache-2.0），架构与训练未公开。它已被 `jev_navigation` 用于 ROS 2 局部路径选择（见 4.5）。[jev_navigation](https://github.com/NOPLAB/jev_navigation)

### 3.4 语音派生与外挂感知

**Prosodia** 用冻结的 Whisper 编码器直接从语音得到类型化决策（情绪、情感、声学属性），**中间不经过 ASR 转写和文本生成**。[Prosodia](https://github.com/alperiox/audio-jevlike)

外挂感知式项目则保留托管 Jev，只在前面加感知模块：

- **jev-vision**：YOLO 检测后按 top-1 分数分流——≥ 0.85 直接采纳，0.15–0.85 交给 Jev 结合场景上下文消歧（如“摄像头装在狗舍里”），< 0.15 升级人工；一帧内所有歧义框合并为一次调用，约 150 ms。[jev-vision](https://github.com/JeremyEltho/jev-vision)
- **jev-canvas**：语音转写 + 指尖检测，Jev 从转写与位置中选择动作、目标与落点，阈值由确定性代码执行。[jev-canvas](https://github.com/gaborishka/jev-canvas)
- **typesafe-computer-use**：macOS OCR 后由 Jev 做有界动作选择。[typesafe-computer-use](https://github.com/awlevin/typesafe-computer-use)

### 3.5 派生模型告诉我们什么

1. **System One 是一种形态，而不是一个模型。** “编码器 / VLM 骨干 + 候选集读出 + 校准”可以在 0.25B–4B 的开源模型上复现，并且能在本地 GPU 上做到 **30–65 ms**，比托管 Jev 的网络往返快一个量级。
2. **速度来自“不生成 + 共享前缀”，不来自特殊的头。** Visual Jev 发现类型化头相对 LM 头读出没有一致优势；真正的加速来自一次编码、KV 复用、多问题批处理。
3. **准确率来自领域微调，不来自接口。** Open-Jev 与 PixelJev 两篇论文独立得出同一结论：接口换来的是合法输出、可用概率与速度，而准确率要靠目标域数据。
4. **多模态化的方式很直接**：把文本编码器换成 VLM 或音频编码器即可；难点在训练数据和能力取舍（Laya Vision 的“游戏 vs 视觉推理”冲突）。
5. **校准不是免费的**：几乎所有开源复刻出厂时都过度自信，需要在目标领域用少量标注重拟合温度，且校准不一定能跨域迁移。
6. **泛化是分水岭**：窄领域可以追平甚至超过 Jev，跨领域零样本明显落后（minojev 在未见领域 31.7% 对 40%）。
7. **许可证要看清**：部分视觉派生权重为非商用许可。

对具身导航而言，第 2、3 点合起来意味着：**一个在导航数据上 LoRA 微调、共享视觉前缀、对候选读出概率的开源 VLM，就是一个可机载的“视觉 Jev”**——不需要等 TypeSafe 发布多模态版本。

## 4. 具身导航：System One 模型放在哪一层

### 4.1 分层架构

结合 Jev 的接口与局限，最合理的系统切分如下：

<div align="center">
<svg viewBox="0 0 760 420" width="100%" style="max-width:760px;font-family:sans-serif" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="jevA5" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#64748b"/></marker><marker id="jevA5r" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#dc2626"/></marker></defs>
  <rect width="760" height="420" rx="12" fill="#f8fafc" stroke="#e2e8f0" stroke-width="1.5"/>
  <text x="380" y="26" text-anchor="middle" font-size="14" font-weight="bold" fill="#1e293b">System One 决策头在导航栈中的位置</text>
  <text x="680" y="52" text-anchor="middle" font-size="11" font-weight="bold" fill="#475569">典型频率</text>
  <rect x="60" y="44" width="430" height="44" rx="8" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5"/>
  <text x="275" y="71" text-anchor="middle" font-size="12" fill="#334155">传感器：相机 · 深度 · 激光雷达 · 里程计</text>
  <text x="680" y="71" text-anchor="middle" font-size="11" fill="#475569">15–30 Hz</text>
  <line x1="275" y1="90" x2="275" y2="106" stroke="#64748b" stroke-width="1.5" marker-end="url(#jevA5)"/>
  <rect x="60" y="108" width="430" height="60" rx="8" fill="#ffedd5" stroke="#f59e0b" stroke-width="1.5"/>
  <text x="275" y="132" text-anchor="middle" font-size="12" font-weight="bold" fill="#7c2d12">感知与几何（本地模型 + 确定性代码）</text>
  <text x="275" y="152" text-anchor="middle" font-size="11" fill="#9a3412">定位 · 地图 / 记忆 · 候选生成 · 几何可行性过滤</text>
  <text x="680" y="142" text-anchor="middle" font-size="11" fill="#475569">约 15 Hz</text>
  <line x1="275" y1="170" x2="275" y2="200" stroke="#64748b" stroke-width="1.5" marker-end="url(#jevA5)"/>
  <text x="285" y="190" font-size="10.5" fill="#64748b">紧凑状态：语义描述 + 已过滤候选（不给原始坐标）</text>
  <rect x="60" y="202" width="430" height="64" rx="8" fill="#dbeafe" stroke="#2563eb" stroke-width="2"/>
  <text x="275" y="228" text-anchor="middle" font-size="13" font-weight="bold" fill="#1e3a8a">System One 决策头（Jev / 视觉派生）</text>
  <text x="275" y="250" text-anchor="middle" font-size="11" fill="#1e40af">候选比较 · 风险分级 · 停止 / 重规划 · 升级路由</text>
  <text x="680" y="230" text-anchor="middle" font-size="11" font-weight="bold" fill="#1e40af">2–5 Hz</text>
  <text x="680" y="246" text-anchor="middle" font-size="10" fill="#1e40af">异步，不阻塞控制</text>
  <line x1="492" y1="234" x2="528" y2="234" stroke="#64748b" stroke-width="1.5" stroke-dasharray="4" marker-end="url(#jevA5)"/>
  <rect x="530" y="210" width="84" height="48" rx="8" fill="#f5f3ff" stroke="#7c3aed" stroke-dasharray="4"/>
  <text x="572" y="230" text-anchor="middle" font-size="11" font-weight="bold" fill="#4c1d95">低置信升级</text>
  <text x="572" y="247" text-anchor="middle" font-size="10" fill="#5b21b6">VLM / 人工</text>
  <line x1="275" y1="268" x2="275" y2="304" stroke="#64748b" stroke-width="1.5" marker-end="url(#jevA5)"/>
  <text x="285" y="286" font-size="10.5" fill="#64748b">离散选择 + 概率；结果未到则沿用上一决策</text>
  <rect x="60" y="306" width="430" height="60" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="2"/>
  <text x="275" y="330" text-anchor="middle" font-size="12" font-weight="bold" fill="#14532d">安全盾 + 几何规划器 + 局部控制器（确定性）</text>
  <text x="275" y="350" text-anchor="middle" font-size="11" fill="#166534">碰撞 / 足迹检查 · 路径跟踪 · 执行</text>
  <text x="680" y="336" text-anchor="middle" font-size="11" fill="#475569">20–500 Hz</text>
  <path d="M58,336 C20,336 20,234 56,234" fill="none" stroke="#dc2626" stroke-width="2" marker-end="url(#jevA5r)"/>
  <text x="18" y="290" font-size="11" font-weight="bold" fill="#dc2626">否决</text>
  <rect x="60" y="378" width="640" height="30" rx="6" fill="#fff7ed" stroke="#fdba74"/>
  <text x="380" y="398" text-anchor="middle" font-size="11" fill="#9a3412">置信度低 / 分布过平 / 分布外输入 → 升级到 VLM 或人工；安全永远由绿色层保证，而不是由概率保证</text>
</svg>
<figcaption>图 5　决策头夹在“感知与几何”和“安全与控制”之间：只在已验证的候选里选，且随时可被否决</figcaption>
</div>

三条硬约束：

1. **决策头只在已验证的候选之间选**，不输出坐标、角度或连续控制量；
2. **安全层对决策头拥有否决权**；
3. **高频闭环不等决策头**：结果未返回时，控制器继续执行上一次决定或规则策略。

### 4.2 两条接入路径

第 3 节的派生模型让“System One 决策头”有了两种实现：

| | 路径 A：托管 Jev + 文本化场景 | 路径 B：本地视觉 System One |
|---|---|---|
| 形态 | 感知模块 → 场景图 / JSON → Jev API | 图像 + 候选 → 本地 VLM 骨干 + 类型化头 |
| 延迟 | 网络往返 0.1–0.5 s | 本地 GPU 约 30–50 ms |
| 优势 | 零样本泛化最强，免训练 | 无网络依赖，可上机载，能直接看图 |
| 劣势 | 依赖网络与厂商；视觉→文本转换有信息损失；中文效果打折 | 需要导航数据训练与领域校准；泛化弱 |
| 适合 | 研究原型、低频语义判断 | 机载部署、断网场景、高频战术判断 |

一个务实的组合是**级联**：机载的小型视觉 System One 模型做高频首判，置信度低时升级到托管 Jev 或 VLM，再不行就交给人类或停车。

### 4.3 适合与不适合的职责

适合 System One 决策头的五类窄职责：

1. **候选路点 / 视角比较**：对控制器构造、已通过几何可行性检查的选项做 `Choice`；
2. **语义风险与异常判断**：目标是暂时遮挡还是确实丢失、当前情景是否需要重规划；
3. **停止与进展门控**：用 `Noul` / `Score` 给出概率，由代码按阈值决定继续、回看、回退或升级；
4. **级联路由**：把 confidence 当作**路由信号**，而不是安全保证。
5. **Agent 记忆控制**：判断哪些历史观测与当前子目标相关、是否需要继续检索，再把选出的证据交给规划器；Jev-Mem 提供了通用 Agent 上的先例，导航迁移见 4.6。

不适合交给它的事：

| 任务 | 原因 |
|---|---|
| RGB / 视频感知（托管 Jev） | 不支持非文本输入 |
| SLAM、度量几何、精确计数 | 数字精度是官方列出的弱项 |
| 长链全局规划 | 多跳推理是弱项，应拆成原子问题 |
| 电机 / 底盘高频闭环 | 延迟与可靠性都不满足 |

由此得出一条实践原则：**导航状态在送进决策头之前，必须先做几何计算、命名分桶、检索和裁剪**。与其写“障碍物在 (2.37, −0.84) 处”，不如写“左前方近距离（< 1 m）有障碍物”。

### 4.4 近期导航研究的支撑

截至本文核查的公开资料，尚未找到直接评测 Jev 的 VLN 基准论文；2.7 的 Jev-Mem 与 REFLEX 属于通用 Agent 研究，不能算作导航验证。近期三项导航工作从不同角度支持“**模型只做有界比较 / 验证，几何与执行留给机器人**”这一接口：

- **C²Nav** 让 VLM 比较控制器构造的候选；matched role inversion 实验把比较式问题改回基数 / 绝对式问题后，空间、转移、终止三个决策位置的 SR 分别降到 **12.0%、28.0%、21.0%**。同一模型，问法从“报数值”换成“比候选”，差距巨大——`Choice` 天然是后者。[C²Nav, arXiv:2609.15142](https://arxiv.org/abs/2609.15142)
- **VerNav** 用批量动作验证替代逐步自回归生成，仅在不确定时调用生成器，在离散 R2R 上决策阶段单步延迟降低 **10 倍以上**。“验证优先 + 不确定时升级”正是 System One 决策头的用法，但结果来自离散 R2R，不能外推到 VLN-CE 或真机。[VerNav, arXiv:2609.00920](https://arxiv.org/abs/2609.00920)
- **O2C-Nav** 在连续环境中把每步大模型调用压到一次：免训练生成候选路点并画到 RGB 上，由 MLLM 选点、FMM 执行。它对应的恰好是 4.2 中的路径 B——把“画了候选的图像”直接交给一个视觉 System One 模型选点，是比“转成文本再交给 Jev”更自然的接法。[O2C-Nav, arXiv:2609.06476](https://arxiv.org/abs/2609.06476)

另有几项工作分别回答了“慢判断如何接入快控制”“何时升级”“置信度能不能信”这三个问题：

- **Slow Brain, Fast Planner** 与 System One 决策头的位置几乎完全相同：学习型规划器实时生成多条候选轨迹，但在困难场景中“选不对”；VLM 从候选中做选择，再通过一个**免训练、抗延迟的轨迹级融合层**，按几何相似度与指数衰减把延迟到达的 VLM 选择转成实时打分。在约 2,000 个真实困难场景上，VLM 选择使 ADE 比规划器自身最佳选择降低 30%；仿真中延迟高达 5 s 时仍保持 80% 以上成功率。[Slow Brain, Fast Planner, arXiv:2606.20458](https://arxiv.org/abs/2606.20458) 这正是处理“过期决策”的现成方案：Jev 把延迟从 1–3 s 降到 0.1–0.3 s，融合层则保证即便决策迟到也不会出错。
- **AdaNav** 以动作熵为先验、用启发式到 RL 的训练得到一个轻量的不确定性自适应推理模块，只在需要时才触发显式推理；仅用 6,000 个训练样本，在 R2R val-unseen、RxR-CE 和真实场景上成功率分别提升 20%、11.7%、11.4%。[AdaNav, arXiv:2509.24387](https://arxiv.org/abs/2509.24387) 它说明“置信度门控升级”在 VLN 中本身就能提升性能，而不仅是省算力。
- **ABot-N1** 采用慢系统（带 CoT、输出像素级目标锚点的 VLM）+ 快系统（原生控制频率输出连续路点的动作专家）的双系统导航基础模型。[ABot-N1, arXiv:2607.10383](https://arxiv.org/abs/2607.10383) 若把其中的慢系统拆出一部分“判断”交给 System One 模型，是一个自然的延伸方向。
- **置信度能不能信？** Zollo 与 Zemel 对 OpenVLA、MolmoAct、UniVLA、NORA 的首个 VLA 校准研究发现：置信度在任务约 50% 进度时最准、之后又变差；20 个同义指令的 prompt ensemble 可使 ECE 平均降低 20% 以上；不同自由度间校准差异可达 200%，应逐维做 Platt 缩放。[Confidence Calibration in VLA, arXiv:2507.17383](https://arxiv.org/abs/2507.17383) 另一篇 EMNLP 2026 论文发现 VLM 的口头置信度与其推理轨迹几乎无关——反复自我纠正、最终答错，仍报告高置信，而 ECE、AUROC 检测不到这一问题。[The Mirage of Calibrated Confidence, arXiv:2609.18453](https://arxiv.org/abs/2609.18453) 两者都提醒：**置信度必须在目标任务、目标阶段上单独校准和检验**。
- 更早的两项经典工作仍是必读：**KnowNo** 用共形预测为 LLM 规划器的多选动作构造预测集，在集合不唯一时向人求助，给出统计意义上的成功率保证 [KnowNo, arXiv:2307.01928](https://arxiv.org/abs/2307.01928)；**PriDe** 系统揭示了 LLM 做选择题时的选项 ID 偏差，并提出无标注的先验去偏方法 [PriDe, arXiv:2309.03882](https://arxiv.org/abs/2309.03882)——AnyJev 的循环移位与先验除法正是这一思路的延续。

这些工作共同指向：**减少自由生成，把度量与安全交回代码，用经过校准的置信度决定何时升级**。System One 模型是这个方向的下一步——连“做判断”的模型也不再需要生成能力。

### 4.5 已有的具身 demo

目前所有 Jev 机器人 / 驾驶用例都来自社区项目，证据等级低，但架构上有参考价值。

| 项目 | 平台 | Jev 负责什么 | 报告结果 | 局限 |
|---|---|---|---|---|
| [JEV_SMARTROBOTCONTROL](https://github.com/mahajanparth/JEV_SMARTROBOTCONTROL) | ROS 2 Humble + Gazebo，TurtleBot3，AMCL + Nav2 | 约 5 Hz 监督 Nav2：继续 / 暂停 / 重规划 / 定位恢复（原地转 / 全局重定位 / 后退再转）/ 求助 | 定位恢复与安全兜底可演示；129 项测试中 127 项通过 | 相似房间中 AMCL 仍会收敛错误；未上真机 |
| [jev_navigation](https://github.com/NOPLAB/jev_navigation) | ROS 2 Humble，差速底盘 | 本地视觉决策模型 decider-2b-vision 在 7 个候选（5 条弧线 + 停止 + 到达）中选择 | 20 Hz 控制，指令 0.8 s 过期 | **无激光避障、无足迹碰撞检查**；GPU 与实机未验证 |
| [jev_fsd](https://github.com/BrendanH18/jev_fsd) | OpenStreetMap 城市驾驶仿真 | 在最多 16 个经 3 秒前向模拟过滤的机动中选择 | 约 130 ms、$0.00008 / 决策 | 作者自称 demo；无基准、无复现 |
| [jev-drone](https://github.com/RomanSlack/jev-drone) | MuJoCo 四旋翼 | 约 2.5–3 Hz：绕左 / 绕右 / 爬升 / 刹车 / 重捕获，风险与目标丢失概率 | 中位约 0.11 s；单次运行跑完课程 | 单次运行；三种子对比中无优势 |
| [Embodied Jev](https://github.com/FBddcz/embodied-jev) | MuJoCo Franka 机械臂 | 分层选择子目标与 XYZ 方向 / 步长 / 夹爪 | Meta-World 层 Jev 5/6，与 GPT-6 持平；精细放置不稳 | 单种子；仅仿真 |
| [JevPilot](https://github.com/standardagents/jevpilot) | Three.js 驾驶仿真 | 选择候选路径与速度 | — | 动力学由本地代码负责 |

**JEV_SMARTROBOTCONTROL** 是目前与室内导航最贴近的 Jev 项目，也把“谁拥有运动控制权”这件事做得最清楚：[项目 README](https://github.com/mahajanparth/JEV_SMARTROBOTCONTROL)

- Jev 读 JSON 状态快照，回答一个 `action` Choice（每个动作附带判据说明），有安全局部目标时再回答一个 `target` Choice；动作置信度低于 20% 不执行；
- 一个**命令桥**强制运动控制权互斥（`NAV` / `RECOVERY` / `NONE`），并让过期命令自动失效；Jev 监督 Nav2 但**不能越权驾驶**，只能决定暂停、恢复或重规划；
- 定位丢失时取消导航，请 Jev 选择恢复动作，恢复后由 Jev 判断是否继续；定位质量连续 2 s 达标（不确定度 < 0.35、扫描与地图一致度 ≥ 0.85）即提前结束恢复；
- 20 Hz 障碍过滤独立于 Jev：包络被挡、激光覆盖无效或里程计过期时减速或停车，阻塞 15 s 请求人工。

**jev_navigation** 则是路径 B 的第一个实例：单个 ROS 节点把相机帧发给本地推理服务，decider-2b-vision 在 5 条预设弧线（直行、半径 1 m 的两条缓弯、半径 0.5 m 的两条急弯）、停止和到达共 7 个候选中选择，候选路径锚定到当前里程计位姿，用 0.2 m 前视距离的纯追踪跟踪；同一时间只有一个推理请求在途，新帧替换旧帧，0.8 s 无新结果则指令失效。[项目 README](https://github.com/NOPLAB/jev_navigation) 作者直言其缺陷：**没有 `/scan` 检查和独立避障，模型概率不是碰撞概率，弧线未做足迹与盲区检查**——这恰好是一份“视觉 System One 决策头必须配什么”的反面清单。

**jev_fsd** 最完整地展示了一套可迁移的架构：代码负责感知并提出候选，向前模拟 3 秒剔除碰撞、越界、闯灯的候选，Jev 在幸存候选中选择；超时、无效输出或请求失败时回退到规则驾驶，等待网络期间车辆继续执行上一次选择。

**jev-drone** 的分层最接近可辩护的机器人架构：

| 层 | 频率 | 职责 |
|---|---|---|
| 几何控制 | 500 Hz | 姿态与推力 |
| 引导与安全反射 | 50 Hz | 避障，可否决 Jev |
| 相机 → 符号场景 | 15 Hz | 深度 / 分割 → JSON |
| Jev 战术判断 | 约 2.5–3 Hz | 离散机动选择 + 概率 |

作者同样保留了关键的不利证据：Jev 那一列只是**单次运行**，早期三种子对比中 **Jev 没有优势**，运行方差很大；更激进的隧道实验中位延迟 0.118 s、p90 0.164 s，但仍不能稳定通过全程。

**Embodied Jev** 把 Jev 用在操作任务上，结果提示了一个重要边界：在“预设技能”层面 Jev 与 GPT-6 相当，但让它逐步选择 XYZ 小步移动时，两次搬运虽到达终点却在释放时掉落物体——**离散化越细、越接近连续控制，System One 决策头越吃力**。

这些 demo 支持的结论是：System One 模型可以作为实时系统中的**低频战术判断器**，“异步 + 回退 + 安全否决”的架构可行。它们**不**支持：Jev 能做视觉导航、可替代经典控制器，或已证明能提升通用机器人性能。

### 4.6 从 Jev-Mem 到导航 Agent：让 Jev 管理记忆

前面的导航讨论主要关注“下一步选哪个动作”，但长期运行的 Agent 还要决定“下一步查什么历史”。**Jev-Mem 把记忆管理中的高频判断交给 Jev，再由 System Two 综合证据回答问题**。它是使用 Jev 的 Agent 记忆架构，未提供具身导航验证。[论文](https://arxiv.org/abs/2609.23986)；[作者代码](https://github.com/libingzheren/Jev-Mem)

其核心分工是：写入时保留原始观测及来源，由 Jev 判断记忆类型和候选关系；读取时由 Jev 路由查询、分配检索预算、评估候选及证据，决定是否继续扩展。共享记忆包含语义、时间、因果和实体四类关系。**“停止检索”并不等于“证据充分”**，也可能是继续搜索收益低或预算耗尽。[方法说明](https://arxiv.org/html/2609.23986v1)

作者在 LoCoMo 长期对话问答上使用 GPT-4o-mini 作为回答模型，报告总体 LLM-as-a-Judge 得分 0.777（MAGMA 为 0.700）；构建耗时 158 s（Nemori 为 1,044 s）；平均查询延迟 0.93 s（MAGMA 为 1.47 s）。其中查询延迟包含检索与答案生成，三项比较也并非都针对同一基线。它们衡量的是对话记忆系统，不能换算成导航成功率或控制频率。[作者结果表](https://github.com/libingzheren/Jev-Mem#results-on-locomo)

**以下是本文提出的导航迁移方案，尚待实验验证。** 可以把一次导航经历保存为带时间、地点 ID 和观测来源的记录，再让 Jev 在有限候选中判断相关性：

| 导航 Agent 面临的问题 | 可交给 Jev 的有界判断 | 仍由其他模块负责 |
|---|---|---|
| “刚才在哪个房间见过杯子？” | 哪些观测与杯子及当前任务相关，是否要查更早记录 | 视觉识别、定位与原始观测保存 |
| “这个门口是不是已经来过？” | 候选历史记录是否有语义关联 | 地点匹配、回环检测与拓扑一致性 |
| “上次绕路的原因还成立吗？” | 旧记录是否与本次重规划相关，是否缺少新证据 | 当前障碍检测、地图更新与可通行性验证 |
| “历史信息够不够支持下一子目标？” | 继续检索、请求新观测，或升级给 VLM / LLM | 子目标规划、候选生成与执行 |

例如，机器人接到“回到刚才看见杯子的房间”时，可以先从记忆库找出候选观测，再让 Jev 筛选与任务相关的记录；规划器结合当前地图生成返程候选，最后经过安全检查执行。这样，Jev 既可参与**行动前的证据选择**，也可参与**候选动作比较**，两处调用应分别记录成本与错误。

迁移时尤其要保留时间戳与来源：十分钟前的“门开着”只能作为历史证据，不能替代当前可通行性检查。预算耗尽也必须显式返回“证据不足”，避免把记忆检索的停止信号误接成导航的到达信号。

## 5. 如何验证：latency–accuracy–safety 联合评测

### 5.1 核心假设与反证条件

> **在相同的感知、候选生成、安全盾和控制器下，用 System One 决策头替代自回归 VLM / LLM 做闭集战术决策，能否在可接受的 SR / SPL 损失内，显著改善 P50 / P95 决策延迟、成本、超时率与长回合稳定性？**

反证条件：若在控制感知与候选生成后，System One 决策头的 SR / SPL 显著低于非推理 LLM，且延迟收益被感知与通信开销淹没，则假设不成立。

### 5.2 最小实验矩阵

| 维度 | 设置 |
|---|---|
| 决策头 | 规则 / 托管 Jev / 本地视觉 System One（Visual Jev 式：开源 VLM + 导航数据 LoRA + 前缀共享读出）/ AnyJev 读出 / 小型分类器 / 小 LLM 生成式级联 / 推理 VLM |
| 延迟处理 | 阻塞等待 / 沿用上一决策 / Slow Brain 式轨迹级衰减融合 |
| 接口 | 绝对坐标或角度 / 候选比较 / verifier-first |
| 输入 | 纯几何 JSON / 几何 + 语义标签 / 再加压缩历史 / 画了候选的 RGB（仅视觉决策头） |
| 记忆控制（独立消融） | 无记忆 / 固定 top-k 检索 / LLM 控制检索 / Jev 控制检索；固定观测库、感知与动作策略 |
| 决策位 | waypoint、转向、进展、停止、目标丢失、重规划 |
| 任务指标 | SR、SPL、NE、碰撞率、错误停止率 |
| 系统指标 | P50 / P95 端到端延迟；每 episode 调用数与成本；fallback 率与 stale-decision 率 |
| 校准指标 | ECE、Brier、AURC |

三个基线尤其重要：**小型分类器**——如果它就能达到 Jev 的准确率和延迟，Jev 的优势只剩“免训练”；**AnyJev 读出**——它回答“托管 Jev 的专门训练到底比‘开源 LLM + 去偏读出’多带来多少”；**小 LLM 生成式级联**——REFLEX 已显示，当廉价级联本身足够准时，Jev 的额外收益很小。

### 5.3 必做的压力测试

- **状态长度与无关噪声**：逐步加长历史与无关字段，测准确率退化曲线；
- **候选顺序与命名**：打乱顺序、更换标签（如“候选 A”与“左侧门口”），检验位置与命名偏差——独立测试中仅改选项名就改变了 32.5% 的答案；
- **无证据时的置信度**：删去关键观测字段，检查模型是否仍高置信作答；
- **否定与双重否定**：“不要进厨房”一类指令；
- **中英文指令对照**：Jev 官方承认中文效果打折；
- **对抗文本**：标牌 OCR、指令中的注入内容；
- **网络抖动与断网**：验证 fallback 与 stale-decision 处理；
- **模型版本漂移与重复调用稳定性**；
- **记忆过期与矛盾**：门的开闭变化、物体被移动、相似房间误关联；测相关证据召回率、错误关联率、检索耗时，以及对 SR / SPL 的影响；
- **置信度阈值迁移**：一个场景集上定的阈值能否迁移到另一个。

最后一条原则需要单独强调：**不能把 `confidence` 直接解释为“碰撞安全概率”**，它只是输出分布的统计量，第 2.6 节的独立评测也显示其校准因任务而异。安全保证必须来自确定性的安全盾。

### 5.4 从哪里开始

在 Habitat R2R-CE 或 OpenNav 子集上实现统一候选接口，先做两个最小实验：

1. **停止判断**：`Noul("是否已到达指令描述的目标")`；
2. **候选比较**：给定 3–8 个经几何过滤的候选路点及其语义描述（或画在图上），做 `Choice`。

这两个决策位输入短、输出闭集，正是 System One 模型最应占优的场景；如果在这里都看不到收益，就没有必要往复杂场景推进。同时以固定种子复现 `jev_fsd` 与 `jev-drone` 的基线，而不是只看演示视频。

## 6. 结论

1. **Jev 是一种新的调用形态，而不只是一个更快的模型。** 它把“短、频繁、有界”的判断从生成式模型里剥离出来，变成单次前向的概率接口；速度优势已被第三方基本复现，校准质量则因任务而异。
2. **训练细节不透明，但形态可复现。** RLCD 只有名字与目标；Laya、AnyJev、minojev 与 Open-Jev 论文证明，“骨干 + 候选集读出 + 校准”在开源模型上可做到窄领域追平甚至超过，差距在零样本泛化；而且准确率来自领域微调，不来自接口本身。
3. **多模态由派生模型补上。** Laya Vision、PlayJev、Visual Jev、PixelJev 把 System One 形态搬到了视觉上，本地延迟 30–65 ms，多问题共享视觉前缀还能再快数倍；decider-2b-vision 已被接进 ROS 2 局部路径选择。这对机载部署比托管 Jev 更有吸引力。
4. **在具身导航中，它的位置是战术 / 语义层，也可探索 Agent 记忆控制。** 感知、几何、候选生成、安全与控制留在本地；System One 决策头比较已验证的候选、判断风险、决定是否升级。C²Nav、VerNav、O2C-Nav 支持候选比较与验证接口；Jev-Mem 则提供了记忆管理的通用 Agent 先例，其导航收益仍需独立验证。
5. **架构上合理，证据上未知。** 现有具身 demo 都是单次或单种子仿真，没有 VLN 基准结果。它值得的是一组对照严格的 latency–accuracy–safety 实验，而不是对厂商倍数的复述。

## 7. 后续跟踪

- TypeSafe 是否公开技术报告、模型卡、RLCD 与并行采样细节，以及是否推出多模态版本；
- 视觉 System One 派生模型是否出现导航 / 具身数据上的训练与评测；
- 独立的校准、顺序偏差、命名偏差与重复稳定性研究；
- `jev_fsd`、`jev-drone`、Embodied Jev 的固定种子复现；
- R2R-CE / OpenNav 上停止判断与候选比较两个最小实验的结果。

## 参考资料

**官方**

1. TypeSafe AI. *Introducing System One Models and Jev*. [typesafe.ai/blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
2. TypeSafe AI. 官网与 workflow eval：[typesafe.ai](https://typesafe.ai/)；[evals.typesafe.ai](https://evals.typesafe.ai/)
3. TypeSafe Docs：[Introduction](https://docs.typesafe.ai/introduction)、[Models](https://docs.typesafe.ai/models)、[Primitives](https://docs.typesafe.ai/primitives)、[State](https://docs.typesafe.ai/concepts/state)、[System One](https://docs.typesafe.ai/concepts/system-one)、[Jaggedness: jev-1.13](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
4. MindStudio. *Jev Explained*. [mindstudio.ai](https://www.mindstudio.ai/blog/jev-system-one-model-launch)

**派生模型**

5. Laya. [NandhaKishorM/laya](https://github.com/NandhaKishorM/laya)
6. AnyJev. [MorrisZJ/AnyJev](https://github.com/MorrisZJ/AnyJev)
7. minojev. [zeredy879/minojev](https://github.com/zeredy879/minojev)
8. Laya Vision. [r33drichards/laya-vision](https://github.com/r33drichards/laya-vision)
9. PlayJev. [OmniJev/PlayJev](https://github.com/OmniJev/PlayJev)
10. Jev Visual. [hr98w/jev-visual](https://github.com/hr98w/jev-visual)
11. Prosodia. [alperiox/audio-jevlike](https://github.com/alperiox/audio-jevlike)
12. jev-vision. [JeremyEltho/jev-vision](https://github.com/JeremyEltho/jev-vision)
13. 项目汇总：[cobanov/awesome-jev](https://github.com/cobanov/awesome-jev)；[AbdelStark/awesome-typesafe-jev](https://github.com/AbdelStark/awesome-typesafe-jev)

14. Nokia AnyJev 报道. [MarkTechPost](https://www.marktechpost.com/2026/09/23/nokia-open-sources-anyjev-a-training-free-layer-that-turns-any-open-llm-into-a-calibrated-decision-model/)
15. decider-2b-vision 与 ROS 2 集成. [NOPLAB/jev_navigation](https://github.com/NOPLAB/jev_navigation)

**派生模型论文（arXiv）**

16. Ren et al. *Open-Jev Judgments on CallScreenBench: Calibrated One-Pass Scam Screening with a Small Language Model*. [arXiv:2609.23959](https://arxiv.org/abs/2609.23959)
17. Yu, Yao. *Visual Jev: Accurate and Efficient Decisions from Shared Visual Context*. [arXiv:2609.25845](https://arxiv.org/abs/2609.25845)
18. Zhou, Yang, Zhao. *From Text Decisions to Pixels: A Study of Jev-Style Visual Choice Model*. [arXiv:2609.29283](https://arxiv.org/abs/2609.29283)
19. Piskorz, Kobalczyk, van der Schaar. *Eliciting Numerical Predictive Distributions of LLMs Without Autoregression*. ICLR 2026. [arXiv:2603.02913](https://arxiv.org/abs/2603.02913)

**Jev 应用论文（arXiv）**

20. Jiang, Li, Li. *Jev-Mem: System-One-Controlled Agentic Memory for Efficient AI Agents*. [arXiv:2609.23986](https://arxiv.org/abs/2609.23986)
21. Wu, Lim. *REFLEX with Jev for Efficient Selective Control in LLM Agents*. [arXiv:2609.26532](https://arxiv.org/abs/2609.26532)
22. dos Santos. *Calibrated Decision Models for Autonomous Penetration-Testing Harnesses: JEV and Laya as System One Decision Layers*. [arXiv:2609.28940](https://arxiv.org/abs/2609.28940)

**独立评测**

23. [Jev After Eight Days of Independent Tests](https://dev.to/aws-builders/jev-after-eight-days-of-independent-tests-level-with-mid-price-llms-behind-the-frontier-1c60)
24. [Convex Decision Evals](https://github.com/get-convex/convex-evals)
25. [Jev vs Laya: Same Labels, Same Questions](https://anth.us/blog/jev-vs-laya/)
26. [Nautilus 校准研究](https://github.com/chunxiaoxx/nautilus-compass)
27. [jev-orderby-bench](https://github.com/yodablocks/jev-orderby-bench)
28. [Jev Does Not Play Dice](https://github.com/KantaHayashiAI/jev-does-not-play-dice)

**导航与校准研究（arXiv）**

29. C²Nav. [arXiv:2609.15142](https://arxiv.org/abs/2609.15142)
30. VerNav: Verifier-First Low-Latency Vision-and-Language Navigation. [arXiv:2609.00920](https://arxiv.org/abs/2609.00920)
31. O2C-Nav. [arXiv:2609.06476](https://arxiv.org/abs/2609.06476)
32. Peng et al. *Slow Brain, Fast Planner: Latency-Resilient VLM-Augmented Urban Navigation*. [arXiv:2606.20458](https://arxiv.org/abs/2606.20458)
33. Ding et al. *AdaNav: Adaptive Reasoning with Uncertainty for Vision-Language Navigation*. [arXiv:2509.24387](https://arxiv.org/abs/2509.24387)
34. Gong et al. *ABot-N1: Toward a General Visual Language Navigation Foundation Model*. [arXiv:2607.10383](https://arxiv.org/abs/2607.10383)
35. Zollo, Zemel. *Confidence Calibration in Vision-Language-Action Models*. [arXiv:2507.17383](https://arxiv.org/abs/2507.17383)
36. Yang et al. *The Mirage of Calibrated Confidence: Trajectory-Independence of Verbalized Confidence in Vision-Language Models*. EMNLP 2026. [arXiv:2609.18453](https://arxiv.org/abs/2609.18453)
37. Ren et al. *Robots That Ask For Help: Uncertainty Alignment for Large Language Model Planners* (KnowNo). CoRL 2023. [arXiv:2307.01928](https://arxiv.org/abs/2307.01928)
38. Zheng et al. *Large Language Models Are Not Robust Multiple Choice Selectors* (PriDe). ICLR 2024. [arXiv:2309.03882](https://arxiv.org/abs/2309.03882)

**具身 demo**

39. [JEV_SMARTROBOTCONTROL](https://github.com/mahajanparth/JEV_SMARTROBOTCONTROL)；[jev_navigation](https://github.com/NOPLAB/jev_navigation)；[jev_fsd](https://github.com/BrendanH18/jev_fsd)；[jev-drone](https://github.com/RomanSlack/jev-drone)；[Embodied Jev](https://github.com/FBddcz/embodied-jev)；[JevPilot](https://github.com/standardagents/jevpilot)
