const form = document.getElementById("config-form")
const returnSourceBtn = document.getElementById("return-source-btn")
const messageBox = document.getElementById("message")
const testBtn = document.getElementById("testBtn")
const hotelList = document.getElementById("competitor-hotels")
const addHotelBtn = document.getElementById("add-hotel-btn")
const manualRoomList = document.getElementById("manual-room-mappings")
const addManualRoomBtn = document.getElementById("add-manual-room-btn")
const authSummary = document.getElementById("auth-summary")
const authSessionBox = document.getElementById("auth-session-box")
const authUsernameInput = document.getElementById("auth-username-input")
const authPasswordInput = document.getElementById("auth-password-input")
const authCurrentUserInput = document.getElementById("auth-current-user")
const authLoginBtn = document.getElementById("auth-login-btn")
const authRefreshBtn = document.getElementById("auth-refresh-btn")
const authLogoutBtn = document.getElementById("auth-logout-btn")
const shopSelect = document.getElementById("shop-select")
const currentConfigBox = document.getElementById("current-config-box")
const currentPageBox = document.getElementById("current-page-box")
const refreshPageBtn = document.getElementById("refresh-page-btn")
const baseUrlInput = document.getElementById("baseUrl")
const tenantIdInput = document.getElementById("tenantId")
const shopIdInput = document.getElementById("shopId")
const debugUrlInput = document.getElementById("debugUrl")
const startUrlInput = document.getElementById("startUrl")
const latestPriceLimitInput = document.getElementById("latestPriceLimit")
const maxPagesInput = document.getElementById("maxPages")
const maxHotelsInput = document.getElementById("maxHotels")
const saveResultInput = document.getElementById("saveResult")

let currentConfig = null

returnSourceBtn?.addEventListener("click", async () => {
  returnSourceBtn.disabled = true
  setMessage("正在返回上一页...")
  try {
    const response = await sendMessage({ type: "RETURN_TO_OPTIONS_SOURCE" })
    if (response?.returned === false) {
      throw new Error("未找到可返回的来源页面")
    }
  } catch (error) {
    setMessage(`返回失败: ${error.message}`, true)
    if (window.history.length > 1) {
      window.history.back()
      return
    }
    window.close()
  } finally {
    returnSourceBtn.disabled = false
  }
})

addHotelBtn.addEventListener("click", () => {
  appendHotelRow({ name: "", url: "" })
  syncHotelTitles()
})

addManualRoomBtn.addEventListener("click", () => {
  appendManualRoomRow({
    displayName: "",
    roomType: "",
    rateName: "标准价",
    currentPrice: "",
    competitorRoomNames: [],
    enabled: true
  })
  syncManualRoomTitles()
})

hotelList.addEventListener("click", (event) => {
  const removeBtn = event.target.closest("[data-action='remove-hotel']")
  if (!removeBtn) {
    return
  }
  removeBtn.closest(".hotel-item")?.remove()
  renderEmptyStateIfNeeded()
  syncHotelTitles()
})

manualRoomList.addEventListener("click", (event) => {
  const removeBtn = event.target.closest("[data-action='remove-manual-room']")
  if (!removeBtn) {
    return
  }
  removeBtn.closest(".manual-room-item")?.remove()
  renderManualRoomEmptyStateIfNeeded()
  syncManualRoomTitles()
})

form.addEventListener("submit", async (event) => {
  event.preventDefault()
  setMessage("保存中...")
  try {
    ensureAuthenticated()
    const payload = readForm()
    const savedConfig = await sendMessage({ type: "SAVE_CONFIG", payload })
    applyConfig(savedConfig)
    const hotelCount = Array.isArray(savedConfig?.competitorHotels) ? savedConfig.competitorHotels.length : 0
    const manualRoomCount = Array.isArray(savedConfig?.manualRoomMappings) ? savedConfig.manualRoomMappings.length : 0
    setMessage(`设置已保存，当前有效竞对酒店 ${hotelCount} 家，自定义房型 ${manualRoomCount} 条。`)
  } catch (error) {
    setMessage(`保存失败: ${error.message}`, true)
  }
})

