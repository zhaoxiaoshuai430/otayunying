const ROOT_ID = "fliggy-ops-extension-root"

let panelApi = null

const DEFAULT_EXTENSION_CONFIG = {
  baseUrl: "http://127.0.0.1:8000",
  tenantId: "1",
  shopId: "1",
  debugUrl: "http://127.0.0.1:9222",
  startUrl: "https://hotel.fliggy.com/",
  latestPriceLimit: 5,
  maxPages: 1,
  maxHotels: 1,
  saveResult: false,
  competitorHotels: [],
  merchantPlatformLinks: [],
  manualRoomMappingsByShop: {},
  manualRoomMappings: [],
  manualTargets: ""
}
const COMPETITOR_ROOM_PRICE_MESSAGE_TYPES = [
  "COMPETITOR_ROOM_PRICES_TABS",
  "COMPETITOR_ROOM_PRICES"
]

function coercePositiveInt(value, fallback, minimum, maximum) {
  const next = Number(value)
  if (!Number.isFinite(next)) {
    return fallback
  }
  return Math.min(Math.max(Math.round(next), minimum), maximum)
}

function coerceTopLevelPositiveNumber(value) {
  const next = Number(value)
  if (!Number.isFinite(next) || next <= 0) {
    return null
  }
  return Math.round(next * 100) / 100
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

function normalizeMerchantPlatformSelectors(rawValue) {
  if (!rawValue || typeof rawValue !== "object" || Array.isArray(rawValue)) {
    return undefined
  }
  const result = {}
  for (const [key, value] of Object.entries(rawValue)) {
    if (typeof value === "string") {
      const text = value.trim()
      if (text) {
        result[key] = text
      }
      continue
    }
    if (!Array.isArray(value)) {
      continue
    }
    const values = value.map((item) => String(item || "").trim()).filter(Boolean)
    if (values.length) {
      result[key] = values
    }
  }
  return Object.keys(result).length ? result : undefined
}

function sanitizeMerchantPlatformStorageToken(value) {
  const normalized = String(value || "").trim().toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "")
  return normalized || "platform"
}

function normalizeMerchantPlatformLink(item) {
  if (!item || typeof item !== "object") {
    return null
  }
  const name = String(item.name || item.label || "").replace(/\s+/g, " ").trim()
  const priceUrl = String(item.priceUrl || item.price_url || item.url || "").trim()
  if (!priceUrl) {
    return null
  }
  const loginUrl = String(item.loginUrl || item.login_url || "").trim()
  const username = String(item.username || "").trim()
  const password = String(item.password || "").trim()
  const selectors = normalizeMerchantPlatformSelectors(item.selectors)
  const storageSeed = name || loginUrl || priceUrl
  const storageStateName = String(item.storageStateName || item.storage_state_name || "").trim()
    || `merchant-${sanitizeMerchantPlatformStorageToken(storageSeed)}.json`
  return {
    name: name || "未命名平台",
    priceUrl,
    loginUrl,
    username,
    password,
    selectors,
    storageStateName,
    enabled: item.enabled !== false
  }
}

function normalizeMerchantPlatformLinks(items) {
  if (!Array.isArray(items)) {
    return []
  }
  const result = []
  const seen = new Set()
  for (const item of items) {
    const normalized = normalizeMerchantPlatformLink(item)
    if (!normalized) {
      continue
    }
    const dedupeKey = normalized.priceUrl
    if (seen.has(dedupeKey)) {
      continue
    }
    seen.add(dedupeKey)
    result.push(normalized)
    if (result.length >= 20) {
      break
    }
  }
  return result
}

function normalizeManualRoomTerms(items) {
  if (!Array.isArray(items)) {
    return []
  }

  const result = []
  const seen = new Set()
  for (const rawItem of items) {
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

function normalizeManualRoomMapping(item) {
  if (!item || typeof item !== "object") {
    return null
  }
  const displayName = String(item.displayName || item.display_name || "").replace(/\s+/g, " ").trim()
  const roomType = String(item.roomType || item.room_type || "").replace(/\s+/g, " ").trim()
  const rateName = String(item.rateName || item.rate_name || "").replace(/\s+/g, " ").trim() || "标准价"
  const currentPrice = coerceTopLevelPositiveNumber(item.currentPrice ?? item.current_price)
  if (!displayName || !currentPrice) {
    return null
  }
  return {
    displayName,
    roomType: roomType || displayName,
    rateName,
    currentPrice,
    competitorRoomNames: normalizeManualRoomTerms(item.competitorRoomNames || item.competitor_room_names),
    enabled: item.enabled !== false
  }
}

function normalizeManualRoomMappings(items) {
  if (!Array.isArray(items)) {
    return []
  }

  const result = []
  const seen = new Set()
  for (const item of items) {
    const normalized = normalizeManualRoomMapping(item)
    if (!normalized || normalized.enabled === false) {
      continue
    }
    const dedupeKey = [normalized.displayName, normalized.roomType, normalized.rateName].join("|")
    if (seen.has(dedupeKey)) {
      continue
    }
    seen.add(dedupeKey)
    result.push(normalized)
    if (result.length >= 50) {
      break
    }
  }
  return result
}

function normalizeManualRoomMappingsByShop(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {}
  }
  const result = {}
  for (const [shopId, items] of Object.entries(value)) {
    const normalizedItems = normalizeManualRoomMappings(items)
    if (!normalizedItems.length) {
      continue
    }
    result[String(shopId).trim()] = normalizedItems
  }
  return result
}

function resolveActiveShopId(config) {
  const currentShopId = String(config?.currentShop?.shop_id || "").trim()
  if (currentShopId) {
    return currentShopId
  }
  const shopId = String(config?.shopId || "").trim()
  return shopId || DEFAULT_EXTENSION_CONFIG.shopId
}

function getManualRoomMappingsForShop(config, explicitShopId = "") {
  const mappingsByShop = normalizeManualRoomMappingsByShop(config?.manualRoomMappingsByShop)
  const shopId = String(explicitShopId || resolveActiveShopId(config) || "").trim()
  if (shopId && Array.isArray(mappingsByShop[shopId]) && mappingsByShop[shopId].length) {
    return mappingsByShop[shopId]
  }
  return normalizeManualRoomMappings(config?.manualRoomMappings)
}


function normalizeMerchantRoomMapping(item) {
  if (!item || typeof item !== "object") {
    return null
  }
  const status = String(item.status || "").trim().toLowerCase()
  if (["disabled", "inactive", "deleted", "archived"].includes(status)) {
    return null
  }
  const roomType = String(item.room_name || item.roomName || "").replace(/\s+/g, " ").trim()
  const rateName = String(item.rate_name || item.rateName || "").replace(/\s+/g, " ").trim() || "标准价"
  const currentPrice = coerceTopLevelPositiveNumber(item.last_seen_price ?? item.lastSeenPrice ?? item.current_price ?? item.currentPrice)
  if (!roomType || !currentPrice) {
    return null
  }
  const displayName = String(item.display_name || item.displayName || "").replace(/\s+/g, " ").trim()
    || (rateName && rateName !== "标准价" ? `${roomType} / ${rateName}` : roomType)
  return {
    displayName,
    roomType,
    rateName,
    currentPrice,
    competitorRoomNames: normalizeManualRoomTerms(item.competitorRoomNames || item.competitor_room_names),
    enabled: item.enabled !== false
  }
}

function normalizeMerchantRoomMappings(items) {
  if (!Array.isArray(items)) {
    return []
  }

  const result = []
  const seen = new Set()
  for (const item of items) {
    const normalized = normalizeMerchantRoomMapping(item)
    if (!normalized || normalized.enabled === false) {
      continue
    }
    const dedupeKey = [normalized.roomType, normalized.rateName].join("|")
    if (seen.has(dedupeKey)) {
      continue
    }
    seen.add(dedupeKey)
    result.push(normalized)
    if (result.length >= 100) {
      break
    }
  }
  return result
}

function getPreferredRoomMappingState(config, merchantMappings) {
  const backendMappings = normalizeMerchantRoomMappings(merchantMappings)
  if (backendMappings.length) {
    return {
      items: backendMappings,
      count: backendMappings.length,
      source: "merchant",
      sourceLabel: "后端映射"
    }
  }

  const localMappings = getManualRoomMappingsForShop(config)
  return {
    items: localMappings,
    count: localMappings.length,
    source: localMappings.length ? "local" : "none",
    sourceLabel: localMappings.length ? "本地映射" : "未维护"
  }
}

function mergeStoredConfigAreas(localStored, syncStored) {
  const localData = localStored && typeof localStored === "object" ? localStored : {}
  const syncData = syncStored && typeof syncStored === "object" ? syncStored : {}
  const merged = {
    ...syncData,
    ...localData
  }

  const localUpdatedAt = Number(localData.configUpdatedAt || 0)
  const syncUpdatedAt = Number(syncData.configUpdatedAt || 0)
  if (localUpdatedAt && syncUpdatedAt && localUpdatedAt !== syncUpdatedAt) {
    return localUpdatedAt >= syncUpdatedAt
      ? { ...syncData, ...localData }
      : { ...localData, ...syncData }
  }

  const localCompetitorHotels = normalizeCompetitorHotels(localData.competitorHotels)
  const syncCompetitorHotels = normalizeCompetitorHotels(syncData.competitorHotels)
  if (localCompetitorHotels.length) {
    merged.competitorHotels = localCompetitorHotels
  } else if (syncCompetitorHotels.length) {
    merged.competitorHotels = syncCompetitorHotels
  }

  const localMerchantPlatformLinks = normalizeMerchantPlatformLinks(localData.merchantPlatformLinks)
  const syncMerchantPlatformLinks = normalizeMerchantPlatformLinks(syncData.merchantPlatformLinks)
  if (localMerchantPlatformLinks.length) {
    merged.merchantPlatformLinks = localMerchantPlatformLinks
  } else if (syncMerchantPlatformLinks.length) {
    merged.merchantPlatformLinks = syncMerchantPlatformLinks
  }

  const localManualTargets = String(localData.manualTargets || "").trim()
  const syncManualTargets = String(syncData.manualTargets || "").trim()
  if (localManualTargets) {
    merged.manualTargets = localManualTargets
  } else if (syncManualTargets) {
    merged.manualTargets = syncManualTargets
  }

  const localManualRoomMappingsByShop = normalizeManualRoomMappingsByShop(localData.manualRoomMappingsByShop)
  const syncManualRoomMappingsByShop = normalizeManualRoomMappingsByShop(syncData.manualRoomMappingsByShop)
  merged.manualRoomMappingsByShop = Object.keys(localManualRoomMappingsByShop).length
    ? { ...syncManualRoomMappingsByShop, ...localManualRoomMappingsByShop }
    : syncManualRoomMappingsByShop

  const localManualRoomMappings = normalizeManualRoomMappings(localData.manualRoomMappings)
  const syncManualRoomMappings = normalizeManualRoomMappings(syncData.manualRoomMappings)
  if (localManualRoomMappings.length) {
    merged.manualRoomMappings = localManualRoomMappings
  } else if (syncManualRoomMappings.length) {
    merged.manualRoomMappings = syncManualRoomMappings
  }

  for (const key of ["baseUrl", "tenantId", "shopId", "debugUrl", "startUrl"]) {
    const localValue = String(localData[key] || "").trim()
    const syncValue = String(syncData[key] || "").trim()
    if (localValue) {
      merged[key] = localValue
    } else if (syncValue) {
      merged[key] = syncValue
    }
  }

  for (const key of ["latestPriceLimit", "maxPages", "maxHotels"]) {
    const localValue = Number(localData[key])
    const syncValue = Number(syncData[key])
    if (Number.isFinite(localValue) && localValue > 0) {
      merged[key] = localValue
    } else if (Number.isFinite(syncValue) && syncValue > 0) {
      merged[key] = syncValue
    }
  }

  if (typeof localData.saveResult === "boolean") {
    merged.saveResult = localData.saveResult
  } else if (typeof syncData.saveResult === "boolean") {
    merged.saveResult = syncData.saveResult
  }

  return merged
}

function normalizeConfig(config) {
  const stored = config && typeof config === "object" ? config : {}
  const manualRoomMappingsByShop = normalizeManualRoomMappingsByShop(stored.manualRoomMappingsByShop)
  const shopId = resolveActiveShopId(stored)
  return {
    ...DEFAULT_EXTENSION_CONFIG,
    ...stored,
    baseUrl: String(stored.baseUrl || DEFAULT_EXTENSION_CONFIG.baseUrl).trim() || DEFAULT_EXTENSION_CONFIG.baseUrl,
    tenantId: String(stored.tenantId || DEFAULT_EXTENSION_CONFIG.tenantId).trim() || DEFAULT_EXTENSION_CONFIG.tenantId,
    shopId: String(stored.shopId || DEFAULT_EXTENSION_CONFIG.shopId).trim() || DEFAULT_EXTENSION_CONFIG.shopId,
    debugUrl: String(stored.debugUrl || DEFAULT_EXTENSION_CONFIG.debugUrl).trim() || DEFAULT_EXTENSION_CONFIG.debugUrl,
    startUrl: String(stored.startUrl || DEFAULT_EXTENSION_CONFIG.startUrl).trim() || DEFAULT_EXTENSION_CONFIG.startUrl,
    latestPriceLimit: coercePositiveInt(stored.latestPriceLimit, DEFAULT_EXTENSION_CONFIG.latestPriceLimit, 1, 500),
    maxPages: coercePositiveInt(stored.maxPages, DEFAULT_EXTENSION_CONFIG.maxPages, 1, 20),
    maxHotels: coercePositiveInt(stored.maxHotels, DEFAULT_EXTENSION_CONFIG.maxHotels, 1, 500),
    saveResult: Boolean(stored.saveResult),
    competitorHotels: normalizeCompetitorHotels(stored.competitorHotels),
    merchantPlatformLinks: normalizeMerchantPlatformLinks(stored.merchantPlatformLinks),
    manualRoomMappingsByShop,
    manualRoomMappings: getManualRoomMappingsForShop({
      ...stored,
      manualRoomMappingsByShop
    }, shopId),
    manualTargets: String(stored.manualTargets || "")
  }
}
async function readConfigFromStorage() {
  const [localStored, syncStored] = await Promise.all([
    chrome.storage.local.get(null).catch(() => ({})),
    chrome.storage.sync.get(null).catch(() => ({}))
  ])
  return normalizeConfig(mergeStoredConfigAreas(localStored, syncStored))
}

function selectPreferredConfig(runtimeConfig, storageConfig) {
  const runtimeValue = normalizeConfig(runtimeConfig)
  if (!storageConfig) {
    return runtimeValue
  }
  if (Boolean(runtimeValue?.authenticated && runtimeValue?.authUser && runtimeValue?.currentShop)) {
    return runtimeValue
  }

  const storageValue = normalizeConfig(storageConfig)
  const runtimeHotels = normalizeCompetitorHotels(runtimeValue.competitorHotels)
  const storageHotels = normalizeCompetitorHotels(storageValue.competitorHotels)
  const runtimeMerchantPlatformLinks = normalizeMerchantPlatformLinks(runtimeValue.merchantPlatformLinks)
  const storageMerchantPlatformLinks = normalizeMerchantPlatformLinks(storageValue.merchantPlatformLinks)
  const runtimeManualTargets = String(runtimeValue.manualTargets || "").trim()
  const storageManualTargets = String(storageValue.manualTargets || "").trim()
  const runtimeManualRoomMappings = getManualRoomMappingsForShop(runtimeValue)
  const storageManualRoomMappings = getManualRoomMappingsForShop(storageValue)

  if (!runtimeHotels.length && !storageHotels.length && !runtimeMerchantPlatformLinks.length && !storageMerchantPlatformLinks.length && !runtimeManualTargets && !storageManualTargets && !runtimeManualRoomMappings.length && !storageManualRoomMappings.length) {
    return runtimeValue
  }

  return normalizeConfig({
    ...storageValue,
    ...runtimeValue,
    competitorHotels: runtimeHotels.length ? runtimeHotels : storageHotels,
    merchantPlatformLinks: runtimeMerchantPlatformLinks.length ? runtimeMerchantPlatformLinks : storageMerchantPlatformLinks,
    manualRoomMappingsByShop: Object.keys(runtimeValue?.manualRoomMappingsByShop || {}).length
      ? runtimeValue.manualRoomMappingsByShop
      : storageValue.manualRoomMappingsByShop,
    manualRoomMappings: runtimeManualRoomMappings.length ? runtimeManualRoomMappings : storageManualRoomMappings,
    manualTargets: runtimeManualTargets || storageManualTargets
  })
}
async function getEffectiveConfig() {
  const storageConfig = await readConfigFromStorage().catch(() => null)
  try {
    const runtimeConfig = normalizeConfig(await sendRuntimeMessage({ type: "GET_CONFIG" }))
    return selectPreferredConfig(runtimeConfig, storageConfig)
  } catch (error) {
    if (storageConfig) {
      return storageConfig
    }
    throw error
  }
}

function normalizeDebugSnapshot(config) {
  const stored = config && typeof config === "object" ? config : {}
  return {
    ...stored,
    competitorHotels: normalizeCompetitorHotels(stored.competitorHotels),
    merchantPlatformLinks: normalizeMerchantPlatformLinks(stored.merchantPlatformLinks),
    manualRoomMappingsByShop: normalizeManualRoomMappingsByShop(stored.manualRoomMappingsByShop),
    manualRoomMappings: getManualRoomMappingsForShop(stored),
    manualTargets: String(stored.manualTargets || "")
  }
}
async function buildConfigDebugInfo() {
  const [localStored, syncStored] = await Promise.all([
    chrome.storage.local.get(null).catch(() => ({})),
    chrome.storage.sync.get(null).catch(() => ({}))
  ])
  const mergedStored = mergeStoredConfigAreas(localStored, syncStored)

  let runtimeConfig = null
  let runtimeGetConfigError = null
  let runtimeDebug = null
  let runtimeDebugError = null

  try {
    runtimeDebug = await sendRuntimeMessage({ type: "GET_CONFIG_DEBUG" })
  } catch (error) {
    runtimeDebugError = error instanceof Error ? error.message : String(error)
  }

  try {
    runtimeConfig = normalizeConfig(await sendRuntimeMessage({ type: "GET_CONFIG" }))
  } catch (error) {
    runtimeGetConfigError = error instanceof Error ? error.message : String(error)
  }

  const storageConfig = normalizeConfig(mergedStored)
  const effectiveConfig = selectPreferredConfig(runtimeConfig || storageConfig, storageConfig)
  return {
    source: runtimeDebug ? "background_debug+content_storage" : "content_storage_only",
    local: normalizeDebugSnapshot(localStored),
    sync: normalizeDebugSnapshot(syncStored),
    merged: normalizeDebugSnapshot(mergedStored),
    effective: effectiveConfig,
    runtime: {
      getConfigOk: Boolean(runtimeConfig),
      getConfigError: runtimeGetConfigError,
      getConfigDebugOk: Boolean(runtimeDebug),
      getConfigDebugError: runtimeDebugError,
      config: runtimeConfig,
      debugPayload: runtimeDebug || null
    },
    counts: {
      local: normalizeCompetitorHotels(localStored.competitorHotels).length,
      sync: normalizeCompetitorHotels(syncStored.competitorHotels).length,
      merged: normalizeCompetitorHotels(mergedStored.competitorHotels).length,
      effective: normalizeCompetitorHotels(effectiveConfig.competitorHotels).length
    },
    meta: {
      generatedAt: new Date().toISOString(),
      localUpdatedAt: Number(localStored.configUpdatedAt || 0),
      syncUpdatedAt: Number(syncStored.configUpdatedAt || 0)
    }
  }
}

let bridgeFramePromise = null

function ensureBridgeFrame() {
  if (bridgeFramePromise) {
    return bridgeFramePromise
  }

  bridgeFramePromise = new Promise((resolve, reject) => {
    const existing = document.getElementById("fliggy-ops-bridge-frame")
    if (existing) {
      resolve(existing)
      return
    }

    const frame = document.createElement("iframe")
    frame.id = "fliggy-ops-bridge-frame"
    frame.src = chrome.runtime.getURL("bridge.html")
    frame.style.display = "none"
    frame.setAttribute("aria-hidden", "true")
    frame.onload = () => resolve(frame)
    frame.onerror = () => {
      bridgeFramePromise = null
      reject(new Error("桥接页面加载失败"))
    }
    document.documentElement.appendChild(frame)
  })

  return bridgeFramePromise
}

function normalizeBridgeErrorMessage(message) {
  const text = String(message || "").trim()
  if (!text) {
    return "桥接请求失败，请重新加载扩展并刷新当前飞猪页面后重试"
  }
  if (/^\?+$/.test(text) || /Unsupported message type/i.test(text) || /插件尚未重新加载/.test(text) || /插件内直抓房型价/.test(text)) {
    return "当前页面仍在使用旧版下方助手，请重新加载扩展并刷新当前飞猪页面后重试"
  }
  if (/Failed to fetch/i.test(text)) {
    return "桥接请求仍在命中旧版链路，请重新加载扩展并刷新当前飞猪页面后重试"
  }
  return text
}

async function requestViaExtensionBridge(action, payload = {}) {
  const frame = await ensureBridgeFrame()
  const targetWindow = frame.contentWindow
  if (!targetWindow) {
    throw new Error("桥接页面尚未就绪")
  }

  const requestId = `bridge-${Date.now()}-${Math.random().toString(16).slice(2)}`
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      window.removeEventListener("message", handleMessage)
      reject(new Error("桥接请求超时"))
    }, 300000)

    function handleMessage(event) {
      const data = event.data
      if (event.source !== targetWindow || !data || data.type !== "FLIGGY_OPS_BRIDGE_RESPONSE" || data.requestId !== requestId) {
        return
      }
      clearTimeout(timer)
      window.removeEventListener("message", handleMessage)
      if (!data.ok) {
        reject(new Error(normalizeBridgeErrorMessage(data.error || "\u6865\u63a5\u8bf7\u6c42\u5931\u8d25")))
        return
      }
      resolve(data.data)
    }

    window.addEventListener("message", handleMessage)
    targetWindow.postMessage({
      type: "FLIGGY_OPS_BRIDGE_REQUEST",
      requestId,
      action,
      payload
    }, "*")
  })
}

