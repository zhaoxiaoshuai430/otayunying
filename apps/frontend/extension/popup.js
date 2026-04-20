const resultView = window.FliggyOpsResultView
const statusDot = document.getElementById("status-dot")
const statusText = document.getElementById("status-text")
const authCard = document.getElementById("auth-card")
const authTitle = document.getElementById("auth-title")
const authNote = document.getElementById("auth-note")
const authLoginForm = document.getElementById("auth-login-form")
const authSessionBox = document.getElementById("auth-session-box")
const authBaseUrlInput = document.getElementById("auth-base-url-input")
const authTenantInput = document.getElementById("auth-tenant-input")
const authUsernameInput = document.getElementById("auth-username-input")
const authPasswordInput = document.getElementById("auth-password-input")
const authCurrentUserInput = document.getElementById("auth-current-user")
const shopSwitchBox = document.getElementById("shop-switch-box")
const shopSelect = document.getElementById("shop-select")
const authLoginBtn = document.getElementById("auth-login-btn")
const authRefreshBtn = document.getElementById("auth-refresh-btn")
const authLogoutBtn = document.getElementById("auth-logout-btn")
const appShell = document.getElementById("app-shell")
const pageBox = document.getElementById("page-box")
const configBox = document.getElementById("config-box")
const resultBox = document.getElementById("result-box")
const targetsInput = document.getElementById("targets-input")
const competitorNameInput = document.getElementById("competitor-name-input")
const workflowPriceUrlInput = document.getElementById("workflow-price-url-input")
const workflowAnalyzeBtn = document.getElementById("workflow-analyze-btn")
const workflowFillBtn = document.getElementById("workflow-fill-btn")
const workflowSubmitBtn = document.getElementById("workflow-submit-btn")
const workflowBox = document.getElementById("workflow-box")
const configuredHotelsBox = document.getElementById("configured-hotels-box")
const roomPricesBtn = document.getElementById("room-prices-btn")
const refreshRoomConfigBtn = document.getElementById("refresh-room-config-btn")
const debugRoomConfigBtn = document.getElementById("debug-room-config-btn")
const roomSettingsBtn = document.getElementById("open-room-settings-btn")
const competitorAdviceHotelInput = document.getElementById("competitor-advice-hotel-input")
const competitorAdviceTotalRoomsInput = document.getElementById("competitor-advice-total-rooms-input")
const competitorAdviceAvailableRoomsInput = document.getElementById("competitor-advice-available-rooms-input")
const competitorAdviceCurrentPriceInput = document.getElementById("competitor-advice-current-price-input")
const competitorAdviceStrategySelect = document.getElementById("competitor-advice-strategy-select")
const competitorAdviceBtn = document.getElementById("competitor-advice-btn")
const competitorAdviceBox = document.getElementById("competitor-advice-box")
const uniformPriceUrlInput = document.getElementById("uniform-price-url-input")
const uniformTargetPriceInput = document.getElementById("uniform-target-price-input")
const uniformSubmitBtn = document.getElementById("uniform-submit-btn")
const refreshBtn = document.getElementById("refresh-btn")
const statusBtn = document.getElementById("status-btn")
const collectBtn = document.getElementById("collect-btn")
const panelBtn = document.getElementById("panel-btn")
const optionsBtn = document.getElementById("options-btn")

const RUNTIME_TIMEOUT_MS = 30000
const TAB_TIMEOUT_MS = 4000
const COMPETITOR_ROOM_PRICE_MESSAGE_TYPES = [
  "COMPETITOR_ROOM_PRICES_TABS",
  "COMPETITOR_ROOM_PRICES"
]

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
  manualRoomMappingsByShop: {},
  manualRoomMappings: [],
  manualTargets: ""
}

