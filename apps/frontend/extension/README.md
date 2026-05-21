# 飞猪运营助手浏览器插件

这是一个本地加载的 Chrome/Edge 扩展，用来把当前项目的核心飞猪运营能力整理为浏览器插件入口。当前插件恢复为“右上角 Popup 和页面内运营助手都使用本地完整工作台，云端 UI 暂保留为 HTTP 测试入口”的模式。插件分成三层：

- `popup`：浏览器右上角默认入口，使用本地完整工作台，负责服务状态、当前页摘要、快捷动作、商家改价直连动作和项目页面跳转
- 页面浮层：在飞猪/淘宝相关页右下角注入“运营助手”，通过 iframe 加载同一个本地 `popup.html?embedded=1`
- `popup-shell`：云端 UI 壳实验入口，当前不作为默认 Popup
- `content` / `background`：保留页面采集、回填、配置、登录态、消息转发和后端 API 调用能力

## 当前能力

### 插件内直接完成

- 打开插件后先进行账号登录，并读取当前账号可访问的店铺列表
- 登录后可切换当前店铺，后续请求自动绑定对应店铺
- 当前店铺的竞对酒店配置保存到数据库，并在 Popup / 设置页 / 页面浮层自动同步
- 自动在飞猪相关页面注入右下角运营面板
- 右上角浏览器 Popup 使用本地完整工作台，保持和历史排版一致
- 页面内“运营助手”加载本地完整 Popup iframe，避免 HTTPS 飞猪页面嵌入 HTTP 云端 UI 被浏览器拦截
- 在 popup 中查看当前标签页是否识别为飞猪相关页面
- 检查本地服务状态
- 实时抓取并展示竞对最新价格（默认同时保存快照）
- 按当前页参数发起一轮真实飞猪采集
- 展示竞对价格趋势图，支持“主流房型最低价”和“竞对酒店最低价”两种维度
- 直接触发商家改价预览
- 直接执行“一键按建议价推 OTA”
- 在右下角浮层中直接打开游客抓价、最新价格、建议价分析、改价工作台、商家连接、房型映射和执行改价入口
- 在设置页维护 `baseUrl`、`debugUrl` 和“当前登录店铺”的竞对酒店列表

### 从插件一键跳转到现有项目页面

- 市场能力
  - 游客抓价
  - 价格趋势
  - 最新价格页面
  - 建议价分析
- 商家改价
  - 改价工作台
  - 商家连接
  - 手工补登录
  - 商家抓价
  - 房型映射
  - 执行改价

## 目录说明

- `manifest.json`：扩展清单
- `background.js`：登录态中心、后端 API 代理和项目页面打开入口
- `bridge.js`：内容脚本降级链路的后端桥接代理
- `content.js`：页面浮层装配入口
- `content/page-context.js`：当前页识别与价格卡片提取逻辑
- `content/result-view.js`：页面浮层和 popup 共用的结果渲染辅助
- `popup.html` / `popup.js`：扩展图标点击后的本地完整工作台，也是页面浮层 iframe 使用的同一套 UI
- `popup-shell.html` / `popup-shell.js`：云端 UI 壳实验入口，等待 HTTPS 域名可用后再切换为默认入口
- `options.html` / `options.js`：当前登录店铺的扩展配置页

## 本地加载

1. 启动当前项目后端，确认 `http://127.0.0.1:8000/health` 可访问
2. 打开 Edge 或 Chrome 的扩展管理页
3. 开启“开发者模式”
4. 选择“加载已解压的扩展程序”
5. 选择本目录 `browser-extension/`
6. 打开飞猪相关页面，右下角会出现“运营助手”按钮
7. 点击浏览器扩展图标，先登录插件账号
8. 登录成功后选择当前店铺，再进入统一入口工作台

## 默认依赖

- 本地后端：`http://127.0.0.1:8000`
- 浏览器调试口：`http://127.0.0.1:9222`
- 后端定时采集：可通过项目根目录 `scripts/start_celery_worker.ps1` 和 `scripts/start_celery_beat.ps1` 启动 Celery worker/beat，默认每 2 小时采集一次启用的竞对酒店房型价
- 插件鉴权：
  - `Authorization: Bearer <plugin token>`
