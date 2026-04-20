const DEFAULT_CONFIG = {
  baseUrl: "http://127.0.0.1:8000",
  tenantId: "1",
  shopId: "1",
  debugUrl: "http://127.0.0.1:9222",
  saveResult: false,
  authToken: "",
  authUser: null,
  currentShop: null,
  competitorHotels: []
}

function normalizeCompetitorHotels(items) {
  if (!Array.isArray(items)) {
    return []
  }
  const result = []
  const seen = new Set()
  for (const item of items) {
    if (!item || typeof item !== "object") {
      continue
    }
    const name = String(item.name || "").replace(/\s+/g, " ").trim()
    const url = String(item.url || "").trim()
    if (!name || !url) {
      continue
    }
    const key = `${name}|${url}`
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    result.push({ name, url })
    if (result.length >= 20) {
      break
    }
  }
  return result
}

function normalizeConfig(config) {
  const stored = config && typeof config === "object" ? config : {}
  const authUser = stored.authUser && typeof stored.authUser === "object" ? stored.authUser : null
  const currentShop = stored.currentShop && typeof stored.currentShop === "object" ? stored.currentShop : null
  return {
    ...DEFAULT_CONFIG,
    ...stored,
    baseUrl: String(stored.baseUrl || DEFAULT_CONFIG.baseUrl).trim() || DEFAULT_CONFIG.baseUrl,
    tenantId: String(authUser?.tenant_id || stored.tenantId || DEFAULT_CONFIG.tenantId).trim() || DEFAULT_CONFIG.tenantId,
    shopId: String(currentShop?.shop_id || stored.shopId || DEFAULT_CONFIG.shopId).trim() || DEFAULT_CONFIG.shopId,
    debugUrl: String(stored.debugUrl || DEFAULT_CONFIG.debugUrl).trim() || DEFAULT_CONFIG.debugUrl,
    saveResult: Boolean(stored.saveResult),
    authToken: String(stored.authToken || "").trim(),
    authUser,
    currentShop,
    competitorHotels: normalizeCompetitorHotels(stored.competitorHotels)
  }
}

async function readConfigFromStorage() {
  const [localStored, syncStored] = await Promise.all([
    chrome.storage.local.get(null).catch(() => ({})),
    chrome.storage.sync.get(null).catch(() => ({}))
  ])
  return normalizeConfig({
    ...syncStored,
    ...localStored
  })
}

function buildCompetitorRoomPricesPayload(payload = {}) {
  const config = normalizeConfig(payload.config)
  const hotels = normalizeCompetitorHotels(payload.hotels || config.competitorHotels)
  if (!hotels.length) {
    throw new Error("请先在设置页配置至少一条竞对酒店详情页")
  }
  return {
    shop_id: Number(config.shopId),
    hotels,
    save_result: payload.saveResult !== undefined ? Boolean(payload.saveResult) : Boolean(config.saveResult)
  }
}

function normalizeRequestBaseUrl(baseUrl) {
  return String(baseUrl || DEFAULT_CONFIG.baseUrl).trim().replace(/\/+$/, "")
}

async function requestJsonWithConfig(config, path, options = {}) {
  const endpoint = /^https?:\/\//i.test(path)
    ? path
    : `${normalizeRequestBaseUrl(config.baseUrl)}${path}`
  const requestOptions = {
    method: options.method || "GET",
    headers: {
      "X-Tenant-Id": String(config.tenantId),
      "X-Shop-Id": String(config.shopId),
      ...(String(config.authToken || "").trim() ? { Authorization: `Bearer ${String(config.authToken || "").trim()}` } : {}),
      ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {})
    }
  }
  if (options.body !== undefined) {
    requestOptions.body = JSON.stringify(options.body)
  }
  const response = await fetch(endpoint, requestOptions)
  const text = await response.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch (error) {
    data = null
  }
  if (!response.ok) {
    throw new Error(data?.error || data?.message || text || `HTTP ${response.status}`)
  }
  return data
}