function coercePositiveInt(value, fallback, minimum, maximum) {
  const next = Number(value)
  if (!Number.isFinite(next)) {
    return fallback
  }
  return Math.min(Math.max(Math.round(next), minimum), maximum)
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
  const currentPrice = toPositiveNumber(item.currentPrice ?? item.current_price)
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
  const currentPrice = toPositiveNumber(item.last_seen_price ?? item.lastSeenPrice ?? item.current_price ?? item.currentPrice)
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
  const runtimeManualTargets = String(runtimeValue.manualTargets || "").trim()
  const storageManualTargets = String(storageValue.manualTargets || "").trim()
  const runtimeManualRoomMappings = getManualRoomMappingsForShop(runtimeValue)
  const storageManualRoomMappings = getManualRoomMappingsForShop(storageValue)

  if (!runtimeHotels.length && !storageHotels.length && !runtimeManualTargets && !storageManualTargets && !runtimeManualRoomMappings.length && !storageManualRoomMappings.length) {
    return runtimeValue
  }

  return normalizeConfig({
    ...storageValue,
    ...runtimeValue,
    competitorHotels: runtimeHotels.length ? runtimeHotels : storageHotels,
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
    source: runtimeDebug ? "background_debug+popup_storage" : "popup_storage_only",
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

let currentConfig = null
let currentPageContext = null
let currentWorkflowPreview = null
let currentCompetitorRoomPrices = null
let currentCompetitorPricingAdvice = null
let currentMerchantMappings = []
let merchantMappingsLoaded = false
let currentMerchantMappingShopId = ""

function isAuthenticatedConfig(config) {
  return Boolean(config?.authenticated && config?.authUser && config?.currentShop)
}

chrome.storage?.onChanged?.addListener((changes, areaName) => {
  if (areaName !== "sync" && areaName !== "local") {
    return
  }
  if (!changes?.competitorHotels && !changes?.manualTargets && !changes?.configUpdatedAt) {
    return
  }
  refreshCurrentConfig().catch(() => {})
})

targetsInput?.addEventListener("blur", () => {
  saveManualTargets().catch(() => {})
})

authLoginBtn?.addEventListener("click", async () => {
  await withBusy(async () => {
    const username = String(authUsernameInput?.value || "").trim()
    const password = String(authPasswordInput?.value || "").trim()
    const tenantId = Number(authTenantInput?.value || 0)
    const baseUrl = String(authBaseUrlInput?.value || "").trim()
    if (!baseUrl) {
      throw new Error("请先填写后端地址")
    }
    if (!tenantId) {
      throw new Error("请先填写有效的 Tenant ID")
    }
    if (!username || !password) {
      throw new Error("请先填写用户名和密码")
    }
    currentConfig = await sendRuntimeMessage({
      type: "AUTH_LOGIN",
      payload: {
        baseUrl,
        tenantId,
        username,
        password
      }
    })
    authPasswordInput.value = ""
    currentMerchantMappings = []
    merchantMappingsLoaded = false
    currentMerchantMappingShopId = String(resolveActiveShopId(currentConfig) || "").trim()
    applyCurrentConfig(currentConfig)
    try {
      const response = await requestMerchantMappingsSummary({ onlyEnabled: false })
      currentMerchantMappings = normalizeMerchantRoomMappings(response?.items)
      merchantMappingsLoaded = true
      applyCurrentConfig(currentConfig)
    } catch (error) {
    }
    renderWorkflowPreview()
    updateStatus(`已登录 ${currentConfig?.authUser?.username || username}`, "ok")
    resultBox.textContent = "登录成功，已进入插件工作台。"
  })
})

authRefreshBtn?.addEventListener("click", async () => {
  await withBusy(async () => {
    currentConfig = await sendRuntimeMessage({ type: "GET_AUTH_STATE" })
    currentMerchantMappings = []
    merchantMappingsLoaded = false
    currentMerchantMappingShopId = isAuthenticatedConfig(currentConfig) ? String(resolveActiveShopId(currentConfig) || "").trim() : ""
    applyCurrentConfig(currentConfig)
    if (isAuthenticatedConfig(currentConfig)) {
      try {
        const response = await requestMerchantMappingsSummary({ onlyEnabled: false })
        currentMerchantMappings = normalizeMerchantRoomMappings(response?.items)
        merchantMappingsLoaded = true
        applyCurrentConfig(currentConfig)
      } catch (error) {
      }
    }
    updateStatus(isAuthenticatedConfig(currentConfig) ? "已刷新登录会话" : "当前未登录", isAuthenticatedConfig(currentConfig) ? "ok" : "error")
  })
})

authLogoutBtn?.addEventListener("click", async () => {
  await withBusy(async () => {
    currentConfig = await sendRuntimeMessage({ type: "AUTH_LOGOUT" })
    authPasswordInput.value = ""
    applyCurrentConfig(currentConfig)
    currentWorkflowPreview = null
    currentCompetitorRoomPrices = null
    currentCompetitorPricingAdvice = null
    renderWorkflowPreview()
    renderCompetitorPricingAdvice()
    updateStatus("已退出登录", "ok")
    resultBox.textContent = "当前已退出插件登录。"
  })
})

shopSelect?.addEventListener("change", async () => {
  const shopId = Number(shopSelect.value || 0)
  if (!shopId) {
    return
  }
  await withBusy(async () => {
    currentConfig = await sendRuntimeMessage({
      type: "AUTH_SWITCH_SHOP",
      payload: { shopId }
    })
    currentMerchantMappings = []
    merchantMappingsLoaded = false
    currentMerchantMappingShopId = String(resolveActiveShopId(currentConfig) || "").trim()
    applyCurrentConfig(currentConfig)
    try {
      const response = await requestMerchantMappingsSummary({ onlyEnabled: false })
      currentMerchantMappings = normalizeMerchantRoomMappings(response?.items)
      merchantMappingsLoaded = true
      applyCurrentConfig(currentConfig)
    } catch (error) {
    }
    currentWorkflowPreview = null
    currentCompetitorRoomPrices = null
    currentCompetitorPricingAdvice = null
    renderWorkflowPreview()
    renderCompetitorPricingAdvice()
    updateStatus(`已切换到店铺 ${currentConfig?.currentShop?.shop_name || shopId}`, "ok")
    resultBox.textContent = "店铺已切换，当前配置和工作流已刷新。"
  })
})

workflowAnalyzeBtn.addEventListener("click", async () => {
  await withBusy(async () => {
    const competitorHotelName = String(competitorNameInput.value || "").replace(/\s+/g, " ").trim()
    if (!competitorHotelName) {
      throw new Error("请先输入竞对酒店名称")
    }
    const response = await sendRuntimeMessage({
      type: "COMPETITOR_WORKFLOW_PREVIEW",
      payload: {
        competitorHotelName,
        priceUrl: workflowPriceUrlInput.value
      }
    })
    currentWorkflowPreview = normalizeWorkflowPreview(response)
    updateStatus(`已完成 ${competitorHotelName} 的建议价分析`, "ok")
    renderWorkflowPreview()
    resultBox.textContent = formatWorkflowResult(response)
  })
})

workflowFillBtn.addEventListener("click", () => {
  applySuggestedPricesToWorkflow()
  renderWorkflowPreview()
})

workflowSubmitBtn.addEventListener("click", async () => {
  await submitWorkflowPricing()
})

roomPricesBtn.addEventListener("click", async () => {
  await withBusy(async () => {
    currentConfig = await getEffectiveConfig()
    applyCurrentConfig(currentConfig)
    const configuredHotels = Array.isArray(currentConfig?.competitorHotels) ? currentConfig.competitorHotels : []
    const payload = configuredHotels.length ? { hotels: configuredHotels } : {}
    const response = await requestCompetitorRoomPrices(payload)
    currentCompetitorRoomPrices = response
    currentCompetitorPricingAdvice = null
    if (!String(competitorAdviceHotelInput?.value || "").trim() && Array.isArray(response?.hotels) && response.hotels.length === 1) {
      competitorAdviceHotelInput.value = String(response.hotels[0]?.hotel_name || "")
    }
    renderCompetitorPricingAdvice()
    updateStatus(`已抓取 ${Number(response?.hotel_count || 0)} 家竞对酒店的 ${Number(response?.total_rooms || 0)} 条房型价`, "ok")
    resultBox.innerHTML = renderCompetitorRoomPrices(response)
  })
})
refreshRoomConfigBtn.addEventListener("click", async () => {
  await withBusy(async () => {
    currentConfig = await refreshCurrentConfig()
    const competitorHotels = Array.isArray(currentConfig?.competitorHotels) ? currentConfig.competitorHotels : []
    updateStatus(`已刷新竞对配置，当前 ${competitorHotels.length} 家`, "ok")
    resultBox.textContent = JSON.stringify({
      competitorHotels
    }, null, 2)
  })
})
debugRoomConfigBtn.addEventListener("click", async () => {
  await withBusy(async () => {
    const response = await buildConfigDebugInfo()
    currentConfig = normalizeConfig(response?.effective || response?.merged || {})
    applyCurrentConfig(currentConfig)
    const effectiveCount = Number(response?.counts?.effective || 0)
    updateStatus(`\u8bca\u65ad\u5b8c\u6210\uff0c\u5f53\u524d\u751f\u6548\u7ade\u5bf9\u914d\u7f6e ${effectiveCount} \u5bb6`, effectiveCount ? "ok" : "error")
    resultBox.textContent = JSON.stringify(response, null, 2)
  })
})

roomSettingsBtn.addEventListener("click", async () => {
  await withBusy(async () => {
    await sendRuntimeMessage({ type: "OPEN_OPTIONS" })
    updateStatus("已打开竞对酒店设置", "ok")
  })
})

competitorAdviceBtn?.addEventListener("click", async () => {
  await withBusy(async () => {
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
        strategy: competitorAdviceStrategySelect?.value || "balanced",
        roomPrices: currentCompetitorRoomPrices,
        manualRoomMappings: getPreferredRoomMappingState(currentConfig, currentMerchantMappings).items,
      }
    })
    currentCompetitorPricingAdvice = response
    renderCompetitorPricingAdvice()
    const suggestedPrice = Number(response?.advice_summary?.suggested_price || 0)
    updateStatus(suggestedPrice ? `建议价已生成: ¥${suggestedPrice.toFixed(2)}` : "竞对建议价已生成", "ok")
    resultBox.textContent = formatCompetitorPricingAdviceResult(response)
  })
})
workflowBox.addEventListener("click", async (event) => {
  const action = event.target?.dataset?.action
  if (!action) {
    return
  }
  if (action === "toggle-all-workflow") {
    toggleAllWorkflowItems(event.target.dataset.checked !== "1")
    renderWorkflowPreview()
  }
})

