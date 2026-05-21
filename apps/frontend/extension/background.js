const DEFAULT_CONFIG = {
  baseUrl: "http://49.232.42.9",
  tenantId: "1",
  shopId: "1",
  debugUrl: "http://127.0.0.1:9222",
  startUrl: "https://hotel.fliggy.com/",
  latestPriceLimit: 5,
  maxPages: 1,
  maxHotels: 1,
  saveResult: false,
  competitorTrendAutoRefreshEnabled: true,
  competitorTrendAutoRefreshIntervalMinutes: 120,
  competitorTrendScheduleStateByShop: {},
  authToken: "",
  authUser: null,
  currentShop: null,
  shops: [],
  competitorHotelsMigratedShopKeys: [],
  manualRoomMappingsMigratedScopeKeys: [],
  competitorHotelsByScope: {},
  competitorHotels: [],
  merchantPlatformLinks: [],
  manualRoomMappingsByScope: {},
  manualRoomMappingsByShop: {},
  manualRoomMappings: [],
  manualTargets: ""
}

const COMPETITOR_TREND_ALARM_NAME = "competitor-room-price-trend-refresh"
const DEFAULT_COMPETITOR_TREND_INTERVAL_MINUTES = 120
const MAX_PRICE_SNAPSHOT_ITEMS = 300
const OPTIONS_RETURN_TARGET_KEY = "optionsReturnTarget"
const DEFAULT_MERCHANT_PRICE_URL = "https://hotel.fliggy.com/ebooking/hotelBaseInfoUv.htm#/ebk-rp/roomsVsManage"

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

function formatLocalDateTime(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value)
  const pad = (number) => String(number).padStart(2, "0")
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate())
  ].join("-") + " " + [
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds())
  ].join(":")
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
    gid: String(item.gid || "").trim(),
    hid: String(item.hid || "").trim(),
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
    gid: String(item.gid || '').trim() || undefined,
    hid: String(item.hid || '').trim() || undefined,
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

function normalizeTrendScheduleStateByShop(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {}
  }
  const result = {}
  for (const [shopId, item] of Object.entries(value)) {
    const normalizedShopId = String(shopId || "").trim()
    if (!normalizedShopId || !item || typeof item !== "object" || Array.isArray(item)) {
      continue
    }
    result[normalizedShopId] = {
      lastRunAt: String(item.lastRunAt || "").trim(),
      lastStatus: String(item.lastStatus || "").trim(),
      lastError: String(item.lastError || "").trim(),
      lastSavedCount: Number(item.lastSavedCount || 0),
      lastHotelCount: Number(item.lastHotelCount || 0),
      lastTrendPointCount: Number(item.lastTrendPointCount || 0),
      lastCloudCollectedAt: String(item.lastCloudCollectedAt || "").trim(),
      lastTrendSeriesType: String(item.lastTrendSeriesType || "").trim(),
      lastTrigger: String(item.lastTrigger || "").trim(),
      lastPriceSnapshot: normalizeCompetitorPriceSnapshot(item.lastPriceSnapshot),
      lastNotificationKey: String(item.lastNotificationKey || "").trim(),
      lastCloudNotificationKey: String(item.lastCloudNotificationKey || "").trim(),
      lastPriceChangeCount: Number(item.lastPriceChangeCount || 0),
      updatedAt: String(item.updatedAt || "").trim()
    }
  }
  return result
}

function normalizePriceCompareText(value) {
  return String(value || "").replace(/\s+/g, " ").trim()
}

function normalizePriceCompareKey(value) {
  return normalizePriceCompareText(value).toLowerCase()
}

function normalizeCompetitorPriceSnapshot(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {}
  }
  const result = {}
  for (const [rawKey, rawItem] of Object.entries(value)) {
    if (!rawItem || typeof rawItem !== "object" || Array.isArray(rawItem)) {
      continue
    }
    const key = String(rawKey || "").trim()
    const price = coercePositiveNumber(rawItem.price)
    if (!key || price === null) {
      continue
    }
    result[key] = {
      hotelName: normalizePriceCompareText(rawItem.hotelName),
      roomType: normalizePriceCompareText(rawItem.roomType),
      rateName: normalizePriceCompareText(rawItem.rateName),
      price,
    }
    if (Object.keys(result).length >= MAX_PRICE_SNAPSHOT_ITEMS) {
      break
    }
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

function isAuthenticatedConfig(config) {
  return Boolean(config?.authenticated && config?.authUser && config?.currentShop)
}

function getCompetitorTrendSettings(config) {
  return {
    enabled: config?.competitorTrendAutoRefreshEnabled !== false,
    intervalMinutes: coercePositiveInt(
      config?.competitorTrendAutoRefreshIntervalMinutes,
      DEFAULT_COMPETITOR_TREND_INTERVAL_MINUTES,
      DEFAULT_COMPETITOR_TREND_INTERVAL_MINUTES,
      24 * 60
    )
  }
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
    user_id: Number(value.user_id ?? value.userId ?? 0) || 0,
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

function normalizeCompetitorHotelsByScope(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {}
  }
  const result = {}
  for (const [scopeKey, items] of Object.entries(value)) {
    const key = String(scopeKey || "").trim()
    if (!key || !Array.isArray(items)) {
      continue
    }
    result[key] = normalizeCompetitorHotels(items)
  }
  return result
}

function normalizeManualRoomMappingsByScope(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {}
  }
  const result = {}
  for (const [scopeKey, items] of Object.entries(value)) {
    const key = String(scopeKey || "").trim()
    if (!key || !Array.isArray(items)) {
      continue
    }
    result[key] = normalizeManualRoomMappings(items)
  }
  return result
}

function buildConfigScopeKey(config) {
  const authUser = normalizeAuthUser(config?.authUser)
  const tenantId = authUser?.tenant_id || Number(config?.tenantId || 0)
  const shopId = Number(config?.currentShop?.shop_id || config?.shopId || 0)
  const username = String(authUser?.username || "").trim()
  const userPart = authUser?.user_id ? `user:${authUser.user_id}` : (username ? `name:${username}` : "")
  if (!tenantId || !shopId || !userPart) {
    return ""
  }
  return `${tenantId}:${userPart}:${shopId}`
}

function hasOwnKey(value, key) {
  return Boolean(value && Object.prototype.hasOwnProperty.call(value, key))
}