if (window.top === window.self && !document.getElementById(ROOT_ID)) {
  panelApi = injectPanel()
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "GET_PAGE_CONTEXT") {
    sendResponse({ ok: true, data: getPageContext() })
    return false
  }

  if (message?.type === "GET_PAGE_SNAPSHOT") {
    getPageSnapshot(message)
      .then((data) => {
        sendResponse({ ok: true, data })
      })
      .catch((error) => {
        sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) })
      })
    return true
  }

  if (message?.type === "OPEN_PANEL") {
    if (!panelApi) {
      sendResponse({ ok: false, error: "\u9875\u9762\u9762\u677f\u672a\u521d\u59cb\u5316" })
      return false
    }
    const data = panelApi.open()
    sendResponse({ ok: true, data })
    return false
  }

  if (message?.type === "PING_CONTENT_SCRIPT") {
    const pageContext = getPageContext()
    sendResponse({
      ok: true,
      data: {
        ready: true,
        pageType: String(pageContext?.pageType || ""),
        url: String(window.location.href || "")
      }
    })
    return false
  }

  if (message?.type === "GET_CURRENT_HOTEL_ROOM_PRICES") {
    const pageContext = getPageContext()
    if (String(pageContext?.pageType || "") !== "hotel_detail") {
      sendResponse({ ok: false, error: "\u5f53\u524d\u9875\u9762\u4e0d\u662f\u9152\u5e97\u8be6\u60c5\u9875" })
      return false
    }
    sendResponse({ ok: true, data: parseCurrentHotelDetailRoomPrices() })
    return false
  }

  return false
})