workflowBox.addEventListener("change", (event) => {
  if (!event.target) {
    return
  }
  if (event.target.matches("[data-role='workflow-check']") || event.target.matches("[data-role='workflow-final-price']")) {
    syncWorkflowItemsFromDom()
  }
})

uniformSubmitBtn.addEventListener("click", async () => {
  await withBusy(async () => {
    const priceUrl = String(uniformPriceUrlInput.value || "").trim()
    const targetPrice = toPositiveNumber(uniformTargetPriceInput.value)
    if (!priceUrl) {
      throw new Error("请先填写调价官网链接")
    }
    if (!targetPrice) {
      throw new Error("请先填写有效的目标价格")
    }
    const response = await sendRuntimeMessage({
      type: "MERCHANT_UNIFORM_PRICE_SUBMIT",
      payload: {
        priceUrl,
        targetPrice,
        comment: "browser_extension_uniform_submit"
      }
    })
    updateStatus(`已按目标价 ¥${targetPrice.toFixed(2)} 发起改价`, response.failed_count ? "error" : "ok")
    resultBox.textContent = formatSubmitResult(response)
  })
})

refreshBtn.addEventListener("click", () => load())
statusBtn.addEventListener("click", async () => {
  await withBusy(async () => {
    const status = await sendRuntimeMessage({ type: "SERVICE_STATUS" })
    updateStatus(`服务在线: ${status.plugin}`, "ok")
    resultBox.textContent = JSON.stringify(status, null, 2)
  })
})
collectBtn.addEventListener("click", async () => {
  await withBusy(async () => {
    const collectMaxPages = 1
    const manualTargets = getManualTargets()
    const pageSnapshot = await getCurrentPageSnapshot(true, {
      maxPages: collectMaxPages,
      collectAllPages: false,
      targetHotelNames: manualTargets
    })
    const pageContext = pageSnapshot?.pageContext || currentPageContext
    if (!pageContext || pageContext.unsupported) {
      throw new Error("\u8bf7\u5148\u5728\u8bbe\u7f6e\u9875\u914d\u7f6e\u81f3\u5c11\u4e00\u6761\u7ade\u5bf9\u9152\u5e97\u8be6\u60c5\u9875")
    }
    currentPageContext = pageContext
    renderPageContext(currentPageContext)
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
    resultBox.innerHTML = resultView.renderCollectSummary(response, {
      ...pageContext,
      targetHotelNames: manualTargets
    })
  })
})
panelBtn.addEventListener("click", async () => {
  await withBusy(async () => {
    const tab = await getActiveTab()
    if (!tab?.id) {
      throw new Error("未找到当前活动标签页")
    }
    const response = await sendTabMessage(tab.id, { type: "OPEN_PANEL" })
    currentPageContext = response
    renderPageContext(currentPageContext)
    updateStatus("已在页面中打开运营助手", "ok")
    resultBox.textContent = "页面浮层已打开。"
  })
})
optionsBtn.addEventListener("click", async () => {
  await withBusy(async () => {
    await sendRuntimeMessage({ type: "OPEN_OPTIONS" })
    updateStatus("已打开设置页", "ok")
  })
})

load()

async function load() {
  await withBusy(async () => {
    const [configResult, statusResult, pageSnapshotResult] = await Promise.allSettled([
      getEffectiveConfig(),
      sendRuntimeMessage({ type: "SERVICE_STATUS" }),
      getCurrentPageSnapshot(false)
    ])

    currentConfig = configResult.status === "fulfilled"
      ? configResult.value
      : normalizeConfig(DEFAULT_EXTENSION_CONFIG)

    const nextShopId = isAuthenticatedConfig(currentConfig) ? String(resolveActiveShopId(currentConfig) || "").trim() : ""
    if (nextShopId !== currentMerchantMappingShopId) {
      currentMerchantMappings = []
      merchantMappingsLoaded = false
      currentMerchantMappingShopId = nextShopId
    }

    currentPageContext = pageSnapshotResult.status === "fulfilled"
      ? (pageSnapshotResult.value?.pageContext || unsupportedPageContext("当前页面不是酒店详情页", ""))
      : unsupportedPageContext(pageSnapshotResult.reason?.message || "页面识别失败", "")

    applyCurrentConfig(currentConfig)
    if (isAuthenticatedConfig(currentConfig) && !merchantMappingsLoaded) {
      try {
        const response = await requestMerchantMappingsSummary({ onlyEnabled: false })
        currentMerchantMappings = normalizeMerchantRoomMappings(response?.items)
        merchantMappingsLoaded = true
      } catch (error) {
      }
      applyCurrentConfig(currentConfig)
    }
    renderPageContext(currentPageContext)
    renderWorkflowPreview()
    renderCompetitorPricingAdvice()
    if (configResult.status === "rejected") {
      updateStatus(`配置读取失败: ${configResult.reason?.message || "未知错误"}`, "error")
      resultBox.textContent = configResult.reason?.stack || String(configResult.reason || "未知错误")
      return
    }

    if (statusResult.status === "fulfilled") {
      updateStatus(`服务在线: ${statusResult.value.plugin}`, "ok")
      return
    }

    updateStatus(`服务异常: ${statusResult.reason?.message || "无法连接插件服务"}`, "error")
  })
}

async function ensurePageContext(forceRefresh) {
  if (forceRefresh || !currentPageContext) {
    const pageSnapshot = await getCurrentPageSnapshot(forceRefresh)
    currentPageContext = pageSnapshot?.pageContext || unsupportedPageContext("当前标签页未注入插件内容脚本", "")
    renderPageContext(currentPageContext)
  }
  return currentPageContext
}

async function getCurrentPageSnapshot(forceRefresh, options = {}) {
  const tab = await getActiveTab()
  if (!tab) {
    return {
      pageContext: unsupportedPageContext("未找到当前活动标签页", ""),
      candidateRows: []
    }
  }

  try {
    const snapshot = await sendTabMessage(tab.id, {
      type: "GET_PAGE_SNAPSHOT",
      forceRefresh,
      maxPages: Number(options.maxPages) || 1,
      collectAllPages: Boolean(options.collectAllPages),
      targetHotelNames: Array.isArray(options.targetHotelNames) ? options.targetHotelNames : []
    })
    const pageContext = snapshot?.pageContext || snapshot || {}
    return {
      ...snapshot,
      pageContext: {
        ...pageContext,
        tabUrl: tab.url || pageContext.startUrl || "",
        tabTitle: tab.title || pageContext.pageTitle || ""
      },
      candidateRows: Array.isArray(snapshot?.candidateRows) ? snapshot.candidateRows : []
    }
  } catch (error) {
    return {
      pageContext: unsupportedPageContext(error.message, tab.url || "", tab.title || ""),
      candidateRows: []
    }
  }
}

