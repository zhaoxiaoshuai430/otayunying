const ROOT_ID = "fliggy-ops-extension-root"

const CLOUD_ASSISTANT_ORIGIN = "http://api.aihuawise.com"
const CLOUD_ASSISTANT_URL = `${CLOUD_ASSISTANT_ORIGIN}/ops-assistant`
const CLOUD_PROTOCOL_VERSION = "fliggy-ops-cloud-ui/v1"
const CLOUD_REQUEST_TYPE = "FLIGGY_OPS_CLOUD_REQUEST"
const CLOUD_RESPONSE_TYPE = "FLIGGY_OPS_CLOUD_RESPONSE"
const CLOUD_EVENT_TYPE = "FLIGGY_OPS_CLOUD_EVENT"
const CLOUD_BRIDGE_TIMEOUT_MS = 300000
const DEFAULT_MERCHANT_PRICE_URL = "https://hotel.fliggy.com/ebooking/hotelBaseInfoUv.htm#/ebk-rp/roomsVsManage"

let panelApi = null

const DEFAULT_EXTENSION_CONFIG = {
  baseUrl: "http://49.232.42.9",
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

const LOCAL_MERCHANT_ROW_SELECTORS = [
  ".rate-plan-item",
  "table tbody tr",
  "tr",
  "[role='row']",
  ".room-row",
  ".rate-plan-row",
  ".price-row",
  "[class*='room']",
  "[class*='rate']",
  "[class*='price']",
  "[class*='Room']",
  "[class*='Rate']",
  "[class*='Price']"
]

const LOCAL_MERCHANT_PRICE_INPUT_SELECTORS = [
  "input[type='number']",
  "input[inputmode='decimal']",
  "input[name*='price' i]",
  "input[id*='price' i]",
  "input[class*='price' i]",
  "input[placeholder*='价']",
  "input[placeholder*='房价']",
  "input[placeholder*='价格']",
  "input[aria-label*='价']",
  "input[placeholder*='售卖']",
  "input[placeholder*='金额']",
  "input[placeholder*='请输入']",
  ".ant-input-number-input",
  ".el-input__inner",
  ".aui-input__inner",
  "input[type='text']"
]

const LOCAL_MERCHANT_CONTAINER_HINT_PATTERN = /房型|房价|价格|售价|卖价|标准价|早餐|取消|库存|可售|间|GID|HID/i

const LOCAL_MERCHANT_EDIT_SELECTORS = [
  "button",
  "[role='button']",
  "a"
]

const LOCAL_MERCHANT_SAVE_SELECTORS = [
  "button:has-text('确认修改')",
  "button:has-text('确认提交')",
  "button:has-text('保存设置')",
  "button:has-text('保存全部')",
  "button:has-text('保存')",
  "button:has-text('确定')",
  "button:has-text('确认')",
  "button:has-text('提交')",
  "button:has-text('立即生效')",
  "button",
  "[role='button']",
  ".ant-btn-primary",
  ".el-button--primary",
  ".aui-button--primary"
]

const LOCAL_MERCHANT_CONFIRM_SELECTORS = [
  ".ant-modal-confirm button.ant-btn-primary",
  ".ant-modal button.ant-btn-primary",
  ".el-message-box button.el-button--primary",
  ".aui-dialog button.aui-button--primary",
  ".aui-grid-modal__wrapper.active button.aui-button--primary",
  "button:has-text('确认提交')",
  "button:has-text('确认修改')",
  "button:has-text('确定')",
  "button",
  "[role='button']"
]

function cleanLocalMerchantText(value) {
  return String(value || "").replace(/\s+/g, " ").trim()
}

function normalizeLocalMerchantText(value) {
  return cleanLocalMerchantText(value).toLowerCase()
}

function queryLocalMerchantElements(root, selectors, limit = 120) {
  const result = []
  const seen = new Set()
  for (const selector of selectors) {
    try {
      const nodes = Array.from(root.querySelectorAll(selector)).slice(0, limit)
      for (const node of nodes) {
        if (!node || seen.has(node)) {
          continue
        }
        seen.add(node)
        result.push(node)
        if (result.length >= limit) {
          return result
        }
      }
    } catch (error) {
      continue
    }
  }
  return result
}

function extractLocalMerchantPriceFromText(text) {
  const normalized = cleanLocalMerchantText(text)
  if (!normalized) {
    return null
  }
  const candidates = []
  const pricePatterns = [
    /(?:¥|￥|CNY|价格|房价|现价|卖价|到手价)\s*[:：]?\s*(\d{2,5}(?:\.\d{1,2})?)/gi,
    /(\d{2,5}(?:\.\d{1,2})?)\s*(?:元|\/晚|起)?/g
  ]
  for (const pattern of pricePatterns) {
    let matched = pattern.exec(normalized)
    while (matched) {
      const value = coerceTopLevelPositiveNumber(matched[1])
      if (value && value >= 20 && value <= 99999) {
        candidates.push(value)
      }
      matched = pattern.exec(normalized)
    }
  }
  return candidates.length ? candidates[0] : null
}

function extractLocalMerchantInt(text) {
  const matched = cleanLocalMerchantText(text).match(/(\d{1,4})/)
  return matched ? Number(matched[1]) : null
}

function readLocalMerchantInputPrice(row) {
  const inputs = queryLocalMerchantElements(row, LOCAL_MERCHANT_PRICE_INPUT_SELECTORS, 20)
  for (const input of inputs) {
    const value = coerceTopLevelPositiveNumber(input.value || input.getAttribute("value"))
    if (value) {
      return value
    }
  }
  return null
}

function isVisibleLocalMerchantElement(element) {
  if (!element || element.closest?.(`#${ROOT_ID}`)) {
    return false
  }
  const rect = element.getBoundingClientRect?.()
  if (rect && (rect.width <= 0 || rect.height <= 0)) {
    return false
  }
  const style = window.getComputedStyle ? window.getComputedStyle(element) : null
  return !(style && (style.display === "none" || style.visibility === "hidden" || Number(style.opacity || 1) === 0))
}

function readLocalMerchantInputOwnPrice(input) {
  if (!input || input.disabled || input.readOnly) {
    return null
  }
  const attrs = [
    input.value,
    input.getAttribute("value"),
    input.getAttribute("aria-valuenow"),
    input.getAttribute("data-value"),
    input.getAttribute("title")
  ]
  for (const raw of attrs) {
    const value = coerceTopLevelPositiveNumber(raw)
    if (value && value >= 20 && value <= 99999) {
      return value
    }
  }
  return null
}

function findLocalMerchantPriceContainer(input) {
  let current = input
  let fallback = input?.parentElement || null
  for (let depth = 0; current && depth < 9; depth += 1) {
    if (current.closest?.(`#${ROOT_ID}`)) {
      return null
    }
    const text = cleanLocalMerchantText(current.innerText || current.textContent || "")
    const priceInputCount = queryLocalMerchantElements(current, LOCAL_MERCHANT_PRICE_INPUT_SELECTORS, 30)
      .filter((node) => readLocalMerchantInputOwnPrice(node))
      .length
    if (text && LOCAL_MERCHANT_CONTAINER_HINT_PATTERN.test(text) && text.length >= 4 && text.length <= 1200 && priceInputCount <= 8) {
      return current
    }
    if (text && text.length >= 4 && text.length <= 1200 && priceInputCount <= 4) {
      fallback = current
    }
    current = current.parentElement
  }
  return fallback
}

function collectLocalMerchantRowsFromPriceInputs() {
  const inputs = queryLocalMerchantElements(document, LOCAL_MERCHANT_PRICE_INPUT_SELECTORS, 260)
  const rows = []
  const seen = new Set()
  for (const input of inputs) {
    if (!isVisibleLocalMerchantElement(input)) {
      continue
    }
    const price = readLocalMerchantInputOwnPrice(input)
    if (!price) {
      continue
    }
    const container = findLocalMerchantPriceContainer(input)
    if (!container || seen.has(container)) {
      continue
    }
    container.__fliggyOpsDetectedPrice = price
    seen.add(container)
    rows.push(container)
  }
  return rows
}

function looksLikeLocalMerchantRateName(text) {
  const value = cleanLocalMerchantText(text)
  if (!value || value.length > 80) {
    return false
  }
  return /价|早|早餐|取消|担保|预付|到店付|连住|套餐|标准|含餐/.test(value)
}

function looksLikeLocalMerchantNoise(text) {
  const value = cleanLocalMerchantText(text)
  if (!value) {
    return true
  }
  if (/^(修改|编辑|保存|确定|确认|提交|取消|展开|收起|删除|复制|上架|下架)$/.test(value)) {
    return true
  }
  return /^(¥|￥)?\d+(\.\d+)?(元)?$/.test(value)
}

function parseLocalMerchantItemFromRow(row, index) {
  const rawText = cleanLocalMerchantText(row.innerText || row.textContent || "")
  if (!rawText || rawText.length < 2) {
    return null
  }
  const inputPrice = row.__fliggyOpsDetectedPrice || readLocalMerchantInputPrice(row)
  const textPrice = extractLocalMerchantPriceFromText(rawText)
  const price = inputPrice || textPrice
  if (!price) {
    return null
  }
  const lines = String(row.innerText || row.textContent || "")
    .split(/\n+/)
    .map(cleanLocalMerchantText)
    .filter((line) => line && !looksLikeLocalMerchantNoise(line))
  let roomName = ""
  let rateName = ""
  for (const line of lines.slice(0, 12)) {
    if (!rateName && looksLikeLocalMerchantRateName(line)) {
      rateName = line
      continue
    }
    if (!roomName && !extractLocalMerchantPriceFromText(line)) {
      roomName = line
    }
  }
  if (!roomName && row.getAttribute("title")) {
    roomName = cleanLocalMerchantText(row.getAttribute("title"))
  }
  const gid = cleanLocalMerchantText(
    row.getAttribute("data-gid") ||
    row.getAttribute("gid") ||
    row.dataset?.gid ||
    (rawText.match(/\bGID[:：\s]*([A-Za-z0-9_-]+)/i) || [])[1] ||
    ""
  )
  const hid = cleanLocalMerchantText(
    row.getAttribute("data-hid") ||
    row.getAttribute("hid") ||
    row.dataset?.hid ||
    (rawText.match(/\bHID[:：\s]*([A-Za-z0-9_-]+)/i) || [])[1] ||
    ""
  )
  const availableRooms = /余房|可售|库存|间/.test(rawText) ? extractLocalMerchantInt(rawText) : null
  const displayName = rateName || roomName || `本地房型${index + 1}`
  return {
    room_type: roomName,
    room_name: roomName,
    rate_name: rateName,
    display_name: displayName,
    price,
    current_price: price,
    available_rooms: availableRooms,
    gid,
    hid,
    raw_text: rawText.slice(0, 500),
    local_row_index: index,
    source: "extension_local_merchant_page"
  }
}

function collectLocalMerchantPriceItems() {
  const selectorRows = queryLocalMerchantElements(document, LOCAL_MERCHANT_ROW_SELECTORS, 220)
  const inputRows = collectLocalMerchantRowsFromPriceInputs()
  const rows = [...inputRows, ...selectorRows]
  const items = []
  const seen = new Set()
  const inspectedRows = rows.length
  rows.forEach((row, index) => {
    if (row.closest?.(`#${ROOT_ID}`)) {
      return
    }
    const item = parseLocalMerchantItemFromRow(row, index)
    if (!item) {
      return
    }
    const key = [
      normalizeLocalMerchantText(item.room_name),
      normalizeLocalMerchantText(item.rate_name || item.display_name),
      Number(item.current_price || item.price || 0).toFixed(2)
    ].join("|")
    if (seen.has(key)) {
      return
    }
    seen.add(key)
    items.push(item)
  })
  return {
    status: "success",
    source: "extension_local_merchant_page",
    collect_mode: "extension_current_tab",
    price_url: String(window.location.href || ""),
    current_price: items[0]?.current_price || null,
    room_count: items.length,
    item_count: items.length,
    items,
    debug: {
      inspected_rows: inspectedRows,
      input_container_rows: inputRows.length,
      selector_rows: selectorRows.length,
      visible_price_inputs: queryLocalMerchantElements(document, LOCAL_MERCHANT_PRICE_INPUT_SELECTORS, 260).filter((node) => isVisibleLocalMerchantElement(node) && readLocalMerchantInputOwnPrice(node)).length,
    },
    collected_at: new Date().toLocaleString()
  }
}

function scoreLocalMerchantRow(item, rowText) {
  const text = normalizeLocalMerchantText(rowText)
  if (!text) {
    return 0
  }
  const gid = normalizeLocalMerchantText(item?.gid)
  const hid = normalizeLocalMerchantText(item?.hid)
  const roomName = normalizeLocalMerchantText(item?.room_name || item?.roomName)
  const rateName = normalizeLocalMerchantText(item?.rate_name || item?.rateName || item?.display_name || item?.displayName)
  const displayName = normalizeLocalMerchantText(item?.display_name || item?.displayName)
  let score = 0
  if (gid && text.includes(gid)) score += 10
  if (hid && text.includes(hid)) score += 6
  if (rateName && text.includes(rateName)) score += 5
  if (displayName && text.includes(displayName)) score += 3
  if (roomName && text.includes(roomName)) score += 2
  return score
}

function findLocalMerchantRow(item) {
  const rows = queryLocalMerchantElements(document, LOCAL_MERCHANT_ROW_SELECTORS, 180)
  let bestRow = null
  let bestScore = 0
  let bestText = ""
  rows.forEach((row) => {
    if (row.closest?.(`#${ROOT_ID}`)) {
      return
    }
    const rowText = cleanLocalMerchantText(row.innerText || row.textContent || "")
    const score = scoreLocalMerchantRow(item, rowText)
    if (score > bestScore) {
      bestRow = row
      bestScore = score
      bestText = rowText
    }
  })
  return { row: bestRow, score: bestScore, rowText: bestText }
}

function setLocalMerchantInputValue(input, value) {
  const text = Number(value).toFixed(2)
  input.focus()
  const prototype = Object.getPrototypeOf(input)
  const descriptor = Object.getOwnPropertyDescriptor(prototype, "value")
  if (descriptor?.set) {
    descriptor.set.call(input, text)
  } else {
    input.value = text
  }
  input.dispatchEvent(new Event("input", { bubbles: true }))
  input.dispatchEvent(new Event("change", { bubbles: true }))
  input.blur()
  return text
}

function elementTextMatchesAny(element, patterns) {
  const text = cleanLocalMerchantText(element.innerText || element.textContent || element.getAttribute?.("title") || element.getAttribute?.("aria-label") || "")
  return patterns.some((pattern) => pattern.test(text))
}

function clickFirstLocalMerchantElement(root, selectors, textPatterns = []) {
  const candidates = queryLocalMerchantElements(root, selectors, 80)
  for (const element of candidates) {
    if (textPatterns.length && !elementTextMatchesAny(element, textPatterns)) {
      continue
    }
    try {
      element.click()
      return true
    } catch (error) {
      continue
    }
  }
  return false
}

async function waitLocalMerchant(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms))
}