testBtn.addEventListener("click", async () => {
  setMessage("连接测试中...")
  try {
    ensureAuthenticated()
    const payload = readForm()
    const savedConfig = await sendMessage({ type: "SAVE_CONFIG", payload })
    applyConfig(savedConfig)
    const status = await sendMessage({ type: "SERVICE_STATUS" })
    const hotelCount = Array.isArray(savedConfig?.competitorHotels) ? savedConfig.competitorHotels.length : 0
    const manualRoomCount = Array.isArray(savedConfig?.manualRoomMappings) ? savedConfig.manualRoomMappings.length : 0
    setMessage(`连接成功: ${status.plugin} 在线，当前有效竞对酒店 ${hotelCount} 家，自定义房型 ${manualRoomCount} 条。`)
  } catch (error) {
    setMessage(`连接失败: ${error.message}`, true)
  }
})

authLoginBtn.addEventListener("click", async () => {
  await withAuthBusy(async () => {
    const baseUrl = String(baseUrlInput.value || "").trim()
    const tenantId = Number(tenantIdInput.value || 0)
    const username = String(authUsernameInput.value || "").trim()
    const password = String(authPasswordInput.value || "").trim()
    if (!baseUrl) {
      throw new Error("请先填写后端地址")
    }
    if (!tenantId) {
      throw new Error("请先填写有效的 Tenant")
    }
    if (!username || !password) {
      throw new Error("请先填写用户名和密码")
    }
    const config = await sendMessage({
      type: "AUTH_LOGIN",
      payload: {
        baseUrl,
        tenantId,
        username,
        password
      }
    })
    authPasswordInput.value = ""
    applyConfig(config)
    setMessage(`已登录 ${config?.authUser?.username || username}，当前店铺 ${config?.currentShop?.shop_name || "-"}`)
  })
})

authRefreshBtn.addEventListener("click", async () => {
  await withAuthBusy(async () => {
    const config = await sendMessage({ type: "GET_AUTH_STATE" })
    applyConfig(config)
    setMessage(Boolean(config?.authenticated) ? "登录会话已刷新。" : "当前未登录。")
  })
})

authLogoutBtn.addEventListener("click", async () => {
  await withAuthBusy(async () => {
    const config = await sendMessage({ type: "AUTH_LOGOUT" })
    authPasswordInput.value = ""
    applyConfig(config)
    setMessage("当前已退出登录。")
  })
})

shopSelect.addEventListener("change", async () => {
  const shopId = Number(shopSelect.value || 0)
  if (!shopId) {
    return
  }
  await withAuthBusy(async () => {
    const config = await sendMessage({
      type: "AUTH_SWITCH_SHOP",
      payload: { shopId }
    })
    applyConfig(config)
    setMessage(`已切换到店铺 ${config?.currentShop?.shop_name || shopId}。`)
  })
})

refreshPageBtn.addEventListener("click", async () => {
  await refreshCurrentPageSummary()
})

loadConfig()

async function loadConfig() {
  const [configResult, pageResult] = await Promise.allSettled([
    sendMessage({ type: "GET_CONFIG" }),
    getCurrentPageContextForSettings()
  ])

  if (configResult.status === "fulfilled") {
    applyConfig(configResult.value)
  } else {
    setMessage(`配置读取失败: ${configResult.reason.message}`, true)
  }

  renderCurrentPageContext(
    pageResult.status === "fulfilled"
      ? pageResult.value
      : unsupportedPageContext(pageResult.reason?.message || "页面读取失败")
  )
}

