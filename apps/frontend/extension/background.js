const DEFAULT_CONFIG = {
  baseUrl: "http://127.0.0.1:8000",
  tenantId: "1",
  shopId: "1",
  debugUrl: "http://127.0.0.1:9222",
  startUrl: "https://hotel.fliggy.com/",
  latestPriceLimit: 5,
  maxPages: 1,
  maxHotels: 1,
  saveResult: false,
  authToken: "",
  authUser: null,
  currentShop: null,
  shops: [],
  competitorHotelsMigratedShopKeys: [],
  competitorHotels: [],
  merchantPlatformLinks: [],
  manualRoomMappingsByShop: {},
  manualRoomMappings: [],
  manualTargets: ""
}

function normalizeBaseUrl(baseUrl) {
  return String(baseUrl || DEFAULT_CONFIG.baseUrl).trim().replace(/\/+$/, "")
}

function coercePositiveInt(value, fallback, minimum, maximum) {
  const next = Number(value)
  if (!Number.isFinite(next)) {
    return fallback
  }
  return Math.min(Math.max(Math.round(next), minimum), maximum)
}

function coercePositiveNumber(value) {
  const next = Number(value)
  if (!Number.isFinite(next) || next <= 0) {
    return null
  }
  return Math.round(next * 100) / 100
}

function normalizeHotelNames(names) {
  if (!Array.isArray(names)) {
    return []
  }

  const seen = new Set()
  const result = []
  for (const rawName of names) {
    const name = String(rawName || "").replace(/\s+/g, " ").trim()
    if (!name || seen.has(name)) {
      continue
    }
    seen.add(name)
    result.push(name)
    if (result.length >= 20) {
      break
    }
  }
  return result
}