async function submitLocalMerchantPriceItem(item) {
  const finalPrice = coerceTopLevelPositiveNumber(item?.final_price ?? item?.finalPrice)
  const displayName = cleanLocalMerchantText(item?.display_name || item?.displayName || item?.rate_name || item?.rateName || item?.room_name || item?.roomName || "")
  if (!finalPrice) {
    return { ...item, display_name: displayName, final_price: finalPrice || 0, status: "failed", message: "最终价无效，必须大于 0", submit_channel: "extension_local_page" }
  }
  const matched = findLocalMerchantRow(item)
  if (!matched.row || matched.score <= 0) {
    return { ...item, display_name: displayName, final_price: finalPrice, status: "failed", message: "本地页面未找到匹配房型行", submit_channel: "extension_local_page" }
  }
  let input = queryLocalMerchantElements(matched.row, LOCAL_MERCHANT_PRICE_INPUT_SELECTORS, 20)[0] || null
  if (!input) {
    clickFirstLocalMerchantElement(matched.row, LOCAL_MERCHANT_EDIT_SELECTORS, [/修改价格|修改房价|价格管理|房价管理|修改|改价|编辑|调整|调价/])
    await waitLocalMerchant(400)
    input = queryLocalMerchantElements(matched.row, LOCAL_MERCHANT_PRICE_INPUT_SELECTORS, 20)[0]
      || queryLocalMerchantElements(document, LOCAL_MERCHANT_PRICE_INPUT_SELECTORS, 60)[0]
      || null
  }
  if (!input) {
    return { ...item, display_name: displayName, final_price: finalPrice, status: "failed", message: "已找到房型，但未找到可编辑价格输入框", row_text: matched.rowText, submit_channel: "extension_local_page" }
  }
  const filledValue = setLocalMerchantInputValue(input, finalPrice)
  await waitLocalMerchant(250)
  let clicked = clickFirstLocalMerchantElement(matched.row, LOCAL_MERCHANT_SAVE_SELECTORS, [/确认修改|确认提交|保存|确定|确认|提交|应用|完成|立即生效/])
  if (!clicked) {
    clicked = clickFirstLocalMerchantElement(document, LOCAL_MERCHANT_SAVE_SELECTORS, [/确认修改|确认提交|保存|确定|确认|提交|立即生效/])
  }
  if (!clicked) {
    try {
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }))
    } catch (error) {
      // best effort
    }
  }
  await waitLocalMerchant(600)
  clickFirstLocalMerchantElement(document, LOCAL_MERCHANT_CONFIRM_SELECTORS, [/确认提交|确认修改|确定|确认/])
  await waitLocalMerchant(800)
  return {
    ...item,
    display_name: displayName,
    final_price: finalPrice,
    status: "success",
    message: clicked ? "已在本地已登录页面填价并触发保存" : "已填价并尝试回车提交，未捕获保存按钮",
    row_text: matched.rowText,
    filled_value: filledValue,
    submit_channel: "extension_local_page",
    submitted_at: new Date().toLocaleString()
  }
}