async function requestMerchantCredentialSummary() {
  const config = await readConfigFromStorage()
  const url = `${normalizeRequestBaseUrl(config.baseUrl)}/merchant/credentials?shop_id=${encodeURIComponent(String(Number(config.shopId) || 0))}`
  return requestJsonWithConfig(config, url)
}

async function saveMerchantCredentialSummary(payload = {}) {
  const config = await readConfigFromStorage()
  const saved = await requestJsonWithConfig(config, "/merchant/credentials", {
    method: "POST",
    body: {
      shop_id: Number(config.shopId),
      username: String(payload.username || "").trim(),
      password: String(payload.password || "").trim(),
      login_url: String(payload.loginUrl || payload.login_url || "").trim() || undefined,
      price_url: String(payload.priceUrl || payload.price_url || "").trim() || undefined,
      storage_state_name: String(payload.storageStateName || payload.storage_state_name || "").trim(),
      selectors: payload.selectors && typeof payload.selectors === "object" ? payload.selectors : undefined
    }
  })
  if (!(payload.autoLoginAfterSave || payload.auto_login_after_save)) {
    return { saved, login: null }
  }
  const login = await requestJsonWithConfig(config, "/merchant/fliggy/session/login", {
    method: "POST",
    body: {
      shop_id: Number(config.shopId),
      username: String(payload.username || "").trim(),
      password: String(payload.password || "").trim(),
      login_url: String(payload.loginUrl || payload.login_url || "").trim() || undefined,
      storage_state_name: String(payload.storageStateName || payload.storage_state_name || "").trim(),
      headless: payload.loginHeadless !== undefined ? Boolean(payload.loginHeadless) : Boolean(payload.login_headless),
      selectors: payload.selectors && typeof payload.selectors === "object" ? payload.selectors : undefined
    }
  })
  return { saved, login }
}

async function requestMerchantMappingsSummary(payload = {}) {
  const config = await readConfigFromStorage()
  const url = `${normalizeRequestBaseUrl(config.baseUrl)}/pricing/merchant-mappings?shop_id=${encodeURIComponent(String(Number(config.shopId) || 0))}&platform=${encodeURIComponent(String(payload.platform || "fliggy"))}&only_enabled=${payload.onlyEnabled ? "1" : "0"}`
  return requestJsonWithConfig(config, url)
}

async function saveMerchantMappingSummary(payload = {}) {
  const config = await readConfigFromStorage()
  return requestJsonWithConfig(config, "/pricing/merchant-mappings", {
    method: "POST",
    body: {
      shop_id: Number(config.shopId),
      platform: String(payload.platform || "fliggy"),
      room_name: String(payload.roomName || payload.room_name || "").trim(),
      rate_name: String(payload.rateName || payload.rate_name || "").trim(),
      gid: String(payload.gid || "").trim(),
      hid: String(payload.hid || "").trim(),
      status: String(payload.status || "draft").trim() || "draft",
      notes: String(payload.notes || "").trim(),
      last_seen_price: String(payload.lastSeenPrice ?? payload.last_seen_price ?? "").trim(),
    }
  })
}

async function refreshMerchantMappingsSummary(payload = {}) {
  const config = await readConfigFromStorage()
  return requestJsonWithConfig(config, "/pricing/merchant-mappings/refresh-prices", {
    method: "POST",
    body: {
      shop_id: Number(config.shopId),
      price_url: String(payload.priceUrl || payload.price_url || "").trim() || undefined,
      headless: payload.headless !== undefined ? Boolean(payload.headless) : true,
      selectors: payload.selectors && typeof payload.selectors === "object" ? payload.selectors : undefined,
      selected_items: []
    }
  })
}

