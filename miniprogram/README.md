# Compass Health 微信小程序 MVP

这个目录是 Compass Health 的微信小程序最小可行版本，复用现有 FastAPI 后端。

## 已包含页面

- 登录 / 注册
- 首页概览
- 饮食记录
- AI 配餐
- 统计
- 设置：API 地址、身体档案、食材偏好、退出登录

## 本地开发测试

1. 启动后端：

   ```bash
   cd backend
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

2. 打开微信开发者工具，选择“导入项目”，项目目录选择：

   ```text
   compass-health/miniprogram
   ```

3. AppID 可以先使用测试号，或者把 `project.config.json` 里的 `touristappid` 换成你自己的小程序 AppID。

4. 在微信开发者工具右上角“详情 / 本地设置”里开启：

   ```text
   不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书
   ```

5. 模拟器里测试时，登录页 API 地址使用：

   ```text
   http://127.0.0.1:8000
   ```

6. 手机真机调试时，手机不能访问电脑上的 `127.0.0.1`。把登录页 API 地址改成电脑局域网 IP：

   ```text
   http://你的电脑局域网IP:8000
   ```

   例如：

   ```text
   http://192.168.1.8:8000
   ```

## 发布前要求

正式预览、体验版和线上版通常需要公网 HTTPS API，并在微信公众平台配置 request 合法域名。上线时不要使用 `localhost`、`127.0.0.1` 或局域网 IP。