function normalizePriceSignals(signals) {
  if (!Array.isArray(signals)) {
    return []
  }
  const result = []
  const seen = new Set()
  for (const signal of signals) {
    const text = String(signal || "").trim()
    if (!text || seen.has(text)) {
      continue
    }
    seen.add(text)
    result.push(text)
    if (result.length >= 10) {
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
  const rateName = String(item.rateName || item.rate_name || "").replace(/\s+/g, " ").trim() || "\u6807\u51c6\u4ef7"
  const currentPrice = coercePositiveNumber(item.currentPrice ?? item.current_price)
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

function serializeManualRoomMappingsForApi(items) {
  if (!Array.isArray(items)) {
    return []
  }
  return items.map((item) => ({
    display_name: String(item.displayName || item.display_name || '').replace(/\s+/g, ' ').trim(),
    room_type: String(item.roomType || item.room_type || '').replace(/\s+/g, ' ').trim(),
    rate_name: String(item.rateName || item.rate_name || '').replace(/\s+/g, ' ').trim() || '???',
    current_price: coercePositiveNumber(item.currentPrice ?? item.current_price),
    competitor_room_names: normalizeManualRoomTerms(item.competitorRoomNames || item.competitor_room_names),
    enabled: item.enabled !== false
  })).filter((item) => item.display_name && item.current_price)
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
  return shopId || DEFAULT_CONFIG.shopId
}

function getManualRoomMappingsForShop(config, explicitShopId = "") {
  const mappingsByShop = normalizeManualRoomMappingsByShop(config?.manualRoomMappingsByShop)
  const shopId = String(explicitShopId || resolveActiveShopId(config) || "").trim()
  if (shopId && Array.isArray(mappingsByShop[shopId]) && mappingsByShop[shopId].length) {
    return mappingsByShop[shopId]
  }
  return normalizeManualRoomMappings(config?.manualRoomMappings)
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

function normalizeAuthUser(value) {
  if (!value || typeof value !== "object") {
    return null
  }
  const tenantId = Number(value.tenant_id ?? value.tenantId ?? 0)
  const username = String(value.username || "").trim()
  if (!tenantId || !username) {
    return null
  }
  return {
    tenant_id: tenantId,
    username,
    is_admin: Boolean(value.is_admin ?? value.isAdmin)
  }
}

function normalizeShopSummary(value) {
  if (!value || typeof value !== "object") {
    return null
  }
  const shopId = Number(value.shop_id ?? value.shopId ?? 0)
  if (!shopId) {
    return null
  }
  return {
    shop_id: shopId,
    shop_name: String(value.shop_name || value.shopName || "").trim() || `Shop ${shopId}`,
    status: String(value.status || "enabled").trim() || "enabled"
  }
}

function normalizeShopSummaries(items) {
  if (!Array.isArray(items)) {
    return []
  }
  const result = []
  const seen = new Set()
  for (const item of items) {
    const normalized = normalizeShopSummary(item)
    if (!normalized) {
      continue
    }
    const key = `${normalized.shop_id}`
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    result.push(normalized)
  }
  return result
}

function normalizeMigratedShopKeys(items) {
  if (!Array.isArray(items)) {
    return []
  }
  const result = []
  const seen = new Set()
  for (const item of items) {
    const value = String(item || "").trim()
    if (!value || seen.has(value)) {
      continue
    }
    seen.add(value)
    result.push(value)
  }
  return result
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

  const localAuthToken = String(localData.authToken || "").trim()
  const syncAuthToken = String(syncData.authToken || "").trim()
  merged.authToken = localAuthToken || syncAuthToken

  const localAuthUser = normalizeAuthUser(localData.authUser)
  const syncAuthUser = normalizeAuthUser(syncData.authUser)
  merged.authUser = localAuthUser || syncAuthUser

  const localCurrentShop = normalizeShopSummary(localData.currentShop)
  const syncCurrentShop = normalizeShopSummary(syncData.currentShop)
  merged.currentShop = localCurrentShop || syncCurrentShop

  const localShops = normalizeShopSummaries(localData.shops)
  const syncShops = normalizeShopSummaries(syncData.shops)
  merged.shops = localShops.length ? localShops : syncShops

  const localMigratedKeys = normalizeMigratedShopKeys(localData.competitorHotelsMigratedShopKeys)
  const syncMigratedKeys = normalizeMigratedShopKeys(syncData.competitorHotelsMigratedShopKeys)
  merged.competitorHotelsMigratedShopKeys = localMigratedKeys.length ? localMigratedKeys : syncMigratedKeys

  return merged
}

async function getStoredConfigRaw() {
  const [localStored, syncStored] = await Promise.all([
    chrome.storage.local.get(null).catch(() => ({})),
    chrome.storage.sync.get(null).catch(() => ({}))
  ])
  return mergeStoredConfigAreas(localStored, syncStored)
}

async function getStoredConfig() {
  const stored = await getStoredConfigRaw()
  return {
    ...DEFAULT_CONFIG,
    ...(stored || {})
  }
}

async function setStoredConfigPatch(patch) {
  if (!patch || typeof patch !== "object" || !Object.keys(patch).length) {
    return
  }
  await chrome.storage.local.set(patch).catch(() => {})
  await chrome.storage.sync.set(patch).catch(async () => {
    await chrome.storage.local.set(patch)
  })
}

function diffStoredConfigPatch(currentConfig, patch) {
  const changed = {}
  for (const [key, value] of Object.entries(patch || {})) {
    const currentValue = currentConfig?.[key]
    if (JSON.stringify(currentValue ?? null) === JSON.stringify(value ?? null)) {
      continue
    }
    changed[key] = value
  }
  return changed
}
async function getConfig() {
  const stored = await getStoredConfig()
  const manualRoomMappingsByShop = normalizeManualRoomMappingsByShop(stored.manualRoomMappingsByShop)
  const shopId = resolveActiveShopId(stored)
  return {
    ...DEFAULT_CONFIG,
    ...stored,
    baseUrl: normalizeBaseUrl(stored.baseUrl),
    tenantId: String(stored.tenantId || DEFAULT_CONFIG.tenantId).trim() || DEFAULT_CONFIG.tenantId,
    shopId: String(stored.shopId || DEFAULT_CONFIG.shopId).trim() || DEFAULT_CONFIG.shopId,
    debugUrl: String(stored.debugUrl || DEFAULT_CONFIG.debugUrl).trim() || DEFAULT_CONFIG.debugUrl,
    startUrl: String(stored.startUrl || DEFAULT_CONFIG.startUrl).trim() || DEFAULT_CONFIG.startUrl,
    latestPriceLimit: coercePositiveInt(stored.latestPriceLimit, DEFAULT_CONFIG.latestPriceLimit, 1, 500),
    maxPages: coercePositiveInt(stored.maxPages, DEFAULT_CONFIG.maxPages, 1, 20),
    maxHotels: coercePositiveInt(stored.maxHotels, DEFAULT_CONFIG.maxHotels, 1, 500),
    saveResult: Boolean(stored.saveResult),
    authToken: String(stored.authToken || "").trim(),
    authUser: normalizeAuthUser(stored.authUser),
    currentShop: normalizeShopSummary(stored.currentShop),
    shops: normalizeShopSummaries(stored.shops),
    competitorHotelsMigratedShopKeys: normalizeMigratedShopKeys(stored.competitorHotelsMigratedShopKeys),
    competitorHotels: normalizeCompetitorHotels(stored.competitorHotels),
    merchantPlatformLinks: normalizeMerchantPlatformLinks(stored.merchantPlatformLinks),
    manualRoomMappingsByShop,
    manualRoomMappings: getManualRoomMappingsForShop({
      ...stored,
      manualRoomMappingsByShop
    }, shopId),
    manualTargets: String(stored.manualTargets || DEFAULT_CONFIG.manualTargets)
  }
}

async function getConfigDebug() {
  const [localStored, syncStored] = await Promise.all([
    chrome.storage.local.get(null).catch(() => ({})),
    chrome.storage.sync.get(null).catch(() => ({}))
  ])
  const mergedStored = mergeStoredConfigAreas(localStored, syncStored)
  const effectiveConfig = await getConfig()
  return {
    local: normalizeDebugConfig(localStored),
    sync: normalizeDebugConfig(syncStored),
    merged: normalizeDebugConfig(mergedStored),
    effective: effectiveConfig,
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

function normalizeDebugConfig(config) {
  const value = config && typeof config === "object" ? config : {}
  return {
    ...value,
    authToken: String(value.authToken || "").trim(),
    authUser: normalizeAuthUser(value.authUser),
    currentShop: normalizeShopSummary(value.currentShop),
    shops: normalizeShopSummaries(value.shops),
    competitorHotelsMigratedShopKeys: normalizeMigratedShopKeys(value.competitorHotelsMigratedShopKeys),
    competitorHotels: normalizeCompetitorHotels(value.competitorHotels),
    merchantPlatformLinks: normalizeMerchantPlatformLinks(value.merchantPlatformLinks),
    manualRoomMappingsByShop: normalizeManualRoomMappingsByShop(value.manualRoomMappingsByShop),
    manualRoomMappings: getManualRoomMappingsForShop(value),
    manualTargets: String(value.manualTargets || "")
  }
}

async function saveConfig(partialConfig) {
  const payload = partialConfig && typeof partialConfig === "object" ? partialConfig : {}
  const patch = {}
  const storedConfig = await getConfig()

  if (Object.prototype.hasOwnProperty.call(payload, "baseUrl")) {
    patch.baseUrl = normalizeBaseUrl(payload.baseUrl)
  }
  if (Object.prototype.hasOwnProperty.call(payload, "tenantId")) {
    patch.tenantId = String(payload.tenantId || "").trim() || DEFAULT_CONFIG.tenantId
  }
  if (Object.prototype.hasOwnProperty.call(payload, "shopId")) {
    patch.shopId = String(payload.shopId || "").trim() || DEFAULT_CONFIG.shopId
  }
  if (Object.prototype.hasOwnProperty.call(payload, "debugUrl")) {
    patch.debugUrl = String(payload.debugUrl || "").trim() || DEFAULT_CONFIG.debugUrl
  }
  if (Object.prototype.hasOwnProperty.call(payload, "startUrl")) {
    patch.startUrl = String(payload.startUrl || "").trim() || DEFAULT_CONFIG.startUrl
  }
  if (Object.prototype.hasOwnProperty.call(payload, "latestPriceLimit")) {
    patch.latestPriceLimit = coercePositiveInt(payload.latestPriceLimit, DEFAULT_CONFIG.latestPriceLimit, 1, 500)
  }
  if (Object.prototype.hasOwnProperty.call(payload, "maxPages")) {
    patch.maxPages = coercePositiveInt(payload.maxPages, DEFAULT_CONFIG.maxPages, 1, 20)
  }
  if (Object.prototype.hasOwnProperty.call(payload, "maxHotels")) {
    patch.maxHotels = coercePositiveInt(payload.maxHotels, DEFAULT_CONFIG.maxHotels, 1, 500)
  }
  if (Object.prototype.hasOwnProperty.call(payload, "saveResult")) {
    patch.saveResult = Boolean(payload.saveResult)
  }
  if (Object.prototype.hasOwnProperty.call(payload, "competitorHotels")) {
    const nextCompetitorHotels = normalizeCompetitorHotels(payload.competitorHotels)
    if (String(storedConfig.authToken || "").trim()) {
      await requestJson("/plugin/competitor/hotels", {
        method: "POST",
        body: {
          items: nextCompetitorHotels.map((item, index) => ({
            hotel_name: item.name,
            hotel_url: item.url,
            enabled: true,
            sort_order: (index + 1) * 10
          }))
        }
      })
      patch.competitorHotels = nextCompetitorHotels
    } else {
      const currentCompetitorHotels = normalizeCompetitorHotels(storedConfig?.competitorHotels)
      if (nextCompetitorHotels.length || payload.clearCompetitorHotels === true || !currentCompetitorHotels.length) {
        patch.competitorHotels = nextCompetitorHotels
      }
    }
  }
  if (Object.prototype.hasOwnProperty.call(payload, "manualTargets")) {
    patch.manualTargets = String(payload.manualTargets || "").trim()
  }
  if (Object.prototype.hasOwnProperty.call(payload, "merchantPlatformLinks")) {
    patch.merchantPlatformLinks = normalizeMerchantPlatformLinks(payload.merchantPlatformLinks)
  }
  if (Object.prototype.hasOwnProperty.call(payload, "manualRoomMappings")) {
    const shopId = resolveActiveShopId({
      ...storedConfig,
      ...patch
    })
    const nextMappings = normalizeManualRoomMappings(payload.manualRoomMappings)
    const currentMappingsByShop = normalizeManualRoomMappingsByShop(storedConfig.manualRoomMappingsByShop)
    patch.manualRoomMappingsByShop = {
      ...currentMappingsByShop,
      [shopId]: nextMappings
    }
    patch.manualRoomMappings = nextMappings
  }

  if (Object.keys(patch).length) {
    patch.configUpdatedAt = Date.now()
    await setStoredConfigPatch(patch)
  }
  return getUiConfig()
}

function buildHeaders(config, extraHeaders = {}) {
  const currentShop = normalizeShopSummary(config.currentShop)
  const authUser = normalizeAuthUser(config.authUser)
  const tenantId = authUser?.tenant_id || Number(config.tenantId || 0)
  const shopId = currentShop?.shop_id || Number(config.shopId || 0)
  return {
    "Content-Type": "application/json",
    ...(tenantId ? { "X-Tenant-Id": String(tenantId) } : {}),
    ...(shopId ? { "X-Shop-Id": String(shopId) } : {}),
    ...(String(config.authToken || "").trim() ? { Authorization: `Bearer ${String(config.authToken || "").trim()}` } : {}),
    ...extraHeaders
  }
}

async function requestJson(path, options = {}) {
  const config = await getConfig()
  const url = new URL(`${config.baseUrl}${path}`)

  if (options.query) {
    Object.entries(options.query).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value))
      }
    })
  }

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), Number(options.timeoutMs) || 30000)

  let response
  try {
    response = await fetch(url.toString(), {
      method: options.method || "GET",
      headers: buildHeaders(config, options.headers),
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal
    })
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(`请求超时: ${path}`)
    }
    throw error
  } finally {
    clearTimeout(timeout)
  }

  const rawText = await response.text()
  let payload = null
  try {
    payload = rawText ? JSON.parse(rawText) : null
  } catch (error) {
    payload = { rawText }
  }

  if (!response.ok) {
    if (response.status === 401 && String(config.authToken || "").trim()) {
      await clearAuthState()
    }
    const message = payload?.message || payload?.detail || payload?.rawText || `HTTP ${response.status}`
    throw new Error(message)
  }

  return payload
}

