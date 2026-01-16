---
layout: post
title: speculative decoding
date: 2026-01-09 15:43 +0800
---

# Speculative Decoding

# 背景

当前的大语言模型在推理阶段普遍采用自回归解码，即串行的 token 生成，在 Decode 阶段通常面临着严重的内存带宽瓶颈，会导致大量的计算资源被限制。

为了提高 Decode 的效率，一个思路是提高解码过程的算术强度（即总浮点运算次数 FLOPs 与数据传输量之间的比值），减少解码步骤。因此就有了推测解码（Speculative Decoding）。其经典的模型结构如下：

![alt text](/assets/images/2026-01-09-speculative-decoding/image.png)

引入一个 草稿模型（Draft Model），其模型大小通常远小于主模型，同时 tokenizer 和主模型相同。草稿模型自回归的生成 k 个 token，并交给主模型一次并行的去验证，从而减少 decode 的次数。

为什么会有效？

在一般场景中，大模型自回归生成的每一个 token 的难度不一样，简单的 token 大小模型都可以生成，比较困难的 token 可能只能大模型来生成。

比如说对于句子 "The capital of South Korea is ?" 这个 Prompt，草稿模型的回答很容易生成 The capital of ... 然后就被目标模型所接受。

Speculative Decoding 的工作有很多，这里列出几个比较主流的 work 进行讲解。

- Speculative Decoding
- Medusa
- EAGLE
- DeepSeek MTP
- DeepSeek MTP


# Speculative Decoding

最早的工作是由 Google 和 DeepMind 提出的两篇 Speculative Decoding，其模型结构和算法基本都一样，都是 Draft then Verify
最早的工作是由 Google 和 DeepMind 提出的两篇 Speculative Decoding，其模型结构和算法基本都一样，都是 Draft then Verify
伪代码如下：
![alt text](/assets/images/2026-01-09-speculative-decoding/image-4.png)
假设我们每次草稿模型生成连续的 K 个 token，当前序列长度为 t
1. 使用草稿模型自回归的生成 K 个 token（需保留对应 token 的 prob）
2. 使用主模型并行的验证 K 个序列（得到每一个 token 对应的主模型的 prob）
3. 从生成的第一个 token 开始，进行验证，使用如下的拒绝采样 **Rejection Sampling**
	- 采样一个 0 - 1 之间的随机数 r
	- 判断 r 是否小于主模型的prob比去草稿模型的prob
4. 如果所有的 token 都验证成功，还可以额外获得一个 token


> 使用 Speculative Decoding 的时候就无法指定类似 Topk，Top-P，temperature 等采样方法了，如果要使用的话，其实是针对草稿模型进行这些采样方法。

其中草稿模型的接受率是显著影响其加速效果的，一些草稿模型的训练方法如下：
- 将草稿模型和主模型从一开始就放到一起训练
- 使用序列级蒸馏，也就是学生模型不只是学习教师模型输出的一个 token，而是独立的去预测每一个 token（预测的 token 之间相互独立）
- 将目标模型的一部分激活值设置为草稿模型的输入，由此来训练草稿模型
但是一种简单的做法实际上就是大小模型各训练一个，在工业界中也比较常见

Deepmind 论文中给出的加速效果大约为 2 ～ 3倍左右

![Pasted image 20260111212352](/assets/images/2026-01-09-speculative-decoding/Pasted image 20260111212352.png)

不足：
虽然 Draft-Verify 在多个场景下可以提高效率，但是还是存在如下的缺点：
- 加速效果不稳定：取决于接受率，如果接受率持续较低，加速效果不明显
- 难以获得小而准的 Draft Model：要让草稿模型既轻量又能精准模拟大模型的行为非常困难。现实中经常出现 distribution shift（分布偏移），即草稿模型与大模型输出之间存在差异，导致预测失败率上升。
- 训练和泛化困难：需要额外训练一个 Draft Model，训练出来的模型基本无法迁移到其他的基础模型或数据集
- 系统架构复杂：一次推理需要俩个模型，部署的复杂度和成本较高


# Medusa

相比于引入一个单独的草稿模型，Medusa 提出了一种新的高效的思路，在模型的最后的输出层加入多个轻量级的解码头（Medusa heads），每一个 medusa head 预测一个 token，其权重和模型本身一起训练。

根据训练的过程不同，medusa 分为
- medusa-1：模型权重冻结
- medusa-2：模型和预测头一起训练

