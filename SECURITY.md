# 安全说明

## 密钥怎么放

- 所有密钥（Dify App Key、模型 Key）只放环境变量或本地 `.env`，`.env` 已在 `.gitignore` 中；
- `.env.example` 只保留占位符，任何情况下不要把真实 Key 写进示例文件；
- 网关在服务端持有 Key，浏览器端拿不到，也不会把 Key 写进日志或数据库。

## 提交前自检

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_secrets.ps1
```

脚本会扫描工作区里的 `sk-`、`app-`、`cli_` 等密钥样式与常见私密文件，发现即提示。

## 如果发现泄露

1. **先吊销**（平台侧重置 Key），再清理代码；
2. 清理历史命令参考 `git filter-repo --replace-text`；
3. 假设泄露已经发生，检查账单与调用记录。

## 运行时防护

- 工号 + 密码登录，密码用 PBKDF2-SHA256 加盐存储；
- 落库前对手机号、身份证、详细地址做脱敏（见 `web/app/pii.py`）；
- 只监听 `127.0.0.1`，对外试点时再套反向代理与 HTTPS。

## 报告问题

这是个人作品项目，发现安全问题请直接提 Issue，不要公开贴出可用密钥。