async function clearAuthState() {
  await setStoredConfigPatch({
    authToken: "",
    authUser: null,
    currentShop: null,
    shops: [],
    configUpdatedAt: Date.now()
  })
}

function buildMigrationShopKey(config) {
  const tenantId = Number(config?.authUser?.tenant_id || config?.tenantId || 0)
  const shopId = Number(config?.currentShop?.shop_id || config?.shopId || 0)
  if (!tenantId || !shopId) {
    return ""
  }
  return `${tenantId}:${shopId}`
}

async function maybeMigrateLegacyCompetitorHotels(config, remoteHotels) {
  const migrationKey = buildMigrationShopKey(config)
  const localHotels = normalizeCompetitorHotels(config?.competitorHotels)
  const migratedKeys = normalizeMigratedShopKeys(config?.competitorHotelsMigratedShopKeys)
  if (!migrationKey || !localHotels.length || migratedKeys.includes(migrationKey) || Array.isArray(remoteHotels) && remoteHotels.length) {
    return Array.isArray(remoteHotels) ? remoteHotels : []
  }
  await requestJson("/plugin/competitor/hotels", {
    method: "POST",
    body: {
      items: localHotels.map((item, index) => ({
        hotel_name: item.name,
        hotel_url: item.url,
        enabled: true,
        sort_order: (index + 1) * 10
      }))
    }
  })
  await setStoredConfigPatch({
    competitorHotelsMigratedShopKeys: [...migratedKeys, migrationKey],
    configUpdatedAt: Date.now()
  })
  return localHotels
}