function getManualTargets() {
  return String(targetsInput.value || "")
    .split(/[\n,，、;]/)
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item, index, array) => array.indexOf(item) === index)
    .slice(0, 20)
}

async function saveManualTargets() {
  currentConfig = await sendRuntimeMessage({
    type: "SAVE_CONFIG",
    payload: { manualTargets: getManualTargets().join("\n") }
  })
  applyCurrentConfig(currentConfig)
}

function unsupportedPageContext(message, tabUrl, tabTitle = "") {
  return {
    unsupported: true,
    pageType: "unsupported",
    pageTitle: tabTitle,
    startUrl: tabUrl,
    targetHotelNames: [],
    error: message
  }
}

function fallbackPageContext(pageContext) {
  return pageContext && !pageContext.unsupported
    ? pageContext
    : {
        pageType: "generic",
        cityName: "",
        keyword: "",
        startUrl: pageContext?.startUrl || "",
        targetHotelNames: []
      }
}

function normalizeWorkflowPreview(response) {
  const items = Array.isArray(response?.items) ? response.items : []
  const summary = response?.workflow_summary && typeof response.workflow_summary === "object"
    ? response.workflow_summary
    : {}
  return {
    competitorHotelName: response?.competitor_hotel_name || summary?.competitor_hotel_name || "",
    priceUrl: response?.price_url || "",
    readySubmitCount: Number(response?.ready_submit_count || 0),
    workflowSummary: summary,
    items: items.map((item, index) => {
      const currentPrice = toPositiveNumber(item?.current_price ?? item?.price)
      const suggestedPrice = toPositiveNumber(item?.suggested_price ?? item?.final_price)
      const finalPrice = toPositiveNumber(item?.final_price) ?? suggestedPrice ?? currentPrice
      return {
        id: `${item?.gid || "gid"}-${item?.hid || "hid"}-${index}`,
        displayName: item?.display_name || item?.rate_name || item?.room_name || `房型${index + 1}`,
        roomName: item?.room_name || "",
        rateName: item?.rate_name || item?.display_name || "",
        gid: item?.gid || "",
        hid: item?.hid || "",
        currentPrice,
        suggestedPrice,
        finalPrice,
        changePct: toPositiveNumber(item?.change_pct) || 0,
        riskLevel: item?.risk_level || "L2",
        submitReady: Boolean(item?.submit_ready),
        selected: Boolean(item?.submit_ready)
      }
    })
  }
}

function renderConfig(config) {
  const manualTargets = String(config.manualTargets || "")
    .split(/\n+/)
    .map((item) => item.trim())
    .filter(Boolean)
  const competitorHotels = Array.isArray(config?.competitorHotels) ? config.competitorHotels : []
  const mappingState = getPreferredRoomMappingState(config, currentMerchantMappings)
  configBox.textContent = [
    `服务: ${config.baseUrl}`,
    `登录状态: ${isAuthenticatedConfig(config) ? "已登录" : "未登录"}`,
    `登录账号: ${config?.authUser?.username || "-"}`,
    `当前店铺: ${config?.currentShop?.shop_name || "-"} (${config?.currentShop?.shop_id || config.shopId || "-"})`,
    `tenant/shop: ${config.tenantId}/${config.shopId}`,
    `调试页: ${config.debugUrl}`,
    `分页 / 酒店: ${config.maxPages} / ${config.maxHotels}`,
    `最新价条数: ${config.latestPriceLimit}`,
    `保存结果: ${config.saveResult ? "开启" : "关闭"}`,
    `竞对酒店: ${competitorHotels.length ? `${competitorHotels.length} 家` : "未配置"}`,
    `房型映射: ${mappingState.count ? `${mappingState.count} 条${mappingState.source === "merchant" ? "（后端）" : ""}` : "未维护"}`,
    `维护目标: ${manualTargets.length ? manualTargets.join(" / ") : "未填写"}`
  ].join("\n")
}

function applyCurrentConfig(config) {
  currentConfig = config || currentConfig || {}
  renderAuthState(currentConfig)
  targetsInput.value = String(currentConfig?.manualTargets || "")
  renderConfig(currentConfig)
  renderConfiguredCompetitorHotels(currentConfig)
  renderCompetitorPricingAdvice()
}

function renderAuthState(config) {
  const authenticated = isAuthenticatedConfig(config)
  authBaseUrlInput.value = String(config?.baseUrl || DEFAULT_EXTENSION_CONFIG.baseUrl)
  authTenantInput.value = String(config?.authUser?.tenant_id || config?.tenantId || DEFAULT_EXTENSION_CONFIG.tenantId)
  authUsernameInput.value = authenticated ? String(config?.authUser?.username || "") : String(authUsernameInput.value || "")
  if (authCurrentUserInput) {
    authCurrentUserInput.value = authenticated
      ? `${String(config?.authUser?.username || "")} / tenant ${String(config?.authUser?.tenant_id || "")}`
      : ""
  }

  authLoginForm?.classList.toggle("hidden", authenticated)
  authLoginBtn?.classList.toggle("hidden", authenticated)
  authRefreshBtn?.classList.toggle("hidden", !authenticated)
  authLogoutBtn?.classList.toggle("hidden", !authenticated)
  authSessionBox?.classList.toggle("hidden", !authenticated)
  shopSwitchBox?.classList.toggle("hidden", !authenticated)
  appShell?.classList.toggle("hidden", !authenticated)

  if (!authenticated) {
    authTitle.textContent = "登录后选择店铺，再进入插件工作台。"
    authNote.textContent = "当前版本按账号加载可访问店铺，并按店铺读取竞对配置。"
    authSessionBox.innerHTML = ""
    if (shopSelect) {
      shopSelect.innerHTML = '<option value="">请先登录</option>'
    }
    return
  }

  const currentShop = config?.currentShop || null
  const shops = Array.isArray(config?.shops) ? config.shops : []
  authTitle.textContent = "当前账号已登录，可直接切换店铺。"
  authNote.textContent = "切换店铺后，竞对配置、采集结果和商家动作都会自动跟随当前店铺。"
  authSessionBox.innerHTML = `
    <div><strong>${escapeHtml(config?.authUser?.username || "当前账号")}</strong> 已登录。</div>
    <div class="tip">Tenant ${escapeHtml(String(config?.authUser?.tenant_id || ""))} | 可访问店铺 ${shops.length} 家</div>
  `
  if (shopSelect) {
    shopSelect.innerHTML = shops.length
      ? shops.map((shop) => `<option value="${escapeHtml(String(shop.shop_id || ""))}" ${Number(shop.shop_id || 0) === Number(currentShop?.shop_id || 0) ? "selected" : ""}>${escapeHtml(shop.shop_name || `Shop ${shop.shop_id}`)}</option>`).join("")
      : '<option value="">暂无可访问店铺</option>'
  }
}

