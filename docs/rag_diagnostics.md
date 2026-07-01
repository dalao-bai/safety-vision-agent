# RAG 检索诊断与优化指南

> 适用于 `backend/app/retrieval/standards.py` 的混合检索管道（Dense + BM25 + RRF + CrossEncoder）

---

## 1. 快速判断"不准"的层次

RAG 的问题出在四层中的哪一层，决定了怎么修：

```
用户提问
    │
    ├── [层1] 分块  ── 条文被切烂了？关键信息跨块丢失？
    ├── [层2] 召回  ── Dense / BM25 有没有把相关 chunk 捞出来？
    ├── [层3] 融合  ── RRF 权重是否让噪声块排到了相关块前面？
    └── [层4] 重排  ── CrossEncoder 有没有把最相关的推到最前？
```

---

## 2. 运行评估

### 2.1 生成评估数据集

```bash
cd backend
python scripts/gen_eval_dataset.py   # 输出 eval_dataset.json
```

数据集格式：每条样本含 `question` + `relevant_chunk_ids`（人工标注的相关块 ID）。

### 2.2 跑指标

```bash
# 完整管道（含重排）
python scripts/eval_rag.py --no-gen --top-k 5

# 关掉 CrossEncoder，对比贡献
python scripts/eval_rag.py --no-gen --no-rerank --top-k 5

# 同时输出每条问题的详细结果
python scripts/eval_rag.py --no-gen --out metrics.json
```

---

## 3. 读懂指标

| 指标 | 含义 | 健康值参考 |
|---|---|---|
| `context_recall` | 相关 chunk 被召回的比例 | > 0.8 |
| `context_precision` | 召回结果中相关 chunk 的比例 | > 0.5 |
| `mrr` | 第一个相关结果的排名倒数均值 | > 0.6 |
| `ndcg@k` | 综合考虑排名和相关性的得分 | > 0.6 |

### 症状 → 层次对应

| 症状 | 说明 | 定位层次 |
|---|---|---|
| recall 低 | 相关 chunk 根本没被召回 | 层1（分块）或层2（召回） |
| precision 低但 recall 高 | 召回了但夹带太多噪声 | 层3（RRF）或层4（重排） |
| mrr 低 | 相关结果排在后面 | 层4（重排没起效） |
| 有无 rerank 指标差异小 | 重排模型没贡献 | 重排模型未加载或未命中 |

---

## 4. 诊断具体哪个问题召回失败

```bash
python -c "
import json
d = json.load(open('metrics.json'))
for r in d['details']:
    if r['context_recall'] == 0:
        print(r['question'])
"
```

recall=0 的问题说明该知识点在向量库里完全找不到，可能原因：

1. 对应 `.md` 文件没有被 `build_standards_index.py` 处理到
2. 分块把关键条文切断，语义被稀释
3. embedding 语义不对齐（问题用口语，标准原文用术语）

---

## 5. 各层优化方法

### 层1：分块优化

相关参数（`.env`）：

```
CHUNK_MAX_CHARS=800      # 每块最大字符数
CHUNK_OVERLAP_CHARS=100  # 滑窗重叠字符数
```

- **条文被切断** → 减小 `CHUNK_MAX_CHARS`（如 600）使完整条文不被截断
- **上下文丢失** → 增大 `CHUNK_OVERLAP_CHARS`（如 150）保留跨块上下文
- **极长节段** → 检查 OCR 输出是否缺少标题层级，导致整个章节成一块

代码位置：`backend/app/retrieval/standards.py:14` `chunk_markdown()`

### 层2：召回优化

相关参数：

```
RETRIEVAL_TOP_K_DENSE=20   # 向量召回数量
RETRIEVAL_TOP_K_BM25=20    # BM25 召回数量
```

- **Dense 不准** → 检查 embedding 模型；中文专业术语建议用中文专用 embedding 模型
- **BM25 不准** → 当前用字符级分词（`list(query)`），适合中文，可考虑换 jieba 词语级
- **都不准** → 扩大召回数量（如各 30），给 RRF 更多候选

### 层3：RRF 融合优化

相关参数：

```
RETRIEVAL_RRF_K=60    # RRF 平滑参数，越大越平等对待两路结果
```

- `k` 越小 → 靠前排名权重越大，头部结果影响更显著
- `k` 越大 → 两路结果更均等融合
- 若 Dense 质量明显好于 BM25，可降低 `k`（如 30）放大 Dense 优势

代码位置：`backend/app/retrieval/standards.py:158` `_rrf_fusion()`

### 层4：重排优化

相关参数：

```
RERANKER_MODEL=BAAI/bge-reranker-base
RERANKER_ENABLED=true
RETRIEVAL_FINAL_K=5    # 重排后保留条数
```

**确认重排是否生效：**

```python
# 在 Python 中测试
from app.retrieval.standards import StandardsIndex
from app.config import get_settings
s = get_settings()
idx = StandardsIndex(persist_dir=s.chroma_dir, embedder=..., reranker_enabled=True)
idx._ensure_reranker()
print(idx._reranker)  # None 说明模型未加载
```

- 模型未加载 → 检查 `HF_HUB_OFFLINE=1` 时模型是否已缓存到本地
- 重排提升不大 → 换更强的 `bge-reranker-large` 或 `ms-marco-MiniLM-L-12-v2`

---

## 6. 对比实验模板

```bash
# 基准：只用 Dense
python scripts/eval_rag.py --no-gen --no-rerank --out baseline_dense.json

# 加 BM25+RRF
python scripts/eval_rag.py --no-gen --no-rerank --out baseline_rrf.json

# 完整管道
python scripts/eval_rag.py --no-gen --out full_pipeline.json

# 对比三组 recall
python -c "
import json
for f in ['baseline_dense.json', 'baseline_rrf.json', 'full_pipeline.json']:
    d = json.load(open(f))
    s = d['summary']
    print(f'{f}: recall={s[\"mean_context_recall\"]:.3f} mrr={s[\"mean_mrr\"]:.3f}')
"
```

---

## 7. 实时查看单次检索过程

在 `debug JSONL` 里找 `tool_result` 事件中 `tool_name=search_standards` 的条目，`result.hits` 字段包含每次检索返回的完整 chunk 列表（含 source 和 heading），可以人工判断相关性。

```bash
cat runtime/debug/{session_id}.jsonl | python -m json.tool | grep -A 30 '"tool_name": "search_standards"'
```