function applyConfig(config) {
  currentConfig = config || {}
  const authenticated = Boolean(currentConfig?.authenticated && currentConfig?.authUser && currentConfig?.currentShop)
  baseUrlInput.value = currentConfig?.baseUrl || ""
  tenantIdInput.value = String(currentConfig?.authUser?.tenant_id || currentConfig?.tenantId || "")
  tenantIdInput.disabled = authenticated
  shopIdInput.value = String(currentConfig?.currentShop?.shop_id || currentConfig?.shopId || "")
  shopIdInput.disabled = true
  debugUrlInput.value = currentConfig?.debugUrl || ""
  startUrlInput.value = currentConfig?.startUrl || ""
  latestPriceLimitInput.value = currentConfig?.latestPriceLimit || ""
  maxPagesInput.value = currentConfig?.maxPages || ""
  maxHotelsInput.value = currentConfig?.maxHotels || ""
  saveResultInput.checked = Boolean(currentConfig?.saveResult)
  renderCompetitorHotels(Array.isArray(currentConfig?.competitorHotels) ? currentConfig.competitorHotels : [])
  renderManualRoomMappings(Array.isArray(currentConfig?.manualRoomMappings) ? currentConfig.manualRoomMappings : [])
  renderAuthSummary(currentConfig)
  renderCurrentConfigSummary(currentConfig)
  setConfigDisabled(!authenticated)
}

function renderAuthSummary(config) {
  const authenticated = Boolean(config?.authenticated && config?.authUser && config?.currentShop)
  const username = String(config?.authUser?.username || "").trim()
  const tenantId = String(config?.authUser?.tenant_id || config?.tenantId || "").trim()
  const currentShop = config?.currentShop || null
  const shops = Array.isArray(config?.shops) ? config.shops : []

  authLoginBtn.textContent = authenticated ? "重新登录" : "登录并进入"
  authRefreshBtn.classList.toggle("hidden", !authenticated)
  authLogoutBtn.classList.toggle("hidden", !authenticated)
  authSessionBox.classList.toggle("hidden", !authenticated)

  if (!authenticated) {
    authSummary.innerHTML = `
      <div><strong>当前未登录</strong></div>
      <div class="tip">先在下方当前配置里填好后端地址与 Tenant，再在这里输入账号密码登录。</div>
    `
    authCurrentUserInput.value = ""
    shopSelect.innerHTML = '<option value="">请先登录后选择店铺</option>'
    return
  }

  authSummary.innerHTML = `
    <div><strong>${escapeHtml(username || "当前账号")}</strong> 已登录。</div>
    <div class="tip">Tenant ${escapeHtml(tenantId || "-")} | 当前店铺 ${escapeHtml(currentShop?.shop_name || "-")} (${escapeHtml(String(currentShop?.shop_id || config?.shopId || "-"))}) | 可访问店铺 ${shops.length} 家</div>
  `
  authCurrentUserInput.value = username
    ? `${username} / tenant ${tenantId || "-"}`
    : ""
  shopSelect.innerHTML = shops.length
    ? shops.map((shop) => `<option value="${escapeHtml(String(shop.shop_id || ""))}" ${Number(shop.shop_id || 0) === Number(currentShop?.shop_id || 0) ? "selected" : ""}>${escapeHtml(shop.shop_name || `Shop ${shop.shop_id}`)}</option>`).join("")
    : '<option value="">暂无可访问店铺</option>'
}

function setConfigDisabled(disabled) {
  addHotelBtn.disabled = disabled
  addManualRoomBtn.disabled = disabled
  testBtn.disabled = disabled
  form.querySelector("button[type='submit']").disabled = disabled
  form.querySelectorAll("#competitor-hotels input, #competitor-hotels button, #manual-room-mappings input, #manual-room-mappings textarea, #manual-room-mappings button").forEach((node) => {
    node.disabled = disabled
  })
}

function setAuthBusy(isBusy) {
  ;[
    authUsernameInput,
    authPasswordInput,
    authLoginBtn,
    authRefreshBtn,
    authLogoutBtn,
    shopSelect
  ].forEach((node) => {
    if (node) {
      node.disabled = isBusy
    }
  })
}