function normalizeCompetitorPricingAdviceHotels(items) {
  if (!Array.isArray(items)) {
    return []
  }
  const hotels = []
  for (const item of items) {
    if (!item || typeof item !== "object") {
      continue
    }
    const hotelName = String(item.hotel_name || item.name || "").replace(/\s+/g, " ").trim()
    if (!hotelName) {
      continue
    }
    const rooms = Array.isArray(item.rooms)
      ? item.rooms.map((room) => {
          if (!room || typeof room !== "object") {
            return null
          }
          const price = Number(room.price)
          if (!Number.isFinite(price) || price <= 0) {
            return null
          }
          const roomType = String(room.room_type || room.roomType || room.rate_name || room.rateName || "").replace(/\s+/g, " ").trim()
          const rateName = String(room.rate_name || room.rateName || roomType || "").replace(/\s+/g, " ").trim()
          return {
            room_type: roomType || rateName || "未命名房型",
            rate_name: rateName || roomType || "未命名价型",
            price: Math.round(price * 100) / 100,
            breakfast: String(room.breakfast || "").trim() || undefined,
            cancelable: String(room.cancelable || "").trim() || undefined
          }
        }).filter(Boolean)
      : []
    if (!rooms.length) {
      continue
    }
    hotels.push({
      hotel_name: hotelName,
      hotel_url: String(item.hotel_url || item.url || "").trim() || undefined,
      rooms
    })
    if (hotels.length >= 20) {
      break
    }
  }
  return hotels
}

function toPositiveNumber(value) {
  const next = Number(value)
  if (!Number.isFinite(next) || next <= 0) {
    return null
  }
  return Math.round(next * 100) / 100
}

function toPositiveInteger(value) {
  const next = Number(value)
  if (!Number.isFinite(next) || next <= 0) {
    return null
  }
  return Math.round(next)
}

function toNonNegativeInteger(value) {
  const next = Number(value)
  if (!Number.isFinite(next) || next < 0) {
    return null
  }
  return Math.round(next)
}

async function requestCompetitorPricingAdvice(payload = {}) {
  const config = await readConfigFromStorage()
  const totalRooms = toPositiveInteger(payload.totalRooms ?? payload.inventorySnapshot?.total_rooms)
  const availableRooms = toNonNegativeInteger(payload.availableRooms ?? payload.inventorySnapshot?.available_rooms)
  const currentPrice = toPositiveNumber(payload.currentPrice ?? payload.inventorySnapshot?.current_price)
  if (!totalRooms) {
    throw new Error("请先填写总房量")
  }
  if (availableRooms === null) {
    throw new Error("请先填写可售房量")
  }
  if (availableRooms > totalRooms) {
    throw new Error("可售房量不能大于总房量")
  }
  const competitorHotels = normalizeCompetitorPricingAdviceHotels(
    payload.competitorHotels || payload.competitor_hotels || payload.roomPrices?.hotels
  )
  if (!competitorHotels.length) {
    throw new Error("请先抓取竞对房型价，再生成建议价")
  }
  return requestJsonWithConfig(config, "/plugin/pricing/competitor-advice-preview", {
    method: "POST",
    body: {
      shop_id: Number(config.shopId),
      competitor_hotel_name: String(payload.competitorHotelName || payload.competitor_hotel_name || "").replace(/\s+/g, " ").trim() || undefined,
      strategy: String(payload.strategy || "balanced").trim() || "balanced",
      inventory_snapshot: {
        total_rooms: totalRooms,
        available_rooms: availableRooms,
        ...(currentPrice ? { current_price: currentPrice } : {})
      },
      competitor_hotels: competitorHotels
    }
  })
}
function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function isHotelDetailTab(tab) {
  const url = String(tab?.url || tab?.pendingUrl || "").toLowerCase()
  return url.includes("hotel_detail") || url.includes("/hotel/") || url.includes("item.htm?id=")
}

async function waitForTabComplete(tabId, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const currentTab = await chrome.tabs.get(tabId).catch(() => null)
    if (!currentTab) {
      throw new Error(`酒店详情页标签已关闭: ${tabId}`)
    }
    if (currentTab.status === "complete" || isHotelDetailTab(currentTab)) {
      return currentTab
    }
    await delay(500)
  }

  const lastTab = await chrome.tabs.get(tabId).catch(() => null)
  if (lastTab && isHotelDetailTab(lastTab)) {
    return lastTab
  }
  throw new Error(`等待酒店详情页加载超时: ${tabId}`)
}

async function sendMessageToTab(tabId, message) {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message))
        return
      }
      if (!response?.ok) {
        reject(new Error(response?.error || "Unknown tab message error"))
        return
      }
      resolve(response.data)
    })
  })
}