async function getUiConfig() {
  let localConfig = await getConfig()
  const authToken = String(localConfig.authToken || "").trim()
  if (!authToken) {
    return {
      ...localConfig,
      authenticated: false,
      authUser: null,
      currentShop: null,
      shops: [],
    }
  }

  try {
    const authState = await requestJson("/plugin/auth/me", { method: "GET" })
    if (!authState?.authenticated) {
      await clearAuthState()
      return {
        ...localConfig,
        authenticated: false,
        authUser: null,
        currentShop: null,
        shops: [],
      }
    }
    let remoteHotelsPayload = await requestJson("/plugin/competitor/hotels", { method: "GET" })
    let remoteHotels = normalizeCompetitorHotels(
      Array.isArray(remoteHotelsPayload?.items)
        ? remoteHotelsPayload.items.map((item) => ({
            name: item.hotel_name || item.name,
            url: item.hotel_url || item.url
          }))
        : []
    )
    remoteHotels = await maybeMigrateLegacyCompetitorHotels({
      ...localConfig,
      authUser: authState.user,
      currentShop: authState.current_shop
    }, remoteHotels)
    const patch = {
      authUser: normalizeAuthUser(authState.user),
      currentShop: normalizeShopSummary(authState.current_shop),
      shops: normalizeShopSummaries(authState.shops),
      competitorHotels: remoteHotels,
      tenantId: String(authState?.user?.tenant_id || localConfig.tenantId || DEFAULT_CONFIG.tenantId),
      shopId: String(authState?.current_shop?.shop_id || localConfig.shopId || DEFAULT_CONFIG.shopId)
    }
    const changedPatch = diffStoredConfigPatch(localConfig, patch)
    if (Object.keys(changedPatch).length) {
      await setStoredConfigPatch(changedPatch)
      localConfig = await getConfig()
    }
    return {
      ...localConfig,
      ...patch,
      authenticated: true
    }
  } catch (error) {
    if (/401|login required|invalid plugin token/i.test(String(error?.message || error || ""))) {
      await clearAuthState()
      return {
        ...localConfig,
        authenticated: false,
        authUser: null,
        currentShop: null,
        shops: [],
      }
    }
    throw error
  }
}

async function loginPluginAuth(payload = {}) {
  const stored = await getConfig()
  const baseUrl = normalizeBaseUrl(payload.baseUrl || stored.baseUrl)
  if (baseUrl && baseUrl !== stored.baseUrl) {
    await setStoredConfigPatch({
      baseUrl,
      configUpdatedAt: Date.now()
    })
  }
  const response = await requestJson("/plugin/auth/login", {
    method: "POST",
    headers: {
      "X-Tenant-Id": String(payload.tenantId || payload.tenant_id || ""),
      "X-Shop-Id": "1"
    },
    body: {
      tenant_id: Number(payload.tenantId || payload.tenant_id || 0) || 1,
      username: String(payload.username || "").trim(),
      password: String(payload.password || "").trim()
    }
  })
  await setStoredConfigPatch({
    baseUrl,
    authToken: String(response?.token || "").trim(),
    authUser: normalizeAuthUser(response?.user),
    currentShop: normalizeShopSummary(response?.current_shop),
    shops: normalizeShopSummaries(response?.shops),
    tenantId: String(response?.user?.tenant_id || stored.tenantId || DEFAULT_CONFIG.tenantId),
    shopId: String(response?.current_shop?.shop_id || stored.shopId || DEFAULT_CONFIG.shopId),
    configUpdatedAt: Date.now()
  })
  return getUiConfig()
}

async function logoutPluginAuth() {
  const config = await getConfig()
  if (String(config.authToken || "").trim()) {
    try {
      await requestJson("/plugin/auth/logout", { method: "POST" })
    } catch (error) {
      // Ignore logout transport errors; local logout should still win.
    }
  }
  await clearAuthState()
  return getUiConfig()
}

async function switchPluginShopSelection(payload = {}) {
  const shopId = Number(payload.shopId ?? payload.shop_id ?? 0)
  if (!shopId) {
    throw new Error("请选择店铺")
  }
  await requestJson("/plugin/auth/switch-shop", {
    method: "POST",
    body: { shop_id: shopId }
  })
  await setStoredConfigPatch({
    currentShop: { shop_id: shopId, shop_name: String(payload.shopName || "").trim() || `Shop ${shopId}`, status: "enabled" },
    shopId: String(shopId),
    configUpdatedAt: Date.now()
  })
  return getUiConfig()
}

function normalizePageContext(pageContext) {
  if (!pageContext || typeof pageContext !== "object") {
    return {}
  }
  return {
    startUrl: String(pageContext.startUrl || "").trim(),
    targetPageUrlKeyword: String(pageContext.targetPageUrlKeyword || "").trim(),
    targetHotelNames: normalizeHotelNames(pageContext.targetHotelNames),
    pageType: String(pageContext.pageType || "").trim(),
    cityName: String(pageContext.cityName || "").trim(),
    keyword: String(pageContext.keyword || "").trim(),
    checkIn: String(pageContext.checkIn || "").trim(),
    checkOut: String(pageContext.checkOut || "").trim(),
    pageTitle: String(pageContext.pageTitle || "").trim(),
    sourcePageUrl: String(pageContext.sourcePageUrl || "").trim()
  }
}