function applyScopedHotelConfig(config) {
  const scopeKey = buildConfigScopeKey(config)
  if (!scopeKey || !String(config?.authToken || "").trim()) {
    return config
  }
  const competitorHotelsByScope = normalizeCompetitorHotelsByScope(config.competitorHotelsByScope)
  const manualRoomMappingsByScope = normalizeManualRoomMappingsByScope(config.manualRoomMappingsByScope)
  const shopId = resolveActiveShopId(config)
  const hasScopedHotels = hasOwnKey(competitorHotelsByScope, scopeKey)
  const hasScopedMappings = hasOwnKey(manualRoomMappingsByScope, scopeKey)
  const scopedMappings = hasScopedMappings ? manualRoomMappingsByScope[scopeKey] : []
  const scopedMappingsByShop = {
    ...normalizeManualRoomMappingsByShop(config.manualRoomMappingsByShop),
    [shopId]: scopedMappings
  }

  return {
    ...config,
    competitorHotelsByScope,
    manualRoomMappingsByScope,
    competitorHotels: hasScopedHotels ? competitorHotelsByScope[scopeKey] : [],
    manualRoomMappingsByShop: scopedMappingsByShop,
    manualRoomMappings: hasScopedMappings ? scopedMappings : []
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

  const localManualMappingMigratedKeys = normalizeMigratedShopKeys(localData.manualRoomMappingsMigratedScopeKeys)
  const syncManualMappingMigratedKeys = normalizeMigratedShopKeys(syncData.manualRoomMappingsMigratedScopeKeys)
  merged.manualRoomMappingsMigratedScopeKeys = localManualMappingMigratedKeys.length
    ? localManualMappingMigratedKeys
    : syncManualMappingMigratedKeys

  const localCompetitorHotelsByScope = normalizeCompetitorHotelsByScope(localData.competitorHotelsByScope)
  const syncCompetitorHotelsByScope = normalizeCompetitorHotelsByScope(syncData.competitorHotelsByScope)
  merged.competitorHotelsByScope = {
    ...syncCompetitorHotelsByScope,
    ...localCompetitorHotelsByScope
  }

  const localManualRoomMappingsByScope = normalizeManualRoomMappingsByScope(localData.manualRoomMappingsByScope)
  const syncManualRoomMappingsByScope = normalizeManualRoomMappingsByScope(syncData.manualRoomMappingsByScope)
  merged.manualRoomMappingsByScope = {
    ...syncManualRoomMappingsByScope,
    ...localManualRoomMappingsByScope
  }

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
  return applyScopedHotelConfig({
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
    competitorTrendAutoRefreshEnabled: stored.competitorTrendAutoRefreshEnabled !== false,
    competitorTrendAutoRefreshIntervalMinutes: coercePositiveInt(
      stored.competitorTrendAutoRefreshIntervalMinutes,
      DEFAULT_COMPETITOR_TREND_INTERVAL_MINUTES,
      DEFAULT_COMPETITOR_TREND_INTERVAL_MINUTES,
      24 * 60
    ),
    competitorTrendScheduleStateByShop: normalizeTrendScheduleStateByShop(stored.competitorTrendScheduleStateByShop),
    authToken: String(stored.authToken || "").trim(),
    authUser: normalizeAuthUser(stored.authUser),
    currentShop: normalizeShopSummary(stored.currentShop),
    shops: normalizeShopSummaries(stored.shops),
    competitorHotelsMigratedShopKeys: normalizeMigratedShopKeys(stored.competitorHotelsMigratedShopKeys),
    manualRoomMappingsMigratedScopeKeys: normalizeMigratedShopKeys(stored.manualRoomMappingsMigratedScopeKeys),
    competitorHotelsByScope: normalizeCompetitorHotelsByScope(stored.competitorHotelsByScope),
    competitorHotels: normalizeCompetitorHotels(stored.competitorHotels),
    merchantPlatformLinks: normalizeMerchantPlatformLinks(stored.merchantPlatformLinks),
    manualRoomMappingsByScope: normalizeManualRoomMappingsByScope(stored.manualRoomMappingsByScope),
    manualRoomMappingsByShop,
    manualRoomMappings: getManualRoomMappingsForShop({
      ...stored,
      manualRoomMappingsByShop
    }, shopId),
    manualTargets: String(stored.manualTargets || DEFAULT_CONFIG.manualTargets)
  })
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
    competitorTrendAutoRefreshEnabled: value.competitorTrendAutoRefreshEnabled !== false,
    competitorTrendAutoRefreshIntervalMinutes: coercePositiveInt(
      value.competitorTrendAutoRefreshIntervalMinutes,
      DEFAULT_COMPETITOR_TREND_INTERVAL_MINUTES,
      DEFAULT_COMPETITOR_TREND_INTERVAL_MINUTES,
      24 * 60
    ),
    competitorTrendScheduleStateByShop: normalizeTrendScheduleStateByShop(value.competitorTrendScheduleStateByShop),
    authToken: String(value.authToken || "").trim(),
    authUser: normalizeAuthUser(value.authUser),
    currentShop: normalizeShopSummary(value.currentShop),
    shops: normalizeShopSummaries(value.shops),
    competitorHotelsMigratedShopKeys: normalizeMigratedShopKeys(value.competitorHotelsMigratedShopKeys),
    manualRoomMappingsMigratedScopeKeys: normalizeMigratedShopKeys(value.manualRoomMappingsMigratedScopeKeys),
    competitorHotelsByScope: normalizeCompetitorHotelsByScope(value.competitorHotelsByScope),
    competitorHotels: normalizeCompetitorHotels(value.competitorHotels),
    merchantPlatformLinks: normalizeMerchantPlatformLinks(value.merchantPlatformLinks),
    manualRoomMappingsByScope: normalizeManualRoomMappingsByScope(value.manualRoomMappingsByScope),
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
  if (Object.prototype.hasOwnProperty.call(payload, "competitorTrendAutoRefreshEnabled")) {
    patch.competitorTrendAutoRefreshEnabled = payload.competitorTrendAutoRefreshEnabled !== false
  }
  if (Object.prototype.hasOwnProperty.call(payload, "competitorTrendAutoRefreshIntervalMinutes")) {
    patch.competitorTrendAutoRefreshIntervalMinutes = coercePositiveInt(
      payload.competitorTrendAutoRefreshIntervalMinutes,
      DEFAULT_COMPETITOR_TREND_INTERVAL_MINUTES,
      DEFAULT_COMPETITOR_TREND_INTERVAL_MINUTES,
      24 * 60
    )
  }
  if (Object.prototype.hasOwnProperty.call(payload, "competitorHotels")) {
    const nextCompetitorHotels = normalizeCompetitorHotels(payload.competitorHotels)
    if (String(storedConfig.authToken || "").trim()) {
      const scopeKey = buildConfigScopeKey(storedConfig)
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
      if (scopeKey) {
        patch.competitorHotelsByScope = {
          ...normalizeCompetitorHotelsByScope(storedConfig.competitorHotelsByScope),
          [scopeKey]: nextCompetitorHotels
        }
      }
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
    const nextConfig = {
      ...storedConfig,
      ...patch
    }
    const shopId = resolveActiveShopId(nextConfig)
    let nextMappings = normalizeManualRoomMappings(payload.manualRoomMappings)
    if (String(storedConfig.authToken || "").trim()) {
      nextMappings = await saveManualRoomMappingsToCloud(nextMappings, nextConfig)
    }
    const scopeKey = buildConfigScopeKey(nextConfig)
    const currentMappingsByShop = normalizeManualRoomMappingsByShop(storedConfig.manualRoomMappingsByShop)
    patch.manualRoomMappingsByShop = {
      ...currentMappingsByShop,
      [shopId]: nextMappings
    }
    if (scopeKey) {
      patch.manualRoomMappingsByScope = {
        ...normalizeManualRoomMappingsByScope(storedConfig.manualRoomMappingsByScope),
        [scopeKey]: nextMappings
      }
    }
    patch.manualRoomMappings = nextMappings
  }

  if (Object.keys(patch).length) {
    patch.configUpdatedAt = Date.now()
    await setStoredConfigPatch(patch)
  }
  await scheduleCompetitorTrendAlarm(await getConfig())
  return getUiConfig()
}

async function scheduleCompetitorTrendAlarm(config) {
  if (!chrome.alarms?.create) {
    return
  }
  const settings = getCompetitorTrendSettings(config)
  if (!settings.enabled) {
    await chrome.alarms.clear(COMPETITOR_TREND_ALARM_NAME).catch(() => {})
    return
  }
  await chrome.alarms.create(COMPETITOR_TREND_ALARM_NAME, {
    delayInMinutes: settings.intervalMinutes,
    periodInMinutes: settings.intervalMinutes
  })
}

async function updateCompetitorTrendScheduleState(config, partialState = {}) {
  const shopId = String(resolveActiveShopId(config) || "").trim()
  if (!shopId) {
    return
  }
  const currentConfig = await getConfig()
  const stateByShop = normalizeTrendScheduleStateByShop(currentConfig.competitorTrendScheduleStateByShop)
  await setStoredConfigPatch({
    competitorTrendScheduleStateByShop: {
      ...stateByShop,
      [shopId]: {
        ...(stateByShop[shopId] || {}),
        ...partialState,
        updatedAt: new Date().toISOString()
      }
    }
  })
}

async function getCompetitorTrendScheduleStatus() {
  const config = await getUiConfig()
  const settings = getCompetitorTrendSettings(config)
  const shopId = String(resolveActiveShopId(config) || "").trim()
  const stateByShop = normalizeTrendScheduleStateByShop(config.competitorTrendScheduleStateByShop)
  const currentState = shopId ? stateByShop[shopId] || null : null
  let alarm = null
  if (chrome.alarms?.get) {
    alarm = await chrome.alarms.get(COMPETITOR_TREND_ALARM_NAME).catch(() => null)
  }
  return {
    shopId: shopId || null,
    enabled: settings.enabled,
    intervalMinutes: settings.intervalMinutes,
    nextRunAt: alarm?.scheduledTime ? new Date(alarm.scheduledTime).toISOString() : null,
    ...(currentState || {})
  }
}

function buildCompetitorPriceSnapshot(crawlResult) {
  const hotels = Array.isArray(crawlResult?.hotels) ? crawlResult.hotels : []
  const snapshot = {}
  for (const hotel of hotels) {
    if (!hotel || typeof hotel !== "object" || Array.isArray(hotel)) {
      continue
    }
    const hotelName = normalizePriceCompareText(hotel.hotel_name || hotel.name)
    const rooms = Array.isArray(hotel.rooms) ? hotel.rooms : []
    for (const room of rooms) {
      if (!room || typeof room !== "object" || Array.isArray(room)) {
        continue
      }
      const price = coercePositiveNumber(room.price)
      if (price === null) {
        continue
      }
      const roomType = normalizePriceCompareText(room.room_type || room.roomName || room.display_name)
      const rateName = normalizePriceCompareText(room.rate_name || room.rateName || roomType)
      if (!hotelName || !roomType) {
        continue
      }
      const key = [
        normalizePriceCompareKey(hotelName),
        normalizePriceCompareKey(roomType),
        normalizePriceCompareKey(rateName || roomType)
      ].join("|")
      snapshot[key] = {
        hotelName,
        roomType,
        rateName,
        price,
      }
      if (Object.keys(snapshot).length >= MAX_PRICE_SNAPSHOT_ITEMS) {
        return snapshot
      }
    }
  }
  return snapshot
}

function buildCompetitorTrendPriceSnapshot(trendSummary) {
  const series = Array.isArray(trendSummary?.series) ? trendSummary.series : []
  const snapshot = {}
  for (const item of series) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      continue
    }
    const hotelName = normalizePriceCompareText(item.hotel_name || item.category_name || "竞对酒店")
    const roomType = normalizePriceCompareText(item.category_name || "酒店最低价")
    const rateName = normalizePriceCompareText(item.category_name || item.hotel_name || roomType)
    const points = Array.isArray(item.points) ? item.points : []
    const latestPoint = points
      .slice()
      .sort((left, right) => String(left?.collected_at || "").localeCompare(String(right?.collected_at || "")))
      .pop()
    const price = coercePositiveNumber(item.latest_min_price ?? latestPoint?.min_price)
    if (!hotelName || !roomType || price === null) {
      continue
    }
    const key = [
      normalizePriceCompareKey(hotelName),
      normalizePriceCompareKey(roomType),
      normalizePriceCompareKey(rateName || roomType)
    ].join("|")
    snapshot[key] = {
      hotelName,
      roomType,
      rateName,
      price,
      collectedAt: String(item.latest_collected_at || latestPoint?.collected_at_end || latestPoint?.collected_at || "").trim()
    }
    if (Object.keys(snapshot).length >= MAX_PRICE_SNAPSHOT_ITEMS) {
      return snapshot
    }
  }
  return snapshot
}

