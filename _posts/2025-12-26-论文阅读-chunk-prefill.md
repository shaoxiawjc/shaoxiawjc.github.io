---
layout: post
title: "【论文阅读】Chunk Prefill"
date: 2025-12-26 22:59 +0800
---



# Chunk Prefill

[2308.16369\] SARATHI: Efficient LLM Inference by Piggybacking Decodes with Chunked Prefills](https://arxiv.org/abs/2308.16369)



之前一直对于 Chunk Prefill 是一个概念上的模糊理解，大致如下：

- 将 Prefill 拆成多个 chunk 进行
- chunk prefill 可以和 decode 在同一个 batch 中执行



重读一下进行回顾





# Background



# Decode Block Arch


![image-20251226231338290](/assets/images/image-20251226231338290.png)