function normalizeCandidateRows(rows) {
  if (!Array.isArray(rows)) {
    return []
  }

  const result = []
  const seen = new Set()
  for (const row of rows) {
    if (!row || typeof row !== "object") {
      continue
    }
    const name = String(row.name || "").replace(/\s+/g, " ").trim()
    const text = String(row.text || "").trim()
    const href = String(row.href || "").trim()
    if (!text) {
      continue
    }
    const price = coercePositiveNumber(row.price)
    const priceText = String(row.price_text || "").trim()
    const priceSignals = normalizePriceSignals(row.price_signals)
    const score = coercePositiveInt(row.score, 1, 1, 99)
    const key = `${name}|${href}|${String(price || "")}|${text.slice(0, 120)}`
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    result.push({
      name,
      text,
      href,
      price,
      price_text: priceText,
      price_signals: priceSignals,
      score,
      line_count: coercePositiveInt(row.line_count, 1, 1, 50)
    })
    if (result.length >= 200) {
      break
    }
  }
  return result
}

function normalizePageSnapshot(pageSnapshot, fallbackPageContext) {
  if (!pageSnapshot || typeof pageSnapshot !== "object") {
    const pageContext = normalizePageContext(fallbackPageContext)
    return pageContext.startUrl
      ? {
          page_context: pageContext,
          candidate_rows: [],
          captured_at: ""
        }
      : null
  }

  const pageContext = normalizePageContext(pageSnapshot.pageContext || fallbackPageContext)
  const candidateRows = normalizeCandidateRows(pageSnapshot.candidateRows)
  if (!pageContext.startUrl && candidateRows.length === 0) {
    return null
  }
  return {
    page_context: pageContext,
    candidate_rows: candidateRows,
    captured_at: String(pageSnapshot.capturedAt || "").trim(),
    page_count: coercePositiveInt(pageSnapshot.pageCount, 1, 1, 20),
    page_urls: Array.isArray(pageSnapshot.pageUrls)
      ? pageSnapshot.pageUrls.map((item) => String(item || "").trim()).filter(Boolean).slice(0, 20)
      : []
  }
}

function buildCollectRequest(config, payload = {}) {
  const pageContext = normalizePageContext(payload.pageContext)
  const pageSnapshot = normalizePageSnapshot(payload.pageSnapshot, pageContext)
  const targetHotelNames = normalizeHotelNames(payload.targetHotelNames)
  const maxHotels = coercePositiveInt(
    payload.maxHotels ?? config.maxHotels,
    config.maxHotels,
    1,
    500
  )

  return {
    shop_id: Number(config.shopId),
    start_url: String(payload.startUrl || pageContext.startUrl || config.startUrl).trim(),
    max_pages: coercePositiveInt(payload.maxPages, config.maxPages, 1, 20),
    max_hotels: maxHotels,
    target_hotel_names: targetHotelNames,
    target_page_url_keyword: String(payload.targetPageUrlKeyword || pageContext.targetPageUrlKeyword || "").trim(),
    save_result: Boolean(payload.saveResult ?? config.saveResult),
    collect_mode: "extension_page",
    debug_url: "",
    page_snapshot: pageSnapshot
  }
}

function buildMerchantPricingPayload(config, payload = {}) {
  return {
    shop_id: Number(config.shopId),
    price_url: String(payload.priceUrl || "").trim() || undefined,
    headless: payload.headless !== undefined ? Boolean(payload.headless) : true,
    selectors: payload.selectors && typeof payload.selectors === "object" ? payload.selectors : undefined,
    selected_items: Array.isArray(payload.selectedItems) ? payload.selectedItems : [],
    confirmed_items: Array.isArray(payload.confirmedItems) ? payload.confirmedItems : undefined,
    collect_mode: String(payload.collectMode || "cdp_current_page").trim() || "cdp_current_page",
    debug_url: String(payload.debugUrl || config.debugUrl || "").trim() || undefined,
    comment: String(payload.comment || "").trim()
  }
}