function injectPanel() {
  const pageContextTools = window.FliggyOpsPageContext
  const viewTools = window.FliggyOpsResultView
  if (!pageContextTools || !viewTools) {
    return null
  }

  const host = document.createElement("div")
  host.id = ROOT_ID
  document.documentElement.appendChild(host)

  const shadow = host.attachShadow({ mode: "open" })
  shadow.innerHTML = `
    <style>
      :host {
        all: initial;
      }
      .fliggy-ops-launcher {
        position: fixed;
        right: 20px;
        bottom: 20px;
        z-index: 2147483646;
        width: 64px;
        height: 64px;
        border: none;
        border-radius: 22px;
        background: linear-gradient(135deg, #ff8a00 0%, #ff3d00 100%);
        box-shadow: 0 18px 40px rgba(209, 74, 16, 0.32);
        color: #fff7eb;
        font: 600 13px/1.2 "Noto Sans SC", "Microsoft YaHei", sans-serif;
        cursor: pointer;
      }
      .fliggy-ops-panel {
        position: fixed;
        right: 20px;
        bottom: 96px;
        z-index: 2147483646;
        width: 392px;
        max-height: 78vh;
        display: none;
        overflow: hidden;
        border-radius: 24px;
        background:
          radial-gradient(circle at top left, rgba(255, 196, 87, 0.28), transparent 36%),
          linear-gradient(180deg, #fffaf2 0%, #fff4e3 100%);
        box-shadow: 0 24px 60px rgba(113, 54, 7, 0.22);
        border: 1px solid rgba(185, 121, 39, 0.18);
        color: #4d2f0f;
        font: 14px/1.5 "Noto Sans SC", "Microsoft YaHei", sans-serif;
      }
      .fliggy-ops-panel.is-open {
        display: block;
      }
      .fliggy-ops-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 12px;
        padding: 18px 20px 14px;
        border-bottom: 1px solid rgba(185, 121, 39, 0.16);
      }
      .fliggy-ops-title {
        margin: 0;
        font-size: 18px;
        font-weight: 700;
      }
      .fliggy-ops-subtitle {
        margin: 6px 0 0;
        color: #8a6132;
        font-size: 12px;
      }
      .fliggy-ops-close {
        border: none;
        background: rgba(255, 255, 255, 0.74);
        color: #7c4b14;
        width: 32px;
        height: 32px;
        border-radius: 999px;
        font-size: 18px;
        cursor: pointer;
      }
      .fliggy-ops-body {
        padding: 16px 20px 20px;
        overflow: auto;
        max-height: calc(78vh - 74px);
      }
      .fliggy-ops-nav {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        margin-top: 14px;
      }
      .fliggy-ops-nav-button {
        border: none;
        border-radius: 14px;
        padding: 11px 12px;
        background: rgba(255, 255, 255, 0.74);
        color: #7c4b14;
        font: 700 13px/1.2 "Noto Sans SC", "Microsoft YaHei", sans-serif;
        box-shadow: inset 0 0 0 1px rgba(194, 120, 34, 0.12);
        cursor: pointer;
      }
      .fliggy-ops-nav-button.is-active {
        background: linear-gradient(135deg, #ffb648 0%, #ff7a18 100%);
        color: #fff9f2;
        box-shadow: none;
      }
      .fliggy-ops-page {
        display: none;
      }
      .fliggy-ops-page.is-active {
        display: block;
      }
      .fliggy-ops-hidden {
        display: none !important;
      }
      .fliggy-ops-status {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 12px;
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.72);
      }
      .fliggy-ops-dot {
        width: 10px;
        height: 10px;
        border-radius: 999px;
        background: #d97706;
        box-shadow: 0 0 0 4px rgba(217, 119, 6, 0.14);
      }
      .fliggy-ops-dot.ok {
        background: #059669;
        box-shadow: 0 0 0 4px rgba(5, 150, 105, 0.12);
      }
      .fliggy-ops-dot.error {
        background: #dc2626;
        box-shadow: 0 0 0 4px rgba(220, 38, 38, 0.12);
      }
      .fliggy-ops-section {
        margin-top: 16px;
      }
      .fliggy-ops-section h3 {
        margin: 0 0 10px;
        font-size: 13px;
        color: #7c4b14;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }
      .fliggy-ops-card,
      .fliggy-ops-result {
        padding: 12px;
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.72);
        white-space: pre-wrap;
        word-break: break-word;
      }
      .fliggy-ops-meta {
        display: grid;
        gap: 6px;
      }
      .fliggy-ops-row {
        display: flex;
        gap: 8px;
      }
      .fliggy-ops-label {
        flex: 0 0 74px;
        color: #8f6332;
        font-size: 12px;
      }
      .fliggy-ops-value {
        flex: 1;
      }
      .fliggy-ops-actions {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }
      .fliggy-ops-input-label {
        display: block;
        margin-bottom: 8px;
        color: #7c4b14;
        font-size: 12px;
      }
      .fliggy-ops-textarea {
        width: 100%;
        min-height: 72px;
        box-sizing: border-box;
        resize: vertical;
        border: 1px solid rgba(194, 120, 34, 0.16);
        border-radius: 14px;
        padding: 10px 12px;
        background: rgba(255, 255, 255, 0.94);
        color: #7c2d12;
        font: 13px/1.4 "Noto Sans SC", "Microsoft YaHei", sans-serif;
      }
      .fliggy-ops-input {
        width: 100%;
        box-sizing: border-box;
        border: 1px solid rgba(194, 120, 34, 0.16);
        border-radius: 14px;
        padding: 10px 12px;
        background: rgba(255, 255, 255, 0.94);
        color: #7c2d12;
        font: 13px/1.4 "Noto Sans SC", "Microsoft YaHei", sans-serif;
      }
      .fliggy-ops-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }
      .fliggy-ops-room-config-list {
        display: grid;
        gap: 10px;
      }
      .fliggy-ops-room-config-item {
        padding: 12px;
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.72);
        box-shadow: inset 0 0 0 1px rgba(194, 120, 34, 0.1);
      }
      .fliggy-ops-room-config-head {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 8px;
        margin-bottom: 10px;
        color: #8f6332;
        font-size: 12px;
      }
      .fliggy-ops-room-config-remove {
        padding: 8px 10px;
        font-size: 12px;
      }
      .fliggy-ops-check {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 10px;
        color: #7c4b14;
        font-size: 12px;
      }
      .fliggy-ops-button {
        border: none;
        border-radius: 14px;
        padding: 12px 10px;
        background: #fff;
        color: #7c2d12;
        font: 600 13px/1.3 "Noto Sans SC", "Microsoft YaHei", sans-serif;
        box-shadow: inset 0 0 0 1px rgba(194, 120, 34, 0.16);
        cursor: pointer;
      }
      .fliggy-ops-button.primary {
        background: linear-gradient(135deg, #ffb648 0%, #ff7a18 100%);
        color: #fff9f2;
        box-shadow: none;
      }
      .fliggy-ops-button:disabled,
      .fliggy-ops-textarea:disabled {
        opacity: 0.56;
        cursor: wait;
      }
      .fliggy-ops-tags {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 8px;
      }
      .fliggy-ops-tag {
        padding: 4px 8px;
        border-radius: 999px;
        background: rgba(255, 184, 72, 0.2);
        color: #7c4b14;
        font-size: 12px;
      }
      .fliggy-ops-list {
        margin: 8px 0 0;
        padding-left: 18px;
      }
      .fliggy-ops-list li + li {
        margin-top: 8px;
      }
      .fliggy-ops-footer {
        margin-top: 12px;
        color: #94653a;
        font-size: 12px;
      }
      .fliggy-ops-empty-state,
      .fliggy-ops-tip {
        color: #8a6132;
        font-size: 12px;
      }
      .fliggy-ops-summary-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
        margin-top: 10px;
      }
      .fliggy-ops-summary-pill {
        padding: 10px;
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.82);
        box-shadow: inset 0 0 0 1px rgba(194, 120, 34, 0.08);
      }
      .fliggy-ops-summary-label {
        color: #8f6332;
        font-size: 11px;
      }
      .fliggy-ops-summary-value {
        margin-top: 4px;
        color: #7c2d12;
        font-size: 16px;
        font-weight: 700;
      }
      .fliggy-ops-workflow-tools {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 10px;
      }
      .fliggy-ops-workflow-tools button {
        border: none;
        border-radius: 12px;
        padding: 8px 10px;
        background: rgba(255, 184, 72, 0.18);
        color: #7c4b14;
        font: 600 12px/1.2 "Noto Sans SC", "Microsoft YaHei", sans-serif;
        cursor: pointer;
      }
      .fliggy-ops-workflow-tools button.secondary {
        background: rgba(255, 255, 255, 0.84);
        font-weight: 500;
        cursor: default;
      }
      .fliggy-ops-workflow-tools button:disabled {
        opacity: 0.62;
        cursor: not-allowed;
      }
      .fliggy-ops-workflow-list {
        display: grid;
        gap: 10px;
        margin-top: 12px;
      }
      .fliggy-ops-workflow-item {
        padding: 12px;
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.88);
        box-shadow: inset 0 0 0 1px rgba(194, 120, 34, 0.08);
      }
      .fliggy-ops-workflow-item-top {
        display: flex;
        align-items: flex-start;
        gap: 10px;
      }
      .fliggy-ops-workflow-item-name {
        color: #7c2d12;
        font-size: 14px;
        font-weight: 700;
      }
      .fliggy-ops-workflow-item-meta {
        margin-top: 4px;
        color: #8f6332;
        font-size: 12px;
      }
      .fliggy-ops-price-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin-top: 10px;
      }
      .fliggy-ops-price-grid-label {
        color: #8f6332;
        font-size: 11px;
        margin-bottom: 4px;
      }
    </style>
    <button class="fliggy-ops-launcher" type="button">运营助手</button>
    <section class="fliggy-ops-panel" aria-live="polite">
      <header class="fliggy-ops-header">
        <div>
          <h2 class="fliggy-ops-title">飞猪运营助手</h2>
          <p class="fliggy-ops-subtitle">页面内就地识别、读取竞对价格，并按当前页参数发起采集。</p>
        </div>
        <button class="fliggy-ops-close" type="button" aria-label="关闭">×</button>
      </header>
      <div class="fliggy-ops-body">
        <div class="fliggy-ops-status">
          <span class="fliggy-ops-dot"></span>
          <span class="fliggy-ops-status-text">等待检查服务</span>
        </div>
        <div class="fliggy-ops-nav">
          <button class="fliggy-ops-nav-button is-active" type="button" data-page="basic">基础功能</button>
          <button class="fliggy-ops-nav-button" type="button" data-page="merchant">商家改价</button>
        </div>
        <div class="fliggy-ops-page is-active" data-page="basic">
          <section class="fliggy-ops-section">
            <h3>账号登录</h3>
            <div id="fliggy-ops-auth-session" class="fliggy-ops-card">当前未登录，请先登录插件账号并选择店铺。</div>
            <div id="fliggy-ops-auth-login-form" class="fliggy-ops-grid" style="margin-top: 10px;">
              <label class="fliggy-ops-input-label">后端地址<input id="fliggy-ops-auth-base-url" class="fliggy-ops-input" type="url" placeholder="http://127.0.0.1:8000"></label>
              <label class="fliggy-ops-input-label">Tenant ID<input id="fliggy-ops-auth-tenant-id" class="fliggy-ops-input" type="number" min="1" step="1" placeholder="1"></label>
              <label class="fliggy-ops-input-label">用户名<input id="fliggy-ops-auth-username" class="fliggy-ops-input" type="text" placeholder="请输入用户名"></label>
              <label class="fliggy-ops-input-label">密码<input id="fliggy-ops-auth-password" class="fliggy-ops-input" type="password" placeholder="请输入密码"></label>
            </div>
            <div id="fliggy-ops-auth-shop-box" class="fliggy-ops-grid fliggy-ops-hidden" style="margin-top: 10px;">
              <label class="fliggy-ops-input-label">当前店铺<select id="fliggy-ops-auth-shop-select" class="fliggy-ops-input"><option value="">暂无可访问店铺</option></select></label>
              <label class="fliggy-ops-input-label">当前账号<input id="fliggy-ops-auth-current-user" class="fliggy-ops-input" type="text" readonly></label>
            </div>
            <div class="fliggy-ops-actions" style="margin-top: 8px;">
              <button class="fliggy-ops-button primary" data-action="auth-login" type="button">登录并进入</button>
              <button class="fliggy-ops-button fliggy-ops-hidden" data-action="auth-refresh" type="button">刷新会话</button>
              <button class="fliggy-ops-button fliggy-ops-hidden" data-action="auth-logout" type="button">退出登录</button>
            </div>
          </section>
          <section class="fliggy-ops-section">
            <h3>当前页面</h3>
            <div class="fliggy-ops-card fliggy-ops-page-context">识别中...</div>
          </section>
          <section class="fliggy-ops-section">
            <h3>指定酒店</h3>
            <label class="fliggy-ops-input-label" for="fliggy-ops-target-input">一行一个酒店名，也支持逗号分隔</label>
            <textarea id="fliggy-ops-target-input" class="fliggy-ops-textarea" placeholder="Example:
West Lake State Guest House
Grand Hyatt Hangzhou"></textarea>
            <div class="fliggy-ops-footer">采集时只返回这里填写的酒店；留空则使用页面自动识别结果。</div>
          </section>
          <section class="fliggy-ops-section">
            <h3>配置竞对房型价</h3>
            <p class="fliggy-ops-footer">先抓取上方竞对房型价，再结合整店库存和我的房型映射生成建议价；已维护映射时会优先按这些房型输出。</p>
            <div id="fliggy-ops-configured-hotels-box" class="fliggy-ops-card" style="margin-top: 8px;">读取竞对酒店配置中...</div>
            <div class="fliggy-ops-actions" style="margin-top: 8px;">
              <button class="fliggy-ops-button primary" data-action="room-prices" type="button">抓取配置房型价</button>
              <button class="fliggy-ops-button" data-action="refresh-room-config" type="button">&#21047;&#26032;&#31454;&#23545;&#37197;&#32622;</button>
              <button class="fliggy-ops-button" data-action="debug-room-config" type="button">&#35786;&#26029;&#31454;&#23545;&#37197;&#32622;</button>
              <button class="fliggy-ops-button" data-action="settings" type="button">维护竞对酒店</button>
            </div>
          </section>
                    <section class="fliggy-ops-section">
            <h3>竞对建议价</h3>
            <p class="fliggy-ops-footer">先抓取上方竞对房型价，再结合本店房型当前价、竞对房型价和整店库存生成建议价。</p>
            <div class="fliggy-ops-grid" style="margin-top: 8px;">
              <label class="fliggy-ops-input-label">总房量<input id="fliggy-ops-advice-total-rooms" class="fliggy-ops-input" type="number" min="1" step="1" placeholder="例如 120"></label>
              <label class="fliggy-ops-input-label">可售房量<input id="fliggy-ops-advice-available-rooms" class="fliggy-ops-input" type="number" min="0" step="1" placeholder="例如 36"></label>
              <label class="fliggy-ops-input-label">整店兜底价(选填)<input id="fliggy-ops-advice-current-price" class="fliggy-ops-input" type="number" min="1" step="0.01" placeholder="没有本店房型快照时才使用"></label>
              <label class="fliggy-ops-input-label">策略<select id="fliggy-ops-advice-strategy" class="fliggy-ops-input"><option value="balanced">balanced</option><option value="conservative">conservative</option><option value="aggressive">aggressive</option></select></label>
            </div>
            <label class="fliggy-ops-input-label" for="fliggy-ops-advice-hotel" style="margin-top: 8px;">指定竞对酒店（可选）</label>
            <input id="fliggy-ops-advice-hotel" class="fliggy-ops-input" type="text" placeholder="留空则综合本次抓到的所有竞对酒店">
            <div class="fliggy-ops-actions" style="margin-top: 8px; grid-template-columns: 1fr;">
              <button class="fliggy-ops-button primary" data-action="competitor-pricing-advice" type="button">生成建议价</button>
            </div>
            <div class="fliggy-ops-card fliggy-ops-competitor-advice" style="margin-top: 10px;">先点“抓取配置房型价”，再生成建议价。</div>
          </section><section class="fliggy-ops-section">
            <h3>当前配置</h3>
            <div class="fliggy-ops-card fliggy-ops-config">加载中...</div>
          </section>
          <section class="fliggy-ops-section">
            <h3>快捷动作</h3>
            <div class="fliggy-ops-actions">
              <button class="fliggy-ops-button" data-action="status" type="button">检查服务</button>
              <button class="fliggy-ops-button" data-action="refresh-context" type="button">刷新页面识别</button>
              <button class="fliggy-ops-button primary" data-action="collect" type="button">按当前页采集</button>
              <button class="fliggy-ops-button" data-action="settings" type="button">打开设置</button>
            </div>
          </section>
          <section class="fliggy-ops-section">
            <h3>返回结果</h3>
            <div class="fliggy-ops-result" data-result-page="basic">尚未执行动作。</div>
          </section>
          <div class="fliggy-ops-footer">这里保留页面采集和竞对抓价。</div>
        </div>
        <div class="fliggy-ops-page" data-page="merchant">
          <section class="fliggy-ops-section">
            <h3>商家连接</h3>
            <div class="fliggy-ops-grid">
              <label class="fliggy-ops-input-label">商家账号<input id="fliggy-ops-merchant-username" class="fliggy-ops-input" type="text" placeholder="请输入商家账号"></label>
              <label class="fliggy-ops-input-label">会话文件名<input id="fliggy-ops-merchant-storage-state" class="fliggy-ops-input" type="text" placeholder="默认留空"></label>
              <label class="fliggy-ops-input-label">商家密码<input id="fliggy-ops-merchant-password" class="fliggy-ops-input" type="password" placeholder="需要时再填写"></label>
              <label class="fliggy-ops-input-label">商家登录页 URL<input id="fliggy-ops-merchant-login-url" class="fliggy-ops-input" type="url" placeholder="https://..."></label>
            </div>
            <label class="fliggy-ops-input-label" for="fliggy-ops-merchant-price-url">商家价格页 URL</label>
            <input id="fliggy-ops-merchant-price-url" class="fliggy-ops-input" type="url" placeholder="https://...">
            <label class="fliggy-ops-input-label" for="fliggy-ops-merchant-selectors">选择器 JSON</label>
            <textarea id="fliggy-ops-merchant-selectors" class="fliggy-ops-textarea" placeholder='例如?{"priceInput":"#price"}'></textarea>
            <label class="fliggy-ops-check"><input id="fliggy-ops-merchant-auto-login" type="checkbox">保存后立即登录并生成会话</label>
            <label class="fliggy-ops-check"><input id="fliggy-ops-merchant-login-headless" type="checkbox" checked>自动登录使用无头模式</label>
            <div class="fliggy-ops-actions" style="margin-top: 8px;">
              <button class="fliggy-ops-button" data-action="load-merchant-credential" type="button">读取商家连接</button>
              <button class="fliggy-ops-button primary" data-action="save-merchant-credential" type="button">保存商家连接</button>
            </div>
            <div class="fliggy-ops-card fliggy-ops-merchant-credential" style="margin-top: 10px;">尚未读取商家连接。</div>
          </section>
          <section class="fliggy-ops-section" style="display: none;" hidden>
            <h3>价格映射</h3>
            <label class="fliggy-ops-input-label" for="fliggy-ops-mapping-price-url">映射刷新使用的价格页 URL</label>
            <input id="fliggy-ops-mapping-price-url" class="fliggy-ops-input" type="url" placeholder="默认复用商家价格页 URL">
            <label class="fliggy-ops-input-label" for="fliggy-ops-mapping-selectors">选择器 JSON</label>
            <textarea id="fliggy-ops-mapping-selectors" class="fliggy-ops-textarea" placeholder='例如?{"roomRow":".room-row"}'></textarea>
            <div class="fliggy-ops-grid">
              <label class="fliggy-ops-input-label">房型名称<input id="fliggy-ops-mapping-room-name" class="fliggy-ops-input" type="text" placeholder="例如?高级大床房"></label>
              <label class="fliggy-ops-input-label">价型名称<input id="fliggy-ops-mapping-rate-name" class="fliggy-ops-input" type="text" placeholder="例如?标准价"></label>
              <label class="fliggy-ops-input-label">GID<input id="fliggy-ops-mapping-gid" class="fliggy-ops-input" type="text" placeholder="GID"></label>
              <label class="fliggy-ops-input-label">HID<input id="fliggy-ops-mapping-hid" class="fliggy-ops-input" type="text" placeholder="HID"></label>
              <label class="fliggy-ops-input-label">状态<input id="fliggy-ops-mapping-status" class="fliggy-ops-input" type="text" value="draft" placeholder="draft / active"></label>
              <label class="fliggy-ops-input-label">最近价格<input id="fliggy-ops-mapping-last-price" class="fliggy-ops-input" type="number" min="0" step="0.01" placeholder="可选"></label>
            </div>
            <label class="fliggy-ops-input-label" for="fliggy-ops-mapping-notes">备注</label>
            <input id="fliggy-ops-mapping-notes" class="fliggy-ops-input" type="text" placeholder="可选备注">
            <div class="fliggy-ops-actions" style="margin-top: 8px;">
              <button class="fliggy-ops-button" data-action="load-merchant-mappings" type="button">读取映射</button>
              <button class="fliggy-ops-button" data-action="refresh-merchant-mappings" type="button">刷新映射价格</button>
              <button class="fliggy-ops-button primary" data-action="save-merchant-mapping" type="button">保存映射</button>
            </div>
            <div class="fliggy-ops-card fliggy-ops-merchant-mapping" style="margin-top: 10px;">尚未读取价格映射。</div>
          </section>
          <section class="fliggy-ops-section">
            <h3>执行改价</h3>
            <div style="display: none;" hidden>
              <label class="fliggy-ops-input-label" for="fliggy-ops-workflow-price-url">调价官网链接</label>
              <input id="fliggy-ops-workflow-price-url" class="fliggy-ops-input" type="url" placeholder="默认复用商家价格页 URL">
            </div>
            <div class="fliggy-ops-footer" style="margin-bottom: 8px;">这里恢复为单链接模式，直接使用已保存的商家价格页链接。</div>
            <div class="fliggy-ops-actions" style="margin-top: 8px;">
              <button class="fliggy-ops-button" data-action="merchant-pricing-load" type="button">读取房型</button>
              <button class="fliggy-ops-button primary" data-action="merchant-uniform-submit" type="button">一键改价</button>
            </div>
            <label class="fliggy-ops-input-label" for="fliggy-ops-uniform-target-price">单一目标价格</label>
            <input id="fliggy-ops-uniform-target-price" class="fliggy-ops-input" type="number" min="1" step="0.01" placeholder="例如?429">
            <div class="fliggy-ops-card fliggy-ops-merchant-pricing" style="margin-top: 10px;">先点“读取房型”，勾选你要修改的房型，再按目标价提交。</div>
            <div class="fliggy-ops-footer">提交前会抓取商家当前价并校验映射；映射由系统自动维护，如果不取消勾选，默认会提交所有可改价房型。</div>
          </section>
          <section class="fliggy-ops-section">
            <h3>返回结果</h3>
            <div class="fliggy-ops-result" data-result-page="merchant">尚未执行动作。</div>
          </section>
          <div class="fliggy-ops-footer">这里承载商家连接、价格映射和执行改价的新功能。</div>
        </div>
      </div>      </div>
    </section>
  `

  const launcher = shadow.querySelector(".fliggy-ops-launcher")
  const panel = shadow.querySelector(".fliggy-ops-panel")
  const closeButton = shadow.querySelector(".fliggy-ops-close")
  const statusDot = shadow.querySelector(".fliggy-ops-dot")
  const statusText = shadow.querySelector(".fliggy-ops-status-text")
  const configBox = shadow.querySelector(".fliggy-ops-config")
  const pageContextBox = shadow.querySelector(".fliggy-ops-page-context")
  const authSessionBox = shadow.querySelector("#fliggy-ops-auth-session")
  const authLoginForm = shadow.querySelector("#fliggy-ops-auth-login-form")
  const authShopBox = shadow.querySelector("#fliggy-ops-auth-shop-box")
  const authBaseUrlInput = shadow.querySelector("#fliggy-ops-auth-base-url")
  const authTenantIdInput = shadow.querySelector("#fliggy-ops-auth-tenant-id")
  const authUsernameInput = shadow.querySelector("#fliggy-ops-auth-username")
  const authPasswordInput = shadow.querySelector("#fliggy-ops-auth-password")
  const authShopSelect = shadow.querySelector("#fliggy-ops-auth-shop-select")
  const authCurrentUserInput = shadow.querySelector("#fliggy-ops-auth-current-user")
  const pageViews = Array.from(shadow.querySelectorAll(".fliggy-ops-page"))
  const navButtons = Array.from(shadow.querySelectorAll(".fliggy-ops-nav-button"))
  const resultBoxes = Array.from(shadow.querySelectorAll(".fliggy-ops-result[data-result-page]"))
  const targetInput = shadow.querySelector("#fliggy-ops-target-input")
  const configuredHotelsBox = shadow.querySelector("#fliggy-ops-configured-hotels-box")
  const competitorAdviceHotelInput = shadow.querySelector("#fliggy-ops-advice-hotel")
  const competitorAdviceTotalRoomsInput = shadow.querySelector("#fliggy-ops-advice-total-rooms")
  const competitorAdviceAvailableRoomsInput = shadow.querySelector("#fliggy-ops-advice-available-rooms")
  const competitorAdviceCurrentPriceInput = shadow.querySelector("#fliggy-ops-advice-current-price")
  const competitorAdviceStrategyInput = shadow.querySelector("#fliggy-ops-advice-strategy")
  const competitorAdviceBox = shadow.querySelector(".fliggy-ops-competitor-advice")
  const merchantCredentialBox = shadow.querySelector(".fliggy-ops-merchant-credential")
  const merchantPlatformLinksBox = shadow.querySelector(".fliggy-ops-merchant-platform-links")
  const merchantMappingBox = shadow.querySelector(".fliggy-ops-merchant-mapping")
  const merchantUsernameInput = shadow.querySelector("#fliggy-ops-merchant-username")
  const merchantPasswordInput = shadow.querySelector("#fliggy-ops-merchant-password")
  const merchantLoginUrlInput = shadow.querySelector("#fliggy-ops-merchant-login-url")
  const merchantPriceUrlInput = shadow.querySelector("#fliggy-ops-merchant-price-url")
  const merchantPlatformNameInput = shadow.querySelector("#fliggy-ops-merchant-platform-name")
  const merchantPlatformUsernameInput = shadow.querySelector("#fliggy-ops-merchant-platform-username")
  const merchantPlatformPasswordInput = shadow.querySelector("#fliggy-ops-merchant-platform-password")
  const merchantPlatformLoginUrlInput = shadow.querySelector("#fliggy-ops-merchant-platform-login-url")
  const merchantPlatformUrlInput = shadow.querySelector("#fliggy-ops-merchant-platform-url")
  const merchantPlatformSelectorsInput = shadow.querySelector("#fliggy-ops-merchant-platform-selectors")
  const merchantStorageStateInput = shadow.querySelector("#fliggy-ops-merchant-storage-state")
  const merchantSelectorsInput = shadow.querySelector("#fliggy-ops-merchant-selectors")
  const merchantAutoLoginInput = shadow.querySelector("#fliggy-ops-merchant-auto-login")
  const merchantLoginHeadlessInput = shadow.querySelector("#fliggy-ops-merchant-login-headless")
  const mappingPriceUrlInput = shadow.querySelector("#fliggy-ops-mapping-price-url")
  const mappingSelectorsInput = shadow.querySelector("#fliggy-ops-mapping-selectors")
  const mappingRoomNameInput = shadow.querySelector("#fliggy-ops-mapping-room-name")
  const mappingRateNameInput = shadow.querySelector("#fliggy-ops-mapping-rate-name")
  const mappingGidInput = shadow.querySelector("#fliggy-ops-mapping-gid")
  const mappingHidInput = shadow.querySelector("#fliggy-ops-mapping-hid")
  const mappingStatusInput = shadow.querySelector("#fliggy-ops-mapping-status")
  const mappingLastPriceInput = shadow.querySelector("#fliggy-ops-mapping-last-price")
  const mappingNotesInput = shadow.querySelector("#fliggy-ops-mapping-notes")
  const workflowPriceUrlInput = shadow.querySelector("#fliggy-ops-workflow-price-url")
  const uniformTargetPriceInput = shadow.querySelector("#fliggy-ops-uniform-target-price")
  const merchantPricingBox = shadow.querySelector(".fliggy-ops-merchant-pricing")
  const buttons = Array.from(shadow.querySelectorAll(".fliggy-ops-button"))
  const formControls = Array.from(shadow.querySelectorAll(".fliggy-ops-input, .fliggy-ops-textarea, .fliggy-ops-check input"))

  let config = null
  let pageContext = pageContextTools.detectPageContext()
  let busy = false
  let currentMerchantWorkflowPreview = null
  let currentCompetitorRoomPrices = null
  let currentCompetitorPricingAdvice = null
  let currentMerchantMappings = []
  let merchantMappingsLoaded = false
  let currentMerchantMappingShopId = ""
  let currentMerchantPlatformOverrideUrl = ""
  let activePage = "basic"

  function isAuthenticatedConfig(currentConfig) {
    return Boolean(currentConfig?.authenticated && currentConfig?.authUser && currentConfig?.currentShop)
  }

  navButtons.forEach((button) => {
    button.addEventListener("click", () => {
      if (busy) {
        return
      }
      setActivePage(String(button.dataset.page || "basic").trim() || "basic")
    })
  })

  targetInput.addEventListener("blur", () => {
    if (busy) {
      return
    }
    saveManualTargets().catch(() => {})
  })

  authShopSelect?.addEventListener("change", async () => {
    const shopId = Number(authShopSelect.value || 0)
    if (!shopId || busy) {
      return
    }
    setBusy(true)
    try {
      config = await sendRuntimeMessage({
        type: "AUTH_SWITCH_SHOP",
        payload: { shopId }
      })
      authPasswordInput.value = ""
      currentMerchantWorkflowPreview = null
      currentCompetitorRoomPrices = null
      currentCompetitorPricingAdvice = null
      renderEmbeddedAuthState(config)
      targetInput.value = String(config?.manualTargets || "")
      renderConfiguredCompetitorHotelsSummary(config)
      renderMerchantPlatformLinks()
      renderMerchantWorkflowPreview()
      renderCompetitorPricingAdvice()
      configBox.textContent = renderConfigSummary(config)
      await loadMerchantMappings(true).catch(() => {})
      updateStatus(`已切换到店铺 ${config?.currentShop?.shop_name || shopId}`, "ok")
      setResultText("店铺已切换，当前助手配置已刷新。")
    } catch (error) {
      updateStatus(`切换店铺失败: ${error.message}`, "error")
      setResultText(error.stack || error.message)
    } finally {
      setBusy(false)
    }
  })

  launcher.addEventListener("click", () => {
    if (panel.classList.contains("is-open")) {
      close()
      return
    }
    open()
  })

  closeButton.addEventListener("click", close)

  merchantPricingBox?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]")
    if (!button) {
      return
    }
    const action = button.dataset.action
    if (action === "toggle-all-merchant-workflow") {
      toggleAllMerchantWorkflowItems(button.dataset.checked !== "1")
      renderMerchantWorkflowPreview()
    }
  })

  merchantPricingBox?.addEventListener("change", (event) => {
    const node = event.target
    if (!node) {
      return
    }
    if (node.matches("[data-role='merchant-workflow-check']") || node.matches("[data-role='merchant-workflow-final-price']")) {
      syncMerchantWorkflowItemsFromDom()
    }
  })

  merchantPlatformLinksBox?.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]")
    if (!button || busy) {
      return
    }
    const index = Number(button.dataset.index || -1)
    const platformLinks = getMerchantPlatformLinks()
    const platformLink = platformLinks[index]
    if (!platformLink) {
      return
    }

    const action = String(button.dataset.action || "").trim()
    if (action === "use-merchant-platform-link") {
      setMerchantPlatformOverrideUrl(platformLink.priceUrl)
      updateStatus(`已带入 ${platformLink.name} 的改价链接`, "ok")
      setResultText(platformLink.priceUrl)
      return
    }
    if (action !== "remove-merchant-platform-link") {
      return
    }

    setBusy(true)
    try {
      const nextLinks = platformLinks.filter((_, itemIndex) => itemIndex !== index)
      config = normalizeConfig(await sendRuntimeMessage({
        type: "SAVE_CONFIG",
        payload: { merchantPlatformLinks: nextLinks }
      }))
      renderMerchantPlatformLinks()
      configBox.textContent = renderConfigSummary(config)
      updateStatus(`已移除 ${platformLink.name} 的改价链接`, "ok")
      setResultText(renderMerchantPlatformLinkResult(config?.merchantPlatformLinks))
    } catch (error) {
      updateStatus(`移除平台链接失败: ${error.message}`, "error")
      setResultText(error.stack || error.message)
    } finally {
      setBusy(false)
    }
  })

  merchantPlatformLinksBox?.addEventListener("change", async (event) => {
    const node = event.target
    if (!node || busy || !node.matches("[data-role='merchant-platform-link-enabled']")) {
      return
    }
    const index = Number(node.dataset.index || -1)
    const platformLinks = getMerchantPlatformLinks()
    const platformLink = platformLinks[index]
    if (!platformLink) {
      return
    }

    setBusy(true)
    try {
      const nextLinks = platformLinks.map((item, itemIndex) => itemIndex === index
        ? { ...item, enabled: Boolean(node.checked) }
        : item)
      config = normalizeConfig(await sendRuntimeMessage({
        type: "SAVE_CONFIG",
        payload: { merchantPlatformLinks: nextLinks }
      }))
      renderMerchantPlatformLinks()
      configBox.textContent = renderConfigSummary(config)
      updateStatus(`${platformLink.name} 已${node.checked ? "加入" : "移出"}一键改价`, "ok")
      setResultText(renderMerchantPlatformLinkResult(config?.merchantPlatformLinks))
    } catch (error) {
      updateStatus(`更新平台链接失败: ${error.message}`, "error")
      setResultText(error.stack || error.message)
    } finally {
      setBusy(false)
    }
  })

  shadow.addEventListener("click", async (event) => {
    const target = event.target.closest(".fliggy-ops-button")
    if (!target) {
      return
    }

    const action = target.dataset.action
    setBusy(true)
    try {
      pageContext = pageContextTools.detectPageContext()
      viewTools.renderPageContext(pageContextBox, pageContext)

      if (action === "auth-login") {
        const baseUrl = String(authBaseUrlInput?.value || "").trim()
        const tenantId = Number(authTenantIdInput?.value || 0)
        const username = String(authUsernameInput?.value || "").trim()
        const password = String(authPasswordInput?.value || "").trim()
        if (!baseUrl) {
          throw new Error("请先填写后端地址")
        }
        if (!tenantId) {
          throw new Error("请先填写有效的 Tenant ID")
        }
        if (!username || !password) {
          throw new Error("请先填写用户名和密码")
        }
        config = await sendRuntimeMessage({
          type: "AUTH_LOGIN",
          payload: { baseUrl, tenantId, username, password }
        })
        authPasswordInput.value = ""
        currentCompetitorRoomPrices = null
        currentCompetitorPricingAdvice = null
        targetInput.value = String(config?.manualTargets || "")
        renderEmbeddedAuthState(config)
        renderConfiguredCompetitorHotelsSummary(config)
      renderMerchantPlatformLinks()
      renderCompetitorPricingAdvice()
      configBox.textContent = renderConfigSummary(config)
        updateStatus(`已登录 ${config?.authUser?.username || username}`, "ok")
        setResultText("登录成功，已进入页面内运营助手。")
      } else if (action === "auth-refresh") {
        config = await sendRuntimeMessage({ type: "GET_AUTH_STATE" })
        renderEmbeddedAuthState(config)
        targetInput.value = String(config?.manualTargets || "")
        renderConfiguredCompetitorHotelsSummary(config)
      renderMerchantPlatformLinks()
      renderCompetitorPricingAdvice()
      configBox.textContent = renderConfigSummary(config)
        updateStatus(isAuthenticatedConfig(config) ? "已刷新登录会话" : "当前未登录", isAuthenticatedConfig(config) ? "ok" : "error")
        setResultText(isAuthenticatedConfig(config) ? "登录会话已刷新。" : "当前未登录，请先登录插件账号。")
      } else if (action === "auth-logout") {
        config = await sendRuntimeMessage({ type: "AUTH_LOGOUT" })
        authPasswordInput.value = ""
        currentMerchantWorkflowPreview = null
        currentCompetitorRoomPrices = null
        currentCompetitorPricingAdvice = null
        renderMerchantWorkflowPreview()
        renderEmbeddedAuthState(config)
        targetInput.value = String(config?.manualTargets || "")
        renderConfiguredCompetitorHotelsSummary(config)
      renderMerchantPlatformLinks()
      renderCompetitorPricingAdvice()
      configBox.textContent = renderConfigSummary(config)
        updateStatus("已退出登录", "ok")
        setResultText("当前已退出页面内运营助手登录。")
      } else if (action === "status") {
        const response = await sendRuntimeMessage({ type: "SERVICE_STATUS" })
        updateStatus(`服务在线: ${response.plugin}`, "ok")
        setResultText(JSON.stringify(response, null, 2))
      } else if (action === "refresh-context") {
        await loadConfig()
        updateStatus("已刷新页面识别", "ok")
        setResultText(JSON.stringify(viewTools.summarizeCollectContext(pageContext), null, 2))
      } else if (action === "refresh-room-config") {
        await loadConfig()
        const competitorHotels = Array.isArray(config?.competitorHotels) ? config.competitorHotels : []
        updateStatus(`已刷新竞对配置，当前 ${competitorHotels.length} 家`, "ok")
        setResultText(JSON.stringify({ competitorHotels }, null, 2))
      } else if (action === "debug-room-config") {
        const response = await buildConfigDebugInfo()
        config = normalizeConfig(response?.effective || response?.merged || {})
        renderConfiguredCompetitorHotelsSummary(config)
      renderMerchantPlatformLinks()
      renderCompetitorPricingAdvice()
      configBox.textContent = renderConfigSummary(config)
        const effectiveCount = Number(response?.counts?.effective || 0)
        updateStatus(`\u8bca\u65ad\u5b8c\u6210\uff0c\u5f53\u524d\u751f\u6548\u7ade\u5bf9\u914d\u7f6e ${effectiveCount} \u5bb6`, effectiveCount ? "ok" : "error")
        setResultText(JSON.stringify(response, null, 2))
      } else if (action === "room-prices") {
        await loadConfig()
        const response = await fetchCompetitorRoomPricesDirect()
        currentCompetitorRoomPrices = response
        currentCompetitorPricingAdvice = null
        if (!String(competitorAdviceHotelInput?.value || "").trim() && Array.isArray(response?.hotels) && response.hotels.length === 1) {
          competitorAdviceHotelInput.value = String(response.hotels[0]?.hotel_name || "")
        }
        renderCompetitorPricingAdvice()
        updateStatus(`已抓取 ${Number(response?.hotel_count || 0)} 家竞对酒店的 ${Number(response?.total_rooms || 0)} 条房型价`, "ok")
        setResultHtml(renderCompetitorRoomPrices(response))
      } else if (action === "collect") {
        const manualTargets = getManualTargets()
        const pageSnapshot = await pageContextTools.collectPageSnapshot({
          maxPages: 1,
          collectAllPages: false,
          targetHotelNames: manualTargets
        })
        pageContext = pageSnapshot.pageContext
        await saveManualTargets()
        const response = await sendRuntimeMessage({
          type: "RUN_COLLECT",
          payload: {
            pageContext,
            pageSnapshot,
            targetHotelNames: manualTargets,
            maxPages: 1
          }
        })
        updateStatus("已完成当前页真实采集", "ok")
        setResultHtml(viewTools.renderCollectSummary(response, {
          ...pageContext,
          targetHotelNames: manualTargets,
        }))
      } else if (action === "competitor-pricing-advice") {
        if (!Array.isArray(currentCompetitorRoomPrices?.hotels) || !currentCompetitorRoomPrices.hotels.length) {
          throw new Error("请先抓取竞对房型价，再生成建议价")
        }
        const totalRooms = toPositiveInteger(competitorAdviceTotalRoomsInput?.value)
        if (!totalRooms) {
          throw new Error("请先填写有效的总房量")
        }
        const availableRooms = toNonNegativeInteger(competitorAdviceAvailableRoomsInput?.value)
        if (availableRooms === null) {
          throw new Error("请先填写有效的可售房量")
        }
        if (availableRooms > totalRooms) {
          throw new Error("可售房量不能大于总房量")
        }
        const currentPrice = toPositiveNumber(competitorAdviceCurrentPriceInput?.value)
        const response = await sendRuntimeMessage({
          type: "COMPETITOR_PRICING_ADVICE_PREVIEW",
          payload: {
            competitorHotelName: competitorAdviceHotelInput?.value,
            totalRooms,
            availableRooms,
            currentPrice: currentPrice || undefined,
            strategy: competitorAdviceStrategyInput?.value || "balanced",
            roomPrices: currentCompetitorRoomPrices,
            manualRoomMappings: getPreferredRoomMappingState(config, currentMerchantMappings).items,
          }
        })
        currentCompetitorPricingAdvice = response
        renderCompetitorPricingAdvice()
        const recommendedRoomCount = Number(response?.advice_summary?.recommended_room_count || response?.room_recommendations?.length || 0)
        const suggestedPrice = Number(response?.advice_summary?.suggested_price || 0)
        updateStatus(recommendedRoomCount ? `已生成 ${recommendedRoomCount} 个房型建议价` : (suggestedPrice ? `建议价已生成: ¥${suggestedPrice.toFixed(2)}` : "竞对建议价已生成"), "ok")
        setResultText(formatCompetitorPricingAdviceResult(response))
      } else if (action === "add-merchant-platform-link") {
        const name = String(merchantPlatformNameInput?.value || "").trim()
        const username = String(merchantPlatformUsernameInput?.value || "").trim()
        const password = String(merchantPlatformPasswordInput?.value || "").trim()
        const loginUrl = String(merchantPlatformLoginUrlInput?.value || "").trim()
        const priceUrl = String(merchantPlatformUrlInput?.value || "").trim()
        if (!priceUrl) {
          throw new Error("请先填写有效的改价链接")
        }
        const currentLinks = getMerchantPlatformLinks()
        const nextLinks = normalizeMerchantPlatformLinks([
          ...currentLinks,
          {
            name: name || `平台${currentLinks.length + 1}`,
            username,
            password,
            loginUrl,
            priceUrl,
            selectors: parseJsonInput(merchantPlatformSelectorsInput?.value || "", "平台选择器 JSON"),
            enabled: true
          }
        ])
        config = normalizeConfig(await sendRuntimeMessage({
          type: "SAVE_CONFIG",
          payload: { merchantPlatformLinks: nextLinks }
        }))
        merchantPlatformNameInput.value = ""
        merchantPlatformUsernameInput.value = ""
        merchantPlatformPasswordInput.value = ""
        merchantPlatformLoginUrlInput.value = ""
        merchantPlatformUrlInput.value = ""
        merchantPlatformSelectorsInput.value = ""
        renderMerchantPlatformLinks()
        configBox.textContent = renderConfigSummary(config)
        updateStatus(`已新增 ${name || `平台${nextLinks.length}`} 平台配置`, "ok")
        setResultText(renderMerchantPlatformLinkResult(config?.merchantPlatformLinks))
      } else if (action === "load-merchant-credential") {
        const response = await requestMerchantCredentialSummary()
        setMerchantPlatformOverrideUrl("")
        applyMerchantCredential(response)
        updateStatus("已读取商家连接", "ok")
        setResultText(JSON.stringify(response, null, 2))
      } else if (action === "save-merchant-credential") {
        const credentialPayload = {
          username: String(merchantUsernameInput?.value || "").trim(),
          password: String(merchantPasswordInput?.value || "").trim(),
          loginUrl: String(merchantLoginUrlInput?.value || "").trim(),
          priceUrl: String(merchantPriceUrlInput?.value || "").trim(),
          storageStateName: String(merchantStorageStateInput?.value || "").trim(),
          selectors: parseJsonInput(merchantSelectorsInput?.value || "", "商家连接选择器 JSON"),
          autoLoginAfterSave: Boolean(merchantAutoLoginInput?.checked),
          loginHeadless: Boolean(merchantLoginHeadlessInput?.checked)
        }
        const response = await saveMerchantCredentialSummary(credentialPayload)
        setMerchantPlatformOverrideUrl("")
        await loadMerchantCredential()
        updateStatus(response?.login ? "已保存商家连接并生成会话" : "已保存商家连接", "ok")
        setResultText(JSON.stringify(response, null, 2))
      } else if (action === "load-merchant-mappings") {
        const response = await loadMerchantMappings()
        updateStatus(`已读取 ${Number(response?.count || 0)} 条价格映射`, "ok")
        setResultText(JSON.stringify(response, null, 2))
      } else if (action === "refresh-merchant-mappings") {
        const response = await refreshMerchantMappingsSummary({
          priceUrl: String(mappingPriceUrlInput?.value || merchantPriceUrlInput?.value || "").trim(),
          selectors: parseJsonInput(mappingSelectorsInput?.value || merchantSelectorsInput?.value || "", "\u6620\u5c04\u9009\u62e9\u5668 JSON"),
          headless: true,
        })
        await loadMerchantMappings()
        updateStatus("已刷新映射价格", "ok")
        setResultText(JSON.stringify(response, null, 2))
      } else if (action === "save-merchant-mapping") {
        const roomName = String(mappingRoomNameInput?.value || "").trim()
        if (!roomName) {
          throw new Error("请先填写房型名称")
        }
        const response = await saveMerchantMappingSummary({
          roomName,
          rateName: String(mappingRateNameInput?.value || "").trim(),
          gid: String(mappingGidInput?.value || "").trim(),
          hid: String(mappingHidInput?.value || "").trim(),
          status: String(mappingStatusInput?.value || "draft").trim() || "draft",
          notes: String(mappingNotesInput?.value || "").trim(),
          lastSeenPrice: String(mappingLastPriceInput?.value || "").trim(),
        })
        await loadMerchantMappings()
        updateStatus("已保存价格映射", "ok")
        setResultText(JSON.stringify(response, null, 2))
      } else if (action === "merchant-pricing-load") {
        const priceUrl = String(merchantPriceUrlInput?.value || "").trim()
        if (!priceUrl) {
          throw new Error("请先保存商家价格页链接")
        }
        const response = await sendRuntimeMessage({
          type: "MERCHANT_PRICING_ITEMS",
          payload: {
            priceUrl,
            selectors: parseJsonInput(merchantSelectorsInput?.value || "", "商家连接选择器 JSON"),
            headless: true,
            collectMode: "cdp_current_page",
          }
        })
        currentMerchantWorkflowPreview = normalizeMerchantWorkflowPreview(response)
        renderMerchantWorkflowPreview()
        updateStatus(`已读取 ${Number(response?.item_count || 0)} 条房型，当前可提交 ${Number(currentMerchantWorkflowPreview?.readySubmitCount || 0)} 条`, "ok")
        setResultText(formatMerchantWorkflowResult(response))
      } else if (action === "merchant-pricing-preview") {
        const response = await sendRuntimeMessage({
          type: "MERCHANT_PRICING_PREVIEW",
          payload: {
            priceUrl: String(merchantPriceUrlInput?.value || "").trim(),
            selectors: parseJsonInput(merchantSelectorsInput?.value || "", "商家连接选择器 JSON"),
            headless: true,
          }
        })
        currentMerchantWorkflowPreview = normalizeMerchantWorkflowPreview(response)
        renderMerchantWorkflowPreview()
        updateStatus(`已抓取 ${Number(response?.item_count || 0)} 条商家房型价，待提交 ${Number(currentMerchantWorkflowPreview?.readySubmitCount || 0)} 条`, "ok")
        setResultText(formatMerchantWorkflowResult(response))
      } else if (action === "merchant-pricing-fill") {
        applySuggestedPricesToMerchantWorkflow()
        renderMerchantWorkflowPreview()
        updateStatus("已将建议价回填到已勾选房型", "ok")
      } else if (action === "merchant-pricing-submit") {
        syncMerchantWorkflowItemsFromDom()
        const confirmedItems = collectConfirmedMerchantWorkflowItems()
        if (!confirmedItems.length) {
          throw new Error("请先抓取预览，并勾选至少一条可提交房型")
        }
        const response = await sendRuntimeMessage({
          type: "MERCHANT_PRICING_SUBMIT_CURRENT",
          payload: {
            priceUrl: String(workflowPriceUrlInput?.value || merchantPriceUrlInput?.value || "").trim(),
            confirmedItems,
            comment: "browser_extension_confirm_submit"
          }
        })
        updateStatus("已按确认后的最终价提交到 OTA", response?.failed_count ? "error" : "ok")
        setResultText(formatMerchantSubmitResult(response))
        currentMerchantWorkflowPreview = null
        renderMerchantWorkflowPreview()
      } else if (action === "merchant-uniform-submit") {
        const priceUrl = String(merchantPriceUrlInput?.value || "").trim()
        const targetPrice = toPositiveNumber(uniformTargetPriceInput?.value)
        if (!targetPrice) {
          throw new Error("请先填写有效的目标价格")
        }
        syncMerchantWorkflowItemsFromDom()
        const selectedItems = collectSelectedMerchantWorkflowItems()
        if (currentMerchantWorkflowPreview?.items?.length && !selectedItems.length) {
          throw new Error("请先勾选至少一条可提交房型")
        }
        if (!priceUrl) {
          throw new Error("请先保存商家价格页链接")
        }
        const response = await sendRuntimeMessage({
          type: "MERCHANT_UNIFORM_PRICE_SUBMIT",
          payload: {
            priceUrl,
            targetPrice,
            selectedItems,
            selectors: parseJsonInput(merchantSelectorsInput?.value || "", "商家连接选择器 JSON"),
            comment: "browser_extension_uniform_submit"
          }
        })
        currentMerchantWorkflowPreview = null
        renderMerchantWorkflowPreview()
        const failedCount = Number(response?.failed_count || 0)
        updateStatus(`已按目标价 ¥${targetPrice.toFixed(2)} 发起改价`, failedCount ? "error" : "ok")
        setResultText(formatMerchantSubmitResult(response))
      } else if (action === "settings") {
        await sendRuntimeMessage({ type: "OPEN_OPTIONS" })
        updateStatus("已打开设置页", "ok")
      }
    } catch (error) {
      updateStatus(`请求失败: ${error.message}`, "error")
      setResultText(error.stack || error.message)
    } finally {
      setBusy(false)
    }
  })

  loadConfig()
  loadMerchantEmbeddedData().catch(() => {})
  viewTools.renderPageContext(pageContextBox, pageContext)
  setActivePage(activePage)
  checkService()
  chrome.storage?.onChanged?.addListener((changes, areaName) => {
    if (areaName !== "sync" && areaName !== "local") {
      return
    }
    if (!changes?.competitorHotels && !changes?.merchantPlatformLinks && !changes?.manualTargets && !changes?.configUpdatedAt && !changes?.authToken && !changes?.authUser && !changes?.currentShop && !changes?.shops) {
      return
    }
    loadConfig().catch(() => {})
  })

  function setActivePage(pageKey) {
    activePage = pageKey === "merchant" ? "merchant" : "basic"
    pageViews.forEach((page) => {
      page.classList.toggle("is-active", page.dataset.page === activePage)
    })
    navButtons.forEach((button) => {
      button.classList.toggle("is-active", button.dataset.page === activePage)
    })
  }

  function getActiveResultBox() {
    return resultBoxes.find((box) => box.dataset.resultPage === activePage) || resultBoxes[0] || null
  }

  function setResultText(textValue) {
    const box = getActiveResultBox()
    if (box) {
      box.textContent = textValue
    }
  }

  function setResultHtml(html) {
    const box = getActiveResultBox()
    if (box) {
      box.innerHTML = html
    }
  }

  function open() {
    pageContext = pageContextTools.detectPageContext()
    viewTools.renderPageContext(pageContextBox, pageContext)
    loadConfig().catch(() => {})
    loadMerchantEmbeddedData().catch(() => {})
    setActivePage(activePage)
    panel.classList.add("is-open")
    return pageContext
  }

  function close() {
    panel.classList.remove("is-open")
  }

  async function loadConfig() {
    try {
      config = await getEffectiveConfig()
      const nextShopId = isAuthenticatedConfig(config) ? String(resolveActiveShopId(config) || "").trim() : ""
      if (nextShopId !== currentMerchantMappingShopId) {
        currentMerchantMappings = []
        merchantMappingsLoaded = false
        currentMerchantMappingShopId = nextShopId
      }
      renderEmbeddedAuthState(config)
      targetInput.value = String(config?.manualTargets || "")
      renderConfiguredCompetitorHotelsSummary(config)
      renderMerchantPlatformLinks()
      renderCompetitorPricingAdvice()
      configBox.textContent = renderConfigSummary(config)
      if (isAuthenticatedConfig(config) && !merchantMappingsLoaded) {
        loadMerchantMappings().catch(() => {})
      }
    } catch (error) {
      if (authSessionBox) {
        authSessionBox.textContent = `登录信息读取失败: ${error.message}`
      }
      configBox.textContent = `配置读取失败: ${error.message}`
    }
  }

  function renderEmbeddedAuthState(currentConfig) {
    if (!authSessionBox) {
      return
    }
    const authenticated = isAuthenticatedConfig(currentConfig)
    authBaseUrlInput.value = String(currentConfig?.baseUrl || DEFAULT_EXTENSION_CONFIG.baseUrl)
    authTenantIdInput.value = String(currentConfig?.authUser?.tenant_id || currentConfig?.tenantId || DEFAULT_EXTENSION_CONFIG.tenantId)
    authUsernameInput.value = authenticated
      ? String(currentConfig?.authUser?.username || "")
      : String(authUsernameInput?.value || "")

    authLoginForm?.classList.toggle("fliggy-ops-hidden", authenticated)
    authShopBox?.classList.toggle("fliggy-ops-hidden", !authenticated)

    const authLoginButton = shadow.querySelector('[data-action="auth-login"]')
    const authRefreshButton = shadow.querySelector('[data-action="auth-refresh"]')
    const authLogoutButton = shadow.querySelector('[data-action="auth-logout"]')
    authLoginButton?.classList.toggle("fliggy-ops-hidden", authenticated)
    authRefreshButton?.classList.toggle("fliggy-ops-hidden", !authenticated)
    authLogoutButton?.classList.toggle("fliggy-ops-hidden", !authenticated)

    if (!authenticated) {
      authSessionBox.textContent = "当前未登录，请先登录插件账号并选择店铺。"
      if (authCurrentUserInput) {
        authCurrentUserInput.value = ""
      }
      if (authShopSelect) {
        authShopSelect.innerHTML = '<option value="">请先登录</option>'
      }
      return
    }

    const shops = Array.isArray(currentConfig?.shops) ? currentConfig.shops : []
    const currentShop = currentConfig?.currentShop || null
    authSessionBox.textContent = `当前账号 ${String(currentConfig?.authUser?.username || "")} 已登录，Tenant ${String(currentConfig?.authUser?.tenant_id || "")}，可访问店铺 ${shops.length} 家。`
    if (authCurrentUserInput) {
      authCurrentUserInput.value = `${String(currentConfig?.authUser?.username || "")} / tenant ${String(currentConfig?.authUser?.tenant_id || "")}`
    }
    if (authShopSelect) {
      authShopSelect.innerHTML = shops.length
        ? shops.map((shop) => `<option value="${escapeHtml(String(shop.shop_id || ""))}" ${Number(shop.shop_id || 0) === Number(currentShop?.shop_id || 0) ? "selected" : ""}>${escapeHtml(shop.shop_name || `Shop ${shop.shop_id}`)}</option>`).join("")
        : '<option value="">暂无可访问店铺</option>'
    }
  }

  async function loadMerchantEmbeddedData() {
    await Promise.allSettled([
      loadMerchantCredential(),
      loadMerchantMappings()
    ])
  }

  async function loadMerchantCredential() {
    const response = await requestMerchantCredentialSummary()
    applyMerchantCredential(response)
    return response
  }

  async function loadMerchantMappings(force = false) {
    const shopId = isAuthenticatedConfig(config) ? String(resolveActiveShopId(config) || "").trim() : ""
    if (!shopId) {
      currentMerchantMappings = []
      merchantMappingsLoaded = false
      currentMerchantMappingShopId = ""
      merchantMappingBox.textContent = renderMerchantMappingSummary({ count: 0, items: [] })
      renderConfiguredCompetitorHotelsSummary(config)
      renderCompetitorPricingAdvice()
      configBox.textContent = renderConfigSummary(config)
      return { count: 0, items: [] }
    }
    if (!force && merchantMappingsLoaded && currentMerchantMappingShopId === shopId) {
      return { count: currentMerchantMappings.length, items: currentMerchantMappings }
    }
    const response = await requestMerchantMappingsSummary({ onlyEnabled: false })
    currentMerchantMappings = normalizeMerchantRoomMappings(response?.items)
    merchantMappingsLoaded = true
    currentMerchantMappingShopId = shopId
    merchantMappingBox.textContent = renderMerchantMappingSummary(response)
    renderConfiguredCompetitorHotelsSummary(config)
    renderCompetitorPricingAdvice()
    configBox.textContent = renderConfigSummary(config)
    return response
  }

  function applyMerchantCredential(response) {
    const payload = response?.saved || response || {}
    merchantCredentialBox.textContent = renderMerchantCredentialSummary(payload)
    merchantUsernameInput.value = String(payload?.username || "")
    merchantLoginUrlInput.value = String(payload?.login_url || "")
    merchantPriceUrlInput.value = String(payload?.price_url || "")
    merchantStorageStateInput.value = String(payload?.storage_state_name || "")
    merchantSelectorsInput.value = payload?.selectors ? JSON.stringify(payload.selectors, null, 2) : ""
    if (!mappingPriceUrlInput.value) {
      mappingPriceUrlInput.value = String(payload?.price_url || "")
    }
  }

  function renderMerchantCredentialSummary(payload) {
    return [
      `商家账号: ${payload?.username_masked || payload?.username || "-"}`,
      `密码状态: ${payload?.has_password ? "已保存" : "未保存"}`,
      `登录 URL: ${payload?.login_url || "-"}`,
      `价格 URL: ${payload?.price_url || "-"}`,
      `会话文件: ${payload?.storage_state_name || "-"}`,
      `最近登录: ${payload?.last_login_at || "-"}`
    ].join("\n")
  }

  function maskMerchantPlatformUsername(username) {
    const value = String(username || "").trim()
    if (!value) {
      return "-"
    }
    if (value.includes("@")) {
      const [prefix, suffix] = value.split("@", 2)
      const maskedPrefix = prefix.length <= 2
        ? `${prefix.slice(0, 1)}*`
        : `${prefix.slice(0, 2)}${"*".repeat(Math.max(2, prefix.length - 2))}`
      return `${maskedPrefix}@${suffix}`
    }
    if (value.length <= 3) {
      return `${value.slice(0, 1)}${"*".repeat(Math.max(1, value.length - 1))}`
    }
    return `${value.slice(0, 2)}${"*".repeat(Math.max(2, value.length - 4))}${value.slice(-2)}`
  }

  function hasMerchantPlatformCredential(platformLink) {
    return Boolean(
      String(platformLink?.loginUrl || "").trim()
      && String(platformLink?.username || "").trim()
      && String(platformLink?.password || "").trim()
    )
  }

  function getMerchantPlatformLinks() {
    return normalizeMerchantPlatformLinks(config?.merchantPlatformLinks)
  }

  function getSelectedMerchantPlatformLinks() {
    return getMerchantPlatformLinks().filter((item) => item.enabled)
  }

  function getMerchantPlatformOverrideUrl() {
    return String(currentMerchantPlatformOverrideUrl || "").trim()
  }

  function setMerchantPlatformOverrideUrl(priceUrl = "") {
    currentMerchantPlatformOverrideUrl = String(priceUrl || "").trim()
    if (workflowPriceUrlInput) {
      workflowPriceUrlInput.value = currentMerchantPlatformOverrideUrl
    }
  }

  function resolveMerchantPlatformTarget(priceUrl = "") {
    const normalizedUrl = String(priceUrl || "").trim()
    if (!normalizedUrl) {
      return null
    }
    const platformLinks = getMerchantPlatformLinks()
    return platformLinks.find((item) => item.priceUrl === normalizedUrl)
      || platformLinks.find((item) => item.enabled && item.priceUrl === normalizedUrl)
      || null
  }

  async function prepareMerchantPlatformCredential(platformLink, options = {}) {
    if (!platformLink) {
      return null
    }
    if (!hasMerchantPlatformCredential(platformLink)) {
      if (options.requireCredentials) {
        throw new Error(`平台 ${platformLink.name} 缺少登录链接、账号或密码`)
      }
      return null
    }
    return saveMerchantCredentialSummary({
      username: platformLink.username,
      password: platformLink.password,
      loginUrl: platformLink.loginUrl,
      priceUrl: platformLink.priceUrl,
      storageStateName: platformLink.storageStateName,
      selectors: platformLink.selectors,
      autoLoginAfterSave: true,
      loginHeadless: Boolean(merchantLoginHeadlessInput?.checked)
    })
  }

  function resolveMerchantPricingLoadUrl() {
    const overrideUrl = getMerchantPlatformOverrideUrl()
    if (overrideUrl) {
      return overrideUrl
    }
    const merchantPriceUrl = String(merchantPriceUrlInput?.value || "").trim()
    if (merchantPriceUrl) {
      return merchantPriceUrl
    }
    const selectedLinks = getSelectedMerchantPlatformLinks()
    const fallbackLink = selectedLinks[0] || getMerchantPlatformLinks()[0] || null
    return String(fallbackLink?.priceUrl || "").trim()
  }

  function renderMerchantPlatformLinkResult(items) {
    const links = normalizeMerchantPlatformLinks(items)
    if (!links.length) {
      return "当前使用单链接模式。"
    }
    return [
      "当前使用单链接模式。",
      `历史平台链接: ${links.length} 个`,
      "页面内入口已不再使用这些平台链接。"
    ].join("\n")
  }

  function renderMerchantPlatformLinks() {
    if (!merchantPlatformLinksBox) {
      return
    }
    const items = getMerchantPlatformLinks()
    if (!items.length) {
      merchantPlatformLinksBox.innerHTML = '<div class="fliggy-ops-empty-state">当前使用单链接模式。</div>'
      return
    }
    merchantPlatformLinksBox.innerHTML = `
      <div class="fliggy-ops-footer" style="margin-bottom: 8px;">当前页面已恢复单链接模式，以下仅展示历史平台链接，不再参与读取房型或一键改价。</div>
      <div style="display: grid; gap: 8px;">
        ${items.map((item, index) => `
          <div class="fliggy-ops-workflow-item">
            <div class="fliggy-ops-workflow-item-top" style="align-items: flex-start;">
              <div style="display: grid; gap: 4px; width: 100%;">
                <div class="fliggy-ops-workflow-item-name">${escapeHtml(item.name)}</div>
                <div class="fliggy-ops-footer">改价链接: ${escapeHtml(item.priceUrl)}</div>
                <div class="fliggy-ops-footer">登录链接: ${escapeHtml(item.loginUrl || "-")}</div>
                <div class="fliggy-ops-footer">商家账号: ${escapeHtml(maskMerchantPlatformUsername(item.username))} / 密码: ${item.password ? "已录入" : "未录入"}</div>
              </div>
            </div>
          </div>
        `).join("")}
      </div>
    `
  }

  async function submitMerchantUniformPricingAcrossPlatforms(payload = {}) {
    const targetLinks = getSelectedMerchantPlatformLinks()
    const fallbackPriceUrl = String(payload.fallbackPriceUrl || "").trim()
    const targets = targetLinks.length
      ? targetLinks
      : (fallbackPriceUrl ? [{ name: "当前链接", priceUrl: fallbackPriceUrl, enabled: true }] : [])
    if (!targets.length) {
      throw new Error("请先保存商家价格页链接")
    }

    const results = []
    for (const target of targets) {
      try {
        const prepared = await prepareMerchantPlatformCredential(target, { requireCredentials: Boolean(target.loginUrl || target.username || target.password) })
        const response = await sendRuntimeMessage({
          type: "MERCHANT_UNIFORM_PRICE_SUBMIT",
          payload: {
            priceUrl: target.priceUrl,
            targetPrice: payload.targetPrice,
            selectedItems: Array.isArray(payload.selectedItems) ? payload.selectedItems : [],
            selectors: target.selectors,
            comment: "browser_extension_uniform_submit"
          }
        })
        results.push({
          platformName: target.name,
          priceUrl: target.priceUrl,
          prepared,
          ok: true,
          response
        })
      } catch (error) {
        results.push({
          platformName: target.name,
          priceUrl: target.priceUrl,
          ok: false,
          error: error instanceof Error ? error.message : String(error)
        })
      }
    }

    const failedPlatformCount = results.filter((item) => !item.ok).length
    const totalSuccessCount = results.reduce((sum, item) => sum + Number(item?.response?.success_count || 0), 0)
    const totalFailedCount = results.reduce((sum, item) => sum + Number(item?.response?.failed_count || 0) + (item.ok ? 0 : 1), 0)
    const totalSkippedCount = results.reduce((sum, item) => sum + Number(item?.response?.skipped_submit_count || 0), 0)
    return {
      status: failedPlatformCount ? (failedPlatformCount === results.length ? "failed" : "partial") : "success",
      platform_count: results.length,
      failed_platform_count: failedPlatformCount,
      success_platform_count: results.length - failedPlatformCount,
      target_price: payload.targetPrice,
      success_count: totalSuccessCount,
      failed_count: totalFailedCount,
      skipped_submit_count: totalSkippedCount,
      results
    }
  }

  function renderMerchantMappingSummary(response) {
    const items = Array.isArray(response?.items) ? response.items : []
    const summary = [
      `映射数量: ${Number(response?.count || items.length)}`
    ]
    const lines = items.slice(0, 6).map((item) => {
      const roomName = String(item?.room_name || "-").trim()
      const rateName = String(item?.rate_name || "未填写价型").trim()
      const gid = String(item?.gid || "-").trim()
      const hid = String(item?.hid || "-").trim()
      const status = String(item?.status || "-").trim()
      const lastSeenPrice = String(item?.last_seen_price ?? item?.lastSeenPrice ?? "-").trim() || "-"
      return `${roomName} / ${rateName} / ${status} / ${gid} / ${hid} / ${lastSeenPrice}`
    })
    return summary.concat(lines.length ? lines : ["暂无映射"]).join("\n")
  }

  function parseJsonInput(rawText, label) {
    const text = String(rawText || "").trim()
    if (!text) {
      return undefined
    }
    try {
      const parsed = JSON.parse(text)
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("必须是 JSON 对象")
      }
      return parsed
    } catch (error) {
      throw new Error(`${label} 解析失败: ${error.message}`)
    }
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

  function formatSignedPrice(value) {
    if (!Number.isFinite(Number(value))) {
      return "-"
    }
    const amount = Number(value)
    const sign = amount > 0 ? "+" : amount < 0 ? "-" : "±"
    return `${sign}¥${Math.abs(amount).toFixed(2)}`
  }

  function formatSignedPercent(value) {
    if (!Number.isFinite(Number(value))) {
      return "-"
    }
    const amount = Number(value)
    const sign = amount > 0 ? "+" : amount < 0 ? "-" : "±"
    return `${sign}${Math.abs(amount).toFixed(2)}%`
  }

