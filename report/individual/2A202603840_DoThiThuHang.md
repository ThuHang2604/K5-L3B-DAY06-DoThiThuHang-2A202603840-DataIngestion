# Báo cáo cá nhân — Day 6

**Họ tên:** Đỗ Thị Thu Hằng · **MSSV:** 2A202603840 · **Lớp:** L3B

## Dữ liệu và pipeline
- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:** Tài liệu kỹ thuật PostgreSQL 16 (docs chính thức, bản 16.16, https://www.postgresql.org/docs/16/), 7 chương: Indexes, Concurrency Control, Performance Tips (Part *The SQL Language*) và Routine Database Maintenance Tasks, Backup and Restore, High Availability/Load Balancing/Replication, Reliability and the Write-Ahead Log (Part *Server Administration*). Quyền sử dụng: theo Legal Notice của docs v16 (đã lưu `data/legal_notice.txt`, URL ghi trong `data/manifest.json`). Truy cập ngày 2026-11-14.
  - Quy tắc tính: HTML không phân trang nên mỗi **trang section** là một đơn vị nguồn (`page_id` = slug), chỉ tính đơn vị có ≥1.500 ký tự sau chuẩn hóa. Đã xem 47 đơn vị, **giữ 36** (20 thuộc *The SQL Language*, 16 thuộc *Server Administration*), tổng 368.961 ký tự. 11 đơn vị bị loại (trang đầu chương chỉ có đoạn mở đầu ngắn hoặc section ngắn), chi tiết trong `results/ingest_log.csv`.
- **Chuẩn hóa, lỗi và giới hạn:** crawl bằng `src/crawl_pg_docs.py` (requests + BeautifulSoup); bỏ navheader/navfooter/mục lục con, chuẩn hóa Unicode NFC, giữ heading dạng markdown, giữ khối code nguyên vẹn; lưu cache HTML, manifest và log từng trang (`kept`/`skipped_short`/`skipped_empty`/`error`). Hai giới hạn phát hiện khi audit:
  1. Bộ trích xuất chỉ lấy các thẻ `h1–h4`, `p`, `li`, `pre`, `table`, nên **bỏ mất thẻ định nghĩa `<dt>`** (tên các mục trong danh sách định nghĩa). Ví dụ trang `explicit-locking`: các đoạn "Behaves similarly to FOR UPDATE..." mất tên chế độ khóa đang được mô tả (FOR NO KEY UPDATE, FOR SHARE, FOR KEY SHARE). Lỗi này làm chunk mất chủ thể (xem coherence dòng A/B `explicit-locking`).
  2. Heading và `section_title` còn dấu `#` ở cuối (ký hiệu liên kết của trang docs), lọt vào tiền tố chữ của chunk B; không ảnh hưởng nhãn đánh giá.
- **Embedding, vector store, metric, lệnh chạy, chi phí:**
  - Embedding: `intfloat/multilingual-e5-base` (local, CPU), sentence-transformers 6.3.0, torch 2.15.0, 768 chiều, vector chuẩn hóa. Query thêm tiền tố `query: `, tài liệu thêm `passage: `; giữ nguyên cho cả ba cấu hình.
  - Vector store: PostgreSQL 16.16 + pgvector 0.8.7 (Docker Compose của starter), bảng `chunks`, metric cosine (`<=>`), tìm kiếm **exact** (không có index ANN).
  - Môi trường: Python 3.13.14, Docker 28.4.0; phiên bản đầy đủ trong `starter/requirements-lock.txt`.
  - Lệnh (chạy từ `starter/`): `docker compose -p day6_student_starter up -d --wait` → `python -m src.crawl_pg_docs` → `python -m src.lab6 ingest` → `python -m src.lab6 validate` → `python -m src.lab6 evaluate` → `python -m src.lab6 audit`.
  - Chi phí: 0 USD (embedding local, không dùng API trả phí).
  - Nạp lại không nhân đôi: chạy `ingest` hai lần, số dòng trước/sau nạp lại là A 835 → 835, B 418 → 418 (chiến lược nạp lại: xóa theo `strategy` rồi chèn lại trong một transaction; `chunk_id` xác định: `<strategy>:<page_id>:<chỉ số>`).
- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:** mỗi chunk có `document_id` (`pg16-docs`), `source` (URL trang), `page` (page_id), cùng `part`, `chapter`, `section_title`, `chunk_index`, `start_char`, `end_char`. Trường lọc là **`part`** (kiểu text, hai giá trị: *The SQL Language*, *Server Administration*), lấy trực tiếp từ mục lục docs, không tự đặt; chọn vì nhiều chủ đề nằm ở cả hai Part (ANALYZE, khóa ACCESS EXCLUSIVE, hot standby) nên lọc theo Part có tác dụng phân biệt.

## Cấu hình và benchmark
- **A / B / C:**
  - **A:** chunk cố định 500 ký tự, overlap 50, gắn nguồn và trang, không lọc.
  - **B:** chunk theo heading/đoạn, gom đoạn tối đa 1.200 ký tự, khối code không bị cắt, đoạn cuối nhỏ (<300 ký tự) gộp vào đoạn trước, thêm tiền tố "tiêu đề trang > heading"; cùng metadata, không lọc.
  - **C:** dùng đúng index của B; **khác biệt duy nhất B–C** là thêm điều kiện `WHERE part = <giá trị>` cho câu hỏi có filter. Câu không có filter chạy không lọc (kết quả giống B).
- **≥20 câu, phân chia, filter, kiểm chứng evidence:** 26 câu tiếng Việt (`benchmark/questions.jsonl`): **19 dev / 7 test** (q01–q19 dev, q20–q26 test), chia trước khi chạy. 6 câu có filter theo `part` (4 dev: q12–q15; 2 test: q23, q24). Loại câu: 8 trực tiếp, 6 diễn đạt lại, 6 điều kiện/ngoại lệ, 6 câu filter. Mỗi câu có `expected_answer`, `gold_source_id`, `gold_page`, `evidence_quote` (trích nguyên văn tiếng Anh). Kiểm chứng bằng `python -m src.lab6 validate`: mọi evidence nằm nguyên văn trong trang gold sau chuẩn hóa, và giá trị filter khớp `part` của trang gold. Filter là input giả định được cung cấp trước khi truy xuất, không lấy từ gold.
- **Tiêu chí chọn chiến lược đã chốt trước khi xem test:** ưu tiên Evidence Hit@3 trên dev; nếu hòa thì xét grounding; nếu vẫn hòa thì xét tài nguyên (số chunk, thời gian). *Lưu ý trung thực:* lệnh `evaluate` in dev và test cùng lúc, và grounding được chấm trên 5 câu test; quyết định cuối vì vậy không hoàn toàn độc lập với test (xem phần hạn chế).

## Kết quả
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 11/19 | 16/19 | 835 | 129,6 s (ingest) | 0 |
| A | test | 4/7 | 6/7 | 835 | — | 0 |
| B | dev | 13/19 | 16/19 | 418 | 121,0 s (ingest) | 0 |
| B | test | 3/7 | 7/7 | 418 | — | 0 |
| C | dev | 14/19 | 16/19 | 418 (dùng index B) | 0 s thêm | 0 |
| C | test | 5/7 | 7/7 | 418 (dùng index B) | 0 s thêm | 0 |

Tổng 26 câu: Hit@1 A 15/26, B 16/26, C 19/26; Evidence Hit@3 A 22/26, B 23/26, C 23/26. Thời gian ingest lần chạy đầu: A 121,2 s, B 112,1 s (lần chạy lại 129,6 s và 121,0 s, nên đo thời gian dao động ~7%). Độ dài chunk: A median 500, p90 500, max 500 ký tự (tổng 408.911 ký tự do overlap); B median 984,5, p90 1.218, max 1.481 ký tự (tổng 386.564 ký tự gồm tiền tố). Chi tiết: `results/ingest_stats.json`, `results/metrics.csv`.

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 0,9 (n=10) | 15/15 | N/A (không dùng filter) | 0 / 1 / 4 → 1,8 |
| B | 1,6 (n=10) | 15/15 | N/A (không dùng filter) | 0 / 0 / 5 → 2,0 |
| C | 1,6 (cùng chunk với B; n=10) | 15/15 | 2/2 câu test có filter (dev: 4/4) | 0 / 0 / 5 → 2,0 |

Ghi chú: filter tuân thủ 2/2 là kết quả hiển nhiên do điều kiện `WHERE` ép buộc; giá trị thực của filter nằm ở Hit@1 và thứ hạng.

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu:** trace top-3 đầy đủ ở `results/trace_A.jsonl`, `trace_B.jsonl`, `trace_C.jsonl`; nhãn và lý do từng dòng ở `results/audit_coherence.csv`, `audit_metadata.csv`, `audit_grounding.csv`. Cách chọn mẫu (xác định trước khi xem điểm): coherence lấy 10 `page_id` đầu theo thứ tự chữ cái, vị trí là điểm giữa trang, chấm chunk bao phủ vị trí đó (nếu rơi vào khoảng trống giữa hai chunk thì lấy chunk gần nhất); metadata và grounding lấy 5 câu test có id nhỏ nhất (q20–q24) × top-3. Thang coherence/grounding 0/1/2 theo `GUIDE.md`; quy ước coherence: chunk bị cắt giữa từ/câu ở cả hai đầu không được quá 1 điểm.

**Phương pháp chấm (ghi rõ theo quy định):** nhãn coherence và grounding do Claude (Anthropic) đề xuất lần đầu kèm lý do, sau đó tác giả đọc lại từng dòng và xác nhận hoặc sửa; không phải chấm độc lập. Với metadata, kiểm tra bằng một script đối chiếu `source`, `page`, `part`, `chapter` của 45 bản ghi với manifest và kiểm tra nội dung chunk nằm trong trang nguồn tương ứng, kết hợp việc tác giả mở thử một số URL docs. Người chấm cuối cùng là tác giả; nguy cơ thiên lệch được nêu ở phần hạn chế.

## Phân tích và kết luận
- **So sánh A–B (đổi chunking):** Hit@1 dev tăng 11/19 → 13/19, Hit@3 dev bằng nhau (16/19); trên test Hit@3 tăng 6/7 → 7/7 nhưng Hit@1 giảm 4/7 → 3/7. Coherence tăng rõ từ 0,9 lên 1,6 và grounding từ 1,8 lên 2,0: mọi chunk A đều bị cắt giữa từ hoặc giữa câu ở ít nhất một đầu nên không đạt 2 điểm, còn chunk B giữ nguyên đoạn kèm tiêu đề mục. B chỉ có 418 chunk so với 835 của A, thời gian ingest tương đương. Đánh đổi: chunk B dài hơn (median ~985 ký tự) nên một chunk có thể trộn hai ý (ví dụ `different-replication-solutions`, điểm coherence 1).
- **So sánh B–C (chỉ thêm filter):** Hit@1 tăng 16/26 → 19/26 (dev 13→14, test 3→5), Hit@3 không đổi (23/26), không tốn thêm tài nguyên. Ví dụ q23 (test): B xếp `indexes-examine` ở top-1 vì trang đó cũng nói về ANALYZE, còn C với `part = Server Administration` đưa chunk của `routine-vacuuming` chứa đúng câu bằng chứng lên top-1, và cả ba chunk C đều thuộc trang đúng. Giới hạn: chỉ 6/26 câu có filter nên tác động chỉ đo được trên 6 câu; grounding B và C đều đạt 2,0 nên khác biệt B–C chủ yếu ở thứ hạng.
- **Hai ví dụ sai:**
  1. **q01 (dev, gold `indexes-types`) ở cấu hình A:** top-3 đều thuộc trang khác (`indexes-ordering`, `indexes-partial`, `indexes-expressional`); B đưa đúng trang lên hạng 2. Giả thuyết: chunk 500 ký tự mất tiêu đề trang nên khó phân biệt các trang cùng chủ đề index (chưa kiểm chứng riêng).
  2. **q11 (dev, gold `explicit-locking`) ở B và C:** top-1 là trang `hot-standby` (cùng thuật ngữ ACCESS EXCLUSIVE), hai chunk còn lại đúng trang nhưng không chứa câu bằng chứng, nên Hit@3 = 0. Câu này không có filter nên C không cứu được. Có thể liên quan lỗi bỏ thẻ `<dt>` ở trang `explicit-locking` (mất tên chế độ khóa), chưa kiểm chứng riêng.
- **Quan sát thêm (tính sau khi chạy, không thay định nghĩa chính):** Hit@3 mức trang đạt A 25/26, B 26/26, C 26/26, so với Evidence Hit@3 chặt hơn là 22/23/23. Phần lớn lỗi còn lại là tìm đúng trang nhưng câu bằng chứng nằm ở chunk khác (ví dụ q16 ở B/C và q19, q26 ở A), cho thấy định nghĩa "đủ evidence trong một chunk" rất nghiêm ngặt.
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:** Theo tiêu chí đã chốt: Hit@3 dev hòa 16/19 cả ba; grounding B = C = 2,0 > A = 1,8; tài nguyên B = C (418 chunk) < A (835 chunk). Vậy **A bị loại; B và C hòa theo tiêu chí**. Chọn **C làm cấu hình khuyến nghị** khi biết trước phạm vi (Part), vì Hit@1 cao hơn (19/26 so với 16/26) và không tốn thêm tài nguyên; đây là quan sát phụ, không thuộc tiêu chí chốt trước. Khi không biết Part trước thì dùng B (C tự suy biến thành B). Đánh đổi của C: cần biết giá trị filter trước khi truy xuất và `part` chỉ lọc thô (các chương cùng Part vẫn lẫn nhau, ví dụ q24 vẫn có hai chunk `explicit-locking` trong top-3).
- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:** (1) chỉ 26 câu và 7 câu test, chênh lệch 1–3 câu không có ý nghĩa thống kê, không kết luận chiến lược tốt nhất tổng quát; (2) một corpus duy nhất (docs PostgreSQL 16, tiếng Anh) với câu hỏi tiếng Việt nên có thêm sai số truy xuất xuyên ngôn ngữ; (3) dev và test dùng chung một số trang nguồn (`routine-vacuuming`: q12 dev, q23/q26 test; `transaction-iso`: q08 dev, q25 test) nên có nguy cơ rò rỉ chủ đề; (4) bộ câu hỏi, mã pipeline và nhãn đề xuất đều có sự hỗ trợ của Claude nên có nguy cơ thiên lệch giữa cách đặt câu và cách chunk, và nhãn không phải chấm độc lập; (5) chấm grounding chỉ trên 5 câu test (q20–q24), cả ba cấu hình đều tìm được bằng chứng nên điểm B/C/A khác nhau ít (2,0 / 2,0 / 1,8); metadata đạt 45/45 vì metadata do pipeline sinh từ manifest, nên chỉ số này phản ánh tính đúng đắn của pipeline chứ không phân biệt chiến lược; (6) `evaluate` in dev/test cùng lúc; (7) thời gian ingest đo trên CPU máy cá nhân, vài lần chạy, có dao động; (8) filter 6/6 là hiển nhiên do `WHERE`; (9) lỗi bỏ thẻ `<dt>` và dấu `#` ở heading của bộ crawl (xem phần chuẩn hóa) chưa được sửa trước khi đo.
- **Nếu làm lại hoặc mở rộng:** sửa crawler để giữ thẻ `<dt>` và bỏ dấu `#`, rồi ingest và đo lại; thêm câu hỏi và tập test độc lập; thử filter theo `chapter` (mịn hơn `part`); đo thêm Hit đa chunk (hợp các chunk liền kề); thử hybrid retrieval (dense + BM25) với tham số chọn trên dev; thử chunk B có overlap hoặc kích thước tối đa khác; thử model embedding mạnh hơn cho truy xuất xuyên ngôn ngữ.

## Công cụ AI và cách kiểm tra
Dùng Claude (Anthropic) để giải thích đề, viết mã pipeline (`crawl_pg_docs.py`, `lab6.py`), soạn bộ câu hỏi và đề xuất nhãn audit. Cách kiểm tra: chạy `validate` để chứng minh mọi evidence nằm nguyên văn trong trang gold; chạy hai lần `ingest` để kiểm tra nạp lại không nhân đôi; đọc trace top-3, đọc lại và xác nhận/sửa từng nhãn audit; đối chiếu metadata với manifest. Tác giả đã đọc và hiểu mã nguồn và có thể giải thích từng bước.