- 店铺上下文兼容头：
  - `X-Tenant-Id`
  - `X-Shop-Id`
- 云端 UI：
  - `http://api.aihuawise.com/ops-assistant`

## 云端 UI 消息协议

云端页面通过 `postMessage` 与 Popup 壳或页面内插件壳通信，协议固定为 `fliggy-ops-cloud-ui/v1`。当前默认入口暂不使用云端 UI，因为飞猪页面是 HTTPS，不能稳定嵌入 HTTP 云端页面。

请求格式：

```json
{
  "protocol": "fliggy-ops-cloud-ui/v1",
  "type": "FLIGGY_OPS_CLOUD_REQUEST",
  "requestId": "request-id",
  "action": "plugin.runtime",
  "payload": {
    "message": {
      "type": "SERVICE_STATUS",
      "payload": {}
    }
  }
}
```

响应格式：

```json
{
  "protocol": "fliggy-ops-cloud-ui/v1",
  "type": "FLIGGY_OPS_CLOUD_RESPONSE",
  "requestId": "request-id",
  "ok": true,
  "data": {}
}
```

插件侧当前开放的动作：

- `plugin.runtime`：转发到白名单内的 `chrome.runtime.sendMessage` 类型
- `bridge.request`：调用现有 `bridge.html` 降级桥
- `page.getContext`：读取当前页面类型和上下文
- `page.getSnapshot`：采集当前页面快照
- `page.getCurrentHotelRoomPrices`：读取酒店详情页房型价
- `page.collectLocalMerchantPriceItems`：读取已登录商家后台价格项
- `page.submitLocalMerchantPrices`：在已登录商家后台回填并提交价格
- `panel.close` / `panel.ping`：控制页面内面板和检测协议状态

右上角 Popup 壳还额外支持 `panel.open`，用于从云端 UI 打开当前业务页内的右下角运营面板。Popup 壳没有直接访问网页 DOM 的权限，涉及当前页的能力会先定位当前活动业务标签页，再转发给该页的 `content.js`。

## 云端更新流程

用 WinSCP 更新页面时，只上传云端 UI 对应的静态文件或后端模板到服务器。当前仓库内置的云端 UI 位于 `apps/backend/app/static/ops-assistant/`，后端通过 `/ops-assistant` 暴露为 `http://api.aihuawise.com/ops-assistant`。由于当前域名只配置了 HTTP，默认插件入口仍使用本地完整 Popup；等 `https://api.aihuawise.com/ops-assistant` 可用后，再把默认入口切回云端 UI，才能实现多电脑免重载更新页面。

只有以下内容变化时，才需要每台电脑更新插件壳：

- `manifest.json` 权限、CSP、host permissions
- `popup-shell.js` / `content.js` 的消息协议或插件能力白名单
- 页面采集、商家后台回填、浏览器标签页操作等本地能力
- 本地备用 `popup.html` / `popup.js`

## 当前插件化原则

- 不自动登录
- 不新开浏览器实例
- 插件自身要求先登录再用；飞猪页面采集仍然只接管当前已经登录的飞猪页面
- 只接管当前已经登录并停留在飞猪相关页的浏览器页面
- Popup 默认使用本地完整工作台，保证右上角入口排版和历史功能一致
- 页面内“运营助手”浮层通过 iframe 加载本地完整 Popup，避免 HTTP 云端页面在 HTTPS 飞猪页面中被混合内容策略拦截
- `manifest.json` 将 `popup.html`、`popup.js` 和 `content/result-view.js` 一并声明为 `web_accessible_resources`，确保右下角 iframe 能加载完整工作台脚本
- 当前默认入口更新仍需更新插件本体；只有未来切回 HTTPS 云端 UI 后，固定协议不变时才可做到只更新云端页面
- 复杂流程继续复用现有项目页面，不在 Popup 中硬塞整套重型表单
- 当前页采集优先提取真实酒店卡片和明确价格信号；当卡片节点不好命中时，会回退到页面文本附近的酒店名/价格配对，尽量减少 `Raw Rows: 0` 和抓错价


