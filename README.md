# NoLogo Downloader (MVP)

Website responsive cho iPhone/PC, backend Python FastAPI + yt-dlp.

## Tính năng hiện tại
- Nhận URL TikTok/Douyin công khai.
- Phân tích metadata và các định dạng video mà yt-dlp nhận diện.
- Tải video theo chất lượng cao nhất hoặc giới hạn 1080p/720p/480p.
- Không yêu cầu đăng nhập tài khoản.

## Giới hạn quan trọng
- Không bảo đảm mọi bài đăng có bản không watermark. Website chỉ chọn định dạng mà nền tảng cung cấp cho extractor.
- MVP hiện tập trung vào video; album ảnh/slideshow Douyin/TikTok cần triển khai và kiểm thử riêng.
- Nền tảng có thể thay đổi API/biện pháp truy cập; cần cập nhật yt-dlp thường xuyên.
- Chỉ dùng với nội dung bạn sở hữu hoặc có quyền tải. Không vượt quyền riêng tư, paywall hay cơ chế đăng nhập.
- Không dùng làm dịch vụ công cộng quy mô lớn nếu chưa bổ sung giới hạn tốc độ, hàng đợi, giới hạn dung lượng/thời gian, chống lạm dụng và dọn file tạm.

## Chạy thử trên máy tính
Yêu cầu Python 3.10+.

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app:app --reload
```

Mở http://127.0.0.1:8000

## Đưa lên mạng
Có thể triển khai backend lên Render bằng cách kết nối repository GitHub chứa dự án này. Render đọc cấu hình `render.yaml`.
Sau khi deploy, mở URL HTTPS được Render cấp.

Lưu ý: gói hosting miễn phí hoặc cấu hình yếu có thể timeout khi tải video lớn. Nên dùng gói có đủ RAM, dung lượng tạm và băng thông. Trước khi công khai, cần bổ sung:
- giới hạn kích thước file và thời gian xử lý;
- rate limiting / CAPTCHA;
- dọn thư mục tạm sau khi gửi file;
- hàng đợi tác vụ cho video dài;
- kiểm tra cập nhật và điều khoản của nền tảng.
