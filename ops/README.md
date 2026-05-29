# ops/ —— 服务器运维脚本

本目录存放宿主机运维脚本，纳入仓库做版本管理与备份。
**这些脚本是生产部署的唯一真源**：宿主机 `/home/tdxback/` 下对应文件是指向本目录的软链接，
因此直接编辑本目录文件即对线上生效，crontab 与脚本内部路径无需改动。

## 文件

| 文件 | 作用 |
|------|------|
| `check.sh` | 一键健康检核：系统/磁盘/内存/mihomo代理/Docker与各容器/网口/网络连通/网页端口。只读、不需 root、彩色、带汇总。退出码 0=全绿 1=有告警 2=有失败。 |
| `check-cron.sh` | 定时调度包装：跑 `check.sh` → 全量报告覆盖写 `check-latest.log`；失败(退出码2)追加 `check-fail.log`；每次把完整报告邮件发出(主题带 ✅/▲/✘)，发信日志 `check-mail.log`。 |
| `send_mail.py` | 邮件发送：读 `../​.env` 的 163 SMTP 配置(465→SMTP_SSL)。用法 `send_mail.py "<主题>" <正文文件>`。 |

## 部署（软链接，已配置）

```bash
ln -s /home/tdxback/aiagents-stock/ops/check.sh      /home/tdxback/check.sh
ln -s /home/tdxback/aiagents-stock/ops/check-cron.sh /home/tdxback/check-cron.sh
ln -s /home/tdxback/aiagents-stock/ops/send_mail.py  /home/tdxback/send_mail.py
```

## crontab（tdxback 用户级）

```
0 3 * * 0  /home/tdxback/docker-prune.sh   # 周日03:00 Docker 空间回收(脚本另在 $HOME，未纳管)
0 8 * * *  /home/tdxback/check-cron.sh      # 每天08:00 健康检核 + 邮件
```

## 日志（写在 $HOME，不入库）

- `/home/tdxback/check-latest.log` —— 最近一次完整报告(覆盖)
- `/home/tdxback/check-fail.log` —— 仅失败批次追加
- `/home/tdxback/check-mail.log` —— 发信结果

## 手动用法

```bash
bash /home/tdxback/check.sh            # 立即检核
bash /home/tdxback/check.sh --no-color # 无颜色(便于重定向存档)
```

> 配置项（容器/端口期望值、阈值、代理端口）在 `check.sh` 顶部。
> 收发件邮箱在仓库根 `.env`（EMAIL_FROM/EMAIL_TO/EMAIL_PASSWORD，**不入库**）。
