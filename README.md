## Bài làm của học viên — Đỗ Thị Thu Hằng (2A202603840, L3B)

**Đề tài:** so sánh 3 chiến lược dữ liệu (A: chunk cố định, B: chunk theo heading, C: B + filter metadata `part`) trên tài liệu kỹ thuật **PostgreSQL 16** (docs chính thức, 36 trang section hợp lệ), embedding `intfloat/multilingual-e5-base`, lưu bằng PostgreSQL + pgvector.

**Báo cáo:** [report/individual/2A202603840_DoThiThuHang.md](report/individual/2A202603840_DoThiThuHang.md)

### Cài đặt (Windows CMD, Python 3.11–3.14, Docker)
```cmd
cd starter
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m pip install requests beautifulsoup4 lxml sentence-transformers tqdm
copy .env.example .env
docker compose -p day6_student_starter up -d --wait
python scripts\check_setup.py
```
Phiên bản đã dùng: xem `starter/requirements-lock.txt` (Python 3.13.14, sentence-transformers 6.3.0, torch 2.15.0, PostgreSQL 16.16, pgvector 0.8.7). Không commit `.env`.

### Chạy lại (từ thư mục `starter/`)
```cmd
python -m src.crawl_pg_docs      # tải docs v16 -> data/manifest.json, data/pages/, results/ingest_log.csv
python -m src.lab6 ingest        # chunk A/B, embedding, nạp pgvector (chạy 2 lần: số dòng không đổi)
python -m src.lab6 validate      # kiểm tra benchmark (26 câu, evidence nằm nguyên văn trong trang gold)
python -m src.lab6 evaluate      # top-3 cho A/B/C -> results/trace_*.jsonl, results/metrics.csv
python -m src.lab6 audit         # tạo mẫu chấm thủ công (coherence, metadata, grounding)
```

### Dữ liệu và kết quả
| Đường dẫn | Nội dung |
|---|---|
| `data/manifest.json`, `data/legal_notice.txt` | nguồn, version, quyền, quy tắc đếm trang, danh sách trang |
| `data/pages/` | văn bản đã chuẩn hóa của 36 trang hợp lệ |
| `benchmark/questions.jsonl` | 26 câu (19 dev / 7 test, 6 câu filter) kèm evidence |
| `artifacts/experiment_log.csv` | cấu hình và kết quả A/B/C |
| `results/` | log ingest, thống kê, trace top-3, metrics, nhãn audit |
| `starter/src/crawl_pg_docs.py`, `starter/src/lab6.py` | mã pipeline |

HTML gốc được cache ở `data/raw_html/` (không commit); chạy lại `crawl_pg_docs` để tải lại.

---

# Day 06 · Data Ingestion Engineering

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.