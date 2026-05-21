const CLOUD_ASSISTANT_ORIGIN = "http://api.aihuawise.com"
const CLOUD_ASSISTANT_URL = `${CLOUD_ASSISTANT_ORIGIN}/ops-assistant`
const CLOUD_PROTOCOL_VERSION = "fliggy-ops-cloud-ui/v1"
const CLOUD_REQUEST_TYPE = "FLIGGY_OPS_CLOUD_REQUEST"
const CLOUD_RESPONSE_TYPE = "FLIGGY_OPS_CLOUD_RESPONSE"
const CLOUD_EVENT_TYPE = "FLIGGY_OPS_CLOUD_EVENT"
const CLOUD_BRIDGE_TIMEOUT_MS = 300000
const RUNTIME_TIMEOUT_MS = 30000
const TAB_TIMEOUT_MS = 8000

const cloudFrame = document.getElementById("cloud-frame")
const statusPanel = document.getElementById("status")
const statusNote = document.getElementById("status-note")
const reloadBtn = document.getElementById("reload-btn")
const localBtn = document.getElementById("local-btn")
const fallbackBtn = document.getElementById("fallback-btn")
const optionsBtn = document.getElementById("options-btn")

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

function buildCloudAssistantUrl() {
  const url = new URL(CLOUD_ASSISTANT_URL)
  url.searchParams.set("embedded", "1")
  url.searchParams.set("host", "extension-popup")
  url.searchParams.set("protocol", CLOUD_PROTOCOL_VERSION)
  return url.toString()
}

function openLocalFallback() {
  window.location.href = chrome.runtime.getURL("popup.html?local=1")
}

function setStatus(note, visible = true) {
  if (statusNote && note) {
    statusNote.textContent = note
  }
  statusPanel?.classList.toggle("is-hidden", !visible)
}

function withTimeout(promise, timeoutMs, label) {
  let timer = null
  return new Promise((resolve, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} 超时`)), timeoutMs)
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

async function getActiveBusinessTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true }).catch(() => [])
  const activeTab = tabs.find((tab) => tab?.id && !String(tab.url || "").startsWith(chrome.runtime.getURL("")))
  if (!activeTab?.id) {
    throw new Error("未找到当前活动业务页")
  }
  return activeTab
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

let bridgeFramePromise = null

function ensureBridgeFrame() {
  if (bridgeFramePromise) {
    return bridgeFramePromise
  }

  bridgeFramePromise = new Promise((resolve, reject) => {
    const existing = document.getElementById("fliggy-ops-popup-bridge-frame")
    if (existing) {
      resolve(existing)
      return
    }

    const frame = document.createElement("iframe")
    frame.id = "fliggy-ops-popup-bridge-frame"
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

async function requestViaExtensionBridge(action, payload = {}) {
  const frame = await ensureBridgeFrame()
  const targetWindow = frame.contentWindow
  if (!targetWindow) {
    throw new Error("桥接页面尚未就绪")
  }

  const requestId = `popup-bridge-${Date.now()}-${Math.random().toString(16).slice(2)}`
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
        reject(new Error(String(data.error || "桥接请求失败")))
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

function postCloudMessage(message) {
  const targetWindow = cloudFrame?.contentWindow
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

async function getActivePageContext() {
  const tab = await getActiveBusinessTab()
  return sendTabMessage(tab.id, { type: "GET_PAGE_CONTEXT" })
}

async function getActivePageSnapshot(payload = {}) {
  const tab = await getActiveBusinessTab()
  return sendTabMessage(tab.id, { type: "GET_PAGE_SNAPSHOT", payload })
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
    return getActivePageContext()
  }
  if (action === "page.getSnapshot") {
    return getActivePageSnapshot(payload)
  }
  if (action === "page.getCurrentHotelRoomPrices") {
    const tab = await getActiveBusinessTab()
    return sendTabMessage(tab.id, { type: "GET_CURRENT_HOTEL_ROOM_PRICES" })
  }
  if (action === "page.collectLocalMerchantPriceItems") {
    const tab = await getActiveBusinessTab()
    return sendTabMessage(tab.id, { type: "LOCAL_MERCHANT_PRICE_ITEMS" })
  }
  if (action === "page.submitLocalMerchantPrices") {
    const tab = await getActiveBusinessTab()
    return sendTabMessage(tab.id, {
      type: "LOCAL_MERCHANT_PRICE_SUBMIT",
      payload: {
        confirmedItems: payload.confirmedItems || payload.confirmed_items || []
      }
    })
  }
  if (action === "panel.open") {
    const tab = await getActiveBusinessTab()
    return sendTabMessage(tab.id, { type: "OPEN_PANEL" })
  }
  if (action === "panel.close") {
    window.close()
    return { closed: true }
  }
  if (action === "panel.ping") {
    return {
      ready: true,
      protocol: CLOUD_PROTOCOL_VERSION,
      origin: CLOUD_ASSISTANT_ORIGIN,
      host: "extension-popup"
    }
  }
  throw new Error(`Unsupported cloud action: ${String(action || "<empty>")}`)
}

window.addEventListener("message", (event) => {
  const data = event.data
  if (
    event.source !== cloudFrame?.contentWindow
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

cloudFrame?.addEventListener("load", () => {
  setStatus("", false)
  sendCloudEvent("plugin.ready", {
    host: "extension-popup",
    capabilities: [
      "plugin.runtime",
      "bridge.request",
      "page.getContext",
      "page.getSnapshot",
      "page.getCurrentHotelRoomPrices",
      "page.collectLocalMerchantPriceItems",
      "page.submitLocalMerchantPrices",
      "panel.open",
      "panel.close",
      "panel.ping"
    ]
  })
})

cloudFrame?.addEventListener("error", () => {
  setStatus("云端助手加载失败，可以重试或打开本地备用工作台。", true)
})

reloadBtn?.addEventListener("click", () => {
  setStatus("正在重新加载云端助手...", true)
  if (cloudFrame) {
    cloudFrame.src = buildCloudAssistantUrl()
  }
})

localBtn?.addEventListener("click", openLocalFallback)
fallbackBtn?.addEventListener("click", openLocalFallback)
optionsBtn?.addEventListener("click", () => {
  sendRuntimeMessage({ type: "OPEN_OPTIONS" }).catch(() => chrome.runtime.openOptionsPage())
})

if (cloudFrame) {
  cloudFrame.src = buildCloudAssistantUrl()
}