function buildCompetitorPriceChangeSummary(previousSnapshot, nextSnapshot) {
  const previous = normalizeCompetitorPriceSnapshot(previousSnapshot)
  const next = normalizeCompetitorPriceSnapshot(nextSnapshot)
  const changes = []
  for (const [key, nextItem] of Object.entries(next)) {
    const previousItem = previous[key]
    if (!previousItem) {
      continue
    }
    const previousPrice = coercePositiveNumber(previousItem.price)
    const nextPrice = coercePositiveNumber(nextItem.price)
    if (previousPrice === null || nextPrice === null || Math.round(previousPrice * 100) === Math.round(nextPrice * 100)) {
      continue
    }
    changes.push({
      key,
      hotelName: nextItem.hotelName || previousItem.hotelName,
      roomType: nextItem.roomType || previousItem.roomType,
      rateName: nextItem.rateName || previousItem.rateName,
      previousPrice,
      nextPrice,
      changeAmount: Math.round((nextPrice - previousPrice) * 100) / 100,
      changePct: Math.round(((nextPrice - previousPrice) / previousPrice) * 10000) / 100,
    })
  }
  changes.sort((left, right) => Math.abs(right.changePct) - Math.abs(left.changePct))
  return {
    hasBaseline: Object.keys(previous).length > 0,
    snapshotCount: Object.keys(next).length,
    changeCount: changes.length,
    changes,
    notificationKey: changes.map((item) => `${item.key}:${item.previousPrice}->${item.nextPrice}`).join(";"),
  }
}