async function waitForHotelDetailReceiver(tabId, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs
  let lastError = "????????????"

  while (Date.now() < deadline) {
    const currentTab = await chrome.tabs.get(tabId).catch(() => null)
    if (!currentTab) {
      throw new Error(`??????????: ${tabId}`)
    }

    try {
      const ping = await sendMessageToTab(tabId, { type: "PING_CONTENT_SCRIPT" })
      if (String(ping?.pageType || "") === "hotel_detail") {
        return currentTab
      }
      lastError = `???????????: ${String(ping?.pageType || "unknown")}`
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error)
    }

    await delay(500)
  }

  throw new Error(lastError)
}

async function requestCompetitorRoomPrices(payload = {}) {
  const requestPayload = buildCompetitorRoomPricesPayload(payload)
  const results = []

  for (const hotel of requestPayload.hotels) {
    let tabId = null
    try {
      const tab = await chrome.tabs.create({ url: hotel.url, active: false })
      tabId = tab?.id || null
      if (!tabId) {
        throw new Error("打开酒店详情页失败")
      }
      await waitForTabComplete(tabId, 30000)
      await waitForHotelDetailReceiver(tabId, 20000)
      await delay(800)
      const pageResult = await sendMessageToTab(tabId, { type: "GET_CURRENT_HOTEL_ROOM_PRICES" })
      const firstHotel = Array.isArray(pageResult?.hotels) ? pageResult.hotels[0] : null
      const rooms = Array.isArray(firstHotel?.rooms) ? firstHotel.rooms : []
      results.push({
        hotel_name: String(hotel.name || firstHotel?.hotel_name || "当前酒店").trim(),
        hotel_url: String(hotel.url || firstHotel?.hotel_url || "").trim(),
        room_count: rooms.length,
        rooms,
      })
    } catch (error) {
      results.push({
        hotel_name: String(hotel.name || "当前酒店").trim(),
        hotel_url: String(hotel.url || "").trim(),
        error: error instanceof Error ? error.message : String(error),
        rooms: [],
      })
    } finally {
      if (tabId) {
        await chrome.tabs.remove(tabId).catch(() => {})
      }
    }
  }

  return {
    shop_id: Number(requestPayload.shop_id || 0),
    hotel_count: results.length,
    total_rooms: results.reduce((sum, item) => sum + Number(Array.isArray(item?.rooms) ? item.rooms.length : 0), 0),
    saved_count: 0,
    hotels: results,
  }
}

async function handleBridgeRequest(action, payload) {
  if (action === "competitor-room-prices") {
    return requestCompetitorRoomPrices(payload)
  }
  if (action === "merchant-credential-get") {
    return requestMerchantCredentialSummary()
  }
  if (action === "merchant-credential-save") {
    return saveMerchantCredentialSummary(payload)
  }
  if (action === "merchant-mapping-list") {
    return requestMerchantMappingsSummary(payload)
  }
  if (action === "merchant-mapping-save") {
    return saveMerchantMappingSummary(payload)
  }
  if (action === "merchant-mapping-refresh") {
    return refreshMerchantMappingsSummary(payload)
  }
  if (action === "competitor-pricing-advice-preview") {
    return requestCompetitorPricingAdvice(payload)
  }
  throw new Error(`Unsupported bridge action: ${String(action || "unknown")}`)
}

window.addEventListener("message", async (event) => {
  const data = event.data
  if (!data || data.type !== "FLIGGY_OPS_BRIDGE_REQUEST" || !data.requestId) {
    return
  }
  try {
    const result = await handleBridgeRequest(data.action, data.payload || {})
    event.source?.postMessage({
      type: "FLIGGY_OPS_BRIDGE_RESPONSE",
      requestId: data.requestId,
      ok: true,
      data: result
    }, "*")
  } catch (error) {
    event.source?.postMessage({
      type: "FLIGGY_OPS_BRIDGE_RESPONSE",
      requestId: data.requestId,
      ok: false,
      error: error instanceof Error ? error.message : String(error)
    }, "*")
  }
})