async function refreshCurrentConfig() {
  const config = await getEffectiveConfig()
  currentConfig = config
  const nextShopId = isAuthenticatedConfig(config) ? String(resolveActiveShopId(config) || "").trim() : ""
  if (nextShopId !== currentMerchantMappingShopId) {
    currentMerchantMappings = []
    merchantMappingsLoaded = false
    currentMerchantMappingShopId = nextShopId
  }
  applyCurrentConfig(config)
  if (isAuthenticatedConfig(config) && !merchantMappingsLoaded) {
    try {
      const response = await requestMerchantMappingsSummary({ onlyEnabled: false })
      currentMerchantMappings = normalizeMerchantRoomMappings(response?.items)
      merchantMappingsLoaded = true
    } catch (error) {
    }
    applyCurrentConfig(config)
  }
  return config
}

function renderConfiguredCompetitorHotels(config) {
  const hotels = Array.isArray(config?.competitorHotels) ? config.competitorHotels : []
  const mappingState = getPreferredRoomMappingState(config, currentMerchantMappings)
  if (!hotels.length) {
    configuredHotelsBox.innerHTML = '<div class="empty-state">当前还没有维护竞对酒店，请先填写酒店名称或 URL。</div>'
    return
  }

  configuredHotelsBox.innerHTML = `
    <div>已配置 <strong>${hotels.length}</strong> 家竞对酒店</div>
    <div class="tip">当前店铺已维护 <strong>${mappingState.count}</strong> 条${mappingState.sourceLabel}房型映射${mappingState.source === "merchant" ? "，建议价会优先使用后端映射" : ""}</div>
    <div class="tags" style="margin-top: 10px;">
      ${hotels.map((hotel) => `<span class="tag">${escapeHtml(hotel.name || hotel.url || "未命名酒店")}</span>`).join("")}
    </div>
  `
}

function renderCompetitorRoomPrices(response) {
  const hotels = Array.isArray(response?.hotels) ? response.hotels : []
  if (!hotels.length) {
    return '<div class="empty-state">当前没有返回任何竞对酒店房型价。</div>'
  }

  return `
    <div class="summary-box">
      已抓取 ${Number(response?.hotel_count || hotels.length)} 家酒店，返回 ${Number(response?.total_rooms || 0)} 条房型价，写回 ${Number(response?.saved_count || 0)} 条。
    </div>
    <div class="workflow-list" style="margin-top: 12px;">
      ${hotels.map((hotel, index) => renderCompetitorHotelCard(hotel, index)).join("")}
    </div>
  `
}

function formatMerchantSnapshotSource(source, itemCount) {
  const count = Number(itemCount || 0)
  if (source === "manual_room_mappings") {
    return `\u624b\u5de5\u623f\u578b\u4ef7\u683c ${count} \u6761`
  }
  if (source === "merchant_price_snapshot") {
    return `\u6293\u53d6\u623f\u578b\u5feb\u7167 ${count} \u6761`
  }
  return `\u672c\u5e97\u623f\u578b\u6837\u672c ${count} \u6761`
}

function renderCompetitorPricingAdvice() {
  if (!competitorAdviceBox) {
    return
  }
  const hotels = Array.isArray(currentCompetitorRoomPrices?.hotels) ? currentCompetitorRoomPrices.hotels : []
  const mappingState = getPreferredRoomMappingState(currentConfig, currentMerchantMappings)
  const manualRoomMappings = mappingState.items
  if (!hotels.length) {
    competitorAdviceBox.innerHTML = '<div class="empty-state">先抓取上方竞对房型价，再生成建议价。</div>'
    return
  }

  const hotelTags = hotels.slice(0, 6).map((hotel) => `<span class="tag">${escapeHtml(hotel?.hotel_name || "未命名酒店")}</span>`).join("")
  if (!currentCompetitorPricingAdvice) {
    competitorAdviceBox.innerHTML = `
      <div>已缓存 <strong>${Number(currentCompetitorRoomPrices?.hotel_count || hotels.length)}</strong> 家竞对酒店，<strong>${Number(currentCompetitorRoomPrices?.total_rooms || 0)}</strong> 条房型价</div>
      <div class="tip">${manualRoomMappings.length ? `当前店铺已维护 ${manualRoomMappings.length} 条${mappingState.sourceLabel}房型映射，生成建议价时会优先按这些房型输出。` : '当前还没有可用的本店房型映射，生成建议价时将按抓取结果自动匹配。'}</div>
      <div class="tags">${hotelTags}</div>
    `
    return
  }

  const advice = currentCompetitorPricingAdvice
  const summary = advice?.advice_summary || {}
  const competitorContext = advice?.competitor_context || {}
  const merchantHistory = advice?.merchant_history_context || {}
  const merchantSnapshot = advice?.merchant_room_snapshot || {}
  const roomRecommendations = Array.isArray(advice?.room_recommendations) ? advice.room_recommendations : []
  const reasons = Array.isArray(summary?.reasons) ? summary.reasons.filter(Boolean) : []
  const targetName = String(advice?.competitor_hotel_name || competitorAdviceHotelInput?.value || "").trim()
  const sourceLabel = formatMerchantSnapshotSource(merchantSnapshot?.source, merchantSnapshot?.item_count || roomRecommendations.length || 0)
  const roomCards = roomRecommendations.slice(0, 8).map((item) => `
    <div class="workflow-item">
      <div class="workflow-item-name">${escapeHtml(item?.display_name || item?.room_name || item?.rate_name || '未命名房型')}</div>
      <div class="workflow-item-meta">现价 ${formatPrice(item?.current_price)} | 竞对最低 ${formatPrice(item?.competitor_min_price)} | 竞对均价 ${formatPrice(item?.competitor_avg_price)} | 竞对最高 ${formatPrice(item?.competitor_max_price)}</div>
      <div class="workflow-item-meta">建议价 ${formatPrice(item?.suggested_price)} | 调整 ${formatSignedPrice(item?.change_amount)} | 调整比例 ${formatSignedPercent(item?.change_pct)} | 风险 ${escapeHtml(item?.risk_level || '-')}</div>
      <div class="tip">${escapeHtml(item?.reasoning || '-')}</div>
    </div>
  `).join("")

  competitorAdviceBox.innerHTML = `
    <div>
      <strong>${escapeHtml(targetName || '综合竞对酒店')}</strong>
      ${targetName ? ' 的建议价结果' : ' 的建议价结果（按本次抓取汇总）'}
    </div>
    <div class="summary-grid">
      <div class="summary-pill">
        <div class="summary-label">建议房型</div>
        <div class="summary-value">${Number(summary?.recommended_room_count || roomRecommendations.length || 0)}</div>
      </div>
      <div class="summary-pill">
        <div class="summary-label">建议均价</div>
        <div class="summary-value">${formatPrice(summary?.suggested_price)}</div>
      </div>
      <div class="summary-pill">
        <div class="summary-label">竞对均价</div>
        <div class="summary-value">${formatPrice(summary?.competitor_avg_price)}</div>
      </div>
      <div class="summary-pill">
        <div class="summary-label">风险等级</div>
        <div class="summary-value">${escapeHtml(summary?.risk_level || '-')}</div>
      </div>
    </div>
    <div class="tip">竞对样本 ${Number(competitorContext?.price_count || 0)} 条 | ${sourceLabel} | 来源 ${escapeHtml(advice?.recommendation_source || '-')}</div>
    <div class="tip">历史样本 ${Number(merchantHistory?.price_count || 0)} 条 | ${escapeHtml(summary?.reason_summary || '已按当前库存、房型映射和竞对房价生成建议。')}</div>
    ${reasons.length ? `<div class="tags">${reasons.slice(0, 6).map((reason) => `<span class="tag">${escapeHtml(reason)}</span>`).join("")}</div>` : `<div class="tags">${hotelTags}</div>`}
    <div class="workflow-list" style="margin-top: 12px;">
      ${roomCards || '<div class="empty-state">当前没有可展示的房型建议。</div>'}
    </div>
  `
}

