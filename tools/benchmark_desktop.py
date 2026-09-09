"""Reproducible catalog benchmark. Creates only synthetic inputs in a temp folder."""
from __future__ import annotations
import json
import logging
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from emailtools.pipeline import analyze
from emailtools.plans import options_for_mode
from dataclasses import replace


def main():
    with tempfile.TemporaryDirectory(prefix="EmailTools_benchmark_") as temporary:
        root = Path(temporary)
        source = root / "mails"
        source.mkdir()
        size = 0
        for index in range(1000):
            msg = EmailMessage()
            msg["Subject"] = f"합성 메일 {index}"
            msg["From"] = "benchmark@example.com"
            msg.set_content("합성 성능 검증")
            rows = "".join(f"<tr><td>항목 {(index*10+j)%1000:04d}</td><td>값 {index}-{j}</td></tr>" for j in range(100))
            msg.add_alternative(f"<table><tr><th>항목</th><th>값</th></tr>{rows}</table>", subtype="html")
            data = msg.as_bytes()
            (source / f"mail_{index:04d}.eml").write_bytes(data)
            size += len(data)
        tracemalloc.start()
        start = time.perf_counter()
        result = analyze(source, replace(options_for_mode("analyze"), save_attachments=False), root / "spool", logging.Logger("benchmark"))
        analysis_seconds = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        catalog = result.catalog
        assert len(catalog.fields) == 1000
        assert sum(len(entries) for entries in catalog.occurrences.values()) == 100000
        samples = []
        for index in range(220):
            start = time.perf_counter()
            catalog.query(query="항목" if index % 2 else "값 1", search_values=not index % 2,
                sort=("common", "coverage", "repeat", "first")[index % 4], page=index % 10)
            duration = (time.perf_counter() - start) * 1000
            if index >= 20:
                samples.append(duration)
        report = dict(platform=platform.platform(), processor=platform.processor(), python=sys.version,
            mail_count=1000, candidate_count=1000, occurrence_count=100000, input_bytes=size,
            analysis_seconds=round(analysis_seconds, 3), python_peak_mib=round(peak / 1024**2, 2),
            warm_query_p95_ms=round(sorted(samples)[int(len(samples)*.95)-1], 3),
            query_median_ms=round(statistics.median(samples), 3),
            notes="Synthetic HTML tables; Python allocation peak, not whole-process memory. Analysis timing includes tracemalloc overhead. No real email performance claim.")
        (ROOT / "docs/desktop-benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