![alt text](/assets/images/2026-01-09-speculative-decoding/image-3.png)
在推理过程中，medusa 会对于每一个 medusa head 使用不同的 topk 来生成 topk 个 token，并使用 Tree Attention 来进行并行处理，最后通过 typical acceptance 来进行筛选合理的序列路径。

## Train Medusa Head

第 k 个解码头的定义如下，类似 LMHead
第 k 个解码头的定义如下，类似 LMHead

![alt text](/assets/images/2026-01-09-speculative-decoding/image-1.png)
如何训练 Medusa Head？

Medusa-1
- 基于预训练的模型进行训练
- 冻结模型权重，只训练 medusa heads
- 可以引入 Lora 来保证生成质量
Medusa-2
- 同时训练模型和 medusa heads
- 可以保证减少分布偏移的情况

## Tree Attention

Medusa 在推理过程中的每一个头都会输出 topk 个候选 token，然后将所有 heads 生成的序列进行笛卡尔积运算，就得到了我们的候选序列，最后验证并选取前缀最长的序列。如果不使用 Tree Attention，这些序列的每一个都需要当作一个请求进行验证，实际上我们可以采用更加高效的方法，也就是 Tree Attention。


将每一个候选 token 按照顺序组成树状数组，比如：
- 假设第一个 head 输出 `[It, I]`，第二个 head 输出 `is ' the`
- 这可以构成 `2*3=6` 条路径
- 我们可以将路径变成线性的数组，然后使用 tree mask 进行并行计算，避免了对每一个路径都单独计算，如下

```
["It", "I", "is", "'", "the", "is", "'", "the"]
```

对应的 Tree Mask 设置
- `It` 和第二个节点的三个 token 可以有注意力
- `It` 不能和相同节点的 `I` 有注意力

类似下图中的注意力矩阵，就是将 AttentionMask 变成了 Tree Mask，相当于一次计算就把所有的路径计算完，得到每一个序列最后的 logits。

![alt text](/assets/images/2026-01-09-speculative-decoding/image-2.png)

Tree Attention 的优势：如果是早期的验证方式，其方法是将所有的候选序列放到同一个批次里，这会导致一些不必要的计算和空间浪费，比如可能树的根节点的 attention 被计算多次，同时作为 kvcache 也会造成冗余的存储，造成资源的浪费。而 Tree Attention 则可以避免上述的问题。

## Typical Acceptance

早期的 Speculative Decoding 的采采样策略使用的是拒绝策略，当设置使用 temperature 且温度较高的时候，草稿模型生成的 token 会比较偏理主流的分布，很容易被拒绝。导致解码效率的低下。

为了提高整体的推理效率，medusa。提出了 typical acceptance（典型接受）来解决上述的问题。该策略从 **截断采样（Truncation Sampling）** 的研究中汲取灵感，目标是扩大原始模型可接受的候选范围。方式如下我们从 Medusa 的每一个 head 中都获取到了多个 topk 个 tokens 之后，再次输入到模型中使用 Tree Attention 的到了每一个序列对应的 prob，如果草稿模型预测的 token 不超过某个阈值，就接受（有点类似 Top-P）
比如草稿模型通过某个高 temperature 生成了 "fun"。（上下文为 “The weather is”）
而输入到主模型进行验证，得到的 prob 为

|Token|概率|
|---|---|
|"nice"|0.35|
|"bad"|0.30|
|"cold"|0.15|
|"fun"|0.08|
|"wet"|0.06|
|"?"|0.03|
|"sad"|0.02|
|"quick"|0.01|
假设阈值为 0.9 则将概率从高加到低就有了
- "nice" → 0.35
- "bad" → 0.65
- "cold" → 0.80
- "fun" → 0.88 ✅
- "wet" → 0.94 ❌ 超出阈值
因此接受 fun。



## 加速效果

大约在 2.5 ～ 3.7 左右
![Pasted image 20260111212917](/assets/images/2026-01-09-speculative-decoding/Pasted image 20260111212917.png)

## 缺陷

由于 Medusa 的每一个头实际上是独立输出的，不会相互依赖，比如 第 4 个 token 不依赖第 3 个 token，导致丢失部分序列信息，因此 Medusa 的生成效果通常不是很好，同时也会导致草稿模型的接受率较低。

本质上效率较低的原因还是草稿部分的接受率较低，如果能提高草稿模型的接受率就可以达到高的推理性能。

本质上效率较低的原因还是草稿部分的接受率较低，如果能提高草稿模型的接受率就可以达到高的推理性能。


# Eagle