function renderCompetitorPricingAdvice() {
  if (!competitorAdviceBox) {
    return
  }
  const hotels = Array.isArray(currentCompetitorRoomPrices?.hotels) ? currentCompetitorRoomPrices.hotels : []
  const mappingState = getPreferredRoomMappingState(config, currentMerchantMappings)
  const manualRoomMappings = mappingState.items
  if (!hotels.length) {
    competitorAdviceBox.innerHTML = '先抓取上方竞对房型价，再生成建议价。'
    return
  }
  const hotelNames = hotels.slice(0, 6).map((hotel) => escapeHtml(hotel?.hotel_name || '未命名酒店')).join(' / ')
  if (!currentCompetitorPricingAdvice) {
    competitorAdviceBox.innerHTML = `已缓存 ${Number(currentCompetitorRoomPrices?.hotel_count || hotels.length)} 家竞对酒店，${Number(currentCompetitorRoomPrices?.total_rooms || 0)} 条房型价。<div class="fliggy-ops-footer">${manualRoomMappings.length ? `当前店铺已维护 ${manualRoomMappings.length} 条${mappingState.sourceLabel}房型映射，生成建议价时会优先按这些房型输出。` : hotelNames}</div>`
    return
  }
  const advice = currentCompetitorPricingAdvice
  const summary = advice?.advice_summary || {}
  const competitorContext = advice?.competitor_context || {}
  const merchantSnapshot = advice?.merchant_room_snapshot || {}
  const promptProfile = advice?.prompt_profile || {}
  const roomRecommendations = Array.isArray(advice?.room_recommendations) ? advice.room_recommendations : []
  const sourceLabel = merchantSnapshot?.source === 'manual_room_mappings'
    ? `手工房型价格 ${Number(merchantSnapshot?.item_count || roomRecommendations.length || 0)} 条`
    : `抓取房型快照 ${Number(merchantSnapshot?.item_count || roomRecommendations.length || 0)} 条`
  const roomHtml = roomRecommendations.slice(0, 8).map((item) => `
      <div class="fliggy-ops-card" style="margin-top: 8px;">
        <div><strong>${escapeHtml(item?.display_name || item?.room_name || '未命名房型')}</strong></div>
        <div class="fliggy-ops-footer">现价 ${formatPrice(item?.current_price)} | 竞对最低 ${formatPrice(item?.competitor_min_price)} | 竞对均价 ${formatPrice(item?.competitor_avg_price)} | 竞对最高 ${formatPrice(item?.competitor_max_price)}</div>
        <div class="fliggy-ops-footer">建议价 ${formatPrice(item?.suggested_price)} | 调整 ${formatSignedPrice(item?.change_amount)} | 调整比例 ${formatSignedPercent(item?.change_pct)} | 风险 ${escapeHtml(item?.risk_level || '-')}</div>
        <div class="fliggy-ops-footer">匹配样本 ${Number(item?.matched_room_count || 0)} 条 / ${Number(item?.matched_hotel_count || 0)} 家 | ${escapeHtml(item?.reasoning || '-')}</div>
      </div>
    `).join('')
  competitorAdviceBox.innerHTML = `
      <div><strong>${escapeHtml(advice?.competitor_hotel_name || '综合竞对酒店')}</strong></div>
      <div class="fliggy-ops-summary-grid">
        <div class="fliggy-ops-summary-pill"><div class="fliggy-ops-summary-label">建议房型</div><div class="fliggy-ops-summary-value">${Number(summary?.recommended_room_count || roomRecommendations.length || 0)}</div></div>
        <div class="fliggy-ops-summary-pill"><div class="fliggy-ops-summary-label">建议均价</div><div class="fliggy-ops-summary-value">${formatPrice(summary?.suggested_price)}</div></div>
        <div class="fliggy-ops-summary-pill"><div class="fliggy-ops-summary-label">竞对均价</div><div class="fliggy-ops-summary-value">${formatPrice(summary?.competitor_avg_price)}</div></div>
        <div class="fliggy-ops-summary-pill"><div class="fliggy-ops-summary-label">风险等级</div><div class="fliggy-ops-summary-value">${escapeHtml(summary?.risk_level || '-')}</div></div>
      </div>
      <div class="fliggy-ops-footer">角色 ${escapeHtml(promptProfile?.role || '酒店OTA运营专家')} | ${sourceLabel} | 竞对样本 ${Number(competitorContext?.price_count || 0)} 条 | 来源 ${escapeHtml(advice?.recommendation_source || '-')}</div>
      <div class="fliggy-ops-footer">${escapeHtml(summary?.reason_summary || '已生成建议价，可展开下方房型查看明细。')}</div>
      ${roomHtml || '<div class="fliggy-ops-footer" style="margin-top: 8px;">当前没有可展示的房型建议。</div>'}
    `
}