async function withAuthBusy(task) {
  setAuthBusy(true)
  try {
    await task()
  } catch (error) {
    setMessage(error.message || String(error), true)
  } finally {
    setAuthBusy(false)
  }
}

function ensureAuthenticated() {
  if (!Boolean(currentConfig?.authenticated && currentConfig?.currentShop)) {
    throw new Error("请先在当前设置页完成登录并选择当前店铺")
  }
}

function renderCompetitorHotels(items) {
  hotelList.innerHTML = ""
  const rows = Array.isArray(items) && items.length ? items : [{ name: "", url: "" }]
  rows.forEach((item) => appendHotelRow(item))
  renderEmptyStateIfNeeded()
  syncHotelTitles()
}

function appendHotelRow(item) {
  const row = document.createElement("div")
  row.className = "hotel-item"
  row.innerHTML = `
    <div class="hotel-item-head">
      <div class="hotel-item-title">竞对酒店</div>
      <button type="button" class="danger" data-action="remove-hotel">删除</button>
    </div>
    <div class="hotel-item-grid">
      <label>
        酒店名称
        <input type="text" data-field="name" placeholder="例如：杭州君悦酒店" value="${escapeHtmlAttr(item?.name || "")}">
      </label>
      <label>
        详情页 URL
        <input type="url" data-field="url" placeholder="https://hotel.fliggy.com/hotel_detail.htm?id=..." value="${escapeHtmlAttr(item?.url || "")}">
      </label>
    </div>
  `
  hotelList.appendChild(row)
}

function renderEmptyStateIfNeeded() {
  const rows = Array.from(hotelList.querySelectorAll(".hotel-item"))
  if (rows.length) {
    hotelList.querySelector(".hotel-empty")?.remove()
    return
  }
  const empty = document.createElement("div")
  empty.className = "hotel-empty"
  empty.textContent = "还没有竞对酒店配置，先新增一条。"
  hotelList.appendChild(empty)
}

function syncHotelTitles() {
  Array.from(hotelList.querySelectorAll(".hotel-item")).forEach((row, index) => {
    const title = row.querySelector(".hotel-item-title")
    if (title) {
      title.textContent = `竞对酒店 ${index + 1}`
    }
  })
}

function normalizeManualRoomTerms(value) {
  const rawItems = Array.isArray(value)
    ? value
    : String(value || "").split(/[\n,，;；]+/)
  const result = []
  const seen = new Set()
  for (const rawItem of rawItems) {
    const item = String(rawItem || "").replace(/\s+/g, " ").trim()
    if (!item || seen.has(item)) {
      continue
    }
    seen.add(item)
    result.push(item)
    if (result.length >= 20) {
      break
    }
  }
  return result
}

function renderManualRoomMappings(items) {
  manualRoomList.innerHTML = ""
  const rows = Array.isArray(items) && items.length
    ? items
    : [{ displayName: "", roomType: "", rateName: "标准价", currentPrice: "", competitorRoomNames: [], enabled: true }]
  rows.forEach((item) => appendManualRoomRow(item))
  renderManualRoomEmptyStateIfNeeded()
  syncManualRoomTitles()
}