async function submitLocalMerchantPrices(items) {
  const targetItems = Array.isArray(items) ? items : []
  if (!targetItems.length) {
    throw new Error("没有可提交的本地改价房型")
  }
  const submittedItems = []
  for (const item of targetItems) {
    submittedItems.push(await submitLocalMerchantPriceItem(item))
  }
  const successCount = submittedItems.filter((item) => item.status === "success").length
  const failedCount = submittedItems.length - successCount
  return {
    status: failedCount ? (successCount ? "partial_failed" : "failed") : "success",
    audit_mode: "formal_submit",
    source: "extension_local_merchant_submit",
    submit_channel: "extension_local_page",
    price_url: String(window.location.href || ""),
    submitted_count: submittedItems.length,
    success_count: successCount,
    failed_count: failedCount,
    skipped_submit_count: 0,
    items: submittedItems,
    submitted_at: new Date().toLocaleString()
  }
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
  const currentPrice = coerceTopLevelPositiveNumber(item.current_price ?? item.currentPrice)
  if (!roomType) {
    return null
  }
  const displayName = String(item.display_name || item.displayName || "").replace(/\s+/g, " ").trim()
    || (rateName && rateName !== "标准价" ? `${roomType} / ${rateName}` : roomType)
  return {
    displayName,
    roomType,
    rateName,
    currentPrice: currentPrice || null,
    gid: String(item.gid || "").trim(),
    hid: String(item.hid || "").trim(),
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
  const localMappings = getManualRoomMappingsForShop(config)
  if (localMappings.length) {
    return {
      items: localMappings,
      count: localMappings.length,
      source: "local",
      sourceLabel: "本地映射"
    }
  }

  return {
    items: [],
    count: 0,
    source: "none",
    sourceLabel: "未维护"
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
    }, CLOUD_BRIDGE_TIMEOUT_MS)

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

  if (message?.type === "LOCAL_MERCHANT_PRICE_ITEMS") {
    const pageContext = getPageContext()
    if (String(pageContext?.pageType || "") !== "merchant_portal") {
      sendResponse({ ok: false, error: "当前页面不是飞猪商家后台页面" })
      return false
    }
    try {
      sendResponse({ ok: true, data: collectLocalMerchantPriceItems() })
    } catch (error) {
      sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) })
    }
    return false
  }

  if (message?.type === "LOCAL_MERCHANT_PRICE_SUBMIT") {
    const pageContext = getPageContext()
    if (String(pageContext?.pageType || "") !== "merchant_portal") {
      sendResponse({ ok: false, error: "当前页面不是飞猪商家后台页面" })
      return false
    }
    submitLocalMerchantPrices(message?.payload?.confirmedItems || message?.payload?.confirmed_items || [])
      .then((data) => {
        sendResponse({ ok: true, data })
      })
      .catch((error) => {
        sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) })
      })
    return true
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
  const assistantFrameUrl = buildAssistantFrameUrl()
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
        width: 400px;
        height: 780px;
        max-height: calc(100vh - 40px);
        display: none;
        overflow: hidden;
        border-radius: 24px;
        background: #fffaf3;
        box-shadow: 0 24px 60px rgba(113, 54, 7, 0.22);
        border: 1px solid rgba(185, 121, 39, 0.18);
      }
      .fliggy-ops-panel.is-open {
        display: block;
      }
      .fliggy-ops-frame {
        display: block;
        width: 100%;
        height: 100%;
        border: 0;
        background: #fffaf3;
      }
      .fliggy-ops-close {
        position: absolute;
        top: 10px;
        right: 10px;
        z-index: 1;
        width: 30px;
        height: 30px;
        border: none;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.82);
        color: #7c4b14;
        box-shadow: inset 0 0 0 1px rgba(167, 115, 54, 0.18);
        font: 700 18px/1 "Noto Sans SC", "Microsoft YaHei", sans-serif;
        cursor: pointer;
      }
      @media (max-width: 460px) {
        .fliggy-ops-panel {
          right: 10px;
          left: 10px;
          bottom: 86px;
          width: auto;
          height: min(780px, calc(100vh - 104px));
        }
      }
    </style>
    <button class="fliggy-ops-launcher" type="button">运营助手</button>
    <section class="fliggy-ops-panel" aria-live="polite">
      <button class="fliggy-ops-close" type="button" aria-label="关闭">×</button>
      <iframe
        class="fliggy-ops-frame"
        title="飞猪运营助手"
        src="${escapeHtml(assistantFrameUrl)}"
        sandbox="allow-scripts allow-forms allow-same-origin allow-popups allow-downloads"
        allow="clipboard-write"
      ></iframe>
    </section>
  `

  const embeddedPanel = shadow.querySelector(".fliggy-ops-panel")
  const embeddedLauncher = shadow.querySelector(".fliggy-ops-launcher")
  const embeddedCloseButton = shadow.querySelector(".fliggy-ops-close")
  const cloudFrame = shadow.querySelector(".fliggy-ops-frame")

  const allowedRuntimeMessageTypes = new Set([
    "GET_CONFIG",
    "GET_CONFIG_DEBUG",
    "GET_AUTH_STATE",
    "AUTH_LOGIN",
    "AUTH_LOGOUT",
    "AUTH_SWITCH_SHOP",
    "SAVE_CONFIG",
    "SERVICE_STATUS",
    "LATEST_PRICES",
    "RUN_COLLECT",
    "MERCHANT_PRICING_PREVIEW",
    "MERCHANT_PRICING_ITEMS",
    "MERCHANT_PRICING_SUBMIT_SUGGESTED",
    "MERCHANT_PRICING_SUBMIT_CURRENT",
    "MERCHANT_UNIFORM_PRICE_SUBMIT",
    "MERCHANT_CREDENTIAL_GET",
    "MERCHANT_CREDENTIAL_SAVE",
    "MERCHANT_MAPPING_LIST",
    "MERCHANT_MAPPING_SAVE",
    "MERCHANT_MAPPING_REFRESH",
    "COMPETITOR_WORKFLOW_PREVIEW",
    "COMPETITOR_PRICING_ADVICE_PREVIEW",
    "COMPETITOR_PRICE_TREND_SUMMARY",
    "COMPETITOR_SCHEDULE_STATUS",
    "COMPETITOR_ROOM_PRICES",
    "COMPETITOR_ROOM_PRICES_HTTP",
    "COMPETITOR_ROOM_PRICES_TABS",
    "COMPETITOR_ROOM_PRICES_WITH_HOTELS",
    "OPEN_OPTIONS",
    "RETURN_TO_OPTIONS_SOURCE"
  ])

  function buildAssistantFrameUrl() {
    const url = new URL(chrome.runtime.getURL("popup.html"))
    url.searchParams.set("embedded", "1")
    url.searchParams.set("host", "browser-extension")
    url.searchParams.set("protocol", CLOUD_PROTOCOL_VERSION)
    return url.toString()
  }

  function getCloudTargetWindow() {
    return cloudFrame?.contentWindow || null
  }

  function postCloudMessage(message) {
    const targetWindow = getCloudTargetWindow()
    if (!targetWindow) {
      return
    }
    targetWindow.postMessage({
      protocol: CLOUD_PROTOCOL_VERSION,
      ...message
    }, CLOUD_ASSISTANT_ORIGIN)
  }

  function sendCloudEvent(event, data = {}) {
    postCloudMessage({
      type: CLOUD_EVENT_TYPE,
      event,
      data
    })
  }

  function sendCloudResponse(requestId, ok, value) {
    postCloudMessage({
      type: CLOUD_RESPONSE_TYPE,
      requestId,
      ok,
      ...(ok ? { data: value } : { error: String(value || "云端助手协议请求失败") })
    })
  }

  function normalizeCloudRuntimeMessage(payload = {}) {
    const rawMessage = payload?.message && typeof payload.message === "object"
      ? payload.message
      : payload
    const type = String(rawMessage?.type || "").trim()
    if (!allowedRuntimeMessageTypes.has(type)) {
      throw new Error(`Unsupported cloud runtime message type: ${type || "<empty>"}`)
    }
    return {
      type,
      ...(rawMessage.payload !== undefined ? { payload: rawMessage.payload } : {})
    }
  }

  async function handleCloudRequest(action, payload = {}) {
    if (action === "plugin.runtime") {
      return sendRuntimeMessage(normalizeCloudRuntimeMessage(payload))
    }
    if (action === "bridge.request") {
      const bridgeAction = String(payload.action || "").trim()
      if (!bridgeAction) {
        throw new Error("bridge.request action is required")
      }
      return requestViaExtensionBridge(bridgeAction, payload.payload || {})
    }
    if (action === "page.getContext") {
      return getPageContext()
    }
    if (action === "page.getSnapshot") {
      return getPageSnapshot(payload)
    }
    if (action === "page.getCurrentHotelRoomPrices") {
      const pageContext = getPageContext()
      if (String(pageContext?.pageType || "") !== "hotel_detail") {
        throw new Error("当前页面不是酒店详情页")
      }
      return parseCurrentHotelDetailRoomPrices()
    }
    if (action === "page.collectLocalMerchantPriceItems") {
      const pageContext = getPageContext()
      if (String(pageContext?.pageType || "") !== "merchant_portal") {
        throw new Error("当前页面不是飞猪商家后台页面")
      }
      return collectLocalMerchantPriceItems()
    }
    if (action === "page.submitLocalMerchantPrices") {
      const pageContext = getPageContext()
      if (String(pageContext?.pageType || "") !== "merchant_portal") {
        throw new Error("当前页面不是飞猪商家后台页面")
      }
      return submitLocalMerchantPrices(payload.confirmedItems || payload.confirmed_items || [])
    }
    if (action === "panel.close") {
      closeEmbeddedPopupPanel()
      return { closed: true }
    }
    if (action === "panel.ping") {
      return {
        ready: true,
        protocol: CLOUD_PROTOCOL_VERSION,
        origin: CLOUD_ASSISTANT_ORIGIN,
        pageContext: getPageContext()
      }
    }
    throw new Error(`Unsupported cloud action: ${String(action || "<empty>")}`)
  }

  window.addEventListener("message", (event) => {
    const data = event.data
    if (
      event.source !== getCloudTargetWindow()
      || event.origin !== CLOUD_ASSISTANT_ORIGIN
      || !data
      || data.protocol !== CLOUD_PROTOCOL_VERSION
      || data.type !== CLOUD_REQUEST_TYPE
      || !data.requestId
    ) {
      return
    }
    const requestId = String(data.requestId)
    handleCloudRequest(String(data.action || ""), data.payload || {})
      .then((result) => sendCloudResponse(requestId, true, result))
      .catch((error) => sendCloudResponse(requestId, false, error instanceof Error ? error.message : String(error)))
  })

  function openEmbeddedPopupPanel() {
    embeddedPanel?.classList.add("is-open")
    const data = { pageContext: getPageContext(), cloudUi: true, protocol: CLOUD_PROTOCOL_VERSION }
    sendCloudEvent("panel.opened", data)
    return data
  }

  function closeEmbeddedPopupPanel() {
    embeddedPanel?.classList.remove("is-open")
    sendCloudEvent("panel.closed", { pageContext: getPageContext() })
  }

  embeddedLauncher?.addEventListener("click", openEmbeddedPopupPanel)
  embeddedCloseButton?.addEventListener("click", closeEmbeddedPopupPanel)
  cloudFrame?.addEventListener("load", () => {
    sendCloudEvent("plugin.ready", {
      pageContext: getPageContext(),
      capabilities: [
        "plugin.runtime",
        "bridge.request",
        "page.getContext",
        "page.getSnapshot",
        "page.getCurrentHotelRoomPrices",
        "page.collectLocalMerchantPriceItems",
        "page.submitLocalMerchantPrices",
        "panel.close",
        "panel.ping"
      ]
    })
  })

  return { open: openEmbeddedPopupPanel, close: closeEmbeddedPopupPanel }

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
        width: 400px;
        height: 780px;
        max-height: calc(100vh - 40px);
        display: none;
        overflow: hidden;
        border-radius: 24px;
        background:
          radial-gradient(circle at top right, rgba(255, 183, 77, 0.18), transparent 24%),
          linear-gradient(180deg, #fffaf3 0%, #fff0d6 100%);
        box-shadow: 0 24px 60px rgba(113, 54, 7, 0.22);
        border: 1px solid rgba(185, 121, 39, 0.18);
        color: #5f370f;
        font: 14px/1.5 "Noto Sans SC", "Microsoft YaHei", sans-serif;
      }
      .fliggy-ops-panel.is-open {
        display: block;
      }
      .fliggy-ops-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 8px;
        padding: 14px 48px 0 14px;
        border-bottom: none;
      }
      .fliggy-ops-title {
        margin: 0;
        color: #5f370f;
        font-size: 30px;
        line-height: 1.15;
        font-weight: 700;
      }
      .fliggy-ops-subtitle {
        margin: 6px 0 0;
        color: #8d6542;
        font-size: 12px;
      }
      .fliggy-ops-close {
        position: absolute;
        top: 12px;
        right: 14px;
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
        padding: 0 14px 14px;
        overflow: auto;
        max-height: calc(100% - 86px);
      }
      .fliggy-ops-nav {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 8px;
        margin-top: 14px;
        padding: 10px;
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.88);
        box-shadow: 0 12px 32px rgba(104, 54, 9, 0.1);
      }
      .fliggy-ops-nav-button {
        border: none;
        border-radius: 12px;
        padding: 10px 8px;
        background: rgba(255, 255, 255, 0.7);
        color: #8d6542;
        font: 700 12px/1.2 "Noto Sans SC", "Microsoft YaHei", sans-serif;
        box-shadow: inset 0 0 0 1px rgba(167, 115, 54, 0.12);
        cursor: pointer;
      }
      .fliggy-ops-nav-button.is-active {
        background: linear-gradient(135deg, #ffb648 0%, #ff7a18 100%);
        color: #fff9f2;
        box-shadow: none;
      }
      .fliggy-ops-subnav-card {
        margin-top: 14px;
        padding: 10px;
      }
      .fliggy-ops-subnav {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
      }
      #fliggy-ops-workspace-group-card .fliggy-ops-subnav {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .fliggy-ops-subnav-button {
        border: none;
        border-radius: 14px;
        padding: 10px 8px;
        background: rgba(255, 255, 255, 0.74);
        color: #7c4b14;
        font: 700 12px/1.2 "Noto Sans SC", "Microsoft YaHei", sans-serif;
        box-shadow: inset 0 0 0 1px rgba(194, 120, 34, 0.12);
        cursor: pointer;
      }
      .fliggy-ops-subnav-button.is-active {
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
        margin-top: 14px;
        padding: 14px;
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.88);
        box-shadow: 0 12px 32px rgba(104, 54, 9, 0.1);
      }
      .fliggy-ops-hero-card,
      .fliggy-ops-group-banner,
      .fliggy-ops-feature-card {
        margin-top: 14px;
      }
      .fliggy-ops-hero-card {
        background: linear-gradient(135deg, rgba(255, 183, 77, 0.22), rgba(255, 255, 255, 0.94));
      }
      .fliggy-ops-group-banner {
        padding: 16px 16px 14px;
        overflow: hidden;
      }
      .fliggy-ops-group-banner.basic {
        background:
          radial-gradient(circle at top right, rgba(255, 183, 77, 0.24), transparent 30%),
          linear-gradient(135deg, rgba(255, 248, 236, 0.98), rgba(255, 255, 255, 0.92));
      }
      .fliggy-ops-group-banner.merchant {
        background:
          radial-gradient(circle at top right, rgba(239, 108, 0, 0.18), transparent 32%),
          linear-gradient(135deg, rgba(255, 238, 224, 0.98), rgba(255, 255, 255, 0.92));
      }
      .fliggy-ops-section-title {
        margin-bottom: 6px;
        font-size: 12px;
        color: #7c4b14;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .fliggy-ops-hero-title,
      .fliggy-ops-group-banner-title {
        font-size: 17px;
        font-weight: 700;
      }
      .fliggy-ops-hero-note,
      .fliggy-ops-group-banner-note {
        margin-top: 6px;
        color: #8a6132;
        font-size: 12px;
      }
      .fliggy-ops-group-banner-tags {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 12px;
      }
      .fliggy-ops-group-banner-tag {
        padding: 4px 8px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.88);
        color: #7c4b14;
        font-size: 11px;
        box-shadow: inset 0 0 0 1px rgba(194, 120, 34, 0.12);
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
        margin-top: 10px;
      }
      .fliggy-ops-section h3 {
        margin: 0 0 10px;
        font-size: 13px;
        color: #7c4b14;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }
      .fliggy-ops-card {
        margin-top: 14px;
        padding: 14px;
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.88);
        box-shadow: 0 12px 32px rgba(104, 54, 9, 0.1);
        word-break: break-word;
      }
      .fliggy-ops-result {
        min-height: 38px;
        white-space: pre-wrap;
        word-break: break-word;
      }
      .fliggy-ops-card .fliggy-ops-card {
        margin-top: 6px;
        padding: 6px 7px;
        border-radius: 12px;
        background: rgba(255, 183, 77, 0.12);
        box-shadow: none;
      }
      .fliggy-ops-meta {
        display: grid;
        gap: 4px;
      }
      .fliggy-ops-row {
        display: flex;
        gap: 6px;
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
        gap: 7px;
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .fliggy-ops-input-label {
        display: grid;
        gap: 4px;
        margin: 0;
        color: #7c4b14;
        font-size: 12px;
      }
      .fliggy-ops-textarea {
        width: 100%;
        min-height: 48px;
        box-sizing: border-box;
        resize: vertical;
        border: 1px solid rgba(167, 115, 54, 0.18);
        border-radius: 14px;
        padding: 6px 8px;
        background: rgba(255, 255, 255, 0.92);
        color: #5f370f;
        font: 13px/1.4 "Noto Sans SC", "Microsoft YaHei", sans-serif;
      }
      .fliggy-ops-input {
        width: 100%;
        box-sizing: border-box;
        border: 1px solid rgba(167, 115, 54, 0.18);
        border-radius: 12px;
        padding: 6px 8px;
        background: rgba(255, 255, 255, 0.92);
        color: #5f370f;
        font: 13px/1.4 "Noto Sans SC", "Microsoft YaHei", sans-serif;
      }
      .fliggy-ops-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 7px;
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
        border-radius: 12px;
        padding: 7px 8px;
        background: #fff;
        color: #5f370f;
        font: 600 13px/1.25 "Noto Sans SC", "Microsoft YaHei", sans-serif;
        box-shadow: inset 0 0 0 1px rgba(167, 115, 54, 0.18);
        cursor: pointer;
        text-align: left;
      }
      .fliggy-ops-button.primary {
        background: linear-gradient(135deg, #ffb648 0%, #ff7a18 100%);
        color: #fff9f2;
        box-shadow: none;
      }
      .fliggy-ops-button.danger {
        background: linear-gradient(135deg, #ff9f68 0%, #d9480f 100%);
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
        gap: 6px;
        margin-top: 6px;
      }
      .fliggy-ops-tag {
        padding: 3px 7px;
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
        margin-top: 7px;
        color: #94653a;
        font-size: 11px;
      }
      .fliggy-ops-empty-state,
      .fliggy-ops-tip {
        color: #8a6132;
        font-size: 12px;
      }
      .fliggy-ops-summary-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 6px;
        margin-top: 7px;
      }
      .fliggy-ops-summary-pill {
        padding: 6px;
        border-radius: 10px;
        background: rgba(255, 255, 255, 0.82);
        box-shadow: inset 0 0 0 1px rgba(194, 120, 34, 0.08);
      }
      .fliggy-ops-summary-label {
        color: #8f6332;
        font-size: 11px;
      }
      .fliggy-ops-summary-value {
        margin-top: 2px;
        color: #7c2d12;
        font-size: 14px;
        font-weight: 700;
      }
      .fliggy-ops-chart-shell {
        margin-top: 6px;
        padding: 6px;
        border-radius: 12px;
        background: rgba(255, 255, 255, 0.82);
        box-shadow: inset 0 0 0 1px rgba(194, 120, 34, 0.1);
      }
      .fliggy-ops-chart-svg {
        display: block;
        width: 100%;
        height: auto;
      }
      .fliggy-ops-chart-axis-labels {
        display: flex;
        justify-content: space-between;
        gap: 6px;
        margin-top: 5px;
        color: #8f6332;
        font-size: 11px;
      }
      .fliggy-ops-chart-legend {
        display: grid;
        gap: 6px;
        margin-top: 8px;
      }
      .fliggy-ops-chart-legend-item {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 8px;
        border-radius: 10px;
        background: rgba(255, 248, 236, 0.9);
      }
      .fliggy-ops-chart-swatch {
        width: 10px;
        height: 10px;
        border-radius: 999px;
        flex: 0 0 10px;
      }
      .fliggy-ops-chart-legend-text {
        flex: 1;
        min-width: 0;
      }
      .fliggy-ops-chart-legend-title {
        color: #7c2d12;
        font-weight: 700;
      }
      .fliggy-ops-chart-legend-meta {
        margin-top: 2px;
        color: #8f6332;
        font-size: 11px;
      }
      .fliggy-ops-details summary {
        cursor: pointer;
        font-weight: 700;
        list-style: none;
      }
      .fliggy-ops-details summary::-webkit-details-marker {
        display: none;
      }
      .fliggy-ops-details-body {
        margin-top: 8px;
      }
      .fliggy-ops-workflow-tools {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-top: 7px;
      }
      .fliggy-ops-workflow-tools button {
        border: none;
        border-radius: 12px;
        padding: 6px 8px;
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
        gap: 7px;
        margin-top: 8px;
      }
      .fliggy-ops-workflow-item {
        padding: 6px 7px;
        border-radius: 12px;
        background: rgba(255, 255, 255, 0.88);
        box-shadow: inset 0 0 0 1px rgba(194, 120, 34, 0.08);
      }
      .fliggy-ops-workflow-item-top {
        display: flex;
        align-items: flex-start;
        gap: 7px;
      }
      .fliggy-ops-workflow-item-name {
        color: #7c2d12;
        font-size: 14px;
        font-weight: 700;
      }
      .fliggy-ops-workflow-item-meta {
        margin-top: 2px;
        color: #8f6332;
        font-size: 12px;
      }
      .fliggy-ops-price-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 7px;
        margin-top: 7px;
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
          <button class="fliggy-ops-nav-button is-active" type="button" data-page="workspace">工作台</button>
          <button class="fliggy-ops-nav-button" type="button" data-page="feedback">反馈</button>
        </div>
        <section id="fliggy-ops-workspace-group-card" class="fliggy-ops-card fliggy-ops-subnav-card">
          <div class="fliggy-ops-subnav" role="tablist" aria-label="工作台分组切换">
            <button class="fliggy-ops-subnav-button is-active" type="button" data-workspace-group="basic">基础功能</button>
            <button class="fliggy-ops-subnav-button" type="button" data-workspace-group="merchant">商家改价</button>
          </div>
        </section>
        <div class="fliggy-ops-page is-active" data-page="workspace" data-workspace-group-page="basic">
          <section id="fliggy-ops-workspace-gate" class="fliggy-ops-card fliggy-ops-hero-card">
            <div class="fliggy-ops-section-title">打开设置</div>
            <div class="fliggy-ops-hero-title">账号登录、当前页面和当前配置已迁到设置页。</div>
            <div id="fliggy-ops-auth-session" class="fliggy-ops-hero-note">请先在设置页登录并选择店铺，再回到页面内运营助手使用这里的工作台。</div>
            <div class="fliggy-ops-actions" style="margin-top: 10px; grid-template-columns: 1fr;">
              <button class="fliggy-ops-button primary" data-action="settings" type="button">打开设置页</button>
            </div>
          </section>
          <section class="fliggy-ops-card fliggy-ops-group-banner basic fliggy-ops-hidden">
            <div class="fliggy-ops-section-title">基础功能</div>
            <div class="fliggy-ops-group-banner-title">页面采集、竞对配置和建议价</div>
            <div class="fliggy-ops-group-banner-note">这里集中处理服务检查、页面采集、竞对酒店配置和建议价生成。</div>
            <div class="fliggy-ops-group-banner-tags">
              <span class="fliggy-ops-group-banner-tag">检查服务</span>
              <span class="fliggy-ops-group-banner-tag">按当前页采集</span>
              <span class="fliggy-ops-group-banner-tag">查看竞对价格</span>
              <span class="fliggy-ops-group-banner-tag">生成建议价</span>
            </div>
          </section>
          <section class="fliggy-ops-card fliggy-ops-subnav-card">
            <div class="fliggy-ops-subnav" role="tablist" aria-label="基础功能切换">
              <button class="fliggy-ops-subnav-button is-active" type="button" data-basic-section="room-prices">配置竞对房型价</button>
              <button class="fliggy-ops-subnav-button" type="button" data-basic-section="advice">我的价格</button>
              <button class="fliggy-ops-subnav-button" type="button" data-basic-section="quick-actions">快捷动作</button>
            </div>
          </section>
          <section class="fliggy-ops-card fliggy-ops-feature-card" data-basic-section-card="room-prices">
            <div class="fliggy-ops-section-title">配置竞对房型价</div>
            <div class="fliggy-ops-group-banner-note">这里读取当前店铺已维护的竞对酒店配置，并按详情页抓取所有可见房型/价型价格。</div>
            <div id="fliggy-ops-configured-hotels-box" class="fliggy-ops-card" style="margin-top: 10px;">读取竞对酒店配置中...</div>
            <div class="fliggy-ops-actions" style="margin-top: 10px; grid-template-columns: 1fr;">
              <button class="fliggy-ops-button primary" data-action="room-prices" type="button">查看竞对价格</button>
              <button class="fliggy-ops-button fliggy-ops-hidden" data-action="refresh-room-config" type="button">刷新竞对配置</button>
              <button class="fliggy-ops-button fliggy-ops-hidden" data-action="debug-room-config" type="button">诊断竞对配置</button>
              <button class="fliggy-ops-button fliggy-ops-hidden" data-action="settings" type="button">维护竞对酒店</button>
            </div>
            <div id="fliggy-ops-competitor-room-prices-box" class="fliggy-ops-card" style="margin-top: 10px;">抓取完成后，会直接在这里展示竞对房型价。</div>
          </section>
          <section class="fliggy-ops-card fliggy-ops-feature-card fliggy-ops-hidden" data-basic-section-card="advice">
            <div class="fliggy-ops-section-title">我的价格</div>
            <div class="fliggy-ops-group-banner-note">优先使用后端已维护的我的房型价格和房型映射；整店兜底价仅在没有房型价格时作为补充。</div>
            <label class="fliggy-ops-input-label" for="fliggy-ops-trend-series" style="margin-top: 8px;">趋势维度</label>
            <select id="fliggy-ops-trend-series" class="fliggy-ops-input">
              <option value="room_category">主流房型最低价</option>
              <option value="hotel_min_price">竞对酒店最低价</option>
            </select>
            <div class="fliggy-ops-actions" style="margin-top: 10px; grid-template-columns: 1fr;">
              <button class="fliggy-ops-button" data-action="competitor-trend-refresh" type="button">刷新竞对趋势图</button>
            </div>
            <div id="fliggy-ops-competitor-trend-box" class="fliggy-ops-card" style="margin-top: 10px;">正在加载竞对趋势...</div>
            <div class="fliggy-ops-grid" style="margin-top: 10px;">
              <label class="fliggy-ops-input-label">总房量<input id="fliggy-ops-advice-total-rooms" class="fliggy-ops-input" type="number" min="1" step="1" placeholder="例如 120"></label>
              <label class="fliggy-ops-input-label">可售房量<input id="fliggy-ops-advice-available-rooms" class="fliggy-ops-input" type="number" min="0" step="1" placeholder="例如 36"></label>
              <label class="fliggy-ops-input-label">整店兜底价(选填)<input id="fliggy-ops-advice-current-price" class="fliggy-ops-input" type="number" min="1" step="0.01" placeholder="没有本店房型快照时才使用"></label>
              <label class="fliggy-ops-input-label">策略<select id="fliggy-ops-advice-strategy" class="fliggy-ops-input"><option value="balanced">balanced</option><option value="conservative">conservative</option><option value="aggressive">aggressive</option></select></label>
            </div>
            <label class="fliggy-ops-input-label" for="fliggy-ops-advice-hotel" style="margin-top: 8px;">指定竞对酒店（可选）</label>
            <input id="fliggy-ops-advice-hotel" class="fliggy-ops-input" type="text" placeholder="留空则综合本次抓到的所有竞对酒店">
            <div class="fliggy-ops-card fliggy-ops-competitor-advice" style="margin-top: 10px;">先点“查看竞对价格”，再生成建议价。</div>
            <div class="fliggy-ops-actions" style="margin-top: 10px; grid-template-columns: 1fr;">
              <button class="fliggy-ops-button primary" data-action="competitor-pricing-advice" type="button">生成建议价</button>
            </div>
          </section>
          <section class="fliggy-ops-card fliggy-ops-feature-card fliggy-ops-hidden" data-basic-section-card="quick-actions">
            <div class="fliggy-ops-section-title">快捷动作</div>
            <div class="fliggy-ops-group-banner-note">当前页识别、采集、面板和设置入口集中放在这里，切到这个分组时只展示快捷动作相关内容。</div>
            <div class="fliggy-ops-actions" style="margin-top: 10px;">
              <button class="fliggy-ops-button" data-action="status" type="button">检查服务</button>
              <button class="fliggy-ops-button" data-action="refresh-context" type="button">刷新页面识别</button>
              <button class="fliggy-ops-button primary" data-action="collect" type="button">按当前页采集</button>
              <button class="fliggy-ops-button" data-action="panel" type="button">打开页面面板</button>
              <button class="fliggy-ops-button" data-action="settings" type="button">打开设置页</button>
            </div>
            <label class="fliggy-ops-input-label" for="fliggy-ops-target-input" style="margin-top: 10px;">当前页采集指定酒店</label>
            <textarea id="fliggy-ops-target-input" class="fliggy-ops-textarea" placeholder="一行一个酒店名，也支持逗号分隔"></textarea>
          </section>
        </div>
        <div class="fliggy-ops-page fliggy-ops-hidden" data-page="workspace" data-workspace-group-page="merchant">
          <section class="fliggy-ops-card fliggy-ops-group-banner merchant">
            <div class="fliggy-ops-section-title">商家改价</div>
            <div class="fliggy-ops-group-banner-title">按房型生成建议价，人工确认后提交</div>
            <div class="fliggy-ops-group-banner-note">这里默认接管飞猪平台价格页，按不同房型结合竞对价生成建议，一键回填后仍需人工确认提交。</div>
            <div class="fliggy-ops-group-banner-tags">
              <span class="fliggy-ops-group-banner-tag">生成建议价</span>
              <span class="fliggy-ops-group-banner-tag">一键回填建议价</span>
              <span class="fliggy-ops-group-banner-tag">调整最终价</span>
              <span class="fliggy-ops-group-banner-tag">确认后提交</span>
            </div>
          </section>
          <section class="fliggy-ops-card fliggy-ops-hero-card fliggy-ops-feature-card">
            <div class="fliggy-ops-section-title">竞对驱动改价</div>
            <div class="fliggy-ops-hero-title">飞猪平台价格页一键回填建议价，再确认最终价。</div>
            <div class="fliggy-ops-hero-note">先查看竞对价格，再结合你的房型映射和库存生成建议；已维护“我的房型”时会优先按你的房型名称输出。</div>
            <div class="fliggy-ops-grid">
              <label class="fliggy-ops-input-label">竞对酒店名称<input id="fliggy-ops-competitor-name-input" class="fliggy-ops-input" type="text" placeholder="例如：杭州君悦酒店"></label>
              <label class="fliggy-ops-input-label">飞猪平台价格页<input id="fliggy-ops-workflow-price-url" class="fliggy-ops-input" type="url" value="https://hotel.fliggy.com/ebooking/hotelBaseInfoUv.htm#/ebk-rp/roomsVsManage"></label>
            </div>
            <div class="fliggy-ops-actions" style="margin-top: 10px;">
              <button class="fliggy-ops-button" data-action="merchant-pricing-load" type="button">读取当前页房型价</button>
              <button class="fliggy-ops-button primary" data-action="merchant-pricing-preview" type="button">生成房型建议价</button>
              <button class="fliggy-ops-button" data-action="merchant-pricing-fill" type="button">一键回填建议价</button>
              <button class="fliggy-ops-button danger" data-action="merchant-pricing-submit" type="button">确认最终价并提交</button>
            </div>
            <div id="fliggy-ops-workflow-box" class="fliggy-ops-card fliggy-ops-merchant-pricing" style="margin-top: 10px;">先点击“查看竞对价格”，再生成建议价；已维护我的房型映射时会优先按这些房型输出。</div>
          </section>
          <section class="fliggy-ops-card fliggy-ops-feature-card">
            <div class="fliggy-ops-section-title">高级备用：统一目标价</div>
            <div class="fliggy-ops-group-banner-note">仅适用于你已经线下确认所有可提交房型都要使用同一目标价的场景；优先使用上方“按房型建议价”主流程。</div>
            <div class="fliggy-ops-grid">
              <label class="fliggy-ops-input-label">调价官网链接<input id="fliggy-ops-uniform-price-url" class="fliggy-ops-input" type="url" placeholder="https://..."></label>
              <label class="fliggy-ops-input-label">目标价格<input id="fliggy-ops-uniform-target-price" class="fliggy-ops-input" type="number" min="1" step="0.01" placeholder="例如 429"></label>
            </div>
            <div class="fliggy-ops-actions" style="margin-top: 10px; grid-template-columns: 1fr;">
              <button class="fliggy-ops-button" data-action="merchant-uniform-submit" type="button">确认统一价提交</button>
            </div>
          </section>
          <section class="fliggy-ops-card fliggy-ops-feature-card fliggy-ops-hidden" hidden>
            <div class="fliggy-ops-section-title">商家连接</div>
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
            <h3>房型映射</h3>
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
            </div>
            <label class="fliggy-ops-input-label" for="fliggy-ops-mapping-notes">备注</label>
            <input id="fliggy-ops-mapping-notes" class="fliggy-ops-input" type="text" placeholder="可选备注">
            <div class="fliggy-ops-actions" style="margin-top: 8px;">
              <button class="fliggy-ops-button" data-action="load-merchant-mappings" type="button">读取映射</button>
              <button class="fliggy-ops-button" data-action="refresh-merchant-mappings" type="button">刷新映射状态</button>
              <button class="fliggy-ops-button primary" data-action="save-merchant-mapping" type="button">保存映射</button>
            </div>
            <div class="fliggy-ops-card fliggy-ops-merchant-mapping" style="margin-top: 10px;">尚未读取房型映射。</div>
          </section>
          <section class="fliggy-ops-card fliggy-ops-feature-card fliggy-ops-hidden" hidden>
            <div class="fliggy-ops-section-title">读取房型</div>
            <div class="fliggy-ops-group-banner-note">如需只读取商家当前房型而不直接分析，这里保留原始入口，便于排查当前房型价和映射状态。</div>
            <div class="fliggy-ops-actions" style="margin-top: 8px;">
              <button class="fliggy-ops-button" data-action="merchant-pricing-load" type="button">读取房型</button>
            </div>
            <div class="fliggy-ops-footer">提交前会抓取商家当前价并校验映射；映射由系统自动维护，如果不取消勾选，默认会提交所有可改价房型。</div>
          </section>
          <section class="fliggy-ops-card fliggy-ops-feature-card fliggy-ops-hidden" hidden>
            <div class="fliggy-ops-section-title">返回结果</div>
            <div class="fliggy-ops-result" data-result-page="merchant">尚未执行动作。</div>
          </section>
        </div>
        <section class="fliggy-ops-card fliggy-ops-workspace-result-card" data-page-support="workspace">
          <div class="fliggy-ops-section-title">返回结果</div>
          <div class="fliggy-ops-result" data-result-page="workspace">尚未执行动作。</div>
        </section>
        <div class="fliggy-ops-page" data-page="feedback">
          <section class="fliggy-ops-card fliggy-ops-feature-card">
            <div class="fliggy-ops-section-title">返回结果</div>
            <div class="fliggy-ops-result" data-result-page="feedback">尚未执行动作。</div>
          </section>
        </div>
        <div class="fliggy-ops-hidden" hidden>
          <div class="fliggy-ops-card fliggy-ops-page-context">识别中...</div>
          <div class="fliggy-ops-card fliggy-ops-config">加载中...</div>
        </div>
      </div>      </div>
    </section>
  `

  const launcher = shadow.querySelector(".fliggy-ops-launcher")
  const panel = shadow.querySelector(".fliggy-ops-panel")
  const closeButton = shadow.querySelector(".fliggy-ops-close")
  const statusDot = shadow.querySelector(".fliggy-ops-dot")
  const statusText = shadow.querySelector(".fliggy-ops-status-text")
  const subtitle = shadow.querySelector(".fliggy-ops-subtitle")
  const workspaceGate = shadow.querySelector("#fliggy-ops-workspace-gate")
  const configBox = shadow.querySelector(".fliggy-ops-config")
  const pageContextBox = shadow.querySelector(".fliggy-ops-page-context")
  const authSessionBox = shadow.querySelector("#fliggy-ops-auth-session")
  const pageViews = Array.from(shadow.querySelectorAll(".fliggy-ops-page"))
  const navButtons = Array.from(shadow.querySelectorAll(".fliggy-ops-nav-button"))
  const workspaceGroupCard = shadow.querySelector("#fliggy-ops-workspace-group-card")
  const workspaceGroupButtons = Array.from(shadow.querySelectorAll("[data-workspace-group]"))
  const workspaceGroupPages = Array.from(shadow.querySelectorAll("[data-workspace-group-page]"))
  const workspaceResultCard = shadow.querySelector(".fliggy-ops-workspace-result-card")
  const basicSectionButtons = Array.from(shadow.querySelectorAll("[data-basic-section]"))
  const basicSectionCards = Array.from(shadow.querySelectorAll("[data-basic-section-card]"))
  const resultBoxes = Array.from(shadow.querySelectorAll(".fliggy-ops-result[data-result-page]"))
  const targetInput = shadow.querySelector("#fliggy-ops-target-input")
  const competitorNameInput = shadow.querySelector("#fliggy-ops-competitor-name-input")
  const configuredHotelsBox = shadow.querySelector("#fliggy-ops-configured-hotels-box")
  const competitorRoomPricesBox = shadow.querySelector("#fliggy-ops-competitor-room-prices-box")
  const competitorAdviceHotelInput = shadow.querySelector("#fliggy-ops-advice-hotel")
  const competitorAdviceTotalRoomsInput = shadow.querySelector("#fliggy-ops-advice-total-rooms")
  const competitorAdviceAvailableRoomsInput = shadow.querySelector("#fliggy-ops-advice-available-rooms")
  const competitorAdviceCurrentPriceInput = shadow.querySelector("#fliggy-ops-advice-current-price")
  const competitorAdviceStrategyInput = shadow.querySelector("#fliggy-ops-advice-strategy")
  const competitorTrendRefreshButton = shadow.querySelector('[data-action="competitor-trend-refresh"]')
  const competitorTrendSeriesInput = shadow.querySelector("#fliggy-ops-trend-series")
  const competitorTrendBox = shadow.querySelector("#fliggy-ops-competitor-trend-box")
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
  const mappingNotesInput = shadow.querySelector("#fliggy-ops-mapping-notes")
  const workflowPriceUrlInput = shadow.querySelector("#fliggy-ops-workflow-price-url")
  const uniformPriceUrlInput = shadow.querySelector("#fliggy-ops-uniform-price-url")
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
  let currentCompetitorTrendSummary = null
  let currentMerchantMappings = []
  let merchantMappingsLoaded = false
  let currentMerchantMappingShopId = ""
  let currentMerchantPlatformOverrideUrl = ""
  let activePage = "workspace"
  let activeWorkspaceGroup = "basic"
  let activeBasicSection = "room-prices"

  function isAuthenticatedConfig(currentConfig) {
    return Boolean(currentConfig?.authenticated && currentConfig?.authUser && currentConfig?.currentShop)
  }

  function isMerchantPortalContext(currentPageContext) {
    if (!currentPageContext || typeof currentPageContext !== "object") {
      return false
    }
    if (String(currentPageContext.pageType || "").trim().toLowerCase() === "merchant_portal") {
      return true
    }
    return /ebooking\.fliggy\.com/i.test(String(currentPageContext.startUrl || currentPageContext.sourcePageUrl || ""))
  }

  function applyEmbeddedPageContextUi(currentPageContext) {
    const merchantPortal = isMerchantPortalContext(currentPageContext)
    const roomPricesButton = shadow.querySelector('[data-action="room-prices"]')
    const workflowLoadButton = shadow.querySelector('[data-action="merchant-pricing-load"]')
    const workflowPreviewButton = shadow.querySelector('[data-action="merchant-pricing-preview"]')
    const collectButton = shadow.querySelector('[data-action="collect"]')
    const refreshContextButton = shadow.querySelector('[data-action="refresh-context"]')
    const settingsButton = shadow.querySelector('[data-action="settings"]')

    if (subtitle) {
      subtitle.textContent = merchantPortal
        ? "把竞对抓价、建议调价和官网直改，收进同一个页面助手。当前已识别为商家后台。"
        : "把竞对抓价、建议调价和官网直改，收进同一个页面助手。"
    }
    if (roomPricesButton) {
      roomPricesButton.textContent = "查看竞对价格"
    }
    if (workflowLoadButton) {
      workflowLoadButton.textContent = "读取当前页房型价"
    }
    if (workflowPreviewButton) {
      workflowPreviewButton.textContent = "生成房型建议价"
    }
    if (collectButton) {
      collectButton.textContent = merchantPortal ? "采集当前后台页" : "按当前页采集"
    }
    if (refreshContextButton) {
      refreshContextButton.textContent = merchantPortal ? "刷新后台识别" : "刷新页面识别"
    }
    if (settingsButton) {
      settingsButton.textContent = merchantPortal ? "打开设置页" : "打开设置页"
    }
  }

  navButtons.forEach((button) => {
    button.addEventListener("click", () => {
      if (busy) {
        return
      }
      setActivePage(String(button.dataset.page || "workspace").trim() || "workspace")
    })
  })

  workspaceGroupButtons.forEach((button) => {
    button.addEventListener("click", () => {
      if (busy) {
        return
      }
      setActiveWorkspaceGroup(String(button.dataset.workspaceGroup || "basic").trim() || "basic")
    })
  })

  basicSectionButtons.forEach((button) => {
    button.addEventListener("click", () => {
      if (busy) {
        return
      }
      setActiveBasicSection(String(button.dataset.basicSection || "room-prices").trim() || "room-prices")
    })
  })

  targetInput.addEventListener("blur", () => {
    if (busy) {
      return
    }
    saveManualTargets().catch(() => {})
  })

  competitorTrendSeriesInput?.addEventListener("change", async () => {
    if (busy) {
      return
    }
    setBusy(true)
    try {
      await refreshCompetitorTrendSummary({ silent: false })
      renderCompetitorTrendPanel()
      updateStatus("竞对趋势维度已切换", "ok")
    } catch (error) {
      updateStatus(`趋势刷新失败: ${error.message}`, "error")
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
    if (action === "toggle-all-workflow") {
      toggleAllMerchantWorkflowItems(button.dataset.checked !== "1")
      renderMerchantWorkflowPreview()
    }
  })

  merchantPricingBox?.addEventListener("change", (event) => {
    const node = event.target
    if (!node) {
      return
    }
    if (node.matches("[data-role='workflow-check']") || node.matches("[data-role='workflow-final-price']")) {
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
      applyEmbeddedPageContextUi(pageContext)
      viewTools.renderPageContext(pageContextBox, pageContext)

      if (action === "status") {
        const response = await sendRuntimeMessage({ type: "SERVICE_STATUS" })
        updateStatus(`服务在线: ${response.plugin}`, "ok")
        setResultText(JSON.stringify(response, null, 2))
      } else if (action === "refresh-context") {
        await loadConfig()
        updateStatus(isMerchantPortalContext(pageContext) ? "已刷新后台识别" : "已刷新页面识别", "ok")
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
        renderCompetitorRoomPricesPanel()
        await refreshCompetitorTrendSummary({ silent: true })
        renderCompetitorTrendPanel()
        renderCompetitorPricingAdvice()
        updateStatus(`已抓取 ${Number(response?.hotel_count || 0)} 家竞对酒店的 ${Number(response?.total_rooms || 0)} 条房型价`, "ok")
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
      } else if (action === "panel") {
        updateStatus("当前已在页面面板中", "ok")
        setActivePage("workspace")
      } else if (action === "competitor-pricing-advice") {
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
            manualRoomMappings: getPreferredRoomMappingState(config, currentMerchantMappings).items,
          }
        })
        currentCompetitorPricingAdvice = response
        renderCompetitorPricingAdvice()
        const recommendedRoomCount = Number(response?.advice_summary?.recommended_room_count || response?.room_recommendations?.length || 0)
        const suggestedPrice = Number(response?.advice_summary?.suggested_price || 0)
        updateStatus(recommendedRoomCount ? `已生成 ${recommendedRoomCount} 个房型建议价` : (suggestedPrice ? `建议价已生成: ¥${suggestedPrice.toFixed(2)}` : "我的价格建议已生成"), "ok")
        setResultText(formatCompetitorPricingAdviceResult(response))
      } else if (action === "competitor-trend-refresh") {
        await refreshCompetitorTrendSummary({ silent: false })
        renderCompetitorTrendPanel()
        updateStatus("竞对趋势图已刷新", "ok")
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
        updateStatus(`已读取 ${Number(response?.count || 0)} 条房型映射`, "ok")
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
        })
        await loadMerchantMappings()
        updateStatus("已保存房型映射", "ok")
        setResultText(JSON.stringify(response, null, 2))
      } else if (action === "merchant-pricing-load") {
        const priceUrl = resolveMerchantWorkflowPriceUrl()
        const response = await sendRuntimeMessage({
          type: "MERCHANT_PRICING_ITEMS",
          payload: {
            priceUrl,
            collectMode: "extension_current_tab",
          }
        })
        currentMerchantWorkflowPreview = normalizeMerchantWorkflowPreview(response)
        renderMerchantWorkflowPreview()
        updateStatus(`已读取 ${Number(response?.item_count || 0)} 条房型，当前可提交 ${Number(currentMerchantWorkflowPreview?.readySubmitCount || 0)} 条`, "ok")
        setResultText(formatMerchantWorkflowResult(response))
      } else if (action === "merchant-pricing-preview") {
        const competitorHotelName = String(competitorNameInput?.value || "").replace(/\s+/g, " ").trim()
        const totalRooms = toPositiveInteger(competitorAdviceTotalRoomsInput?.value)
        const availableRooms = toNonNegativeInteger(competitorAdviceAvailableRoomsInput?.value)
        const currentPrice = toPositiveNumber(competitorAdviceCurrentPriceInput?.value)
        const inventorySnapshot = {
          ...(totalRooms ? { total_rooms: totalRooms } : {}),
          ...(availableRooms !== null ? { available_rooms: availableRooms } : {}),
          ...(currentPrice ? { current_price: currentPrice } : {})
        }
        const response = await sendRuntimeMessage({
          type: "COMPETITOR_WORKFLOW_PREVIEW",
          payload: {
            competitorHotelName: competitorHotelName || undefined,
            priceUrl: resolveMerchantWorkflowPriceUrl(),
            refreshCompetitorPrices: true,
            inventorySnapshot,
            strategy: competitorAdviceStrategyInput?.value || "balanced",
            manualRoomMappings: getPreferredRoomMappingState(config, currentMerchantMappings).items,
          }
        })
        currentMerchantWorkflowPreview = normalizeMerchantWorkflowPreview(response)
        renderMerchantWorkflowPreview()
        const refreshedRooms = Number(response?.competitor_room_price_refresh?.total_rooms || 0)
        updateStatus(`已读取本店价格并生成建议价${refreshedRooms ? `，本次同步竞对 ${refreshedRooms} 条房型价` : ""}`, "ok")
        setResultText(formatMerchantWorkflowResult(response))
      } else if (action === "merchant-pricing-fill") {
        applySuggestedPricesToMerchantWorkflow()
        renderMerchantWorkflowPreview()
        updateStatus("已将建议价回填到已勾选房型", "ok")
      } else if (action === "merchant-pricing-submit") {
        syncMerchantWorkflowItemsFromDom()
        const confirmedItems = collectConfirmedMerchantWorkflowItems()
        if (!confirmedItems.length) {
          throw new Error("请先分析并勾选至少一条可提交房型")
        }
        if (!confirmMerchantWorkflowSubmission(confirmedItems)) {
          updateStatus("已取消提交，最终价仍可继续调整", "error")
          return
        }
        const response = await sendRuntimeMessage({
          type: "MERCHANT_PRICING_SUBMIT_CURRENT",
          payload: {
            priceUrl: resolveMerchantWorkflowPriceUrl(),
            confirmedItems,
            comment: "browser_extension_competitor_confirm_submit"
          }
        })
        updateStatus("已按确认后的最终价提交到 OTA", response?.failed_count ? "error" : "ok")
        setResultText(formatMerchantSubmitResult(response))
        currentMerchantWorkflowPreview = null
        renderMerchantWorkflowPreview()
      } else if (action === "merchant-uniform-submit") {
        const priceUrl = String(uniformPriceUrlInput?.value || "").trim()
        const targetPrice = toPositiveNumber(uniformTargetPriceInput?.value)
        if (!priceUrl) {
          throw new Error("请先填写调价官网链接")
        }
        if (!targetPrice) {
          throw new Error("请先填写有效的目标价格")
        }
        if (!confirmUniformMerchantSubmit(priceUrl, targetPrice)) {
          updateStatus("已取消统一目标价提交", "error")
          return
        }
        const response = await sendRuntimeMessage({
          type: "MERCHANT_UNIFORM_PRICE_SUBMIT",
          payload: {
            priceUrl,
            targetPrice,
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
  applyEmbeddedPageContextUi(pageContext)
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
    activePage = pageKey === "feedback" ? "feedback" : "workspace"
    pageViews.forEach((page) => {
      page.classList.toggle("is-active", page.dataset.page === activePage)
    })
    navButtons.forEach((button) => {
      button.classList.toggle("is-active", button.dataset.page === activePage)
    })
    if (workspaceGroupCard) {
      workspaceGroupCard.classList.toggle("fliggy-ops-hidden", activePage !== "workspace")
    }
    if (workspaceResultCard) {
      workspaceResultCard.classList.toggle("fliggy-ops-hidden", activePage !== "workspace")
    }
    setActiveWorkspaceGroup(activeWorkspaceGroup)
  }

  function setActiveWorkspaceGroup(groupKey) {
    const nextGroup = ["basic", "merchant"].includes(groupKey) ? groupKey : "basic"
    activeWorkspaceGroup = nextGroup
    const showWorkspaceGroup = activePage === "workspace"
    workspaceGroupPages.forEach((page) => {
      page.classList.toggle("fliggy-ops-hidden", !showWorkspaceGroup || page.dataset.workspaceGroupPage !== nextGroup)
    })
    workspaceGroupButtons.forEach((button) => {
      button.classList.toggle("is-active", button.dataset.workspaceGroup === nextGroup)
    })
    setActiveBasicSection(activeBasicSection)
  }

  function setActiveBasicSection(sectionKey) {
    const nextSection = ["room-prices", "advice", "quick-actions"].includes(sectionKey)
      ? sectionKey
      : "room-prices"
    activeBasicSection = nextSection
    const showSection = activePage === "workspace" && activeWorkspaceGroup === "basic"
    basicSectionCards.forEach((card) => {
      card.classList.toggle("fliggy-ops-hidden", !showSection || card.dataset.basicSectionCard !== nextSection)
    })
    basicSectionButtons.forEach((button) => {
      button.classList.toggle("is-active", button.dataset.basicSection === nextSection)
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

  function renderCompetitorRoomPricesPanel() {
    if (!competitorRoomPricesBox) {
      return
    }
    if (!currentCompetitorRoomPrices) {
      competitorRoomPricesBox.innerHTML = '抓取完成后，会直接在这里展示竞对房型价。'
      return
    }
    competitorRoomPricesBox.innerHTML = renderCompetitorRoomPrices(currentCompetitorRoomPrices)
  }

  function open() {
    pageContext = pageContextTools.detectPageContext()
    applyEmbeddedPageContextUi(pageContext)
    viewTools.renderPageContext(pageContextBox, pageContext)
    loadConfig().catch(() => {})
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
      if (workflowPriceUrlInput && !String(workflowPriceUrlInput.value || "").trim()) {
        workflowPriceUrlInput.value = DEFAULT_MERCHANT_PRICE_URL
      }
      renderCompetitorRoomPricesPanel()
      renderCompetitorTrendPanel()
      renderCompetitorPricingAdvice()
      configBox.textContent = renderConfigSummary(config)
      if (isAuthenticatedConfig(config)) {
        refreshCompetitorTrendSummary({ silent: true })
          .then(() => renderCompetitorTrendPanel())
          .catch(() => {})
      }
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
    workspaceGate?.classList.toggle("fliggy-ops-hidden", authenticated)

    if (!authenticated) {
      authSessionBox.textContent = "请先在设置页登录并选择店铺，再回到页面内运营助手使用这里的工作台。"
      return
    }

    const shops = Array.isArray(currentConfig?.shops) ? currentConfig.shops : []
    const currentShop = currentConfig?.currentShop || null
    authSessionBox.textContent = `当前账号 ${String(currentConfig?.authUser?.username || "")} 已登录，当前店铺 ${String(currentShop?.shop_name || "-")} (${String(currentShop?.shop_id || currentConfig?.shopId || "-")})，可访问店铺 ${shops.length} 家。`
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
      renderCompetitorRoomPricesPanel()
      renderCompetitorTrendPanel()
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
    renderCompetitorRoomPricesPanel()
    renderCompetitorTrendPanel()
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

  function resolveMerchantWorkflowPriceUrl() {
    return String(workflowPriceUrlInput?.value || "").trim() || DEFAULT_MERCHANT_PRICE_URL
  }

  function setMerchantPlatformOverrideUrl(priceUrl = "") {
    currentMerchantPlatformOverrideUrl = String(priceUrl || "").trim() || DEFAULT_MERCHANT_PRICE_URL
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
      const lastSeenAt = String(item?.last_seen_at || item?.lastSeenAt || "-").trim() || "-"
      return `${roomName} / ${rateName} / ${status} / ${gid} / ${hid} / ${lastSeenAt}`
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

  function formatMarketTrendSignal(signal) {
    return {
      up: "上涨",
      down: "下跌",
      flat: "持平",
      mixed: "分化",
    }[String(signal || "").trim()] || "未知"
  }

  function formatMarketTrendSummary(context) {
    if (!context || typeof context !== "object") {
      return "-"
    }
    const signal = formatMarketTrendSignal(context.majority_signal)
    const pct = formatSignedPercent(context.representative_change_pct)
    const majorityCount = Number(context.majority_hotel_count || 0)
    const seriesCount = Number(context.series_count || 0)
    return `${signal} ${pct} | 同向酒店 ${majorityCount}/${seriesCount} | ${context.window_label || "最近趋势"}`
  }

  async function refreshCompetitorTrendSummary({ silent = false } = {}) {
    if (!isAuthenticatedConfig(config)) {
      currentCompetitorTrendSummary = null
      if (!silent) {
        throw new Error("请先在设置页登录并选择店铺")
      }
      return null
    }
    const response = await sendRuntimeMessage({
      type: "COMPETITOR_PRICE_TREND_SUMMARY",
      payload: {
        days: 2,
        pointLimit: 120,
        seriesType: competitorTrendSeriesInput?.value || "room_category",
        includeAdvice: true
      }
    })
    currentCompetitorTrendSummary = response
    return response
  }

  function formatTrendDateLabel(value) {
    const text = String(value || "").trim()
    if (!text) {
      return "-"
    }
    return text.replace("T", " ").replace("Z", "").slice(0, 19)
  }

  function formatTrendDateInline(value) {
    return formatTrendDateLabel(value).replace("\n", " ")
  }

  function formatRecentTrendChange(amount, pct) {
    if (!Number.isFinite(Number(amount))) {
      return "近三次暂无变化数据"
    }
    const normalizedAmount = Math.round(Number(amount) * 100) / 100
    if (Math.abs(normalizedAmount) < 0.005) {
      return "近三次持平"
    }
    const direction = normalizedAmount > 0 ? "近三次上涨" : "近三次下降"
    const pctText = Number.isFinite(Number(pct)) ? `（${formatSignedPercent(pct)}）` : ""
    return `${direction} ${formatPrice(Math.abs(normalizedAmount))}${pctText}`
  }

  function formatTrendScheduleText(schedule, trendResponse = null) {
    const enabled = schedule?.enabled !== false
    const interval = Number(schedule?.intervalMinutes || 120)
    const lastRunAt = schedule?.lastRunAt
    const nextRunAt = schedule?.nextRunAt
    const lastStatus = String(schedule?.lastStatus || "").trim()
    const lastError = String(schedule?.lastError || "").trim()
    const cloudCollectedAt = trendResponse?.latest_collected_at || schedule?.lastCloudCollectedAt
    const statusText = enabled ? `插件本地采集已开启，每 ${Math.max(interval / 60, 1)} 小时采集并同步云端` : "插件本地采集未开启"
    const runText = lastRunAt ? `最近采集 ${formatTrendDateInline(lastRunAt)}` : "尚未采集"
    const nextText = nextRunAt ? `下次采集 ${formatTrendDateInline(nextRunAt)}` : "等待浏览器调度"
    const cloudText = cloudCollectedAt ? `云端最新采集 ${formatTrendDateInline(cloudCollectedAt)}` : "云端暂无采集时间"
    const errorText = lastStatus === "failed" && lastError ? `，最近失败：${lastError}` : ""
    return `${statusText}；${cloudText}；${runText}；${nextText}${errorText}`
  }

  function getTrendSeriesTitle(item, index) {
    const categoryName = String(item?.category_name || "").trim()
    const hotelName = String(item?.hotel_name || "").trim()
    if (categoryName && hotelName) {
      return `${categoryName} · ${hotelName}`
    }
    return categoryName || hotelName || `趋势 ${index + 1}`
  }

  function renderTrendHotelSourceLink(hotelUrl) {
    const normalizedUrl = String(hotelUrl || "").trim()
    if (!normalizedUrl) {
      return "-"
    }
    if (!/^https?:\/\//i.test(normalizedUrl)) {
      return escapeHtml(normalizedUrl)
    }
    return `<a href="${escapeAttr(normalizedUrl)}" target="_blank" rel="noreferrer">打开酒店详情页</a>`
  }

  function buildCompetitorTrendSvg(series) {
    const visibleSeries = Array.isArray(series) ? series.slice(0, 8) : []
    if (!visibleSeries.length) {
      return ""
    }
    const allLabels = Array.from(new Set(
      visibleSeries.flatMap((item) => Array.isArray(item?.points) ? item.points.map((point) => String(point?.collected_at || "").trim()) : [])
    )).filter(Boolean).sort()
    const labels = allLabels.slice(-3)
    if (!labels.length) {
      return ""
    }
    const labelSet = new Set(labels)
    const recentSeries = visibleSeries.map((item) => {
      const points = Array.isArray(item?.points)
        ? item.points
          .filter((point) => labelSet.has(String(point?.collected_at || "").trim()))
          .sort((left, right) => String(left?.collected_at || "").localeCompare(String(right?.collected_at || "")))
        : []
      const firstPoint = points[0] || null
      const lastPoint = points[points.length - 1] || null
      const firstPrice = Number(firstPoint?.min_price || 0)
      const lastPrice = Number(lastPoint?.min_price || 0)
      const recentChangeAmount = firstPoint && lastPoint ? Math.round((lastPrice - firstPrice) * 100) / 100 : null
      const recentChangePct = firstPrice > 0 && recentChangeAmount !== null
        ? Math.round((recentChangeAmount / firstPrice) * 10000) / 100
        : null
      return {
        ...item,
        points,
        recentChangeAmount,
        recentChangePct,
      }
    })
    const pointsBySeries = recentSeries.map((item) => Array.isArray(item?.points) ? item.points : [])
    const allPoints = pointsBySeries.flat()
    const values = allPoints
      .map((point) => Number(point?.min_price))
      .filter((value) => Number.isFinite(value) && value > 0)
    if (!values.length) {
      return ""
    }
    const width = 340
    const height = 168
    const paddingLeft = 34
    const paddingRight = 10
    const paddingTop = 18
    const paddingBottom = 30
    const chartWidth = width - paddingLeft - paddingRight
    const chartHeight = height - paddingTop - paddingBottom
    const minValue = Math.min(...values)
    const maxValue = Math.max(...values)
    const range = Math.max(maxValue - minValue, 1)
    const colors = ["#ef6c00", "#0f9d58", "#2563eb", "#d93025", "#7c3aed", "#0891b2", "#ca8a04", "#be123c"]
    const xFor = (label) => {
      const index = Math.max(labels.indexOf(String(label || "")), 0)
      return paddingLeft + (labels.length <= 1 ? chartWidth / 2 : (index / (labels.length - 1)) * chartWidth)
    }
    const yFor = (value) => paddingTop + chartHeight - ((Number(value) - minValue) / range) * chartHeight
    const guides = [0, 0.5, 1].map((ratio) => {
      const y = paddingTop + ratio * chartHeight
      return `<line x1="${paddingLeft}" y1="${y.toFixed(1)}" x2="${width - paddingRight}" y2="${y.toFixed(1)}" stroke="rgba(148,101,58,0.16)" stroke-width="1" />`
    }).join("")
    const seriesLines = recentSeries.map((item, index) => {
      const points = (Array.isArray(item?.points) ? item.points : [])
        .filter((point) => Number.isFinite(Number(point?.min_price)))
        .sort((left, right) => String(left?.collected_at || "").localeCompare(String(right?.collected_at || "")))
      const color = colors[index % colors.length]
      const polyline = points.map((point) => `${xFor(point.collected_at).toFixed(1)},${yFor(point.min_price).toFixed(1)}`).join(" ")
      const circles = points.map((point) => `<circle cx="${xFor(point.collected_at).toFixed(1)}" cy="${yFor(point.min_price).toFixed(1)}" r="2.5" fill="${color}" />`).join("")
      return polyline ? `<polyline points="${polyline}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />${circles}` : ""
    }).join("")
    return `
      <div class="fliggy-ops-chart-shell">
        <svg class="fliggy-ops-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="竞对主流房型与酒店最低价折线图">
          <text x="2" y="${paddingTop + 4}" font-size="10" fill="#8f6332">¥${Math.ceil(maxValue)}</text>
          <text x="2" y="${paddingTop + chartHeight}" font-size="10" fill="#8f6332">¥${Math.floor(minValue)}</text>
          ${guides}
          ${seriesLines}
        </svg>
        <div class="fliggy-ops-chart-axis-labels">
          ${labels.map((label) => `<span>${escapeHtml(formatTrendDateInline(label))}</span>`).join("")}
        </div>
        <div class="fliggy-ops-chart-legend">
          ${recentSeries.map((item, index) => `
            <div class="fliggy-ops-chart-legend-item">
              <span class="fliggy-ops-chart-swatch" style="background:${colors[index % colors.length]}"></span>
              <div class="fliggy-ops-chart-legend-text">
                <div class="fliggy-ops-chart-legend-title">${escapeHtml(getTrendSeriesTitle(item, index))}</div>
                <div class="fliggy-ops-chart-legend-meta">最新最低价 ${formatPrice(item?.latest_min_price)} | 时间 ${escapeHtml(formatTrendDateInline(item?.latest_collected_at || item?.latest_bucket_at || ""))} | ${formatRecentTrendChange(item?.recentChangeAmount, item?.recentChangePct)}</div>
              </div>
            </div>
          `).join("")}
        </div>
      </div>
    `
  }

  function renderCompetitorTrendSeriesDetails(series, seriesType) {
    const items = Array.isArray(series) ? series : []
    if (!items.length) {
      return ""
    }
    const isHotelMinPrice = String(seriesType || "") === "hotel_min_price"
    const title = isHotelMinPrice ? "曲线明细：按竞对酒店区分" : "曲线明细：按主流房型 + 竞对酒店区分"
    return `
      <div class="fliggy-ops-workflow-list">
        <div class="fliggy-ops-footer">${escapeHtml(title)}</div>
        ${items.map((item, index) => {
          const categoryName = String(item?.category_name || "").trim()
          const hotelName = String(item?.hotel_name || "").trim()
          const hotelUrl = String(item?.hotel_url || "").trim()
          const recentPoints = (Array.isArray(item?.points) ? item.points : [])
            .filter((point) => Number.isFinite(Number(point?.min_price)))
            .sort((left, right) => String(left?.collected_at || "").localeCompare(String(right?.collected_at || "")))
            .slice(-3)
          const trendStartPoint = recentPoints[0] || null
          const trendEndPoint = recentPoints[recentPoints.length - 1] || null
          const trendDetail = trendStartPoint && trendEndPoint
            ? `趋势依据：${escapeHtml(formatTrendDateInline(trendStartPoint?.collected_at || ""))} 低价 ${formatPrice(trendStartPoint?.min_price)} → ${escapeHtml(formatTrendDateInline(trendEndPoint?.collected_at || ""))} 低价 ${formatPrice(trendEndPoint?.min_price)}`
            : "趋势依据：暂无足够数据"
          const trendChangeAmount = trendStartPoint && trendEndPoint
            ? Math.round((Number(trendEndPoint?.min_price || 0) - Number(trendStartPoint?.min_price || 0)) * 100) / 100
            : null
          const trendChangePct = trendStartPoint && Number(trendStartPoint?.min_price || 0) > 0 && trendChangeAmount !== null
            ? Math.round((trendChangeAmount / Number(trendStartPoint?.min_price || 0)) * 10000) / 100
            : null
          const dimensionText = isHotelMinPrice
            ? "维度: 竞对酒店最低价"
            : `主流房型: ${escapeHtml(categoryName || "-")}`
          return `
            <div class="fliggy-ops-workflow-item">
              <div class="fliggy-ops-workflow-item-name">${escapeHtml(getTrendSeriesTitle(item, index))}</div>
              <div class="fliggy-ops-workflow-item-meta">${dimensionText} | 竞对酒店: ${escapeHtml(hotelName || "-")}</div>
              <div class="fliggy-ops-workflow-item-meta">竞对酒店来源: 云端历史价 | 配置链接: ${renderTrendHotelSourceLink(hotelUrl)}</div>
              <div class="fliggy-ops-workflow-item-meta">最新最低价 ${formatPrice(item?.latest_min_price)} | 最新采集 ${escapeHtml(formatTrendDateInline(item?.latest_collected_at || item?.latest_bucket_at || ""))}</div>
              <div class="fliggy-ops-workflow-item-meta">${formatRecentTrendChange(trendChangeAmount, trendChangePct)} | 点数 ${Number(item?.point_count || 0)}</div>
              <div class="fliggy-ops-workflow-item-meta">${trendDetail}</div>
            </div>
          `
        }).join("")}
      </div>
    `
  }

  function renderCompetitorTrendPanel() {
    if (!competitorTrendBox) {
      return
    }
    if (!isAuthenticatedConfig(config)) {
      competitorTrendBox.innerHTML = '<div class="fliggy-ops-empty-state">登录后会在这里展示竞对价格趋势与自动采集状态。</div>'
      return
    }
    const response = currentCompetitorTrendSummary || {}
    const trendResponse = response?.trend || response
    const schedule = response?.schedule || {}
    const series = Array.isArray(trendResponse?.series) ? trendResponse.series : []
    const advice = trendResponse?.advice || {}
    const adviceItems = Array.isArray(advice?.items) ? advice.items : []
    const seriesType = String(trendResponse?.series_type || competitorTrendSeriesInput?.value || "room_category")
    const dimensionLabel = seriesType === "hotel_min_price" ? "竞对酒店" : "主流房型 + 酒店"
    if (!series.length) {
      competitorTrendBox.innerHTML = `
        <div class="fliggy-ops-empty-state">当前还没有可绘制的${escapeHtml(dimensionLabel)}历史数据，等待自动采集或先手动抓取一次竞对房型价。</div>
        <div class="fliggy-ops-footer">${escapeHtml(formatTrendScheduleText(schedule, trendResponse))}</div>
      `
      return
    }
    const trendDays = Number(trendResponse?.days || 2)
    const trendWindowLabel = trendDays === 2 ? "48 小时" : `${trendDays} 天`
    competitorTrendBox.innerHTML = `
      <div>近 <strong>${trendWindowLabel}</strong> ${escapeHtml(dimensionLabel)}趋势，覆盖 <strong>${Number(trendResponse?.hotel_count || 0)}</strong> 家竞对酒店，<strong>${Number(trendResponse?.point_count || 0)}</strong> 个价格点。</div>
      <div class="fliggy-ops-summary-grid">
        <div class="fliggy-ops-summary-pill"><div class="fliggy-ops-summary-label">最低价</div><div class="fliggy-ops-summary-value">${formatPrice(trendResponse?.price_min)}</div></div>
        <div class="fliggy-ops-summary-pill"><div class="fliggy-ops-summary-label">最高价</div><div class="fliggy-ops-summary-value">${formatPrice(trendResponse?.price_max)}</div></div>
        <div class="fliggy-ops-summary-pill"><div class="fliggy-ops-summary-label">最新均价</div><div class="fliggy-ops-summary-value">${formatPrice(trendResponse?.latest_price_avg)}</div></div>
        <div class="fliggy-ops-summary-pill"><div class="fliggy-ops-summary-label">最新采集</div><div class="fliggy-ops-summary-value">${escapeHtml(formatTrendDateInline(trendResponse?.latest_collected_at || "-"))}</div></div>
      </div>
      ${buildCompetitorTrendSvg(series)}
      ${renderCompetitorTrendSeriesDetails(series, seriesType)}
      <div class="fliggy-ops-footer">${escapeHtml(formatTrendScheduleText(schedule, trendResponse))}</div>
      <div class="fliggy-ops-footer">AI 建议来源：${escapeHtml(String(advice?.source || "rule_based"))}${advice?.summary ? ` | ${escapeHtml(advice.summary)}` : ""}</div>
      <div class="fliggy-ops-tags">${series.map((item, index) => `<span class="fliggy-ops-tag">${escapeHtml(getTrendSeriesTitle(item, index))}</span>`).join("")}</div>
      <div class="fliggy-ops-workflow-list">
        ${adviceItems.length ? adviceItems.map((item) => `
          <div class="fliggy-ops-workflow-item">
            <div class="fliggy-ops-workflow-item-name">${escapeHtml(item?.title || "趋势建议")}</div>
            <div class="fliggy-ops-workflow-item-meta">${escapeHtml(item?.detail || "-")}</div>
          </div>
        `).join("") : '<div class="fliggy-ops-empty-state">暂无趋势建议。</div>'}
      </div>
    `
  }

function renderCompetitorPricingAdvice() {
  if (!competitorAdviceBox) {
    return
  }
  const hotels = Array.isArray(currentCompetitorRoomPrices?.hotels) ? currentCompetitorRoomPrices.hotels : []
  const mappingState = getPreferredRoomMappingState(config, currentMerchantMappings)
  const manualRoomMappings = mappingState.items
  const hotelNames = hotels.slice(0, 6).map((hotel) => escapeHtml(hotel?.hotel_name || '未命名酒店')).join(' / ')
  if (!currentCompetitorPricingAdvice) {
    competitorAdviceBox.innerHTML = hotels.length
      ? `已缓存 ${Number(currentCompetitorRoomPrices?.hotel_count || hotels.length)} 家竞对酒店，${Number(currentCompetitorRoomPrices?.total_rooms || 0)} 条房型价。<div class="fliggy-ops-footer">${manualRoomMappings.length ? `当前店铺已维护 ${manualRoomMappings.length} 条${mappingState.sourceLabel}房型映射；点击生成时将读取数据库最近一次自动抓取的竞对房型价。` : '当前还没有可用的本店房型映射，请先在设置页维护我的房型映射。'}</div>${hotelNames ? `<div class="fliggy-ops-footer">${hotelNames}</div>` : ''}`
      : `无需先手动抓取；点击生成时会直接读取数据库里最近一次自动抓取的竞对房型价。<div class="fliggy-ops-footer">${manualRoomMappings.length ? `当前店铺已维护 ${manualRoomMappings.length} 条${mappingState.sourceLabel}房型映射。` : '当前还没有可用的本店房型映射，请先在设置页维护我的房型映射。'}</div>`
    return
  }
  const advice = currentCompetitorPricingAdvice
  const summary = advice?.advice_summary || {}
  const competitorContext = advice?.competitor_context || {}
  const merchantSnapshot = advice?.merchant_room_snapshot || {}
  const promptProfile = advice?.prompt_profile || {}
  const marketTrend = advice?.market_trend_context || {}
  const roomRecommendations = Array.isArray(advice?.room_recommendations) ? advice.room_recommendations : []
  const sourceLabel = merchantSnapshot?.source === 'manual_room_mappings'
    ? `手工房型价格 ${Number(merchantSnapshot?.item_count || roomRecommendations.length || 0)} 条`
    : `抓取房型快照 ${Number(merchantSnapshot?.item_count || roomRecommendations.length || 0)} 条`
  const roomHtml = roomRecommendations.slice(0, 8).map((item) => `
      <div class="fliggy-ops-card" style="margin-top: 8px;">
        <div><strong>${escapeHtml(item?.display_name || item?.room_name || '未命名房型')}</strong></div>
        <div class="fliggy-ops-footer">现价 ${formatPrice(item?.current_price)} | 竞对最低 ${formatPrice(item?.competitor_min_price)} | 竞对均价 ${formatPrice(item?.competitor_avg_price)} | 竞对最高 ${formatPrice(item?.competitor_max_price)}</div>
        <div class="fliggy-ops-footer">趋势锚点 ${formatPrice(item?.trend_based_price)} | 竞对趋势 ${formatSignedPercent(item?.market_trend_pct)}</div>
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
      <div class="fliggy-ops-footer">角色 ${escapeHtml(promptProfile?.role || '酒店收益管理与OTA定价专家')} | ${sourceLabel} | 竞对样本 ${Number(competitorContext?.price_count || 0)} 条 | 来源 ${escapeHtml(advice?.recommendation_source || '-')}</div>
      <div class="fliggy-ops-footer">竞对趋势 ${escapeHtml(formatMarketTrendSummary(marketTrend))}</div>
      <div class="fliggy-ops-footer">${escapeHtml(summary?.reason_summary || '已生成建议价，可展开下方房型查看明细。')}</div>
      ${roomHtml || '<div class="fliggy-ops-footer" style="margin-top: 8px;">当前没有可展示的房型建议。</div>'}
    `
}

function formatCompetitorPricingAdviceResult(response) {
  const summary = response?.advice_summary || {}
  const competitorContext = response?.competitor_context || {}
  const merchantSnapshot = response?.merchant_room_snapshot || {}
  const promptProfile = response?.prompt_profile || {}
  const marketTrend = response?.market_trend_context || {}
  const roomRecommendations = Array.isArray(response?.room_recommendations) ? response.room_recommendations : []
  const merchantSource = merchantSnapshot?.source === 'manual_room_mappings'
    ? '\u624b\u5de5\u623f\u578b\u4ef7\u683c'
    : (merchantSnapshot?.source === 'merchant_price_snapshot' ? '\u6293\u53d6\u623f\u578b\u5feb\u7167' : '\u672c\u5e97\u623f\u578b\u6837\u672c')
  const roomLines = roomRecommendations.slice(0, 12).map((item) => {
    const roomName = item?.display_name || item?.room_name || '\u672a\u547d\u540d\u623f\u578b'
    return [
      `${roomName}`,
      `\u5f53\u524d\u4ef7: ${formatPrice(item?.current_price)} | \u7ade\u5bf9\u6700\u4f4e: ${formatPrice(item?.competitor_min_price)} | \u7ade\u5bf9\u5747\u4ef7: ${formatPrice(item?.competitor_avg_price)} | \u7ade\u5bf9\u6700\u9ad8: ${formatPrice(item?.competitor_max_price)}`,
      `\u8d8b\u52bf\u951a\u70b9: ${formatPrice(item?.trend_based_price)} | \u7ade\u5bf9\u8d8b\u52bf: ${formatSignedPercent(item?.market_trend_pct)}`,
      `\u5efa\u8bae\u4ef7: ${formatPrice(item?.suggested_price)} | \u8c03\u6574: ${formatSignedPrice(item?.change_amount)} | \u8c03\u6574\u6bd4\u4f8b: ${formatSignedPercent(item?.change_pct)} | \u98ce\u9669: ${item?.risk_level || '-'}`,
      `\u8bf4\u660e: ${item?.reasoning || '-'}`,
    ].join("\\n")
  })
  return [
    `\u7ade\u5bf9\u9152\u5e97: ${response?.competitor_hotel_name || '\u7efc\u5408\u7ade\u5bf9\u9152\u5e97'}`,
    `\u89d2\u8272: ${promptProfile?.role || '\u9152\u5e97OTA\u8fd0\u8425\u4e13\u5bb6'}`,
    `\u672c\u5e97\u4ef7\u683c\u6765\u6e90: ${merchantSource}`,
    `\u7ade\u5bf9\u6837\u672c: ${Number(competitorContext?.price_count || 0)}`,
    `\u7ade\u5bf9\u8d8b\u52bf: ${formatMarketTrendSummary(marketTrend)}`,
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
          competitorMinPrice: toPositiveNumber(item?.competitor_min_price),
          competitorAvgPrice: toPositiveNumber(item?.competitor_avg_price),
          competitorMaxPrice: toPositiveNumber(item?.competitor_max_price),
          matchMode: item?.match_mode || item?.room_advice?.match_mode || "",
          matchedRoomCount: Number(item?.matched_room_count || item?.room_advice?.matched_room_count || 0),
          submitReady: Boolean(item?.submit_ready),
          selected: Boolean(item?.submit_ready)
        }
      })
    }
  }

  function renderMerchantWorkflowPreview() {
    if (!merchantPricingBox) {
      return
    }
    if (!currentMerchantWorkflowPreview || !Array.isArray(currentMerchantWorkflowPreview.items) || currentMerchantWorkflowPreview.items.length === 0) {
      merchantPricingBox.innerHTML = isMerchantPortalContext(pageContext)
        ? '<div class="fliggy-ops-empty-state">当前在商家后台，可直接生成改价分析；如需建议价，请先查看竞对价格并维护本店房型映射。</div>'
        : '<div class="fliggy-ops-empty-state">先输入竞对酒店名称，再开始分析。</div>'
      return
    }

    const items = currentMerchantWorkflowPreview.items
    const submitReadyCount = items.filter((item) => item.submitReady).length
    const selectedCount = items.filter((item) => item.selected && item.submitReady).length
    const allSelected = submitReadyCount > 0 && selectedCount === submitReadyCount
    const summary = currentMerchantWorkflowPreview.workflowSummary || {}
    const competitorContext = summary.competitor_context || {}
    const inventorySnapshot = summary.inventory_snapshot || {}
    const merchantHistory = summary.merchant_history_context || {}
    const priceRecommendation = summary.price_recommendation || {}

    merchantPricingBox.innerHTML = `
      <div>
        <strong>${escapeHtml(currentMerchantWorkflowPreview.competitorHotelName || "竞对酒店")}</strong> 分析完成。
        已生成 ${items.length} 条房型建议，可提交 ${submitReadyCount} 条，当前选中 ${selectedCount} 条。
      </div>
      <div class="fliggy-ops-summary-grid">
        <div class="fliggy-ops-summary-pill">
          <div class="fliggy-ops-summary-label">竞对中位价</div>
          <div class="fliggy-ops-summary-value">${formatPrice(competitorContext.price_median)}</div>
        </div>
        <div class="fliggy-ops-summary-pill">
          <div class="fliggy-ops-summary-label">竞对均价</div>
          <div class="fliggy-ops-summary-value">${formatPrice(competitorContext.price_avg)}</div>
        </div>
        <div class="fliggy-ops-summary-pill">
          <div class="fliggy-ops-summary-label">库存可售</div>
          <div class="fliggy-ops-summary-value">${formatInventory(inventorySnapshot)}</div>
        </div>
        <div class="fliggy-ops-summary-pill">
          <div class="fliggy-ops-summary-label">建议中位价</div>
          <div class="fliggy-ops-summary-value">${formatPrice(priceRecommendation.price_mid)}</div>
        </div>
      </div>
      <div class="fliggy-ops-tip">历史价样本 ${Number(merchantHistory.price_count || 0)} 条，竞对样本 ${Number(competitorContext.price_count || 0)} 条，数据源 ${escapeHtml(competitorContext.data_source || "-")}</div>
      <div class="fliggy-ops-workflow-tools">
        <button type="button" data-action="toggle-all-workflow" data-checked="${allSelected ? "1" : "0"}">${allSelected ? "取消全选" : "全选可提交项"}</button>
        <button type="button" class="secondary" disabled>${escapeHtml(summary.sample_item || "样本房型")}</button>
        <button type="button" class="secondary" disabled>${escapeHtml(summary.recommendation_source || "fallback")}</button>
      </div>
      <div class="fliggy-ops-workflow-list">
        ${items.map((item, index) => renderMerchantWorkflowItem(item, index)).join("")}
      </div>
    `
  }

  function renderMerchantWorkflowItem(item, index) {
    return `
      <div class="fliggy-ops-workflow-item">
        <div class="fliggy-ops-workflow-item-top">
          <input type="checkbox" data-role="workflow-check" data-index="${index}" ${item.selected && item.submitReady ? "checked" : ""} ${item.submitReady ? "" : "disabled"}>
          <div>
            <div class="fliggy-ops-workflow-item-name">${escapeHtml(item.displayName)}</div>
            <div class="fliggy-ops-workflow-item-meta">GID/HID: ${escapeHtml(item.gid || "-")} / ${escapeHtml(item.hid || "-")}</div>
            <div class="fliggy-ops-workflow-item-meta">风险 ${escapeHtml(item.riskLevel)} | 变动 ${item.changePct ? `${item.changePct.toFixed(2)}%` : "-"}${item.submitReady ? "" : " | 未映射不可提交"}</div>
            <div class="fliggy-ops-workflow-item-meta">竞对 ${formatPrice(item.competitorMinPrice)} / ${formatPrice(item.competitorAvgPrice)} / ${formatPrice(item.competitorMaxPrice)} | 匹配 ${escapeHtml(formatMerchantWorkflowMatchMode(item.matchMode))}${item.matchedRoomCount ? ` ${item.matchedRoomCount}条` : ""}</div>
          </div>
        </div>
        <div class="fliggy-ops-price-grid">
          <div>
            <div class="fliggy-ops-price-grid-label">现价</div>
            <div>${formatPrice(item.currentPrice)}</div>
          </div>
          <div>
            <div class="fliggy-ops-price-grid-label">建议价</div>
            <div>${formatPrice(item.suggestedPrice)}</div>
          </div>
          <div>
            <div class="fliggy-ops-price-grid-label">最终价</div>
            <input class="fliggy-ops-input" type="number" min="1" step="0.01" data-role="workflow-final-price" data-index="${index}" value="${item.finalPrice ?? ""}" ${item.submitReady ? "" : "disabled"}>
          </div>
        </div>
      </div>
    `
  }

  function formatMerchantWorkflowMatchMode(value) {
    return ({
      manual_mapping: "手动映射",
      smart_match: "智能匹配",
      broad_match: "宽松匹配",
      market_fallback: "市场兜底"
    })[String(value || "").trim()] || "-"
  }

  function syncMerchantWorkflowItemsFromDom() {
    if (!currentMerchantWorkflowPreview?.items?.length || !merchantPricingBox) {
      return
    }
    currentMerchantWorkflowPreview.items.forEach((item, index) => {
      const checkedNode = merchantPricingBox.querySelector(`[data-role='workflow-check'][data-index='${index}']`)
      const finalPriceNode = merchantPricingBox.querySelector(`[data-role='workflow-final-price'][data-index='${index}']`)
      item.selected = Boolean(checkedNode?.checked) && item.submitReady
      item.finalPrice = toPositiveNumber(finalPriceNode?.value) ?? item.finalPrice
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

  function formatMerchantWorkflowSubmitLine(item) {
    const name = item?.display_name || item?.rate_name || item?.room_name || "未命名房型"
    const currentPrice = Number(item?.current_price || 0)
    const suggestedPrice = Number(item?.suggested_price || 0)
    const finalPrice = Number(item?.final_price || 0)
    const changeText = currentPrice && finalPrice
      ? `，较现价${finalPrice >= currentPrice ? "+" : ""}${(finalPrice - currentPrice).toFixed(2)}`
      : ""
    return `- ${name}: 现价 ${formatPrice(currentPrice)} / 建议 ${formatPrice(suggestedPrice)} / 最终 ${formatPrice(finalPrice)}${changeText}`
  }

  function buildMerchantWorkflowSubmitConfirmation(confirmedItems) {
    const items = Array.isArray(confirmedItems) ? confirmedItems : []
    const riskLevels = items.map((item) => String(item?.risk_level || "").trim()).filter(Boolean)
    const changedCount = items.filter((item) => {
      const currentPrice = Number(item?.current_price || 0)
      const finalPrice = Number(item?.final_price || 0)
      return currentPrice > 0 && finalPrice > 0 && Math.round(currentPrice * 100) !== Math.round(finalPrice * 100)
    }).length
    const sampleLines = items.slice(0, 5).map(formatMerchantWorkflowSubmitLine)
    return [
      "将按以下最终价提交到商家后台，确认后会执行真实改价。",
      `房型数: ${items.length}`,
      `价格发生变化: ${changedCount}`,
      `风险等级: ${riskLevels.length ? riskLevels.join(" / ") : "-"}`,
      sampleLines.length ? "提交预览:" : "",
      sampleLines.join("\n"),
      items.length > sampleLines.length ? `...另有 ${items.length - sampleLines.length} 个房型` : "",
      "",
      "确认继续提交？"
    ].filter((line) => line !== "").join("\n")
  }

  function confirmMerchantWorkflowSubmission(confirmedItems) {
    return window.confirm(buildMerchantWorkflowSubmitConfirmation(confirmedItems))
  }

  function confirmUniformMerchantSubmit(priceUrl, targetPrice) {
    return window.confirm([
      "统一目标价是高级备用流程，确认后会把所有可提交房型按同一个目标价提交到商家后台。",
      `目标价: ¥${Number(targetPrice).toFixed(2)}`,
      `链接: ${priceUrl}`,
      "",
      "优先建议使用上方按房型建议价流程。确认继续提交？"
    ].join("\n"))
  }

  function collectSelectedMerchantWorkflowItems() {
    return collectConfirmedMerchantWorkflowItems()
  }

  function formatMerchantWorkflowResult(response) {
    const summary = response?.workflow_summary || {}
    const competitorContext = summary?.competitor_context || {}
    const priceRecommendation = summary?.price_recommendation || {}
    return [
      `竞对酒店: ${response?.competitor_hotel_name || "-"}`,
      `房型数: ${response?.item_count || 0}`,
      `可提交: ${response?.ready_submit_count || 0}`,
      `竞对均价: ${formatPrice(competitorContext?.price_avg)}`,
      `建议中位价: ${formatPrice(priceRecommendation?.price_mid)}`,
      `建议来源: ${summary?.recommendation_source || response?.recommendation_source || "-"}`
    ].join("\n")
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
    workspaceGroupButtons.forEach((button) => {
      button.disabled = busy
    })
    basicSectionButtons.forEach((button) => {
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











