function renderCompetitorHotelCard(hotel, index) {
  const rooms = Array.isArray(hotel?.rooms) ? hotel.rooms : []
  const hotelName = hotel?.hotel_name || `竞对酒店 ${index + 1}`
  if (hotel?.error) {
    return `
      <div class="workflow-item">
        <div class="workflow-item-name">${escapeHtml(hotelName)}</div>
        <div class="tip">抓取失败: ${escapeHtml(hotel.error)}</div>
      </div>
    `
  }

  return `
    <div class="workflow-item">
      <div class="workflow-item-name">${escapeHtml(hotelName)}</div>
      <div class="tip">房型价 ${rooms.length} 条 | 采集时间 ${escapeHtml(hotel?.collected_at || "-")}</div>
      <div class="workflow-list" style="margin-top: 10px;">
        ${rooms.length ? rooms.map((room, idx) => renderCompetitorRoomRow(room, idx)).join("") : '<div class="empty-state">未识别到可见房型价。</div>'}
      </div>
    </div>
  `
}

function renderCompetitorRoomRow(room, index) {
  const displayName = room?.rate_name || room?.room_type || `房型 ${index + 1}`
  return `
    <div class="workflow-item">
      <div class="workflow-item-name">${escapeHtml(displayName)}</div>
      <div class="workflow-item-meta">房型: ${escapeHtml(room?.room_type || "-")} | 价型: ${escapeHtml(room?.rate_name || room?.room_type || "-")}</div>
      <div class="workflow-item-meta">早餐: ${escapeHtml(room?.breakfast || "未知")} | 退改: ${escapeHtml(room?.cancelable || "未知")}</div>
      <div class="summary-grid" style="margin-top: 10px;">
        <div class="summary-pill">
          <div class="summary-label">实时价格</div>
          <div class="summary-value">${formatPrice(room?.price)}</div>
        </div>
      </div>
    </div>
  `
}

function renderPageContext(pageContext) {
  if (!pageContext || pageContext.unsupported) {
    pageBox.innerHTML = `
      <div class="meta">
        <div class="row"><span class="label">状态</span><span class="value">未识别到飞猪页面</span></div>
        <div class="row"><span class="label">标签页</span><span class="value">${escapeHtml(pageContext?.pageTitle || "-")}</span></div>
        <div class="row"><span class="label">URL</span><span class="value">${escapeHtml(pageContext?.startUrl || "-")}</span></div>
      </div>
      <div class="tip">${escapeHtml(pageContext?.error || "当前标签页未注入插件内容脚本")}</div>
    `
    return
  }

  const tags = pageContext.targetHotelNames.length
    ? `<div class="tags">${pageContext.targetHotelNames.map((name) => `<span class="tag">${escapeHtml(name)}</span>`).join("")}</div>`
    : '<div class="tip">当前页未识别到明确酒店名，将仅使用当前 URL 作为采集入口。</div>'

  pageBox.innerHTML = `
    <div class="meta">
      <div class="row"><span class="label">页面类型</span><span class="value">${escapeHtml(pageContext.pageType || "-")}</span></div>
      <div class="row"><span class="label">城市</span><span class="value">${escapeHtml(pageContext.cityName || "-")}</span></div>
      <div class="row"><span class="label">日期</span><span class="value">${escapeHtml(pageContext.checkIn || "-")} -> ${escapeHtml(pageContext.checkOut || "-")}</span></div>
      <div class="row"><span class="label">关键词</span><span class="value">${escapeHtml(pageContext.keyword || "-")}</span></div>
      <div class="row"><span class="label">URL</span><span class="value">${escapeHtml(pageContext.startUrl || "-")}</span></div>
    </div>
    ${tags}
  `
}

function renderWorkflowPreview() {
  if (!currentWorkflowPreview || !Array.isArray(currentWorkflowPreview.items) || currentWorkflowPreview.items.length === 0) {
    workflowBox.innerHTML = '<div class="empty-state">先输入竞对酒店名称，再开始分析。</div>'
    return
  }

  const items = currentWorkflowPreview.items
  const submitReadyCount = items.filter((item) => item.submitReady).length
  const selectedCount = items.filter((item) => item.selected && item.submitReady).length
  const allSelected = submitReadyCount > 0 && selectedCount === submitReadyCount
  const summary = currentWorkflowPreview.workflowSummary || {}
  const competitorContext = summary.competitor_context || {}
  const inventorySnapshot = summary.inventory_snapshot || {}
  const merchantHistory = summary.merchant_history_context || {}
  const priceRecommendation = summary.price_recommendation || {}

  workflowBox.innerHTML = `
    <div>
      <strong>${escapeHtml(currentWorkflowPreview.competitorHotelName || "竞对酒店")}</strong> 分析完成。
      已生成 ${items.length} 条房型建议，可提交 ${submitReadyCount} 条，当前选中 ${selectedCount} 条。
    </div>
    <div class="summary-grid">
      <div class="summary-pill">
        <div class="summary-label">竞对中位价</div>
        <div class="summary-value">${formatPrice(competitorContext.price_median)}</div>
      </div>
      <div class="summary-pill">
        <div class="summary-label">竞对均价</div>
        <div class="summary-value">${formatPrice(competitorContext.price_avg)}</div>
      </div>
      <div class="summary-pill">
        <div class="summary-label">库存可售</div>
        <div class="summary-value">${formatInventory(inventorySnapshot)}</div>
      </div>
      <div class="summary-pill">
        <div class="summary-label">建议中位价</div>
        <div class="summary-value">${formatPrice(priceRecommendation.price_mid)}</div>
      </div>
    </div>
    <div class="tip">历史价样本 ${Number(merchantHistory.price_count || 0)} 条，竞对样本 ${Number(competitorContext.price_count || 0)} 条，数据源 ${escapeHtml(competitorContext.data_source || "-")}</div>
    <div class="workflow-tools">
      <button type="button" data-action="toggle-all-workflow" data-checked="${allSelected ? "1" : "0"}">${allSelected ? "取消全选" : "全选可提交项"}</button>
      <button type="button" class="secondary" disabled>${escapeHtml(summary.sample_item || "样本房型")}</button>
      <button type="button" class="secondary" disabled>${escapeHtml(summary.recommendation_source || "fallback")}</button>
    </div>
    <div class="workflow-list">
      ${items.map((item, index) => renderWorkflowItem(item, index)).join("")}
    </div>
  `
}