function appendManualRoomRow(item) {
  const currentPrice = Number(item?.currentPrice ?? item?.current_price ?? 0)
  const competitorRoomNames = normalizeManualRoomTerms(item?.competitorRoomNames || item?.competitor_room_names).join("\n")
  const row = document.createElement("div")
  row.className = "manual-room-item"
  row.innerHTML = `
    <div class="manual-room-item-head">
      <div class="manual-room-item-title">我的房型</div>
      <button type="button" class="danger" data-action="remove-manual-room">删除</button>
    </div>
    <div class="manual-room-grid">
      <label>
        房型名称
        <input type="text" data-field="displayName" placeholder="例如：高级大床房" value="${escapeHtmlAttr(item?.displayName || item?.display_name || "")}">
      </label>
      <label>
        房型类型
        <input type="text" data-field="roomType" placeholder="例如：大床房" value="${escapeHtmlAttr(item?.roomType || item?.room_type || "")}">
      </label>
      <label>
        价型名
        <input type="text" data-field="rateName" placeholder="例如：标准价" value="${escapeHtmlAttr(item?.rateName || item?.rate_name || "标准价")}">
      </label>
      <label>
        当前价
        <input type="number" min="1" step="0.01" data-field="currentPrice" placeholder="例如：429" value="${Number.isFinite(currentPrice) && currentPrice > 0 ? escapeHtmlAttr(String(currentPrice)) : ""}">
      </label>
      <label class="full">
        竞对房型匹配词
        <textarea data-field="competitorRoomNames" rows="4" placeholder="每行一个，例如：&#10;高级大床房&#10;豪华大床房">${escapeHtmlText(competitorRoomNames)}</textarea>
      </label>
      <label class="checkbox full">
        <input type="checkbox" data-field="enabled" ${item?.enabled === false ? "" : "checked"}>
        启用这条房型映射
      </label>
    </div>
  `
  manualRoomList.appendChild(row)
}

function renderManualRoomEmptyStateIfNeeded() {
  const rows = Array.from(manualRoomList.querySelectorAll(".manual-room-item"))
  if (rows.length) {
    manualRoomList.querySelector(".manual-room-empty")?.remove()
    return
  }
  const empty = document.createElement("div")
  empty.className = "manual-room-empty"
  empty.textContent = "还没有自定义房型，先新增一条。"
  manualRoomList.appendChild(empty)
}

function syncManualRoomTitles() {
  Array.from(manualRoomList.querySelectorAll(".manual-room-item")).forEach((row, index) => {
    const title = row.querySelector(".manual-room-item-title")
    if (title) {
      title.textContent = `我的房型 ${index + 1}`
    }
  })
}

function parseCombinedHotelEntry(value) {
  const text = String(value || "").trim()
  if (!text) {
    return null
  }
  const matched = text.match(/^(.+?)\s*[|｜]\s*(https?:\/\/\S+)$/i)
  if (!matched) {
    return null
  }
  return {
    name: matched[1].trim(),
    url: matched[2].trim()
  }
}

function readCompetitorHotels() {
  return Array.from(hotelList.querySelectorAll(".hotel-item"))
    .map((row) => {
      const name = row.querySelector("[data-field='name']")?.value?.trim() || ""
      const url = row.querySelector("[data-field='url']")?.value?.trim() || ""
      const combined = parseCombinedHotelEntry(name) || parseCombinedHotelEntry(url)
      return combined || { name, url }
    })
    .filter((item) => item.name || item.url)
    .filter((item) => item.name && item.url)
    .slice(0, 20)
}

function readManualRoomMappings() {
  return Array.from(manualRoomList.querySelectorAll(".manual-room-item"))
    .map((row) => {
      const displayName = row.querySelector("[data-field='displayName']")?.value?.trim() || ""
      const roomType = row.querySelector("[data-field='roomType']")?.value?.trim() || ""
      const rateName = row.querySelector("[data-field='rateName']")?.value?.trim() || "标准价"
      const currentPriceRaw = Number(row.querySelector("[data-field='currentPrice']")?.value || 0)
      const currentPrice = Number.isFinite(currentPriceRaw) && currentPriceRaw > 0
        ? Math.round(currentPriceRaw * 100) / 100
        : null
      const competitorRoomNames = normalizeManualRoomTerms(row.querySelector("[data-field='competitorRoomNames']")?.value || "")
      const enabled = Boolean(row.querySelector("[data-field='enabled']")?.checked)
      if (!displayName || !currentPrice) {
        return null
      }
      return {
        displayName,
        roomType,
        rateName,
        currentPrice,
        competitorRoomNames,
        enabled
      }
    })
    .filter(Boolean)
    .slice(0, 50)
}

