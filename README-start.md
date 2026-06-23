# 本地一键启动说明

## 启动

双击根目录的 `start-all.bat`。

脚本会依次启动：
- Redis Docker 容器：`caiyan-redis`
- Backend：`http://0.0.0.0:8000`
- Celery worker
- Frontend：`http://0.0.0.0:5275`

启动完成后，主窗口会打印同事访问地址：

```text
http://<内网IP>:5275
```

保持 Backend、Celery worker、Frontend 这几个窗口开着；关闭窗口即停止对应服务。

## 停止

双击根目录的 `stop-all.bat`。

默认不会停止 Redis 容器，避免下次启动变慢。脚本会询问是否同时停止 Redis。

## 同事访问不了时

先确认同事访问的是启动窗口打印的地址：

```text
http://<内网IP>:5275
```

如果仍然访问不了，可能是 Windows 防火墙拦截了端口。请用管理员 PowerShell 执行：

```powershell
New-NetFirewallRule -DisplayName "CaiYan Frontend 5275" -Direction Inbound -Protocol TCP -LocalPort 5275 -Action Allow
New-NetFirewallRule -DisplayName "CaiYan Backend 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```
