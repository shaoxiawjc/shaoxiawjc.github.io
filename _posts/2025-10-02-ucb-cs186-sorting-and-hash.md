---
layout: post
title: UCB-CS186 Sorting and Hash
date: 2025-10-02 10:49 +0800
math: true
---

# Sorting & Hash



# Sorting



## 背景

在数据库场景中，我们不可能将所有数据都放在内存中进行排序，因此我们需要其他的排序算法。

## Two Way External Merge Sort

首先是一个较简单的外部排序算法，具体流程如下：

- conquer 阶段：先对单个 Page 里的记录进行排序
- Merge Sort 阶段：对每一个 Page 进行合并，我们将一次合并的结果称位 sorted run
- 重复产生 Merge Sort，直到只剩下一个 Merge Sort

下图为一个例子：

![image-20251002105720429](/assets/images/image-20251002105720429.png)


## Analyse：Two Way External Merge Sort

**IO 次数**

我们可以对上述的算法进行 I/O 次数的分析。

首先我们需要直到，一次数据的传递需要 $$ 2*N $$ 次 I/O，因为我们需要从磁盘里读出 Page，然后排序后再写入磁盘。

其中 N 为需要的 Page 的数量。

接下来的计算就比较简单了，首先是 Conquer 阶段，它是排序的起点，所以需要一次数据传递，然后开始进行 Merge Sort 这个过程。我们可以很容易地得到需要  $$ \lceil{log_{2}{N}}\rceil $$。所以最后需要的次数为 $$ 2*N*(1 + \lceil{log_{2}{N}}\rceil) $$ 次 IO。

**Buffer Page**

对于 Conquer 阶段，我们只需要加载一个 Page，然后在 Page 里排序后再写回即可，所以只需一个 Buffer Page。

对于 Merge Sort 阶段，我们需要对比两个 Page，因此首先需要 2 个 Input Buffer Page 来作为输入缓存区。

接着我们可以思考一下 Merge Sort 应该如何进行。答案是还需要一个输出缓冲区 Output Buffer Page，然后对输入缓存区里的数据逐个比较，并写入到 Output Buffer Page 中。因此需要 3 个 Buffer Page。



我们可以发现，这个算法没有完全利用我们的内存，因此我们可以设计一个更好的算法，来完全利用我们的内存。



## Full External Sort

假设我们现有 B 个可用的 Page，作出如下优化：

Conquer 阶段优化：一次加载 B 个 Page 进行排序，而不是只排序一个 Page。

Merge Sort 阶段优化：一次合并超过 2 个 Page。我们需要一个 Page 作输出缓冲区，一次可以一次性加载 B - 1个 Page 到内存中进行 Merge Sort。

如下图：

![image-20251002111904991](/assets/images/image-20251002111904991.png)



## Analyse：Full External Sort

**IO 次数**

我们可以发现 Full External Sort 减少的是 Merge Sort 的次数。

首先是 Conquer 阶段，它产生了 $$ \lceil N/B \rceil $$ 组需要 Merge Sort 的 sorted runs。

接着，对于每一次的 Merge Sort，我们需要将要排序的数量除以 $$ B-1 $$ 而不是 2

因此得到 IO 次数为 $$ 2*N*  (1 + \lceil{log_{B-1}{N/B}}\rceil) $$







# Hash

场景同排序一样，我们不能将所有数据都放入内存中，不能直接构建一个完整的 Hash 表来实现 Group By，所以我们需要一个外部 Hash 算法。



## 基本算法

使用分治思想，具体如下：



- divide：划分区域
  - 使用哈希函数将数据哈希到 B - 1 个分区上。分区是一组有着相同哈希值的 Pages。同时，我们有 B - 1个输出缓冲区，当我们的输出缓冲区的 Page 填满的时候，我们把它写入到磁盘，对于同一个分区的 Pages，它们写入磁盘的位置应该是相邻的。
  - 对于每一个分区，做如下判断：
    - 如果分区的 Page num 大于 B ，重复 divide，注意要使用不同的哈希函数
    - 如果小于等于，进入 conquer 阶段
- conquer：构建实际的哈希表



例子如下：

![image-20251002114644973](/assets/images/image-20251002114644973.png)