function renderWorkflowItem(item, index) {
  return `
    <div class="workflow-item">
      <div class="workflow-item-top">
        <input type="checkbox" data-role="workflow-check" data-index="${index}" ${item.selected && item.submitReady ? "checked" : ""} ${item.submitReady ? "" : "disabled"}>
        <div>
          <div class="workflow-item-name">${escapeHtml(item.displayName)}</div>
          <div class="workflow-item-meta">GID/HID: ${escapeHtml(item.gid || "-")} / ${escapeHtml(item.hid || "-")}</div>
          <div class="workflow-item-meta">风险 ${escapeHtml(item.riskLevel)} | 变动 ${item.changePct ? `${item.changePct.toFixed(2)}%` : "-"}${item.submitReady ? "" : " | 未映射不可提交"}</div>
        </div>
      </div>
      <div class="price-grid">
        <div>
          <div class="price-grid-label">现价</div>
          <div>${formatPrice(item.currentPrice)}</div>
        </div>
        <div>
          <div class="price-grid-label">建议价</div>
          <div>${formatPrice(item.suggestedPrice)}</div>
        </div>
        <div>
          <div class="price-grid-label">最终价</div>
          <input type="number" min="1" step="0.01" data-role="workflow-final-price" data-index="${index}" value="${item.finalPrice ?? ""}" ${item.submitReady ? "" : "disabled"}>
        </div>
      </div>
    </div>
  `
}

function syncWorkflowItemsFromDom() {
  if (!currentWorkflowPreview?.items) {
    return
  }
  currentWorkflowPreview.items.forEach((item, index) => {
    const checkedNode = workflowBox.querySelector(`[data-role='workflow-check'][data-index='${index}']`)
    const finalPriceNode = workflowBox.querySelector(`[data-role='workflow-final-price'][data-index='${index}']`)
    item.selected = Boolean(checkedNode?.checked) && item.submitReady
    item.finalPrice = toPositiveNumber(finalPriceNode?.value) ?? item.finalPrice
  })
}

function toggleAllWorkflowItems(nextChecked) {
  if (!currentWorkflowPreview?.items) {
    return
  }
  currentWorkflowPreview.items.forEach((item) => {
    if (item.submitReady) {
      item.selected = nextChecked
    }
  })
}

function applySuggestedPricesToWorkflow() {
  if (!currentWorkflowPreview?.items) {
    return
  }
  syncWorkflowItemsFromDom()
  currentWorkflowPreview.items.forEach((item) => {
    if (item.selected && item.submitReady && item.suggestedPrice) {
      item.finalPrice = item.suggestedPrice
    }
  })
}

function collectConfirmedWorkflowItems() {
  if (!currentWorkflowPreview?.items) {
    return []
  }
  return currentWorkflowPreview.items
    .filter((item) => item.selected && item.submitReady && item.gid && item.hid && item.finalPrice)
    .map((item) => ({
      room_name: item.roomName,
      rate_name: item.rateName,
      display_name: item.displayName,
      current_price: item.currentPrice,
      final_price: item.finalPrice,
      suggested_price: item.suggestedPrice,
      risk_level: item.riskLevel,
      gid: item.gid,
      hid: item.hid,
      comment: "browser_extension_competitor_confirm_submit"
    }))
}

async function submitWorkflowPricing() {
  await withBusy(async () => {
    syncWorkflowItemsFromDom()
    const confirmedItems = collectConfirmedWorkflowItems()
    if (!confirmedItems.length) {
      throw new Error("请先分析并勾选至少一条可提交房型")
    }
    const response = await sendRuntimeMessage({
      type: "MERCHANT_PRICING_SUBMIT_CURRENT",
      payload: {
        priceUrl: workflowPriceUrlInput.value,
        confirmedItems,
        comment: "browser_extension_competitor_confirm_submit"
      }
    })
    updateStatus("已按确认后的最终价提交到 OTA", response.failed_count ? "error" : "ok")
    resultBox.textContent = formatSubmitResult(response)
    currentWorkflowPreview = null
    currentCompetitorRoomPrices = null
    currentCompetitorPricingAdvice = null
    renderWorkflowPreview()
    renderCompetitorPricingAdvice()
  })
}

function formatWorkflowResult(response) {
  const summary = response?.workflow_summary || {}
  const competitorContext = summary.competitor_context || {}
  const priceRecommendation = summary.price_recommendation || {}
  return [
    `竞对酒店: ${response?.competitor_hotel_name || "-"}`,
    `房型数: ${response?.item_count || 0}`,
    `可提交: ${response?.ready_submit_count || 0}`,
    `竞对中位价: ${formatPrice(competitorContext.price_median)}`,
    `建议中位价: ${formatPrice(priceRecommendation.price_mid)}`,
    `数据源: ${competitorContext.data_source || "-"}`
  ].join("\n")
}