function formatSignedPriceChange(value) {
  const amount = Number(value || 0)
  const prefix = amount > 0 ? "+" : ""
  return `${prefix}${amount.toFixed(0)}`
}

async function notifyCompetitorPriceChanges({ config, changeSummary, lastNotificationKey }) {
  if (!chrome.notifications?.create || !changeSummary?.changeCount) {
    return false
  }
  if (changeSummary.notificationKey && changeSummary.notificationKey === String(lastNotificationKey || "")) {
    return false
  }
  const topChange = changeSummary.changes[0] || {}
  const title = `竞对价格变化 ${changeSummary.changeCount} 项`
  const message = `${topChange.hotelName || "竞对酒店"} ${topChange.roomType || "房型"}：¥${topChange.previousPrice} -> ¥${topChange.nextPrice}（${formatSignedPriceChange(topChange.changeAmount)}）`
  await chrome.notifications.create(`competitor-price-change-${Date.now()}`, {
    type: "basic",
    iconUrl: chrome.runtime.getURL("notification-icon.svg"),
    title,
    message,
    contextMessage: `店铺 ${resolveActiveShopId(config)} · 每 ${getCompetitorTrendSettings(config).intervalMinutes / 60} 小时自动采集`,
    priority: 1,
  }).catch(() => null)
  return true
}

