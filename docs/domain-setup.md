# 正式域名接入

## 站点信息

- 主域名：`https://njust.shop`。
- `www.njust.shop` 及 HTTP 入口统一以 308 跳转至主域名 HTTPS，保留路径和查询参数。
- 网站名称：课堂学习笔记；网站备案号：苏ICP备2026086876号-1。
- 备案号显示在登录页及登录后的全站页脚，链接至工信部备案查询首页。
- 按用户提供的备案截图显示与备案主体一致的版权信息。江苏版权展示要求参照阿里云官方《添加ICP 备案号和版权处理》：`https://help.aliyun.com/zh/icp-filing/basic-icp-service/the-icp-record-post-processing-1`。
- 根域名与 www 的 A 记录均指向现有 ECS。域名接入复用同源 `/api`，不改变业务数据。

## Nginx 与证书

配置模板为 `deploy/nginx-domain.conf`。启用前确认备案审核通过、DNS 正确、两域名的公网 HTTP 验证路径可达，并完成有效证书签发。

生产配置：`/etc/nginx/sites-available/classagent-domain`，通过同名 `sites-enabled` 软链接启用。原 IP 虚拟主机保留。变更后先执行 `nginx -t`，通过后执行 `systemctl reload nginx`。

证书由现有 `/opt/certbot-venv/bin/certbot` 管理，证书名 `njust.shop`，同时覆盖根域名和 www。证书文件位于 `/etc/letsencrypt/live/njust.shop/`，不复制私钥到仓库或本地报告。

沿用现有 `certbot-renew.timer`：每天两次检查续期，成功后通过 deploy hook 平滑重载 Nginx。按需检查：

```bash
systemctl status certbot-renew.timer --no-pager
/opt/certbot-venv/bin/certbot renew --cert-name njust.shop --dry-run --no-random-sleep-on-renew
nginx -t
curl --fail --silent --show-error https://njust.shop/api/health
curl --head --silent --show-error 'https://www.njust.shop/login?source=www'
```

HTTP 的 `/.well-known/acme-challenge/` 保持 webroot 文件访问，不能一起跳转或被前端路由接管。

## 发布与回退

遵循 `docs/production-deployment.md`：备案页脚仅需更新 web，不因域名接入重启 API、worker、beat、数据库或 Redis。前端生产构建固定 `/api` 和关闭注册入口。

若本地业务版本领先线上，基于实际线上提交单独叠加 `AppShell.tsx`、`SiteFooter.tsx`、`site-footer.css`，在发布记录保存基线与三个文件哈希；不能顺带部署未获授权的业务改动。

2026-11-09 接入前的 Nginx 备份保存在 `/opt/classagent-domain-setup/njust.shop/activation-20261109/`。域名虚拟主机独立启用，移除本次软链接并通过语法检查、平滑重载后，可退回原 IP 站点。前端按发布目录中的 rollback 覆盖文件回退，持久卷保持原状。

上线检查包括：两个域名证书校验、HTTP 与 www 跳转、首页/登录页、同源 API、真实已登录课程和资料访问，以及桌面/手机页脚可见且无横向溢出。验证报告保存在忽略的 `test-results/`，不记录凭证。

## 公安联网备案

本次域名与 HTTPS 接入不代表已经完成公安联网备案。若尚未办理，应由网站主办者通过全国互联网安全管理服务平台的实际流程办理，实名、证件、短信等核验由本人完成，不猜测业务表单或代造身份材料。取得公安备案信息后，再按核准信息展示对应标识与链接；未获核准前不生成虚构公安备案号。

阿里云官方相关入口：`https://help.aliyun.com/zh/icp-filing/basic-icp-service/the-public-security-network-for-the-record-and-profit-for-the-record/`。
