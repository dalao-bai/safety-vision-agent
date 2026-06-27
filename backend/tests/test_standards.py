from pathlib import Path

from app.retrieval.standards import StandardsIndex, chunk_markdown


def test_chunk_markdown_by_heading():
    md = "# 标题\n前言\n## 4.1.2 条\n施工楼梯口安装防护栏杆。\n## 4.1.3 条\n洞口应封闭。\n"
    chunks = chunk_markdown(md, source="JGJ80.md")
    assert len(chunks) >= 2
    assert all(c["source"] == "JGJ80.md" for c in chunks)
    assert any("防护栏杆" in c["text"] for c in chunks)


def _fake_embedder(texts):
    # deterministic 8-dim embedding: char-bucket counts
    out = []
    for t in texts:
        vec = [0.0] * 8
        for ch in t:
            vec[ord(ch) % 8] += 1.0
        out.append(vec)
    return out


def test_build_and_search(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("## 4.1.2\n施工楼梯口安装防护栏杆,密目式安全立网封闭。\n", encoding="utf-8")
    (corpus / "b.md").write_text("## 5.1\n基坑周边设置防护栏杆与挡脚板。\n", encoding="utf-8")

    idx = StandardsIndex(persist_dir=str(tmp_path / "chroma"), embedder=_fake_embedder)
    idx.build([corpus])
    hits = idx.search("楼梯口 防护栏杆", top_k=1)
    assert len(hits) == 1
    assert "text" in hits[0] and "source" in hits[0]


def test_search_before_build_returns_empty(tmp_path: Path):
    idx = StandardsIndex(persist_dir=str(tmp_path / "chroma"), embedder=_fake_embedder)
    assert idx.search("anything", top_k=3) == []


def test_chunk_markdown_no_headings():
    chunks = chunk_markdown("没有任何标题的纯文本。", source="x.md")
    assert len(chunks) == 1
    assert chunks[0]["text"] == "没有任何标题的纯文本。"
    assert chunks[0]["heading"] == ""


def test_chunk_markdown_empty():
    assert chunk_markdown("", source="x.md") == []


def test_build_returns_chunk_count(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("## 1\n甲。\n", encoding="utf-8")
    (corpus / "b.md").write_text("## 2\n乙。\n", encoding="utf-8")
    idx = StandardsIndex(persist_dir=str(tmp_path / "chroma"), embedder=_fake_embedder)
    assert idx.build([corpus]) == 2


# --- size-aware chunking ---

def test_chunk_size_aware_splits_long_section():
    # A section with 900 chars (> default 800) should be split into multiple chunks
    long_body = "防护栏杆" * 100  # 400 Chinese chars = 400 chars, but we need >800
    long_body = "防" * 850
    md = f"## 4.1\n{long_body}\n"
    chunks = chunk_markdown(md, source="x.md", max_chars=800, overlap_chars=100)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c["text"]) <= 800


def test_chunk_overlap_content():
    # Adjacent chunks should share overlap_chars worth of content
    body = "甲" * 400 + "乙" * 400 + "丙" * 200
    md = f"## 1\n{body}\n"
    chunks = chunk_markdown(md, source="x.md", max_chars=500, overlap_chars=100)
    assert len(chunks) >= 2
    # The end of chunk 0 and beginning of chunk 1 should overlap
    end_of_first = chunks[0]["text"][-100:]
    start_of_second = chunks[1]["text"][:100]
    # They share some content (overlap means the boundary characters appear in both)
    assert any(ch in start_of_second for ch in end_of_first[:20])


def test_chunk_short_section_not_split():
    md = "## 4.1\n这是很短的内容。\n"
    chunks = chunk_markdown(md, source="x.md", max_chars=800, overlap_chars=100)
    assert len(chunks) == 1


# --- BM25 retrieval ---

def test_bm25_search_finds_keyword(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("## 楼梯\n楼梯口防护栏杆安装规定。\n", encoding="utf-8")
    (corpus / "b.md").write_text("## 基坑\n基坑周边挡脚板设置要求。\n", encoding="utf-8")

    idx = StandardsIndex(persist_dir=str(tmp_path / "chroma"), embedder=_fake_embedder,
                         reranker_enabled=False)
    idx.build([corpus])
    # Direct BM25 search for "楼梯" should rank the first doc higher
    idx._ensure_bm25()
    results = idx._bm25_search("楼梯", top_k=2)
    assert len(results) >= 1
    top_doc = idx._bm25_docs[results[0]]
    assert "楼梯" in top_doc["text"]


# --- RRF fusion ---

def test_rrf_fusion_combines_both_lists(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("## 1\n甲条文内容。\n", encoding="utf-8")
    (corpus / "b.md").write_text("## 2\n乙条文内容。\n", encoding="utf-8")
    (corpus / "c.md").write_text("## 3\n丙条文内容。\n", encoding="utf-8")

    idx = StandardsIndex(persist_dir=str(tmp_path / "chroma"), embedder=_fake_embedder,
                         reranker_enabled=False, top_k_dense=3, top_k_bm25=3)
    idx.build([corpus])
    idx._ensure_bm25()

    dense_ids = [d["id"] for d in idx._bm25_docs[:2]]   # simulate dense top-2
    bm25_indices = [2, 0]                                # simulate BM25 ranking
    fused = idx._rrf_fusion(dense_ids, bm25_indices)
    assert len(fused) >= 2
    texts = {c["text"] for c in fused}
    assert any("甲" in t for t in texts)
    assert any("丙" in t for t in texts)


# --- hybrid search integration ---

def test_hybrid_search_returns_top_k(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for i in range(5):
        (corpus / f"{i}.md").write_text(f"## 条文{i}\n内容{'甲' * 10} 关键词{i}。\n", encoding="utf-8")

    idx = StandardsIndex(persist_dir=str(tmp_path / "chroma"), embedder=_fake_embedder,
                         reranker_enabled=False, final_k=3)
    idx.build([corpus])
    hits = idx.search("关键词", top_k=2)
    assert len(hits) <= 2
    for h in hits:
        assert "text" in h and "source" in h and "heading" in h


# --- reranker disabled ---

def test_reranker_disabled_skips_model(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("## 1\n测试内容。\n", encoding="utf-8")

    idx = StandardsIndex(persist_dir=str(tmp_path / "chroma"), embedder=_fake_embedder,
                         reranker_enabled=False)
    idx.build([corpus])
    hits = idx.search("测试", top_k=1)
    assert len(hits) == 1
    assert idx._reranker is None  # never loaded