function readForm() {
  return {
    baseUrl: String(baseUrlInput.value || "").trim(),
    debugUrl: String(debugUrlInput.value || "").trim(),
    startUrl: String(startUrlInput.value || "").trim(),
    latestPriceLimit: Number(latestPriceLimitInput.value),
    maxPages: Number(maxPagesInput.value),
    maxHotels: Number(maxHotelsInput.value),
    saveResult: saveResultInput.checked,
    competitorHotels: readCompetitorHotels(),
    manualRoomMappings: readManualRoomMappings()
  }
}

function renderCurrentConfigSummary(config) {
  const manualTargets = String(config?.manualTargets || "")
    .split(/\n+/)
    .map((item) => item.trim())
    .filter(Boolean)
  const competitorHotels = Array.isArray(config?.competitorHotels) ? config.competitorHotels : []
  const manualRoomMappings = Array.isArray(config?.manualRoomMappings) ? config.manualRoomMappings : []
  currentConfigBox.textContent = [
    `服务: ${config?.baseUrl || "-"}`,
    `登录状态: ${Boolean(config?.authenticated) ? "已登录" : "未登录"}`,
    `登录账号: ${config?.authUser?.username || "-"}`,
    `当前店铺: ${config?.currentShop?.shop_name || "-"} (${config?.currentShop?.shop_id || config?.shopId || "-"})`,
    `tenant/shop: ${config?.tenantId || "-"} / ${config?.shopId || "-"}`,
    `调试页: ${config?.debugUrl || "-"}`,
    `分页 / 酒店: ${config?.maxPages || "-"} / ${config?.maxHotels || "-"}`,
    `最新价条数: ${config?.latestPriceLimit || "-"}`,
    `保存结果: ${config?.saveResult ? "开启" : "关闭"}`,
    `竞对酒店: ${competitorHotels.length ? `${competitorHotels.length} 家` : "未配置"}`,
    `房型映射: ${manualRoomMappings.length ? `${manualRoomMappings.length} 条` : "未维护"}`,
    `维护目标: ${manualTargets.length ? manualTargets.join(" / ") : "未填写"}`
  ].join("\n")
}

function renderCurrentPageContext(pageContext) {
  if (!pageContext || pageContext.unsupported) {
    currentPageBox.innerHTML = `
      <div class="meta">
        <div class="row"><span class="row-label">状态</span><span class="row-value">未识别到业务页</span></div>
        <div class="row"><span class="row-label">标签页</span><span class="row-value">${escapeHtml(pageContext?.pageTitle || "-")}</span></div>
        <div class="row"><span class="row-label">URL</span><span class="row-value">${escapeHtml(pageContext?.startUrl || "-")}</span></div>
      </div>
      <div class="tip">${escapeHtml(pageContext?.error || "当前窗口没有可读取的业务标签页")}</div>
    `
    return
  }

  if (isMerchantPortalContext(pageContext)) {
    currentPageBox.innerHTML = `
      <div class="meta">
        <div class="row"><span class="row-label">页面类型</span><span class="row-value">merchant_portal</span></div>
        <div class="row"><span class="row-label">站点</span><span class="row-value">${escapeHtml(pageContext.hostname || "-")}</span></div>
        <div class="row"><span class="row-label">标题</span><span class="row-value">${escapeHtml(pageContext.pageTitle || pageContext.tabTitle || "-")}</span></div>
        <div class="row"><span class="row-label">URL</span><span class="row-value">${escapeHtml(pageContext.startUrl || pageContext.tabUrl || "-")}</span></div>
      </div>
      <div class="tip">当前位于商家后台，可直接回到 Popup 使用改价分析、建议价回填和商家改价动作。</div>
    `
    return
  }

  const targetHotelNames = Array.isArray(pageContext?.targetHotelNames) ? pageContext.targetHotelNames : []
  const tags = targetHotelNames.length
    ? `<div class="tags">${targetHotelNames.map((name) => `<span class="tag">${escapeHtml(name)}</span>`).join("")}</div>`
    : '<div class="tip">当前页未识别到明确酒店名，将仅使用当前 URL 作为采集入口。</div>'

  currentPageBox.innerHTML = `
    <div class="meta">
      <div class="row"><span class="row-label">页面类型</span><span class="row-value">${escapeHtml(pageContext.pageType || "-")}</span></div>
      <div class="row"><span class="row-label">城市</span><span class="row-value">${escapeHtml(pageContext.cityName || "-")}</span></div>
      <div class="row"><span class="row-label">日期</span><span class="row-value">${escapeHtml(pageContext.checkIn || "-")} -> ${escapeHtml(pageContext.checkOut || "-")}</span></div>
      <div class="row"><span class="row-label">关键词</span><span class="row-value">${escapeHtml(pageContext.keyword || "-")}</span></div>
      <div class="row"><span class="row-label">URL</span><span class="row-value">${escapeHtml(pageContext.startUrl || pageContext.tabUrl || "-")}</span></div>
    </div>
    ${tags}
  `
}