function buildCompetitorWorkflowPayload(config, payload = {}) {
  const competitorHotelName = String(payload.competitorHotelName || payload.competitor_hotel_name || "").replace(/\s+/g, " ").trim()
  return {
    shop_id: Number(config.shopId),
    competitor_hotel_name: competitorHotelName,
    price_url: String(payload.priceUrl || "").trim() || undefined,
    headless: payload.headless !== undefined ? Boolean(payload.headless) : true,
    selectors: payload.selectors && typeof payload.selectors === "object" ? payload.selectors : undefined
  }
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
          const price = coercePositiveNumber(room.price)
          if (!price) {
            return null
          }
          const roomType = String(room.room_type || room.roomType || room.rate_name || room.rateName || "").replace(/\s+/g, " ").trim()
          const rateName = String(room.rate_name || room.rateName || roomType || "").replace(/\s+/g, " ").trim()
          return {
            room_type: roomType || rateName || "未命名房型",
            rate_name: rateName || roomType || "未命名价型",
            price,
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

function buildCompetitorPricingAdvicePayload(config, payload = {}) {
  const inventoryInput = payload.inventorySnapshot && typeof payload.inventorySnapshot === "object"
    ? payload.inventorySnapshot
    : {}
  const totalRooms = coercePositiveInt(payload.totalRooms ?? inventoryInput.total_rooms, 0, 1, 9999)
  if (!totalRooms) {
    throw new Error("请先填写总房量")
  }
  const availableRaw = Number(payload.availableRooms ?? inventoryInput.available_rooms)
  const availableRooms = Number.isFinite(availableRaw) ? Math.round(availableRaw) : 0
  if (availableRooms < 0) {
    throw new Error("可售房量不能小于 0")
  }
  if (availableRooms > totalRooms) {
    throw new Error("可售房量不能大于总房量")
  }
  const currentPrice = coercePositiveNumber(payload.currentPrice ?? inventoryInput.current_price)
  const strategy = String(payload.strategy || "balanced").trim().toLowerCase() || "balanced"
  if (!["conservative", "balanced", "aggressive"].includes(strategy)) {
    throw new Error("策略必须为 conservative、balanced 或 aggressive")
  }
  const competitorHotels = normalizeCompetitorPricingAdviceHotels(
    payload.competitorHotels
      || payload.competitor_hotels
      || payload.roomPrices?.hotels
  )
  if (!competitorHotels.length) {
    throw new Error("请先抓取竞对房型价，再生成建议价")
  }
  const competitorHotelName = String(payload.competitorHotelName || payload.competitor_hotel_name || "").replace(/\s+/g, " ").trim()
  const manualRoomMappings = normalizeManualRoomMappings(
    payload.manualRoomMappings
      || payload.manual_room_mappings
      || config.manualRoomMappings
  )
  return {
    shop_id: Number(config.shopId),
    inventory_snapshot: {
      total_rooms: totalRooms,
      available_rooms: availableRooms,
      ...(currentPrice ? { current_price: currentPrice } : {})
    },
    competitor_hotels: competitorHotels,
    manual_room_mappings: serializeManualRoomMappingsForApi(manualRoomMappings),
    competitor_hotel_name: competitorHotelName || undefined,
    strategy
  }
}
function buildUniformSubmitPayload(config, payload = {}) {
  return {
    shop_id: Number(config.shopId),
    target_price: coercePositiveNumber(payload.targetPrice),
    price_url: String(payload.priceUrl || "").trim() || undefined,
    headless: payload.headless !== undefined ? Boolean(payload.headless) : true,
    selectors: payload.selectors && typeof payload.selectors === "object" ? payload.selectors : undefined,
    selected_items: Array.isArray(payload.selectedItems) ? payload.selectedItems : [],
    comment: String(payload.comment || "").trim()
  }
}

function buildCompetitorRoomPricesPayload(config, payload = {}) {
  const hotels = normalizeCompetitorHotels(payload.hotels || config.competitorHotels)
  if (!hotels.length) {
    throw new Error("请先在设置页配置至少一条竞对酒店详情页")
  }
  return {
    shop_id: Number(config.shopId),
    hotels,
    headless: payload.headless !== undefined ? Boolean(payload.headless) : true,
    save_result: payload.saveResult !== undefined ? Boolean(payload.saveResult) : Boolean(config.saveResult),
    debug_url: String(config.debugUrl || "")
  }
}

async function runCollect(payload = {}) {
  const config = await getConfig()
  return requestJson("/plugin/fliggy/collect", {
    method: "POST",
    body: buildCollectRequest(config, payload)
  })
}

async function getLatestPrices(payload = {}) {
  const config = await getConfig()
  const pageContext = normalizePageContext(payload.pageContext)
  return requestJson("/plugin/competitor/latest-prices", {
    method: "POST",
    body: {
      shop_id: Number(config.shopId),
      start_url: String(payload.startUrl || pageContext.startUrl || config.startUrl).trim(),
      max_pages: coercePositiveInt(payload.maxPages, 1, 1, 20),
      max_hotels: coercePositiveInt(payload.maxHotels ?? payload.limit, config.latestPriceLimit, 1, 500),
      target_hotel_names: normalizeHotelNames(payload.targetHotelNames || pageContext.targetHotelNames),
      headless: payload.headless !== undefined ? Boolean(payload.headless) : true,
      save_result: payload.saveResult !== undefined ? Boolean(payload.saveResult) : true,
      collect_mode: String(payload.collectMode || "cdp_current_page").trim() || "cdp_current_page",
      debug_url: String(payload.debugUrl || config.debugUrl).trim() || config.debugUrl,
      target_page_url_keyword: String(payload.targetPageUrlKeyword || pageContext.targetPageUrlKeyword || "").trim()
    }
  })
}

const MERCHANT_PORTAL_TIMEOUT_MS = 300000

async function previewMerchantPricing(payload = {}) {
  const config = await getConfig()
  return requestJson("/plugin/pricing/merchant-preview", {
    method: "POST",
    timeoutMs: MERCHANT_PORTAL_TIMEOUT_MS,
    body: buildMerchantPricingPayload(config, payload)
  })
}

async function listMerchantPricingItems(payload = {}) {
  const config = await getConfig()
  return requestJson("/plugin/pricing/merchant-items", {
    method: "POST",
    timeoutMs: MERCHANT_PORTAL_TIMEOUT_MS,
    body: buildMerchantPricingPayload(config, payload)
  })
}

async function submitSuggestedMerchantPricing(payload = {}) {
  const config = await getConfig()
  return requestJson("/plugin/pricing/merchant-direct-submit", {
    method: "POST",
    timeoutMs: MERCHANT_PORTAL_TIMEOUT_MS,
    body: buildMerchantPricingPayload(config, {
      ...payload,
      comment: payload.comment || "browser_extension_suggested_submit"
    })
  })
}

async function submitCurrentMerchantPricing(payload = {}) {
  const config = await getConfig()
  return requestJson("/plugin/pricing/merchant-direct-submit", {
    method: "POST",
    timeoutMs: MERCHANT_PORTAL_TIMEOUT_MS,
    body: buildMerchantPricingPayload(config, {
      ...payload,
      comment: payload.comment || "browser_extension_current_submit"
    })
  })
}

async function previewCompetitorWorkflow(payload = {}) {
  const config = await getConfig()
  return requestJson("/plugin/pricing/competitor-workflow-preview", {
    method: "POST",
    body: buildCompetitorWorkflowPayload(config, payload)
  })
}

async function previewCompetitorPricingAdvice(payload = {}) {
  const config = await getConfig()
  return requestJson("/plugin/pricing/competitor-advice-preview", {
    method: "POST",
    timeoutMs: 90000,
    body: buildCompetitorPricingAdvicePayload(config, payload)
  })
}

async function crawlCompetitorRoomPrices(payload = {}) {
  return crawlCompetitorRoomPricesViaTabs(payload)
}

async function crawlCompetitorRoomPricesWithHotels(payload = {}) {
  return crawlCompetitorRoomPricesViaTabs(payload)
}

async function submitUniformMerchantPricing(payload = {}) {
  const config = await getConfig()
  const requestBody = buildUniformSubmitPayload(config, {
    ...payload,
    comment: payload.comment || "browser_extension_uniform_submit"
  })
  if (!requestBody.target_price) {
    throw new Error("目标价格必须大于 0")
  }
  return requestJson("/plugin/pricing/uniform-direct-submit", {
    method: "POST",
    timeoutMs: MERCHANT_PORTAL_TIMEOUT_MS,
    body: requestBody
  })
}

async function getMerchantCredentialSummary() {
  const config = await getUiConfig()
  return requestJson("/merchant/credentials", {
    method: "GET",
    query: {
      shop_id: Number(config.shopId)
    }
  })
}

async function saveMerchantCredentialSummary(payload = {}) {
  const config = await getUiConfig()
  const selectors = payload.selectors && typeof payload.selectors === "object" ? payload.selectors : undefined
  const body = {
    shop_id: Number(config.shopId),
    username: String(payload.username || "").trim(),
    password: String(payload.password || "").trim(),
    login_url: String(payload.loginUrl || payload.login_url || "").trim() || undefined,
    price_url: String(payload.priceUrl || payload.price_url || "").trim() || undefined,
    storage_state_name: String(payload.storageStateName || payload.storage_state_name || "").trim(),
    selectors,
  }
  const saved = await requestJson("/merchant/credentials", {
    method: "POST",
    body
  })
  if (!(payload.autoLoginAfterSave || payload.auto_login_after_save)) {
    return { saved, login: null }
  }
  const login = await requestJson("/merchant/fliggy/session/login", {
    method: "POST",
    timeoutMs: MERCHANT_PORTAL_TIMEOUT_MS,
    body: {
      shop_id: Number(config.shopId),
      username: body.username,
      password: body.password,
      login_url: body.login_url,
      storage_state_name: body.storage_state_name,
      headless: payload.loginHeadless !== undefined ? Boolean(payload.loginHeadless) : Boolean(payload.login_headless),
      selectors,
    }
  })
  return { saved, login }
}

async function listMerchantMappingsSummary(payload = {}) {
  const config = await getUiConfig()
  return requestJson("/pricing/merchant-mappings", {
    method: "GET",
    query: {
      shop_id: Number(config.shopId),
      platform: String(payload.platform || "fliggy"),
      only_enabled: payload.onlyEnabled ? "1" : "0"
    }
  })
}

async function saveMerchantMappingSummary(payload = {}) {
  const config = await getUiConfig()
  return requestJson("/pricing/merchant-mappings", {
    method: "POST",
    body: {
      shop_id: Number(config.shopId),
      platform: String(payload.platform || "fliggy"),
      room_name: String(payload.roomName || payload.room_name || "").trim(),
      rate_name: String(payload.rateName || payload.rate_name || "").trim(),
      merchant_room_key: String(payload.merchantRoomKey || payload.merchant_room_key || "").trim(),
      merchant_rate_key: String(payload.merchantRateKey || payload.merchant_rate_key || "").trim(),
      gid: String(payload.gid || "").trim(),
      hid: String(payload.hid || "").trim(),
      status: String(payload.status || "draft").trim() || "draft",
      notes: String(payload.notes || "").trim(),
      last_seen_price: coercePositiveNumber(payload.lastSeenPrice ?? payload.last_seen_price),
    }
  })
}

async function refreshMerchantMappingsSummary(payload = {}) {
  const config = await getUiConfig()
  const selectors = payload.selectors && typeof payload.selectors === "object" ? payload.selectors : undefined
  return requestJson("/pricing/merchant-mappings/refresh-prices", {
    method: "POST",
    body: {
      shop_id: Number(config.shopId),
      price_url: String(payload.priceUrl || payload.price_url || "").trim() || undefined,
      headless: payload.headless !== undefined ? Boolean(payload.headless) : true,
      selectors,
      selected_items: []
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
  let lastError = "详情页接收端未就绪"

  while (Date.now() < deadline) {
    const currentTab = await chrome.tabs.get(tabId).catch(() => null)
    if (!currentTab) {
      throw new Error(`酒店详情页标签已关闭: ${tabId}`)
    }
    if (currentTab.status !== "complete" && !isHotelDetailTab(currentTab)) {
      await delay(500)
      continue
    }

    try {
      const probe = await sendMessageToTab(tabId, { type: "PING_CONTENT_SCRIPT" })
      if (probe?.ready) {
        return probe
      }
      lastError = "详情页接收端返回未就绪"
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error)
    }

    await delay(500)
  }

  throw new Error(`等待酒店详情页接收端超时: ${lastError}`)
}

async function crawlCompetitorRoomPricesViaTabs(payload = {}) {
  const config = await getUiConfig()
  const requestBody = buildCompetitorRoomPricesPayload(config, payload)
  const results = []

  for (const hotel of requestBody.hotels) {
    let tabId = null
    try {
      const tab = await chrome.tabs.create({ url: hotel.url, active: false })
      tabId = tab?.id || null
      if (!tabId) {
        throw new Error("\u6253\u5f00\u9152\u5e97\u8be6\u60c5\u9875\u5931\u8d25")
      }
      await waitForTabComplete(tabId, 30000)
      await waitForHotelDetailReceiver(tabId, 20000)
      const pageResult = await sendMessageToTab(tabId, { type: "GET_CURRENT_HOTEL_ROOM_PRICES" })
      const firstHotel = Array.isArray(pageResult?.hotels) ? pageResult.hotels[0] : null
      const rooms = Array.isArray(firstHotel?.rooms) ? firstHotel.rooms : []
      results.push({
        hotel_name: String(hotel.name || firstHotel?.hotel_name || "\u5f53\u524d\u9152\u5e97").trim(),
        hotel_url: String(hotel.url || firstHotel?.hotel_url || "").trim(),
        room_count: rooms.length,
        rooms,
      })
    } catch (error) {
      results.push({
        hotel_name: String(hotel.name || "\u5f53\u524d\u9152\u5e97").trim(),
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
    shop_id: Number(config.shopId),
    hotel_count: results.length,
    total_rooms: results.reduce((sum, item) => sum + Number(Array.isArray(item?.rooms) ? item.rooms.length : 0), 0),
    saved_count: 0,
    hotels: results,
  }
}

const MESSAGE_HANDLERS = {
  async GET_CONFIG() {
    return getUiConfig()
  },
  async GET_CONFIG_DEBUG() {
    return getConfigDebug()
  },
  async GET_AUTH_STATE() {
    return getUiConfig()
  },
  async AUTH_LOGIN(message) {
    return loginPluginAuth(message.payload || {})
  },
  async AUTH_LOGOUT() {
    return logoutPluginAuth()
  },
  async AUTH_SWITCH_SHOP(message) {
    return switchPluginShopSelection(message.payload || {})
  },
  async SAVE_CONFIG(message) {
    return saveConfig(message.payload || {})
  },
  async SERVICE_STATUS() {
    return requestJson("/plugin/service-status")
  },
  async LATEST_PRICES(message) {
    return getLatestPrices(message.payload || {})
  },
  async RUN_COLLECT(message) {
    return runCollect(message.payload || {})
  },
  async MERCHANT_PRICING_PREVIEW(message) {
    return previewMerchantPricing(message.payload || {})
  },
  async MERCHANT_PRICING_ITEMS(message) {
    return listMerchantPricingItems(message.payload || {})
  },
  async MERCHANT_PRICING_SUBMIT_SUGGESTED(message) {
    return submitSuggestedMerchantPricing(message.payload || {})
  },
  async MERCHANT_PRICING_SUBMIT_CURRENT(message) {
    return submitCurrentMerchantPricing(message.payload || {})
  },
  async COMPETITOR_WORKFLOW_PREVIEW(message) {
    return previewCompetitorWorkflow(message.payload || {})
  },
  async COMPETITOR_PRICING_ADVICE_PREVIEW(message) {
    return previewCompetitorPricingAdvice(message.payload || {})
  },
  async COMPETITOR_ROOM_PRICES(message) {
    return crawlCompetitorRoomPrices(message.payload || {})
  },
  async COMPETITOR_ROOM_PRICES_HTTP(message) {
    return crawlCompetitorRoomPricesWithHotels(message.payload || {})
  },
  async COMPETITOR_ROOM_PRICES_TABS(message) {
    return crawlCompetitorRoomPricesViaTabs(message.payload || {})
  },
  async COMPETITOR_ROOM_PRICES_WITH_HOTELS(message) {
    return crawlCompetitorRoomPricesWithHotels(message.payload || {})
  },
  async MERCHANT_UNIFORM_PRICE_SUBMIT(message) {
    return submitUniformMerchantPricing(message.payload || {})
  },
  async MERCHANT_CREDENTIAL_GET() {
    return getMerchantCredentialSummary()
  },
  async MERCHANT_CREDENTIAL_SAVE(message) {
    return saveMerchantCredentialSummary(message.payload || {})
  },
  async MERCHANT_MAPPING_LIST(message) {
    return listMerchantMappingsSummary(message?.payload || {})
  },
  async MERCHANT_MAPPING_SAVE(message) {
    return saveMerchantMappingSummary(message.payload || {})
  },
  async MERCHANT_MAPPING_REFRESH(message) {
    return refreshMerchantMappingsSummary(message.payload || {})
  },
  async OPEN_OPTIONS() {
    await chrome.runtime.openOptionsPage()
    return { opened: true }
  }
}

chrome.runtime.onInstalled.addListener(async () => {
  const currentConfig = await getStoredConfigRaw()
  if (!currentConfig.baseUrl) {
    await setStoredConfigPatch(DEFAULT_CONFIG)
  }
})

async function openAssistantPanelForTab(tab) {
  const tabId = Number(tab?.id || 0)
  if (!tabId) {
    throw new Error("??????????")
  }

  try {
    await sendMessageToTab(tabId, { type: "OPEN_PANEL" })
    return { opened: true, mode: "panel", tabId }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (/Receiving end does not exist|Could not establish connection|The message port closed before a response was received/i.test(message)) {
      await chrome.runtime.openOptionsPage()
      return { opened: true, mode: "options", tabId, fallback: true, message }
    }
    throw error
  }
}

chrome.action.onClicked.addListener((tab) => {
  openAssistantPanelForTab(tab).catch((error) => {
    console.warn("[fliggy-extension] failed to open assistant panel", error)
    chrome.runtime.openOptionsPage().catch(() => {})
  })
})

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const handler = MESSAGE_HANDLERS[message?.type]
  if (!handler) {
    sendResponse({ ok: false, error: `Unsupported message type: ${String(message?.type || "<empty>")}` })
    return false
  }

  handler(message)
    .then((data) => {
      sendResponse({ ok: true, data })
    })
    .catch((error) => {
      sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) })
    })

  return true
})















