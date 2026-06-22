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