function formatCompetitorPricingAdviceResult(response) {
  const summary = response?.advice_summary || {}
  const competitorContext = response?.competitor_context || {}
  const merchantSnapshot = response?.merchant_room_snapshot || {}
  const promptProfile = response?.prompt_profile || {}
  const roomRecommendations = Array.isArray(response?.room_recommendations) ? response.room_recommendations : []
  const merchantSource = merchantSnapshot?.source === 'manual_room_mappings'
    ? '\u624b\u5de5\u623f\u578b\u4ef7\u683c'
    : (merchantSnapshot?.source === 'merchant_price_snapshot' ? '\u6293\u53d6\u623f\u578b\u5feb\u7167' : '\u672c\u5e97\u623f\u578b\u6837\u672c')
  const roomLines = roomRecommendations.slice(0, 12).map((item) => {
    const roomName = item?.display_name || item?.room_name || '\u672a\u547d\u540d\u623f\u578b'
    return [
      `${roomName}`,
      `\u5f53\u524d\u4ef7: ${formatPrice(item?.current_price)} | \u7ade\u5bf9\u6700\u4f4e: ${formatPrice(item?.competitor_min_price)} | \u7ade\u5bf9\u5747\u4ef7: ${formatPrice(item?.competitor_avg_price)} | \u7ade\u5bf9\u6700\u9ad8: ${formatPrice(item?.competitor_max_price)}`,
      `\u5efa\u8bae\u4ef7: ${formatPrice(item?.suggested_price)} | \u8c03\u6574: ${formatSignedPrice(item?.change_amount)} | \u8c03\u6574\u6bd4\u4f8b: ${formatSignedPercent(item?.change_pct)} | \u98ce\u9669: ${item?.risk_level || '-'}`,
      `\u8bf4\u660e: ${item?.reasoning || '-'}`,
    ].join("\\n")
  })
  return [
    `\u7ade\u5bf9\u9152\u5e97: ${response?.competitor_hotel_name || '\u7efc\u5408\u7ade\u5bf9\u9152\u5e97'}`,
    `\u89d2\u8272: ${promptProfile?.role || '\u9152\u5e97OTA\u8fd0\u8425\u4e13\u5bb6'}`,
    `\u672c\u5e97\u4ef7\u683c\u6765\u6e90: ${merchantSource}`,
    `\u7ade\u5bf9\u6837\u672c: ${Number(competitorContext?.price_count || 0)}`,
    `\u5efa\u8bae\u5747\u4ef7: ${formatPrice(summary?.suggested_price)}`,
    `\u7ade\u5bf9\u5747\u4ef7: ${formatPrice(summary?.competitor_avg_price)}`,
    `\u6458\u8981: ${summary?.reason_summary || '-'}`,
    roomLines.length ? '' : null,
    ...roomLines,
  ].filter((item) => item !== null).join("\\n")
}
  function formatMerchantSubmitResult(response) {
    const items = Array.isArray(response?.items) ? response.items : []
    const sampleLines = items.slice(0, 5).map((item) => {
      const name = item?.display_name || item?.rate_name || item?.room_name || "未命名房型"
      const finalPrice = item?.final_price ?? "-"
      const status = item?.status || "unknown"
      const message = item?.message || ""
      return `- ${name}: ${finalPrice} / ${status}${message ? ` / ${message}` : ""}`
    })
    return [
      "OTA 提交完成",
      `状态: ${response?.status || "unknown"}`,
      `成功: ${response?.success_count || 0}`,
      `失败: ${response?.failed_count || 0}`,
      `跳过: ${response?.skipped_submit_count || 0}`,
      `通道: ${response?.submit_channel || "merchant_portal"}`,
      sampleLines.length ? "提交示例:" : "",
      sampleLines.join("\n")
    ].filter(Boolean).join("\n")
  }

  function formatMerchantBatchSubmitResult(response) {
    const results = Array.isArray(response?.results) ? response.results : []
    if (results.length <= 1) {
      const single = results[0]
      if (single?.ok && single.response) {
        return formatMerchantSubmitResult(single.response)
      }
      if (single && !single.ok) {
        return [
          "OTA 提交完成",
          "状态: failed",
          "成功: 0",
          "失败: 1",
          `平台: ${single.platformName || "当前链接"}`,
          `链接: ${single.priceUrl || "-"}`,
          `错误: ${single.error || "未知错误"}`
        ].join("\n")
      }
      return formatMerchantSubmitResult(response)
    }

    const lines = [
      "多平台改价完成",
      `状态: ${response?.status || "unknown"}`,
      `平台: ${response?.success_platform_count || 0}/${response?.platform_count || results.length} 成功`,
      `成功: ${response?.success_count || 0}`,
      `失败: ${response?.failed_count || 0}`,
      `跳过: ${response?.skipped_submit_count || 0}`
    ]

    if (results.length) {
      lines.push("平台结果:")
      results.slice(0, 12).forEach((item) => {
        const summary = item?.ok
          ? `${item.platformName || "未命名平台"} / success=${Number(item?.response?.success_count || 0)} / failed=${Number(item?.response?.failed_count || 0)} / skipped=${Number(item?.response?.skipped_submit_count || 0)}`
          : `${item.platformName || "未命名平台"} / failed / ${item?.error || "未知错误"}`
        lines.push(`- ${summary}`)
      })
    }
    return lines.join("\n")
  }

  function normalizeMerchantWorkflowPreview(response) {
    const items = Array.isArray(response?.items) ? response.items : []
    const mappingSummary = response?.mapping_summary && typeof response.mapping_summary === "object"
      ? response.mapping_summary
      : {}
    return {
      itemCount: Number(response?.item_count || items.length),
      readySubmitCount: Number(items.filter((item) => Boolean(item?.submit_ready)).length),
      mappingSummary,
      priceUrl: String(response?.price_url || "").trim(),
      collectedAt: String(response?.collected_at || "").trim(),
      source: String(response?.source || "").trim(),
      items: items.map((item, index) => {
        const currentPrice = toPositiveNumber(item?.current_price ?? item?.price)
        return {
          id: `${item?.gid || "gid"}-${item?.hid || "hid"}-${index}`,
          displayName: item?.display_name || item?.rate_name || item?.room_name || `房型${index + 1}`,
          roomName: item?.room_name || "",
          rateName: item?.rate_name || item?.display_name || "",
          gid: item?.gid || "",
          hid: item?.hid || "",
          currentPrice,
          submitReady: Boolean(item?.submit_ready),
          selected: Boolean(item?.submit_ready),
          mappingStatus: item?.mapping_status || "unmapped"
        }
      })
    }
  }

  function renderMerchantWorkflowPreview() {
    if (!merchantPricingBox) {
      return
    }
    if (!currentMerchantWorkflowPreview?.items?.length) {
      merchantPricingBox.innerHTML = '<div class="fliggy-ops-empty-state">先点“读取房型”，勾选要修改的房型，再按目标价提交。</div>'
      return
    }

    const preview = currentMerchantWorkflowPreview
    const items = preview.items
    const submitReadyCount = items.filter((item) => item.submitReady).length
    const selectedCount = items.filter((item) => item.selected && item.submitReady).length
    const allSelected = submitReadyCount > 0 && selectedCount === submitReadyCount
    const mappingSummary = preview.mappingSummary || {}

    merchantPricingBox.innerHTML = `
      <div>
        已读取 <strong>${preview.itemCount}</strong> 条房型，当前可提交 <strong>${submitReadyCount}</strong> 条，已勾选 <strong>${selectedCount}</strong> 条。
      </div>
      <div class="fliggy-ops-summary-grid">
        <div class="fliggy-ops-summary-pill">
          <div class="fliggy-ops-summary-label">\u5df2\u6620\u5c04</div>
          <div class="fliggy-ops-summary-value">${Number(mappingSummary?.mapped || 0)}</div>
        </div>
        <div class="fliggy-ops-summary-pill">
          <div class="fliggy-ops-summary-label">\u90e8\u5206\u6620\u5c04</div>
          <div class="fliggy-ops-summary-value">${Number(mappingSummary?.partial || 0)}</div>
        </div>
        <div class="fliggy-ops-summary-pill">
          <div class="fliggy-ops-summary-label">\u672a\u6620\u5c04</div>
          <div class="fliggy-ops-summary-value">${Number(mappingSummary?.unmapped || 0)}</div>
        </div>
        <div class="fliggy-ops-summary-pill">
          <div class="fliggy-ops-summary-label">\u91c7\u96c6\u65f6\u95f4</div>
          <div class="fliggy-ops-summary-value">${escapeHtml(preview.collectedAt || "-")}</div>
        </div>
      </div>
      <div class="fliggy-ops-tip">\u6765\u6e90: ${escapeHtml(preview.source || "merchant_pricing_item_list")} | \u8c03\u4ef7\u94fe\u63a5: ${escapeHtml(preview.priceUrl || workflowPriceUrlInput?.value || merchantPriceUrlInput?.value || "-")}</div>
      <div class="fliggy-ops-workflow-tools">
        <button type="button" data-action="toggle-all-merchant-workflow" data-checked="${allSelected ? "1" : "0"}">${allSelected ? "取消全选" : "全选可提交项"}</button>
        <button type="button" class="secondary" disabled>可提交 ${submitReadyCount} 条</button>
        <button type="button" class="secondary" disabled>已勾选 ${selectedCount} 条</button>
      </div>
      <div class="fliggy-ops-workflow-list">
        ${items.map((item, index) => renderMerchantWorkflowItem(item, index)).join("")}
      </div>
    `
  }

  function renderMerchantWorkflowItem(item, index) {
    const roomLabel = escapeHtml(item.roomName || item.displayName || `房型${index + 1}`)
    return `
      <div class="fliggy-ops-workflow-item">
        <div class="fliggy-ops-workflow-item-top">
          <input type="checkbox" data-role="merchant-workflow-check" data-index="${index}" ${item.selected && item.submitReady ? "checked" : ""} ${item.submitReady ? "" : "disabled"}>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%;">
            <div class="fliggy-ops-workflow-item-name">${roomLabel}</div>
            <div style="white-space: nowrap; font-weight: 600;">${formatPrice(item.currentPrice)}</div>
          </div>
        </div>
      </div>
    `
  }

  function syncMerchantWorkflowItemsFromDom() {
    if (!currentMerchantWorkflowPreview?.items?.length || !merchantPricingBox) {
      return
    }
    currentMerchantWorkflowPreview.items.forEach((item, index) => {
      const checkedNode = merchantPricingBox.querySelector(`[data-role='merchant-workflow-check'][data-index='${index}']`)
      item.selected = Boolean(checkedNode?.checked) && item.submitReady
    })
  }

  function toggleAllMerchantWorkflowItems(nextChecked) {
    if (!currentMerchantWorkflowPreview?.items?.length) {
      return
    }
    currentMerchantWorkflowPreview.items.forEach((item) => {
      if (item.submitReady) {
        item.selected = nextChecked
      }
    })
  }

  function applySuggestedPricesToMerchantWorkflow() {
    if (!currentMerchantWorkflowPreview?.items?.length) {
      return
    }
    syncMerchantWorkflowItemsFromDom()
    currentMerchantWorkflowPreview.items.forEach((item) => {
      if (item.selected && item.submitReady && item.suggestedPrice) {
        item.finalPrice = item.suggestedPrice
      }
    })
  }

  function collectConfirmedMerchantWorkflowItems() {
    if (!currentMerchantWorkflowPreview?.items?.length) {
      return []
    }
    return currentMerchantWorkflowPreview.items
      .filter((item) => item.selected && item.submitReady && item.gid && item.hid)
      .map((item) => ({
        room_name: item.roomName,
        rate_name: item.rateName,
        display_name: item.displayName,
        gid: item.gid,
        hid: item.hid,
      }))
  }

  function collectSelectedMerchantWorkflowItems() {
    return collectConfirmedMerchantWorkflowItems()
  }

  function formatMerchantWorkflowResult(response) {
    const mappingSummary = response?.mapping_summary || {}
    const lines = [
      "商家房型读取完成",
      `房型数: ${Number(response?.item_count || 0)}`,
      `已映射: ${Number(mappingSummary?.mapped || 0)}`,
      `部分映射: ${Number(mappingSummary?.partial || 0)}`,
      `未映射: ${Number(mappingSummary?.unmapped || 0)}`,
      `来源: ${response?.source || "merchant_pricing_item_list"}`,
      `调价链接: ${response?.price_url || "-"}`
    ]
    const shouldShowDiagnostics = Number(response?.item_count || 0) === 0
      || Boolean(response?.cdp_fallback_reason)
      || Boolean(response?.collect_mode)
    if (shouldShowDiagnostics) {
      lines.push(`采集模式: ${response?.collect_mode || "-"}`)
      lines.push(`请求模式: ${response?.collect_mode_requested || "-"}`)
      lines.push(`CDP回退: ${response?.cdp_fallback_reason || "-"}`)
      lines.push(`会话文件: ${response?.storage_state_used || "-"}`)
      lines.push(`匹配页面: ${response?.matched_page_url || "-"}`)
      lines.push(`调试地址: ${response?.debug_url || "-"}`)
    }
    return lines.join("\n")
  }

  async function saveManualTargets() {
    config = await sendRuntimeMessage({
      type: "SAVE_CONFIG",
      payload: { manualTargets: getManualTargets().join("\n") }
    })
    targetInput.value = String(config?.manualTargets || "")
    renderConfiguredCompetitorHotelsSummary(config)
      renderCompetitorPricingAdvice()
      configBox.textContent = renderConfigSummary(config)
  }

  function getManualTargets() {
    return String(targetInput.value || "")
      .split(/[\n,，、;]/)
      .map((item) => item.trim())
      .filter(Boolean)
      .filter((item, index, array) => array.indexOf(item) === index)
      .slice(0, 20)
  }

  async function checkService() {
    try {
      const status = await sendRuntimeMessage({ type: "SERVICE_STATUS" })
      updateStatus(`服务在线: ${status.plugin}`, "ok")
    } catch (error) {
      updateStatus(`服务不可用: ${error.message}`, "error")
    }
  }

  function setBusy(isBusy) {
    busy = Boolean(isBusy)
    buttons.forEach((button) => {
      button.disabled = busy
    })
    formControls.forEach((control) => {
      control.disabled = busy
    })
    navButtons.forEach((button) => {
      button.disabled = busy
    })
    merchantPricingBox?.querySelectorAll("button, input").forEach((node) => {
      node.disabled = busy
    })
  }

  function updateStatus(message, state) {
    statusText.textContent = message
    statusDot.classList.remove("ok", "error")
    if (state) {
      statusDot.classList.add(state)
    }
  }

  function escapeAttr(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
  }

  function renderConfiguredCompetitorHotelsSummary(currentConfig) {
    if (!configuredHotelsBox) {
      return
    }
    if (!Boolean(currentConfig?.authenticated && currentConfig?.authUser && currentConfig?.currentShop)) {
      configuredHotelsBox.innerHTML = '<div class="fliggy-ops-footer">请先在 Popup 完成登录并选择店铺，再读取竞对配置。</div>'
      return
    }
    const hotels = Array.isArray(currentConfig?.competitorHotels) ? currentConfig.competitorHotels : []
    const mappingState = getPreferredRoomMappingState(currentConfig, currentMerchantMappings)
    if (!hotels.length) {
      configuredHotelsBox.innerHTML = '<div class="fliggy-ops-footer">当前未配置竞对酒店，可在设置中维护酒店名称或 URL。</div>'
      return
    }

    configuredHotelsBox.innerHTML = `
      <div>已配置 <strong>${hotels.length}</strong> 家竞对酒店</div>
      <div class="fliggy-ops-footer" style="margin-top: 8px;">已维护 <strong>${mappingState.count}</strong> 条${mappingState.sourceLabel}房型映射</div>
      <div class="fliggy-ops-footer" style="margin-top: 8px;">${hotels.map((hotel) => escapeHtml(hotel.name || hotel.url || "未命名酒店")).join(" / ")}</div>
    `
  }

  function renderConfigSummary(currentConfig) {
    const competitorHotels = Array.isArray(currentConfig?.competitorHotels)
      ? currentConfig.competitorHotels
      : []
    const mappingState = getPreferredRoomMappingState(currentConfig, currentMerchantMappings)
    return [
      `服务: ${currentConfig.baseUrl}`,
      `登录状态: ${currentConfig?.authenticated ? "已登录" : "未登录"}`,
      `登录账号: ${currentConfig?.authUser?.username || "-"}`,
      `当前店铺: ${currentConfig?.currentShop?.shop_name || "-"} (${currentConfig?.currentShop?.shop_id || currentConfig.shopId || "-"})`,
      `租户 / 店铺: tenant=${currentConfig.tenantId} / shop=${currentConfig.shopId}`,
      `调试页: ${currentConfig.debugUrl}`,
      `起始页: ${currentConfig.startUrl}`,
      `分页 / 酒店: ${currentConfig.maxPages} / ${currentConfig.maxHotels}`,
      `竞对酒店: ${competitorHotels.length ? `${competitorHotels.length} 家` : "未配置"}`,
      `商家价格页链接: ${currentConfig?.currentShop ? "单链接模式" : "未配置"}`,
      `房型映射: ${mappingState.count ? `${mappingState.count} 条${mappingState.source === "merchant" ? "（后端）" : ""}` : "未维护"}`,
      `维护目标: ${getManualTargets().length ? getManualTargets().join(" / ") : "未填写"}`
    ].join("\n")
  }

  function renderCompetitorRoomPrices(response) {
    const hotels = Array.isArray(response?.hotels) ? response.hotels : []
    const header = [
      `配置酒店: ${Number(response?.hotel_count || hotels.length)} 家`,
      `房型价: ${Number(response?.total_rooms || 0)} 条`,
      response?.saved_count !== undefined ? `已保存: ${Number(response.saved_count)} 条` : null
    ].filter(Boolean).join(" | ")

    if (!hotels.length) {
      return `${viewTools.escapeHtml(header)}<div class="fliggy-ops-footer">未返回可展示的竞对房型价。</div>`
    }

    const hotelHtml = hotels.map((hotel, index) => {
      const hotelName = viewTools.escapeHtml(hotel?.hotel_name || `竞对酒店 ${index + 1}`)
      if (hotel?.error) {
        return `<li><strong>${hotelName}</strong><br>\u5931\u8d25: ${viewTools.escapeHtml(String(hotel.error))}</li>`
      }
      const rooms = Array.isArray(hotel?.rooms) ? hotel.rooms : []
      const roomSummary = rooms.slice(0, 8).map((room) => {
        const roomType = viewTools.escapeHtml(String(room?.room_type || "-"))
        const rateName = viewTools.escapeHtml(String(room?.rate_name || room?.room_type || "-"))
        const price = viewTools.escapeHtml(String(room?.price ?? "-"))
        return `${roomType} / ${rateName} / ${price}`
      }).join("<br>")
      return `<li><strong>${hotelName}</strong><br>\u623f\u578b\u6761\u6570: ${rooms.length}${roomSummary ? `<br>${roomSummary}` : ""}</li>`
    }).join("")

    return `${viewTools.escapeHtml(header)}<ol class="fliggy-ops-list">${hotelHtml}</ol>`
  }

  function formatPrice(value) {
    return value ? `¥${Number(value).toFixed(2)}` : "-"
  }

  function escapeHtml(value) {
    return viewTools?.escapeHtml ? viewTools.escapeHtml(value) : String(value || "")
  }

  return {
    open,
    close,
    refresh() {
      pageContext = pageContextTools.detectPageContext()
      viewTools.renderPageContext(pageContextBox, pageContext)
      return pageContext
    }
  }
}