async function notifyCompetitorCloudTrendRefresh({ config, trendSummary, notificationKey, lastNotificationKey }) {
  if (!chrome.notifications?.create || !notificationKey || notificationKey === String(lastNotificationKey || "")) {
    return false
  }
  const latestTime = String(trendSummary?.latest_collected_at || "").trim()
  if (!latestTime) {
    return false
  }
  await chrome.notifications.create(`competitor-cloud-trend-${Date.now()}`, {
    type: "basic",
    iconUrl: chrome.runtime.getURL("notification-icon.svg"),
    title: "本地竞对采集已同步",
    message: `最新采集 ${latestTime}，记录 ${Number(trendSummary?.point_count || 0)} 个价格点。`,
    contextMessage: `店铺 ${resolveActiveShopId(config)} · 插件每 ${getCompetitorTrendSettings(config).intervalMinutes / 60} 小时本地采集并同步云端`,
    priority: 0,
  }).catch(() => null)
  return true
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
  const tenantId = Number(config?.authUser?.tenant_id || config?.tenantId || 0)
  const shopId = Number(config?.currentShop?.shop_id || config?.shopId || 0)
  if (tenantId !== 1 || shopId !== 1) {
    return Array.isArray(remoteHotels) ? remoteHotels : []
  }
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

function buildManualRoomMappingScopeKey(config) {
  const authUser = normalizeAuthUser(config?.authUser)
  const tenantId = authUser?.tenant_id || Number(config?.tenantId || 0)
  const shopId = Number(config?.currentShop?.shop_id || config?.shopId || 0)
  const userPart = authUser?.user_id
    ? `user:${authUser.user_id}`
    : `name:${String(authUser?.username || "").trim()}`
  if (!tenantId || !shopId || userPart === "name:") {
    return ""
  }
  return `${tenantId}:${userPart}:${shopId}`
}

async function loadManualRoomMappingsFromCloud(config = {}) {
  const shopId = Number(resolveActiveShopId(config) || 0)
  const payload = await requestJson("/plugin/manual-room-mappings", {
    method: "GET",
    query: shopId ? { shop_id: shopId } : undefined
  })
  return normalizeManualRoomMappings(Array.isArray(payload?.items) ? payload.items : [])
}

async function saveManualRoomMappingsToCloud(items, config = {}) {
  const shopId = Number(resolveActiveShopId(config) || 0)
  const payload = await requestJson("/plugin/manual-room-mappings", {
    method: "POST",
    body: {
      shop_id: shopId || undefined,
      items: serializeManualRoomMappingsForApi(normalizeManualRoomMappings(items))
    }
  })
  return normalizeManualRoomMappings(Array.isArray(payload?.items) ? payload.items : [])
}

async function maybeMigrateLegacyManualRoomMappings(config, remoteMappings) {
  const migrationKey = buildManualRoomMappingScopeKey(config)
  const localMappings = getManualRoomMappingsForShop(config)
  const migratedKeys = normalizeMigratedShopKeys(config?.manualRoomMappingsMigratedScopeKeys)
  const tenantId = Number(config?.authUser?.tenant_id || config?.tenantId || 0)
  const shopId = Number(config?.currentShop?.shop_id || config?.shopId || 0)
  if (tenantId !== 1 || shopId !== 1) {
    return Array.isArray(remoteMappings) ? remoteMappings : []
  }
  if (!migrationKey || !localMappings.length || migratedKeys.includes(migrationKey) || Array.isArray(remoteMappings) && remoteMappings.length) {
    return Array.isArray(remoteMappings) ? remoteMappings : []
  }
  const savedMappings = await saveManualRoomMappingsToCloud(localMappings, config)
  await setStoredConfigPatch({
    manualRoomMappingsMigratedScopeKeys: [...migratedKeys, migrationKey],
    configUpdatedAt: Date.now()
  })
  return savedMappings.length ? savedMappings : localMappings
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
    let remoteManualRoomMappings = await loadManualRoomMappingsFromCloud({
      ...localConfig,
      authUser: authState.user,
      currentShop: authState.current_shop,
      shopId: String(authState?.current_shop?.shop_id || localConfig.shopId || DEFAULT_CONFIG.shopId)
    })
    remoteManualRoomMappings = await maybeMigrateLegacyManualRoomMappings({
      ...localConfig,
      authUser: authState.user,
      currentShop: authState.current_shop,
      shopId: String(authState?.current_shop?.shop_id || localConfig.shopId || DEFAULT_CONFIG.shopId)
    }, remoteManualRoomMappings)
    const scopedConfig = {
      ...localConfig,
      authUser: authState.user,
      currentShop: authState.current_shop,
      tenantId: String(authState?.user?.tenant_id || localConfig.tenantId || DEFAULT_CONFIG.tenantId),
      shopId: String(authState?.current_shop?.shop_id || localConfig.shopId || DEFAULT_CONFIG.shopId)
    }
    const scopeKey = buildConfigScopeKey(scopedConfig)
    const manualMappingShopId = String(authState?.current_shop?.shop_id || localConfig.shopId || DEFAULT_CONFIG.shopId)
    const manualRoomMappingsByShop = {
      ...normalizeManualRoomMappingsByShop(localConfig.manualRoomMappingsByShop),
      [manualMappingShopId]: remoteManualRoomMappings
    }
    const patch = {
      authUser: normalizeAuthUser(authState.user),
      currentShop: normalizeShopSummary(authState.current_shop),
      shops: normalizeShopSummaries(authState.shops),
      competitorHotelsByScope: scopeKey ? {
        ...normalizeCompetitorHotelsByScope(localConfig.competitorHotelsByScope),
        [scopeKey]: remoteHotels
      } : normalizeCompetitorHotelsByScope(localConfig.competitorHotelsByScope),
      competitorHotels: remoteHotels,
      manualRoomMappingsByScope: scopeKey ? {
        ...normalizeManualRoomMappingsByScope(localConfig.manualRoomMappingsByScope),
        [scopeKey]: remoteManualRoomMappings
      } : normalizeManualRoomMappingsByScope(localConfig.manualRoomMappingsByScope),
      manualRoomMappingsByShop,
      manualRoomMappings: remoteManualRoomMappings,
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
  await scheduleCompetitorTrendAlarm(await getConfig())
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
  await scheduleCompetitorTrendAlarm(await getConfig())
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
  await scheduleCompetitorTrendAlarm(await getConfig())
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
    price_url: String(payload.priceUrl || "").trim() || DEFAULT_MERCHANT_PRICE_URL,
    headless: payload.headless !== undefined ? Boolean(payload.headless) : true,
    selectors: payload.selectors && typeof payload.selectors === "object" ? payload.selectors : undefined,
    selected_items: Array.isArray(payload.selectedItems) ? payload.selectedItems : [],
    confirmed_items: Array.isArray(payload.confirmedItems) ? payload.confirmedItems : undefined,
    merchant_items: Array.isArray(payload.merchantItems) ? payload.merchantItems : [],
    collect_mode: String(payload.collectMode || "cdp_current_page").trim() || "cdp_current_page",
    debug_url: String(payload.debugUrl || config.debugUrl || "").trim() || undefined,
    comment: String(payload.comment || "").trim()
  }
}

function buildCompetitorWorkflowPayload(config, payload = {}) {
  const competitorHotels = normalizeCompetitorPricingAdviceHotels(
    payload.competitorHotels
      || payload.competitor_hotels
      || payload.roomPrices?.hotels
  )
  const competitorHotelName = String(payload.competitorHotelName || payload.competitor_hotel_name || "").replace(/\s+/g, " ").trim()
  return {
    shop_id: Number(config.shopId),
    competitor_hotel_name: competitorHotelName || undefined,
    price_url: String(payload.priceUrl || "").trim() || DEFAULT_MERCHANT_PRICE_URL,
    headless: payload.headless !== undefined ? Boolean(payload.headless) : true,
    selectors: payload.selectors && typeof payload.selectors === "object" ? payload.selectors : undefined,
    merchant_items: Array.isArray(payload.merchantItems) ? payload.merchantItems : [],
    competitor_hotels: competitorHotels,
    manual_room_mappings: serializeManualRoomMappingsForApi(normalizeManualRoomMappings(
      payload.manualRoomMappings
        || payload.manual_room_mappings
        || config.manualRoomMappings
    )),
    inventory_snapshot: payload.inventorySnapshot && typeof payload.inventorySnapshot === "object"
      ? payload.inventorySnapshot
      : {},
    strategy: String(payload.strategy || "balanced").trim().toLowerCase() || "balanced"
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
    price_url: String(payload.priceUrl || "").trim() || DEFAULT_MERCHANT_PRICE_URL,
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

async function saveCompetitorRoomPricesHistory(payload = {}) {
  const config = await getConfig()
  const hotels = Array.isArray(payload.hotels) ? payload.hotels : []
  return requestJson("/plugin/competitor/room-prices/save", {
    method: "POST",
    body: {
      shop_id: Number(config.shopId),
      hotels
    }
  })
}

async function getCompetitorRoomPriceTrendSummary(payload = {}) {
  const config = await getConfig()
  return requestJson("/plugin/competitor/room-price-trends", {
    method: "GET",
    timeoutMs: 90000,
    query: {
      shop_id: Number(config.shopId),
      days: coercePositiveInt(payload.days, 2, 1, 30),
      point_limit: coercePositiveInt(payload.pointLimit, 120, 1, 240),
      hotel_name: String(payload.hotelName || "").trim() || undefined,
      series_type: String(payload.seriesType || payload.series_type || "room_category").trim() || "room_category",
      include_advice: payload.includeAdvice === false ? "0" : "1"
    }
  })
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
  const localPreview = await collectLocalMerchantPriceItems(payload)
  return requestJson("/plugin/pricing/merchant-preview", {
    method: "POST",
    timeoutMs: MERCHANT_PORTAL_TIMEOUT_MS,
    body: buildMerchantPricingPayload(config, {
      ...payload,
      merchantItems: localPreview.items,
      collectMode: "extension_current_tab"
    })
  })
}

async function listMerchantPricingItems(payload = {}) {
  const config = await getConfig()
  const localPreview = await collectLocalMerchantPriceItems(payload)
  const response = await requestJson("/plugin/pricing/merchant-items", {
    method: "POST",
    timeoutMs: MERCHANT_PORTAL_TIMEOUT_MS,
    body: buildMerchantPricingPayload(config, {
      ...payload,
      merchantItems: localPreview.items,
      collectMode: "extension_current_tab"
    })
  })
  return {
    ...response,
    local_merchant_preview: {
      item_count: Number(localPreview?.item_count || localPreview?.items?.length || 0),
      source: localPreview?.source,
      price_url: localPreview?.price_url || localPreview?.tab_url || "",
      debug: localPreview?.debug || null,
    },
    debug: localPreview?.debug || response?.debug || null,
  }
}

async function submitSuggestedMerchantPricing(payload = {}) {
  return submitCurrentMerchantPricing({
    ...payload,
    comment: payload.comment || "browser_extension_suggested_submit"
  })
}

async function submitCurrentMerchantPricing(payload = {}) {
  const confirmedItems = Array.isArray(payload.confirmedItems) ? payload.confirmedItems : []
  if (!confirmedItems.length) {
    throw new Error("请先生成建议价并确认至少一条可提交房型")
  }
  const tab = await findLocalMerchantPortalTab()
  return sendMessageToTab(tab.id, {
    type: "LOCAL_MERCHANT_PRICE_SUBMIT",
    payload: {
      confirmedItems,
      priceUrl: String(payload.priceUrl || "").trim() || DEFAULT_MERCHANT_PRICE_URL,
      comment: payload.comment || "browser_extension_current_submit"
    }
  })
}

async function previewCompetitorWorkflow(payload = {}) {
  const config = await getConfig()
  const manualRoomMappings = normalizeManualRoomMappings(
    payload.manualRoomMappings
      || payload.manual_room_mappings
      || config.manualRoomMappings
  )
  let localPreview = null
  let localPreviewError = ""
  try {
    localPreview = await collectLocalMerchantPriceItems(payload)
  } catch (error) {
    localPreviewError = error instanceof Error ? error.message : String(error)
    if (!manualRoomMappings.length) {
      throw error
    }
  }
  const mappingMerchantItems = manualRoomMappings.map((item) => ({
    display_name: item.displayName,
    room_name: item.roomType || item.displayName,
    room_type: item.roomType || item.displayName,
    rate_name: item.rateName || "标准价",
    current_price: item.currentPrice,
    price: item.currentPrice,
    gid: item.gid || "",
    hid: item.hid || "",
    source: "manual_room_mapping_current_price"
  }))
  const merchantItems = mappingMerchantItems.length
    ? mappingMerchantItems
    : (Array.isArray(localPreview?.items) && localPreview.items.length ? localPreview.items : [])
  const merchantItemsSource = mappingMerchantItems.length
    ? "manual_room_mapping_current_price"
    : (localPreview?.source || "extension_current_tab")
  let competitorRefresh = null
  let competitorHotels = Array.isArray(payload.competitorHotels) ? payload.competitorHotels : []
  if (!competitorHotels.length && payload.refreshCompetitorPrices !== false) {
    try {
      competitorRefresh = await crawlCompetitorRoomPricesViaTabs({
        hotels: payload.hotels,
        saveResult: true,
        requireSave: false
      })
      competitorHotels = Array.isArray(competitorRefresh?.hotels) ? competitorRefresh.hotels : []
    } catch (error) {
      competitorRefresh = {
        status: "failed",
        error: error instanceof Error ? error.message : String(error)
      }
    }
  }
  const response = await requestJson("/plugin/pricing/competitor-workflow-preview", {
    method: "POST",
    timeoutMs: MERCHANT_PORTAL_TIMEOUT_MS,
    body: buildCompetitorWorkflowPayload(config, {
      ...payload,
      competitorHotels,
      manualRoomMappings,
      merchantItems
    })
  })
  return {
    ...response,
    local_merchant_preview: {
      item_count: Number(localPreview?.item_count || localPreview?.items?.length || merchantItems.length || 0),
      source: merchantItemsSource,
      price_url: localPreview?.price_url || localPreview?.tab_url || ""
    },
    local_merchant_preview_error: localPreviewError,
    competitor_room_price_refresh: competitorRefresh
  }
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
  const targetPrice = coercePositiveNumber(payload.targetPrice)
  if (!targetPrice) {
    throw new Error("目标价格必须大于 0")
  }
  const items = Array.isArray(payload.selectedItems) && payload.selectedItems.length
    ? payload.selectedItems
    : (await listMerchantPricingItems(payload)).items
  const confirmedItems = (Array.isArray(items) ? items : [])
    .filter((item) => Boolean(item?.is_mapped || item?.submit_ready || (item?.gid && item?.hid)))
    .map((item) => ({
      room_name: item.room_name || item.roomName || "",
      rate_name: item.rate_name || item.rateName || item.display_name || item.displayName || "",
      display_name: item.display_name || item.displayName || item.rate_name || item.rateName || item.room_name || item.roomName || "未命名房型",
      current_price: coercePositiveNumber(item.current_price ?? item.currentPrice ?? item.price),
      final_price: targetPrice,
      suggested_price: targetPrice,
      risk_level: "L2",
      gid: String(item.gid || "").trim(),
      hid: String(item.hid || "").trim(),
      comment: payload.comment || "browser_extension_uniform_submit"
    }))
    .filter((item) => item.current_price && item.gid && item.hid)
  if (!confirmedItems.length) {
    throw new Error("没有已映射且可提交的本地房型")
  }
  const tab = await findLocalMerchantPortalTab()
  return sendMessageToTab(tab.id, {
    type: "LOCAL_MERCHANT_PRICE_SUBMIT",
    payload: {
      confirmedItems,
      priceUrl: String(payload.priceUrl || "").trim() || DEFAULT_MERCHANT_PRICE_URL,
      comment: payload.comment || "browser_extension_uniform_submit"
    }
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

function isMerchantPortalTab(tab) {
  const url = String(tab?.url || tab?.pendingUrl || "").toLowerCase()
  return (
    url.includes("ebooking")
    || url.includes("hotelbaseinfouv")
    || url.includes("roomsvsmanage")
    || url.includes("merchant")
  ) && /fliggy\.com|taobao\.com|alitrip\.com/.test(url)
}

async function findLocalMerchantPortalTab() {
  const candidates = []
  const seen = new Set()
  const activeTabs = await chrome.tabs.query({ active: true, currentWindow: true }).catch(() => [])
  const fliggyTabs = await chrome.tabs.query({
    url: [
      "https://*.fliggy.com/*",
      "http://*.fliggy.com/*",
      "https://*.taobao.com/*",
      "https://*.alitrip.com/*"
    ]
  }).catch(() => [])
  for (const tab of [...activeTabs, ...fliggyTabs]) {
    if (!tab?.id || seen.has(tab.id) || !isMerchantPortalTab(tab)) {
      continue
    }
    seen.add(tab.id)
    candidates.push(tab)
  }
  let lastError = "未找到已打开的飞猪商家后台页面"
  for (const tab of candidates) {
    try {
      const probe = await sendMessageToTab(tab.id, { type: "PING_CONTENT_SCRIPT" })
      if (probe?.ready && String(probe.pageType || "") === "merchant_portal") {
        return tab
      }
      lastError = `标签页 ${tab.id} 不是商家后台页面`
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error)
    }
  }
  throw new Error(`${lastError}。请先在当前浏览器登录并打开飞猪商家后台改价页，然后重新操作。`)
}

async function collectLocalMerchantPriceItems(payload = {}) {
  const tab = await findLocalMerchantPortalTab()
  const response = await sendMessageToTab(tab.id, {
    type: "LOCAL_MERCHANT_PRICE_ITEMS",
    payload: {
      priceUrl: String(payload.priceUrl || "").trim() || DEFAULT_MERCHANT_PRICE_URL
    }
  })
  const items = Array.isArray(response?.items) ? response.items : []
  if (!items.length) {
    const debug = response?.debug && typeof response.debug === "object"
      ? ` 检测到价格输入框 ${Number(response.debug.visible_price_inputs || 0)} 个，扫描容器 ${Number(response.debug.inspected_rows || 0)} 个。`
      : ""
    throw new Error(`本地已登录商家后台页面未识别到房型价格，请确认已打开 roomsVsManage 改价页且房型列表已加载。${debug}`)
  }
  return {
    ...response,
    tab_id: tab.id,
    tab_url: tab.url,
    local_takeover: true,
  }
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
  const collectedAt = formatLocalDateTime()

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
        collected_at: String(firstHotel?.collected_at || collectedAt).trim() || collectedAt,
        room_count: rooms.length,
        rooms,
      })
    } catch (error) {
      results.push({
        hotel_name: String(hotel.name || "\u5f53\u524d\u9152\u5e97").trim(),
        hotel_url: String(hotel.url || "").trim(),
        collected_at: collectedAt,
        error: error instanceof Error ? error.message : String(error),
        rooms: [],
      })
    } finally {
      if (tabId) {
        await chrome.tabs.remove(tabId).catch(() => {})
      }
    }
  }

  let savedCount = 0
  const saveEnabled = payload.saveResult !== undefined ? Boolean(payload.saveResult) : Boolean(requestBody.save_result)
  const hasRooms = results.some((item) => Array.isArray(item?.rooms) && item.rooms.length > 0)
  if (saveEnabled && hasRooms) {
    try {
      const saveResult = await saveCompetitorRoomPricesHistory({ hotels: results })
      savedCount = Number(saveResult?.saved_count || 0)
    } catch (error) {
      if (payload.requireSave) {
        throw error
      }
    }
  }

  return {
    shop_id: Number(config.shopId),
    hotel_count: results.length,
    total_rooms: results.reduce((sum, item) => sum + Number(Array.isArray(item?.rooms) ? item.rooms.length : 0), 0),
    saved_count: savedCount,
    hotels: results,
  }
}

async function runScheduledCompetitorTrendRefresh(trigger = "alarm") {
  const config = await getUiConfig()
  const settings = getCompetitorTrendSettings(config)
  if (!settings.enabled) {
    return { skipped: true, reason: "schedule_disabled" }
  }
  if (!isAuthenticatedConfig(config)) {
    await updateCompetitorTrendScheduleState(config, {
      lastRunAt: new Date().toISOString(),
      lastStatus: "skipped",
      lastError: "not_authenticated",
      lastSavedCount: 0,
      lastHotelCount: 0,
      lastTrigger: trigger
    })
    return { skipped: true, reason: "not_authenticated" }
  }
  try {
    const crawlResult = await crawlCompetitorRoomPricesViaTabs({
      saveResult: true,
      requireSave: false
    })
    const shopId = String(resolveActiveShopId(config) || "").trim()
    const stateByShop = normalizeTrendScheduleStateByShop(config.competitorTrendScheduleStateByShop)
    const previousState = shopId ? stateByShop[shopId] || {} : {}
    const previousSnapshot = normalizeCompetitorPriceSnapshot(previousState.lastPriceSnapshot)
    let trendSummary = await getCompetitorRoomPriceTrendSummary({
      days: 2,
      pointLimit: 120,
      seriesType: "room_category",
      includeAdvice: false
    })
    let nextSnapshot = buildCompetitorTrendPriceSnapshot(trendSummary)
    if (!Object.keys(nextSnapshot).length) {
      trendSummary = await getCompetitorRoomPriceTrendSummary({
        days: 2,
        pointLimit: 120,
        seriesType: "hotel_min_price",
        includeAdvice: false
      })
      nextSnapshot = buildCompetitorTrendPriceSnapshot(trendSummary)
    }
    const changeSummary = buildCompetitorPriceChangeSummary(previousSnapshot, nextSnapshot)
    const notified = changeSummary.hasBaseline && changeSummary.changeCount > 0
      ? await notifyCompetitorPriceChanges({
          config,
          changeSummary,
          lastNotificationKey: previousState.lastNotificationKey,
        })
      : false
    const cloudNotificationKey = `cloud:${String(trendSummary?.latest_collected_at || "")}:${Number(trendSummary?.point_count || 0)}`
    const cloudCollectedAt = String(trendSummary?.latest_collected_at || "").trim()
    const hasNewCloudCollection = cloudCollectedAt && cloudCollectedAt !== String(previousState.lastCloudCollectedAt || "").trim()
    const cloudNotified = !notified && changeSummary.hasBaseline && hasNewCloudCollection
      ? await notifyCompetitorCloudTrendRefresh({
          config,
          trendSummary,
          notificationKey: cloudNotificationKey,
          lastNotificationKey: previousState.lastCloudNotificationKey,
        })
      : false
    await updateCompetitorTrendScheduleState(config, {
      lastRunAt: new Date().toISOString(),
      lastStatus: "success",
      lastError: "",
      lastSavedCount: Number(crawlResult?.saved_count || 0),
      lastHotelCount: Number(crawlResult?.hotel_count || 0),
      lastTrendPointCount: Number(trendSummary?.point_count || 0),
      lastCloudCollectedAt: cloudCollectedAt,
      lastTrendSeriesType: String(trendSummary?.series_type || "").trim(),
      lastTrigger: trigger,
      lastPriceSnapshot: nextSnapshot,
      lastPriceChangeCount: changeSummary.hasBaseline ? changeSummary.changeCount : 0,
      lastNotificationKey: notified ? changeSummary.notificationKey : String(previousState.lastNotificationKey || ""),
      lastCloudNotificationKey: cloudNotified ? cloudNotificationKey : String(previousState.lastCloudNotificationKey || "")
    })
    return {
      status: "success",
      source: "local_browser_tabs",
      crawl: crawlResult,
      trend: trendSummary,
      snapshot_count: Object.keys(nextSnapshot).length,
      change_count: changeSummary.changeCount,
    }
  } catch (error) {
    await updateCompetitorTrendScheduleState(config, {
      lastRunAt: new Date().toISOString(),
      lastStatus: "failed",
      lastError: error instanceof Error ? error.message : String(error),
      lastSavedCount: 0,
      lastHotelCount: 0,
      lastTrigger: trigger
    })
    throw error
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
  async COMPETITOR_PRICE_TREND_SUMMARY(message) {
    return {
      trend: await getCompetitorRoomPriceTrendSummary(message.payload || {}),
      schedule: await getCompetitorTrendScheduleStatus()
    }
  },
  async COMPETITOR_SCHEDULE_STATUS() {
    return getCompetitorTrendScheduleStatus()
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
  async OPEN_OPTIONS(message, sender) {
    await recordOptionsReturnTarget(sender)
    await chrome.runtime.openOptionsPage()
    return { opened: true }
  },
  async RETURN_TO_OPTIONS_SOURCE(message, sender) {
    return returnToOptionsSource(sender)
  }
}

chrome.runtime.onInstalled.addListener(async () => {
  const currentConfig = await getStoredConfigRaw()
  if (!currentConfig.baseUrl) {
    await setStoredConfigPatch(DEFAULT_CONFIG)
  }
  await scheduleCompetitorTrendAlarm(await getConfig())
})

chrome.runtime.onStartup?.addListener(() => {
  getConfig()
    .then((config) => scheduleCompetitorTrendAlarm(config))
    .catch(() => {})
})

chrome.alarms?.onAlarm?.addListener((alarm) => {
  if (alarm?.name !== COMPETITOR_TREND_ALARM_NAME) {
    return
  }
  runScheduledCompetitorTrendRefresh("alarm").catch((error) => {
    console.warn("[fliggy-extension] scheduled competitor refresh failed", error)
  })
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
      await recordOptionsReturnTarget({ tab })
      await chrome.runtime.openOptionsPage()
      return { opened: true, mode: "options", tabId, fallback: true, message }
    }
    throw error
  }
}

async function resolveOptionsReturnTarget(sender) {
  const senderTab = sender?.tab
  if (senderTab?.id && !String(senderTab.url || "").startsWith(chrome.runtime.getURL(""))) {
    return {
      tabId: senderTab.id,
      windowId: senderTab.windowId,
      url: senderTab.url || "",
      title: senderTab.title || "",
      recordedAt: Date.now()
    }
  }

  const tabs = await chrome.tabs.query({ active: true, currentWindow: true }).catch(() => [])
  const activeTab = tabs.find((tab) => tab?.id && !String(tab.url || "").startsWith(chrome.runtime.getURL("")))
  if (!activeTab) {
    return null
  }
  return {
    tabId: activeTab.id,
    windowId: activeTab.windowId,
    url: activeTab.url || "",
    title: activeTab.title || "",
    recordedAt: Date.now()
  }
}

async function recordOptionsReturnTarget(sender) {
  const target = await resolveOptionsReturnTarget(sender)
  if (target) {
    await chrome.storage.local.set({ [OPTIONS_RETURN_TARGET_KEY]: target })
  }
  return target
}

async function returnToOptionsSource(sender) {
  const stored = await chrome.storage.local.get(OPTIONS_RETURN_TARGET_KEY).catch(() => ({}))
  const target = stored?.[OPTIONS_RETURN_TARGET_KEY] || null
  const currentTabId = Number(sender?.tab?.id || 0)

  if (target?.tabId) {
    const sourceTab = await chrome.tabs.get(Number(target.tabId)).catch(() => null)
    if (sourceTab?.id) {
      await chrome.tabs.update(sourceTab.id, { active: true })
      if (sourceTab.windowId) {
        await chrome.windows.update(sourceTab.windowId, { focused: true }).catch(() => {})
      }
      if (currentTabId && currentTabId !== sourceTab.id) {
        await chrome.tabs.remove(currentTabId).catch(() => {})
      }
      return { returned: true, mode: "tab", tabId: sourceTab.id }
    }
  }

  const targetUrl = String(target?.url || "").trim()
  if (targetUrl && !targetUrl.startsWith(chrome.runtime.getURL(""))) {
    const createdTab = await chrome.tabs.create({ url: targetUrl, active: true })
    if (currentTabId && createdTab?.id !== currentTabId) {
      await chrome.tabs.remove(currentTabId).catch(() => {})
    }
    return { returned: true, mode: "url", tabId: createdTab?.id || null }
  }

  if (currentTabId) {
    await chrome.tabs.remove(currentTabId).catch(() => {})
    return { returned: true, mode: "close" }
  }

  return { returned: false, mode: "none" }
}

chrome.action.onClicked.addListener((tab) => {
  openAssistantPanelForTab(tab).catch((error) => {
    console.warn("[fliggy-extension] failed to open assistant panel", error)
    recordOptionsReturnTarget({ tab }).catch(() => {})
    chrome.runtime.openOptionsPage().catch(() => {})
  })
})

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const handler = MESSAGE_HANDLERS[message?.type]
  if (!handler) {
    sendResponse({ ok: false, error: `Unsupported message type: ${String(message?.type || "<empty>")}` })
    return false
  }

  handler(message, sender)
    .then((data) => {
      sendResponse({ ok: true, data })
    })
    .catch((error) => {
      sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) })
    })

  return true
})