function formatCompetitorPricingAdviceResult(response) {
  const summary = response?.advice_summary || {}
  const competitorContext = response?.competitor_context || {}
  const merchantHistory = response?.merchant_history_context || {}
  const merchantSnapshot = response?.merchant_room_snapshot || {}
  const roomRecommendations = Array.isArray(response?.room_recommendations) ? response.room_recommendations : []
  const roomLines = roomRecommendations.slice(0, 12).map((item) => {
    const roomName = item?.display_name || item?.room_name || item?.rate_name || '\u672a\u547d\u540d\u623f\u578b'
    return [
      `${roomName}`,
      `\u5f53\u524d\u4ef7: ${formatPrice(item?.current_price)} | \u7ade\u5bf9\u6700\u4f4e: ${formatPrice(item?.competitor_min_price)} | \u7ade\u5bf9\u5747\u4ef7: ${formatPrice(item?.competitor_avg_price)} | \u7ade\u5bf9\u6700\u9ad8: ${formatPrice(item?.competitor_max_price)}`,
      `\u5efa\u8bae\u4ef7: ${formatPrice(item?.suggested_price)} | \u8c03\u6574: ${formatSignedPrice(item?.change_amount)} | \u8c03\u6574\u6bd4\u4f8b: ${formatSignedPercent(item?.change_pct)} | \u98ce\u9669: ${item?.risk_level || '-'}`,
      `\u8bf4\u660e: ${item?.reasoning || '-'}`,
    ].join("\\n")
  })
  return [
    `\u7ade\u5bf9\u9152\u5e97: ${response?.competitor_hotel_name || '\u7efc\u5408\u7ade\u5bf9\u9152\u5e97'}`,
    `\u623f\u578b\u5efa\u8bae\u6570: ${Number(summary?.recommended_room_count || roomRecommendations.length || 0)}`,
    `\u5efa\u8bae\u5747\u4ef7: ${formatPrice(summary?.suggested_price)}`,
    `\u7ade\u5bf9\u5747\u4ef7: ${formatPrice(summary?.competitor_avg_price)}`,
    `\u7ade\u5bf9\u4e2d\u4f4d\u4ef7: ${formatPrice(summary?.competitor_median_price)}`,
    `\u7ade\u5bf9\u6837\u672c: ${Number(competitorContext?.price_count || 0)}`,
    `\u672c\u5e97\u53c2\u8003\u6837\u672c: ${Number(merchantHistory?.price_count || 0)}`,
    `\u672c\u5e97\u4ef7\u683c\u6765\u6e90: ${formatMerchantSnapshotSource(merchantSnapshot?.source, merchantSnapshot?.item_count || roomRecommendations.length || 0)}`,
    `\u5efa\u8bae\u6765\u6e90: ${response?.recommendation_source || '-'}`,
    `\u6458\u8981: ${summary?.reason_summary || '-'}`,
    roomLines.length ? '' : null,
    ...roomLines,
  ].filter((item) => item !== null).join("\\n")
}
function formatSubmitResult(response) {
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

function updateStatus(message, state) {
  statusText.textContent = message
  statusDot.classList.remove("ok", "error")
  if (state) {
    statusDot.classList.add(state)
  }
}

async function withBusy(task) {
  setBusy(true)
  try {
    await task()
  } catch (error) {
    updateStatus(`请求失败: ${error.message}`, "error")
    resultBox.textContent = error.stack || error.message
  } finally {
    setBusy(false)
  }
}

function setBusy(isBusy) {
  ;[
    authBaseUrlInput,
    authTenantInput,
    authUsernameInput,
    authPasswordInput,
    authLoginBtn,
    authRefreshBtn,
    authLogoutBtn,
    shopSelect,
    targetsInput,
    competitorNameInput,
    workflowPriceUrlInput,
    workflowAnalyzeBtn,
    workflowFillBtn,
    workflowSubmitBtn,
    roomPricesBtn,
    roomSettingsBtn,
    competitorAdviceHotelInput,
    competitorAdviceTotalRoomsInput,
    competitorAdviceAvailableRoomsInput,
    competitorAdviceCurrentPriceInput,
    competitorAdviceStrategySelect,
    competitorAdviceBtn,
    uniformPriceUrlInput,
    uniformTargetPriceInput,
    uniformSubmitBtn,
    refreshBtn,
    statusBtn,
    collectBtn,
    panelBtn,
    optionsBtn,
    ...Array.from(workflowBox.querySelectorAll("button, input")),
    ...Array.from(competitorAdviceBox?.querySelectorAll("button, input, select") || [])
  ].filter(Boolean).forEach((node) => {
    node.disabled = isBusy
  })
}

async function getActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true })
  return tabs[0] || null
}

function withTimeout(promise, timeoutMs, label) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error(`${label}超时`))
    }, timeoutMs)

    promise
      .then((value) => {
        clearTimeout(timer)
        resolve(value)
      })
      .catch((error) => {
        clearTimeout(timer)
        reject(error)
      })
  })
}

function sendRuntimeMessage(message) {
  return withTimeout(new Promise((resolve, reject) => {
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
  }), RUNTIME_TIMEOUT_MS, `扩展消息 ${message?.type || "unknown"}`)
}

function isUnsupportedMessageTypeError(error) {
  return /Unsupported message type/i.test(String(error?.message || error || ""))
}

function normalizeRequestBaseUrl(baseUrl) {
  return String(baseUrl || DEFAULT_EXTENSION_CONFIG.baseUrl).trim().replace(/\/+$/, "")
}


async function requestMerchantMappingsSummary(payload = {}) {
  try {
    return await sendRuntimeMessage({ type: "MERCHANT_MAPPING_LIST", payload })
  } catch (error) {
    if (!isUnsupportedMessageTypeError(error)) {
      throw error
    }
    const config = await getEffectiveConfig()
    const onlyEnabled = payload.onlyEnabled ? "1" : "0"
    const url = `${normalizeRequestBaseUrl(config.baseUrl)}/pricing/merchant-mappings?shop_id=${encodeURIComponent(String(Number(config.shopId) || 0))}&platform=${encodeURIComponent(String(payload.platform || "fliggy"))}&only_enabled=${onlyEnabled}`
    const response = await fetch(url, {
      headers: {
        "X-Tenant-Id": String(config.tenantId),
        "X-Shop-Id": String(config.shopId),
        ...(String(config.authToken || "").trim() ? { Authorization: `Bearer ${String(config.authToken || "").trim()}` } : {})
      }
    })
    const text = await response.text()
    let data = null
    try {
      data = text ? JSON.parse(text) : null
    } catch (parseError) {
      data = null
    }
    if (!response.ok) {
      throw new Error(data?.error || data?.message || text || `HTTP ${response.status}`)
    }
    return data
  }
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
      return await requestCompetitorRoomPricesViaHttp(payload)
    } catch (httpError) {
      throw new Error(httpError instanceof Error ? httpError.message : String(httpError))
    }
  }
  throw lastError || new Error("\u5f53\u524d\u63d2\u4ef6\u7248\u672c\u4e0d\u652f\u6301\u63d2\u4ef6\u5185\u76f4\u6293\u623f\u578b\u4ef7\uff0c\u8bf7\u5237\u65b0\u6269\u5c55\u540e\u91cd\u8bd5")
}


function summarizeCompetitorConfigDebug(response) {
  const counts = response?.counts || {}
  return [
    `local: ${Number(counts.local || 0)} 家`,
    `sync: ${Number(counts.sync || 0)} 家`,
    `merged: ${Number(counts.merged || 0)} 家`,
    `effective: ${Number(counts.effective || 0)} 家`
  ].join(" | ")
}

function sendTabMessage(tabId, message) {
  return withTimeout(new Promise((resolve, reject) => {
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
  }), TAB_TIMEOUT_MS, `页面消息 ${message?.type || "unknown"}`)
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

function formatPrice(value) {
  return value ? `¥${Number(value).toFixed(2)}` : "-"
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

function formatInventory(snapshot) {
  if (!snapshot || typeof snapshot !== "object") {
    return "-"
  }
  const totalRooms = Number(snapshot.total_rooms || 0)
  const availableRooms = Number(snapshot.available_rooms || 0)
  if (!totalRooms) {
    return "-"
  }
  return `${availableRooms}/${totalRooms}`
}

function escapeHtml(value) {
  return resultView?.escapeHtml ? resultView.escapeHtml(value) : String(value || "")
}