function getPageContext() {
  const pageContextTools = window.FliggyOpsPageContext
  if (!pageContextTools || typeof pageContextTools.detectPageContext !== "function") {
    return {
      pageType: "unavailable",
      startUrl: window.location.href,
      targetHotelNames: []
    }
  }
  return pageContextTools.detectPageContext()
}

async function getPageSnapshot(message = {}) {
  const pageContextTools = window.FliggyOpsPageContext
  if (!pageContextTools) {
    return {
      pageContext: {
        pageType: "unavailable",
        startUrl: window.location.href,
        targetHotelNames: []
      },
      candidateRows: []
    }
  }
  if (typeof pageContextTools.collectPageSnapshot === "function") {
    return pageContextTools.collectPageSnapshot({
      maxPages: Number(message?.maxPages) || 1,
      collectAllPages: Boolean(message?.collectAllPages),
      targetHotelNames: Array.isArray(message?.targetHotelNames) ? message.targetHotelNames : []
    })
  }
  return {
    pageContext: pageContextTools.detectPageContext(),
    candidateRows: []
  }
}

async function fetchCompetitorRoomPricesDirect(options = {}) {
  const config = await getEffectiveConfig().catch(() => null)
  const competitorHotels = Array.isArray(options?.competitorHotels) && options.competitorHotels.length
    ? options.competitorHotels
    : (Array.isArray(config?.competitorHotels) ? config.competitorHotels : [])
  const payload = competitorHotels.length
    ? { hotels: competitorHotels }
    : {}

  return requestCompetitorRoomPrices(payload)
}