EAGLE（Extrapolation Algorithm for Greater Language-model Efficiency）提出了一种新颖的推测采样框架，其核心创新在于：
- 在特征层级而非传统的 token 层级进行自回归预测。特征序列比 token 序列更具规律性，使得预测更为简单有效。
- 通过引入提前一步的 token 序列，解决了特征预测中的不确定性问题，从而提升预测的准确性和草稿生成质量。
- 该方法无需对目标 LLM 进行微调，保证生成文本的分布与传统自回归解码一致，实现无损加速。


核心思路：
两个观点：
- 在特征层面进行自回归比在 token 层面进行自回归更简单
	- 这里的特征指的就是 LLM 的倒数第二层的输出，也就是 LMHead 的输入的 Hidden States。相比于直接使用 Token 序列，Hidden State 会更有规律性
	- 方案：引入一个草稿模型来自回归地去预测特征序列，然后直接使用主模型的 LMHead 来生成 token
- 采样过程的不确定性限制了性能
	- 在之前的工作中，草稿模型的接受率一旦较低，其性能就会变差，我们希望提高草稿模型预测的准确度来提高接受率，从而提高性能
	- 方案：多引入上一个 token 的特征，来提高预测的准确性

实现细节

草稿阶段（Drafting Phase）：
- 输入： 前一个时间步的特征序列，以及提前一步的 token 序列。
- 处理流程：
    - 将 token 序列转换为对应的 embedding 向量序列。
    - 将 embedding 序列与特征序列在维度上拼接。
    - 使用一个自回归头 (Autoregression Head) 来预测下一个特征。
    - 使用 LM Head 将该特征映射为 token 的概率分布，并从中采样出下一个 token。
    - 将预测得到的特征与采样的 token 添加至输入序列中，继续下一轮预测。
- 输出： 一棵由多个候选 token 构成的草稿树（draft tree）。
> 草稿模型的第一次 Forward 和之后的 Forward 有区别

验证阶段（Verification Phase）：
- 输入： 草稿树。
- 处理流程： 使用目标 LLM 对草稿树中的 token 逐一进行验证，判断其是否符合原始模型的分布。
- 输出： 最终被接受的 token 序列，作为模型输出的一部分。

![alt text](/assets/images/2026-01-09-speculative-decoding/image-5.png)
得到了草稿树之后，就可以使用 Tree Attention 在主模型上进行验证了。


EAGLE 之后的工作，大部分都是在优化如何提高草稿模型的接受率
- EGALE-2：优化了草稿树，提出了一些裁剪方法，将草稿树设置为动态草稿树来提高接受率
- EGALE-3：不只是使用倒数第二层特征，而是融合多层特征进行自回归，提高接受率
EAGLE 之后的工作，大部分都是在优化如何提高草稿模型的接受率
- EGALE-2：优化了草稿树，提出了一些裁剪方法，将草稿树设置为动态草稿树来提高接受率
- EGALE-3：不只是使用倒数第二层特征，而是融合多层特征进行自回归，提高接受率


加速效果
![Pasted image 20260111213037](/assets/images/2026-01-09-speculative-decoding/Pasted image 20260111213037.png)

# DeepSeek MTP

> DeepSeek Multi Token Prediction 这一部分是在 V3 论文中的一小部分，其目的是加速训练和提升训练质量，并不是加速推理性能，这里简单说明一下方法

DeepSeek MTP 的结构如下：
训练过程：
- 一个主模型加 n 个 MTP Module，其 LMHead 和 Embedding Layer 是共享的
- 主模型推理完成后，将 hidden state 传入第一个 MTP Module 生成下一个 token
- Module 之间串行生成
- 反向传播时会进行多次
推理过程：
仍然是 Draft-Verify 的过程
- 主模型先推理
- MTP Modules 生成 tokens
- 主模型验证



![Pasted image 20260111214331](/assets/images/2026-01-09-speculative-decoding/Pasted image 20260111214331.png)
MTP 的优势
- 有密集的监督信号，在普通的训练方法中，单个 token 实际上只被利用了一次，而在 MTP 中，一个 token 可以被利用多次
- 有长距离依赖训练，模型可以学习到长上下文的联系

MTP 和 EAGLE 的对比
- MTP 是高度集成在模型内部的，训练成本高。而 EAGLE 则可以使用蒸馏额外训练一个小的预测模型，成本较低。


# Ref

https://github.com/cr7258/ai-infra-learning/tree/main/lesson/04-speculative-decoding