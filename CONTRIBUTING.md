# 参与贡献

感谢关注「笺」。它希望保持「纸、静、少」：一次决定、一张短笺，离线仍可用。

## 本地运行

- 双击 `index.html`：不需要构建；用 `http(s)` 打开时才启用 Service Worker。
- `npm ci`：安装 Capacitor 构建依赖。
- `npm test`：快速守门（Node / Python）。
- `npm run test:v06`：需要 Python Playwright 与本机 Chromium/Edge。
- `npm run android`：构建 debug APK；需要 Android SDK。

改动前请先读 `docs/ENG-CONVENTIONS.md`。涉及菜谱忌口判定时，JavaScript 与 Python 两端必须同步更新；涉及数据结构时，检查旧备份的导入与归一化幂等性。

## 提交规范

1. 一个问题一个可复现的最小改动，并给出对应的回归测试。
2. 不要提交真实个人照片、聊天、备份、密钥、签名文件或模型服务凭据。
3. 不要复制第三方菜谱正文、网站页面、受版权保护的图片；示例素材请使用自有或明确可再分发的内容。
4. 描述测试的实际结果。没有跑过设备测试就写明没有跑过。
5. 提交 Pull Request 时说明用户行为的变化、测试命令和可能的兼容性影响。

安全问题请不要直接公开复现细节，见 [SECURITY.md](SECURITY.md)。

## 许可证

项目自有代码按 [MIT](LICENSE) 开源；第三方依赖仍遵守各自许可证。