function normalizeRequestBaseUrl(baseUrl) {
  return String(baseUrl || DEFAULT_EXTENSION_CONFIG.baseUrl).trim().replace(/\/+$/, "")
}

async function requestCompetitorRoomPricesViaHttp(payload = {}) {
  const config = await getEffectiveConfig()
  const hotels = normalizeCompetitorHotels(payload.hotels || config.competitorHotels)
  if (!hotels.length) {
    throw new Error("\u8bf7\u5148\u5728\u8bbe\u7f6e\u9875\u914d\u7f6e\u81f3\u5c11\u4e00\u6761\u7ade\u5bf9\u9152\u5e97\u8be6\u60c5\u9875")
  }
  const response = await fetch(`${normalizeRequestBaseUrl(config.baseUrl)}/plugin/competitor/room-prices`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Tenant-Id": String(config.tenantId),
      "X-Shop-Id": String(config.shopId),
      ...(String(config.authToken || "").trim() ? { Authorization: `Bearer ${String(config.authToken || "").trim()}` } : {})
    },
    body: JSON.stringify({
      shop_id: Number(config.shopId),
      hotels,
      headless: payload.headless !== undefined ? Boolean(payload.headless) : true,
      save_result: payload.saveResult !== undefined ? Boolean(payload.saveResult) : Boolean(config.saveResult),
      debug_url: String(config.debugUrl || "")
    })
  })
  const textBody = await response.text()
  let data = null
  try {
    data = textBody ? JSON.parse(textBody) : null
  } catch (error) {
    data = null
  }
  if (!response.ok) {
    throw new Error(data?.error || data?.message || textBody || `HTTP ${response.status}`)
  }
  return data
}