async function refreshCurrentPageSummary() {
  refreshPageBtn.disabled = true
  currentPageBox.textContent = "刷新页面信息中..."
  try {
    renderCurrentPageContext(await getCurrentPageContextForSettings())
  } catch (error) {
    renderCurrentPageContext(unsupportedPageContext(error.message || "页面读取失败"))
  } finally {
    refreshPageBtn.disabled = false
  }
}

async function getCurrentPageContextForSettings() {
  const tab = await getLastRelevantTab()
  if (!tab?.id) {
    return unsupportedPageContext("当前窗口没有可读取的业务标签页")
  }
  try {
    const pageContext = await sendTabMessage(tab.id, { type: "GET_PAGE_CONTEXT" })
    return {
      ...pageContext,
      tabUrl: tab.url || pageContext?.startUrl || "",
      tabTitle: tab.title || pageContext?.pageTitle || ""
    }
  } catch (error) {
    return unsupportedPageContext(error.message, tab.url || "", tab.title || "")
  }
}

async function getLastRelevantTab() {
  const tabs = await chrome.tabs.query({ currentWindow: true })
  const candidates = tabs
    .filter((tab) => tab?.id)
    .filter((tab) => !/^chrome-extension:\/\//i.test(String(tab.url || "")))
    .sort((left, right) => Number(right.lastAccessed || 0) - Number(left.lastAccessed || 0))
  return candidates[0] || null
}

function sendTabMessage(tabId, message) {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message))
        return
      }
      if (!response?.ok) {
        reject(new Error(response?.error || "Unknown content script response"))
        return
      }
      resolve(response.data)
    })
  })
}

function unsupportedPageContext(message, tabUrl = "", tabTitle = "") {
  return {
    unsupported: true,
    pageType: "unsupported",
    pageTitle: tabTitle,
    startUrl: tabUrl,
    targetHotelNames: [],
    error: message
  }
}

function isMerchantPortalContext(pageContext) {
  if (!pageContext || typeof pageContext !== "object") {
    return false
  }
  if (String(pageContext.pageType || "").trim().toLowerCase() === "merchant_portal") {
    return true
  }
  const url = String(pageContext.startUrl || pageContext.tabUrl || "")
  return /ebooking\.fliggy\.com/i.test(url)
}

function escapeHtmlAttr(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
}

function escapeHtmlText(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
}

function escapeHtml(value) {
  return escapeHtmlText(value).replace(/"/g, "&quot;")
}

function setMessage(message, isError = false) {
  messageBox.textContent = message
  messageBox.style.color = isError ? "#b42318" : "#8d6542"
}

function sendMessage(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message))
        return
      }
      if (!response?.ok) {
        reject(new Error(response?.error || "Unknown extension error"))
        return
      }
      resolve(response.data)
    })
  })
}