async function requestMerchantMappingApi(path, options = {}) {
  const config = await getEffectiveConfig()
  const requestUrl = new URL(`${normalizeRequestBaseUrl(config.baseUrl)}${path}`)
  const query = options.query && typeof options.query === "object" ? options.query : null
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") {
        continue
      }
      requestUrl.searchParams.set(key, String(value))
    }
  }

  const response = await fetch(requestUrl.toString(), {
    method: String(options.method || "GET").toUpperCase(),
    headers: {
      "Content-Type": "application/json",
      "X-Tenant-Id": String(config.tenantId),
      "X-Shop-Id": String(config.shopId),
      ...(String(config.authToken || "").trim() ? { Authorization: `Bearer ${String(config.authToken || "").trim()}` } : {})
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body)
  })
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

function isUnsupportedMessageTypeError(error) {
  return /Unsupported message type/i.test(String(error?.message || error || ""))
}

async function requestMerchantCredentialSummary() {
  try {
    return await sendRuntimeMessage({ type: "MERCHANT_CREDENTIAL_GET" })
  } catch (error) {
    if (!isUnsupportedMessageTypeError(error)) {
      throw error
    }
    return requestViaExtensionBridge("merchant-credential-get")
  }
}

async function saveMerchantCredentialSummary(payload = {}) {
  try {
    return await sendRuntimeMessage({ type: "MERCHANT_CREDENTIAL_SAVE", payload })
  } catch (error) {
    if (!isUnsupportedMessageTypeError(error)) {
      throw error
    }
    return requestViaExtensionBridge("merchant-credential-save", payload)
  }
}

async function requestMerchantMappingsSummary(payload = {}) {
  try {
    return await sendRuntimeMessage({ type: "MERCHANT_MAPPING_LIST", payload })
  } catch (error) {
    if (!isUnsupportedMessageTypeError(error)) {
      throw error
    }
    return requestViaExtensionBridge("merchant-mapping-list", payload)
  }
}

async function saveMerchantMappingSummary(payload = {}) {
  try {
    return await sendRuntimeMessage({ type: "MERCHANT_MAPPING_SAVE", payload })
  } catch (error) {
    if (!isUnsupportedMessageTypeError(error)) {
      throw error
    }
    return requestViaExtensionBridge("merchant-mapping-save", payload)
  }
}

async function refreshMerchantMappingsSummary(payload = {}) {
  try {
    return await sendRuntimeMessage({ type: "MERCHANT_MAPPING_REFRESH", payload })
  } catch (error) {
    if (!isUnsupportedMessageTypeError(error)) {
      throw error
    }
    return requestViaExtensionBridge("merchant-mapping-refresh", payload)
  }
}

async function requestCompetitorRoomPrices(payload = {}) {
  let lastError = null
  for (const type of COMPETITOR_ROOM_PRICE_MESSAGE_TYPES) {
    try {
      return await sendRuntimeMessage({ type, payload })
    } catch (error) {
      lastError = error
      if (!isUnsupportedMessageTypeError(error)) {
        throw error
      }
    }
  }
  if (lastError && isUnsupportedMessageTypeError(lastError)) {
    try {
      return await requestViaExtensionBridge("competitor-room-prices", payload)
    } catch (bridgeError) {
      throw new Error(bridgeError instanceof Error ? bridgeError.message : String(bridgeError))
    }
  }
  throw lastError || new Error("\u5f53\u524d\u63d2\u4ef6\u7248\u672c\u4e0d\u652f\u6301\u63d2\u4ef6\u5185\u76f4\u6293\u623f\u578b\u4ef7\uff0c\u8bf7\u5237\u65b0\u6269\u5c55\u540e\u91cd\u8bd5")
}

function parseCurrentHotelDetailRoomPrices() {
  const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim()
  const cleanRoomTitle = (value) => normalize(String(value || "").replace(/查看房型图片\s*\(\d+\)/g, "").replace(/报价列表/g, "").trim())
  const splitLines = (value) => {
    const seen = new Set()
    return String(value || "")
      .split("\n")
      .map((line) => normalize(line))
      .filter((line) => {
        if (!line || seen.has(line)) {
          return false
        }
        seen.add(line)
        return true
      })
  }
  const bodyLines = splitLines(document.body?.innerText || "")
  const rooms = []
  const seen = new Set()
  const isBadTitle = (value) => /^(报价列表|卖家|处理时长|评分|打分|点评|电话|地址|地图|设施|政策|住客点评)$/.test(value)
    || /卖家|处理时长|店铺|专营店|打分|点评|电话查询/.test(value)
  const isPriceLine = (value) => /(?:¥|￥)?\s*(\d+(?:\.\d{1,2})?)\s*起/.test(value)
  const parsePrice = (value) => {
    const matched = String(value || "").match(/(?:¥|￥)?\s*(\d+(?:\.\d{1,2})?)\s*起/)
    return matched ? Number(matched[1]) : null
  }
  const isMetaLine = (value) => /^(床型：|面积：|楼层：|窗型：|早餐|无早|含早|可取消|不可取消|不可退)/.test(value)
  const looksLikeRoomTitle = (value) => {
    const text = cleanRoomTitle(value)
    if (!text || text.length < 2 || text.length > 80) {
      return false
    }
    if (isBadTitle(text) || isPriceLine(text) || isMetaLine(text) || /^\d+(?:\.\d+)?$/.test(text)) {
      return false
    }
    return /房|床房|套房|标间|大床|双床|亲子|商务|豪华|观景|清新/.test(text)
  }

  for (let index = 0; index < bodyLines.length; index += 1) {
    const line = bodyLines[index]
    if (!isPriceLine(line)) {
      continue
    }
    const price = parsePrice(line)
    if (!Number.isFinite(price) || price < 50 || price > 99999) {
      continue
    }

    let roomType = ""
    for (let back = 1; back <= 3; back += 1) {
      const candidate = cleanRoomTitle(bodyLines[index - back] || "")
      if (looksLikeRoomTitle(candidate)) {
        roomType = candidate
        break
      }
    }
    if (!roomType) {
      continue
    }

    const detailLines = []
    for (let forward = 1; forward <= 3; forward += 1) {
      const nextLine = bodyLines[index + forward] || ""
      if (!nextLine || isPriceLine(nextLine) || looksLikeRoomTitle(nextLine) || isBadTitle(nextLine)) {
        break
      }
      detailLines.push(nextLine)
    }

    const key = `${roomType}|${price}`
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    const detailText = detailLines.join(' / ')
    rooms.push({
      room_type: roomType,
      rate_name: roomType,
      price,
      breakfast: /含早|含双早|含单早|有早餐/.test(detailText) ? "含早" : (/无早|不含早/.test(detailText) ? "无早" : "未知"),
      cancelable: /免费取消|可取消|可免费/.test(detailText) ? "可取消" : (/不可取消|不可退/.test(detailText) ? "不可取消" : "未知"),
      raw: `${roomType} | ${detailText} | ${price}起`.slice(0, 300)
    })
  }

  const hotelName = normalize(document.querySelector('h1,h2,[class*="hotel"],[class*="name"],[class*="title"]')?.textContent || document.title || "当前酒店")
  return {
    hotel_count: 1,
    total_rooms: rooms.length,
    saved_count: 0,
    hotels: [{
      hotel_name: hotelName,
      hotel_url: window.location.href,
      rooms
    }]
  }
}
function sendRuntimeMessage(message) {
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











































